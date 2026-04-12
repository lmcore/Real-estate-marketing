"""Typer-based CLI for Shadow Tester."""

from __future__ import annotations

import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from shadow_tester.comps import Target, find_comparables, geocode
from shadow_tester.comps.geocoding import GeocodingError
from shadow_tester.config import get_settings
from shadow_tester.dvf import compute_commune_stats, ingest_commune_years
from shadow_tester.insee import (
    ingest_from_file,
    ingest_from_url,
    load_commune,
    summarize_commune,
)
from shadow_tester.listings import (
    Listing,
    add_listing,
    delete_listing,
    detect_condition,
    get_listing,
    list_listings,
    parse_listing_html,
)
from shadow_tester.listings.fetch import FetchError, fetch_listing_html
from shadow_tester.listings.matcher import (
    AUTO_MATCH_THRESHOLD,
    SUGGEST_THRESHOLD,
    match_all_unmatched,
    match_listing,
)
from shadow_tester.listings.repo import update_listing as _update_listing
from shadow_tester.listings.stats import compute_listing_stats
from shadow_tester.listings.vision import (
    VisionError,
    vision_to_condition_detection,
)
from shadow_tester.listings.vision import (
    analyze_photos as run_vision_analysis,
)
from shadow_tester.notes import (
    ALLOWED_CONDITIONS,
    ALLOWED_SOURCES,
    PropertyNote,
    add_note,
    delete_note,
    get_note,
    list_notes,
)

app = typer.Typer(
    help="Shadow Tester — demand analyzer for real-estate projects based on public data.",
    no_args_is_help=True,
)
dvf_app = typer.Typer(help="DVF (Demandes de Valeurs Foncières) commands.", no_args_is_help=True)
insee_app = typer.Typer(help="INSEE commune indicators commands.", no_args_is_help=True)
comps_app = typer.Typer(help="Comparable-properties engine.", no_args_is_help=True)
notes_app = typer.Typer(help="User property notes (condition, travaux, observations).", no_args_is_help=True)
listings_app = typer.Typer(help="Capture & analyse real-estate listings.", no_args_is_help=True)
app.add_typer(dvf_app, name="dvf")
app.add_typer(insee_app, name="insee")
app.add_typer(comps_app, name="comps")
app.add_typer(notes_app, name="notes")
app.add_typer(listings_app, name="listings")

console = Console()
logger = logging.getLogger(__name__)


def _parse_years(value: str) -> list[int]:
    """Accepts "2022,2023,2024" or "2022-2024"."""
    value = value.strip()
    if "-" in value and "," not in value:
        start_s, end_s = value.split("-", 1)
        start, end = int(start_s), int(end_s)
        if end < start:
            raise typer.BadParameter(f"Year range {value!r} is inverted.")
        return list(range(start, end + 1))
    try:
        return [int(y) for y in value.split(",") if y.strip()]
    except ValueError as exc:
        raise typer.BadParameter(f"Could not parse years {value!r}") from exc


@dvf_app.command("ingest")
def dvf_ingest(
    commune: str | None = typer.Option(
        None,
        "--commune",
        "-c",
        help="INSEE commune code (defaults to config, Manosque=04112).",
    ),
    years: str = typer.Option(
        ...,
        "--years",
        "-y",
        help="Years to ingest, e.g. '2022,2023,2024' or '2022-2024'.",
    ),
    force: bool = typer.Option(False, "--force", help="Bypass cache and re-download CSVs."),
) -> None:
    """Download DVF transactions for a commune and load them into SQLite."""
    settings = get_settings()
    code = commune or settings.default_commune
    year_list = _parse_years(years)

    console.print(
        f"[bold]Ingesting DVF[/] commune=[cyan]{code}[/] years={year_list} force={force}"
    )
    results = ingest_commune_years(code, year_list, force=force)

    table = Table(title=f"DVF ingestion — {code}")
    table.add_column("Year", justify="right")
    table.add_column("Rows", justify="right")
    table.add_column("Status")
    table.add_column("Source")
    for r in results:
        status = "[yellow]SKIPPED[/]" if r.skipped else "[green]OK[/]"
        table.add_row(str(r.year), str(r.rows_loaded), status, r.source_url)
    console.print(table)

    total = sum(r.rows_loaded for r in results)
    console.print(f"[bold green]Total rows loaded:[/] {total}")


@dvf_app.command("stats")
def dvf_stats(
    commune: str | None = typer.Option(
        None, "--commune", "-c", help="INSEE commune code."
    ),
    type_local: str | None = typer.Option(
        None,
        "--type",
        "-t",
        help="Filter: 'Maison' or 'Appartement'.",
    ),
    year: int | None = typer.Option(None, "--year", "-y", help="Filter by year."),
) -> None:
    """Show aggregated price/m² statistics for a commune."""
    settings = get_settings()
    code = commune or settings.default_commune

    stats = compute_commune_stats(code, type_local=type_local, year=year)

    if not stats.buckets:
        console.print(
            f"[yellow]No DVF data for commune {code}[/] with the current filters. "
            "Did you run `shadow-tester dvf ingest`?"
        )
        raise typer.Exit(code=1)

    table = Table(
        title=f"DVF stats — commune {code} "
        f"({stats.total_transactions} transactions{' — '+type_local if type_local else ''})"
    )
    table.add_column("Year", justify="right")
    table.add_column("Type")
    table.add_column("N", justify="right")
    table.add_column("Median €/m²", justify="right")
    table.add_column("P25 €/m²", justify="right")
    table.add_column("P75 €/m²", justify="right")
    table.add_column("Med. surface", justify="right")
    table.add_column("Med. prix", justify="right")

    def fmt_money(x: float | None) -> str:
        return f"{x:,.0f}".replace(",", " ") if x is not None else "-"

    def fmt_surface(x: float | None) -> str:
        return f"{x:,.0f} m²".replace(",", " ") if x is not None else "-"

    for b in stats.buckets:
        table.add_row(
            str(b.year),
            b.type_local,
            str(b.n_transactions),
            fmt_money(b.median_prix_m2),
            fmt_money(b.p25_prix_m2),
            fmt_money(b.p75_prix_m2),
            fmt_surface(b.median_surface),
            fmt_money(b.median_valeur),
        )
    console.print(table)


@insee_app.command("ingest")
def insee_ingest(
    source: str = typer.Argument(
        ...,
        help="URL of the INSEE 'dossier complet' ZIP, or local path to a CSV / ZIP.",
    ),
    millesime: int = typer.Option(
        ...,
        "--millesime",
        "-m",
        help="Vintage year of the dataset (e.g. 2020 for RP 2020 / FILOSOFI 2020).",
    ),
    commune: str | None = typer.Option(
        None,
        "--commune",
        "-c",
        help="Optional INSEE commune code to filter to (default: load all communes).",
    ),
    force: bool = typer.Option(False, "--force", help="Re-download and re-extract."),
) -> None:
    """Ingest an INSEE 'Dossier Complet' file.

    ``source`` can be either an HTTP(S) URL (e.g. to the dossier complet ZIP)
    or a path to a local file already downloaded.
    """
    communes = [commune] if commune else None

    if source.startswith(("http://", "https://")):
        console.print(f"[bold]Ingesting INSEE[/] from URL millesime={millesime}")
        result = ingest_from_url(
            source, millesime=millesime, communes=communes, force=force
        )
    else:
        path = Path(source).expanduser().resolve()
        if not path.exists():
            raise typer.BadParameter(f"{path} does not exist")
        console.print(f"[bold]Ingesting INSEE[/] from {path} millesime={millesime}")
        result = ingest_from_file(
            path, millesime=millesime, communes=communes, source_url=str(path)
        )

    console.print(
        f"[green]OK[/] millesime={result.millesime} rows_loaded={result.rows_loaded}"
    )


@insee_app.command("show")
def insee_show(
    commune: str | None = typer.Option(None, "--commune", "-c"),
) -> None:
    """Show the latest ingested INSEE indicators for a commune."""
    settings = get_settings()
    code = commune or settings.default_commune
    row = load_commune(code)
    if not row:
        console.print(f"[yellow]No INSEE data for commune {code}[/]")
        raise typer.Exit(code=1)

    table = Table(title=f"INSEE — {row.get('nom_commune') or code} ({code})")
    table.add_column("Indicator")
    table.add_column("Value", justify="right")

    def fmt(v: object, unit: str = "") -> str:
        if v is None:
            return "-"
        if isinstance(v, float):
            return f"{v:,.2f}".replace(",", " ") + (f" {unit}" if unit else "")
        return f"{v}{(' ' + unit) if unit else ''}"

    table.add_row("Millésime", str(row.get("millesime") or "-"))
    table.add_row("Population", fmt(row.get("population"), "hab"))
    table.add_row("Superficie", fmt(row.get("superficie_km2"), "km²"))
    table.add_row("Densité", fmt(row.get("densite_hab_km2"), "hab/km²"))
    table.add_row("Logements (total)", fmt(row.get("logements_total")))
    table.add_row("Résidences principales", fmt(row.get("residences_principales")))
    table.add_row("Résidences secondaires", fmt(row.get("residences_secondaires")))
    table.add_row("Logements vacants", fmt(row.get("logements_vacants")))
    table.add_row("Taux de vacance", fmt(row.get("taux_vacance"), "%"))
    table.add_row("Part rés. secondaires", fmt(row.get("taux_residences_sec"), "%"))
    table.add_row("Part propriétaires", fmt(row.get("part_proprietaires"), "%"))
    table.add_row("Revenu médian (UC)", fmt(row.get("revenu_median_uc"), "€/an"))
    table.add_row("Taux de pauvreté", fmt(row.get("taux_pauvrete"), "%"))
    table.add_row("Population active 15-64", fmt(row.get("pop_active_1564")))
    table.add_row("Taux chômage 15-64", fmt(row.get("taux_chomage_1564"), "%"))
    console.print(table)


@app.command("summary")
def summary(
    commune: str | None = typer.Option(None, "--commune", "-c"),
) -> None:
    """Print a cross-source (DVF + INSEE) market snapshot for a commune."""
    settings = get_settings()
    code = commune or settings.default_commune
    s = summarize_commune(code)

    console.print(
        f"[bold]Shadow Tester — synthèse marché[/] "
        f"[cyan]{s.nom_commune or code}[/] ({code})"
    )

    def money(v: float | None) -> str:
        return f"{v:,.0f} €".replace(",", " ") if v is not None else "-"

    def pct(v: float | None) -> str:
        return f"{v:.1f} %" if v is not None else "-"

    def num(v: float | None) -> str:
        return f"{v:,.0f}".replace(",", " ") if v is not None else "-"

    demo = Table(title="Démographie & revenus (INSEE)", show_header=False)
    demo.add_column("Indicator")
    demo.add_column("Value", justify="right")
    demo.add_row("Population", num(s.population))
    demo.add_row("Densité", num(s.densite_hab_km2) + " hab/km²" if s.densite_hab_km2 else "-")
    demo.add_row("Revenu médian / UC", money(s.revenu_median_uc))
    demo.add_row("Taux de vacance", pct(s.taux_vacance))
    demo.add_row("Part rés. secondaires", pct(s.taux_residences_sec))
    demo.add_row("Part propriétaires", pct(s.part_proprietaires))
    demo.add_row("Taux de chômage 15-64", pct(s.taux_chomage_1564))
    console.print(demo)

    market = Table(
        title=f"Marché immobilier DVF — {s.n_transactions} transactions"
        + (f" (année de référence {s.year_dvf})" if s.year_dvf else "")
    )
    market.add_column("Type")
    market.add_column("Médian €/m²", justify="right")
    market.add_column("Prix médian", justify="right")
    market.add_column("Affordability", justify="right")
    market.add_row(
        "Maison",
        money(s.median_prix_m2_maison),
        money(s.median_valeur_maison),
        f"{s.affordability_years_maison}× revenu/an" if s.affordability_years_maison else "-",
    )
    market.add_row(
        "Appartement",
        money(s.median_prix_m2_appartement),
        money(s.median_valeur_appartement),
        f"{s.affordability_years_appartement}× revenu/an"
        if s.affordability_years_appartement
        else "-",
    )
    console.print(market)

    if s.affordability_years_maison is not None:
        if s.affordability_years_maison < 6:
            console.print("[green]→ marché abordable[/] (< 6× revenu annuel médian)")
        elif s.affordability_years_maison < 9:
            console.print("[yellow]→ marché tendu[/] (6–9× revenu annuel)")
        else:
            console.print("[red]→ marché très tendu[/] (> 9× revenu annuel)")


@comps_app.command("find")
def comps_find(
    commune: str | None = typer.Option(None, "--commune", "-c", help="INSEE commune code."),
    type_local: str = typer.Option(
        ..., "--type", "-t", help="'Maison' or 'Appartement'.",
    ),
    surface: float = typer.Option(..., "--surface", "-s", help="Target built surface (m²)."),
    rooms: int | None = typer.Option(None, "--rooms", "-r", help="Number of main rooms."),
    budget: float | None = typer.Option(
        None, "--budget", "-b", help="Target total price in EUR (triggers a verdict vs the fourchette)."
    ),
    address: str | None = typer.Option(
        None,
        "--address",
        "-a",
        help="Exact address to geocode via the BAN for distance ranking "
        "(e.g. '12 rue des Alpes, 04100 Manosque').",
    ),
    lat: float | None = typer.Option(None, "--lat", help="Latitude (bypasses geocoding)."),
    lon: float | None = typer.Option(None, "--lon", help="Longitude (bypasses geocoding)."),
    street: str | None = typer.Option(
        None,
        "--street",
        help="Street/quartier keyword: substring match on DVF 'adresse_nom_voie'.",
    ),
    radius: float = typer.Option(
        5.0, "--radius", help="Distance radius (km) for the distance score."
    ),
    surface_tol: float = typer.Option(
        0.25, "--surface-tol", help="Surface tolerance as a fraction (0.25 = ±25%)."
    ),
    years: int = typer.Option(5, "--years", help="Max age (years) for DVF comps."),
    limit: int = typer.Option(10, "--limit", "-n", help="Max number of comps to return."),
) -> None:
    """Find DVF transactions comparable to a target bien."""
    settings = get_settings()
    code = commune or settings.default_commune

    # Resolve geographic anchor.
    anchor_lat, anchor_lon = lat, lon
    anchor_label: str | None = None
    if address and (lat is None or lon is None):
        try:
            result = geocode(address, citycode=code)
        except GeocodingError as exc:
            console.print(f"[red]Geocoding failed:[/] {exc}")
            raise typer.Exit(code=2) from exc
        if result is None:
            console.print(
                f"[yellow]BAN returned no match for {address!r}[/] — "
                "falling back to commune-wide search."
            )
        else:
            anchor_lat, anchor_lon = result.lat, result.lon
            anchor_label = result.label
            precision = "précis" if result.is_precise else f"approximatif ({result.feature_type})"
            console.print(
                f"[green]Geocoded[/] → {result.label} "
                f"(score {result.score:.2f}, {precision})"
            )

    try:
        target = Target(
            commune=code,
            type_local=type_local,
            surface=surface,
            rooms=rooms,
            budget=budget,
            address=address,
            lat=anchor_lat,
            lon=anchor_lon,
            street_keyword=street,
            surface_tol=surface_tol,
            radius_km=radius,
            max_years_old=years,
            limit=limit,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    result = find_comparables(target)

    # Target panel
    target_tbl = Table(title="Target", show_header=False)
    target_tbl.add_column("Field")
    target_tbl.add_column("Value")
    target_tbl.add_row("Commune", code)
    target_tbl.add_row("Type", target.type_local)
    target_tbl.add_row("Surface", f"{target.surface:.0f} m² (±{target.surface_tol*100:.0f}%)")
    if target.rooms:
        target_tbl.add_row("Pièces", str(target.rooms))
    if target.budget:
        target_tbl.add_row("Budget", f"{target.budget:,.0f} €".replace(",", " "))
    if anchor_label:
        target_tbl.add_row("Anchor (BAN)", anchor_label)
    elif anchor_lat is not None and anchor_lon is not None:
        target_tbl.add_row("Anchor", f"({anchor_lat:.5f}, {anchor_lon:.5f})")
    elif target.street_keyword:
        target_tbl.add_row("Anchor", f"street~{target.street_keyword!r}")
    else:
        target_tbl.add_row("Anchor", "[dim]commune-wide[/]")
    console.print(target_tbl)

    if not result.comps:
        console.print(
            "[yellow]No comparable transactions found[/] with these filters. "
            "Try widening --surface-tol or --years, or drop --street / --address."
        )
        raise typer.Exit(code=1)

    # Comps table
    comps_tbl = Table(
        title=f"Top {len(result.comps)} comparables "
        f"(confidence: {result.confidence})"
    )
    comps_tbl.add_column("Score", justify="right")
    comps_tbl.add_column("Date")
    comps_tbl.add_column("Dist.", justify="right")
    comps_tbl.add_column("Surface", justify="right")
    comps_tbl.add_column("Pièces", justify="right")
    comps_tbl.add_column("État")
    comps_tbl.add_column("Adresse")
    comps_tbl.add_column("Prix", justify="right")
    comps_tbl.add_column("€/m²", justify="right")

    _CONDITION_COLORS = {
        "brut": "red",
        "a_renover": "dark_orange",
        "partiel": "yellow",
        "renove": "green",
    }

    def fmt_eur(v: float | None) -> str:
        return f"{v:,.0f} €".replace(",", " ") if v is not None else "-"

    def fmt_condition(c_val: str | None, c_src: str | None) -> str:
        if c_val is None:
            return "[dim]-[/]"
        color = _CONDITION_COLORS.get(c_val, "")
        label = c_val.replace("_", " ")
        src = f" ({c_src})" if c_src else ""
        return f"[{color}]{label}{src}[/]" if color else f"{label}{src}"

    for c in result.comps:
        comps_tbl.add_row(
            f"{c.total_score:.2f}",
            c.date_mutation,
            f"{c.distance_km:.2f} km" if c.distance_km is not None else "-",
            f"{c.surface:.0f} m²",
            str(c.rooms) if c.rooms is not None else "-",
            fmt_condition(c.condition, c.condition_source),
            c.adresse,
            fmt_eur(c.valeur_fonciere),
            fmt_eur(c.prix_m2),
        )
    console.print(comps_tbl)

    # Aggregate / suggested price fourchette
    if result.median_prix_m2 is not None:
        agg = Table(title="Fourchette de prix suggérée", show_header=False)
        agg.add_column("Metric")
        agg.add_column("Value", justify="right")
        agg.add_row("P25 €/m²", fmt_eur(result.p25_prix_m2))
        agg.add_row("Médian €/m²", fmt_eur(result.median_prix_m2))
        agg.add_row("P75 €/m²", fmt_eur(result.p75_prix_m2))
        agg.add_row("Prix bas (P25)", fmt_eur(result.suggested_price_low))
        agg.add_row("Prix médian", fmt_eur(result.suggested_price_mid))
        agg.add_row("Prix haut (P75)", fmt_eur(result.suggested_price_high))
        console.print(agg)

    if result.verdict:
        color = (
            "red" if "au-dessus" in result.verdict
            else "green" if "dans" in result.verdict
            else "yellow"
        )
        console.print(f"[bold {color}]→ {result.verdict}[/]")


# ---------- Notes subcommands ----------


@notes_app.command("add")
def notes_add(
    condition: str = typer.Option(
        ...,
        "--condition",
        "-c",
        help=f"Property condition ({', '.join(ALLOWED_CONDITIONS)}). Aliases accepted.",
    ),
    source: str = typer.Option(
        ...,
        "--source",
        "-s",
        help=f"How you know ({', '.join(ALLOWED_SOURCES)}).",
    ),
    id_mutation: str | None = typer.Option(None, "--id-mutation", "-m", help="DVF mutation ID."),
    adresse: str | None = typer.Option(None, "--address", "-a", help="Free-form address."),
    commune: str | None = typer.Option(None, "--commune", help="INSEE commune code."),
    lat: float | None = typer.Option(None, "--lat", help="Latitude."),
    lon: float | None = typer.Option(None, "--lon", help="Longitude."),
    travaux: float | None = typer.Option(None, "--travaux", help="Estimated renovation cost (EUR TTC)."),
    prix_annonce: float | None = typer.Option(None, "--prix-annonce", help="Asking price seen in listing."),
    note: str | None = typer.Option(None, "--note", "-n", help="Free-form observation."),
) -> None:
    """Add a note (condition, travaux, observations) on a property."""
    if not id_mutation and not adresse:
        raise typer.BadParameter(
            "At least one of --id-mutation or --address is required."
        )
    try:
        pn = PropertyNote(
            condition=condition,
            source=source,
            id_mutation=id_mutation,
            adresse=adresse,
            commune=commune,
            lat=lat,
            lon=lon,
            travaux_estime=travaux,
            prix_annonce=prix_annonce,
            note=note,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    saved = add_note(pn)
    console.print(
        f"[green]Note #{saved.id} ajoutée[/] — "
        f"condition=[bold]{saved.condition}[/], source={saved.source}"
    )
    if saved.id_mutation:
        console.print(f"  mutation: {saved.id_mutation}")
    if saved.adresse:
        console.print(f"  adresse:  {saved.adresse}")


@notes_app.command("list")
def notes_list(
    commune: str | None = typer.Option(None, "--commune", "-c", help="Filter by commune."),
    condition: str | None = typer.Option(None, "--condition", help="Filter by condition."),
    limit: int = typer.Option(50, "--limit", "-n", help="Max notes to display."),
) -> None:
    """List property notes, most recent first."""
    results = list_notes(commune=commune, condition=condition, limit=limit)
    if not results:
        console.print("[yellow]Aucune note trouvée.[/]")
        return

    tbl = Table(title=f"Notes ({len(results)})")
    tbl.add_column("#", justify="right")
    tbl.add_column("Condition")
    tbl.add_column("Source")
    tbl.add_column("Mutation")
    tbl.add_column("Adresse")
    tbl.add_column("Commune")
    tbl.add_column("Travaux", justify="right")
    tbl.add_column("Prix ann.", justify="right")
    tbl.add_column("Mis à jour")

    def fmt_eur(v: float | None) -> str:
        return f"{v:,.0f} €".replace(",", " ") if v is not None else "-"

    for n in results:
        tbl.add_row(
            str(n.id),
            n.condition.replace("_", " "),
            n.source,
            n.id_mutation or "-",
            (n.adresse or "-")[:40],
            n.commune or "-",
            fmt_eur(n.travaux_estime),
            fmt_eur(n.prix_annonce),
            (n.updated_at or "")[:10],
        )
    console.print(tbl)


@notes_app.command("show")
def notes_show(
    note_id: int = typer.Argument(..., help="Note ID to display."),
) -> None:
    """Show detailed information about a single note."""
    n = get_note(note_id)
    if n is None:
        console.print(f"[red]Note #{note_id} introuvable.[/]")
        raise typer.Exit(code=1)

    tbl = Table(title=f"Note #{n.id}", show_header=False)
    tbl.add_column("Field")
    tbl.add_column("Value")
    tbl.add_row("Condition", n.condition.replace("_", " "))
    tbl.add_row("Source", n.source)
    if n.id_mutation:
        tbl.add_row("Mutation DVF", n.id_mutation)
    if n.adresse:
        tbl.add_row("Adresse", n.adresse)
    if n.commune:
        tbl.add_row("Commune", n.commune)
    if n.lat is not None and n.lon is not None:
        tbl.add_row("Coordonnées", f"{n.lat:.5f}, {n.lon:.5f}")
    if n.travaux_estime is not None:
        tbl.add_row("Travaux estimés", f"{n.travaux_estime:,.0f} €".replace(",", " "))
    if n.prix_annonce is not None:
        tbl.add_row("Prix annonce", f"{n.prix_annonce:,.0f} €".replace(",", " "))
    if n.note:
        tbl.add_row("Note", n.note)
    tbl.add_row("Créé le", n.created_at or "-")
    tbl.add_row("Mis à jour", n.updated_at or "-")
    console.print(tbl)


@notes_app.command("delete")
def notes_delete(
    note_id: int = typer.Argument(..., help="Note ID to delete."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete a property note."""
    n = get_note(note_id)
    if n is None:
        console.print(f"[red]Note #{note_id} introuvable.[/]")
        raise typer.Exit(code=1)

    if not yes:
        console.print(
            f"Supprimer la note #{note_id} ({n.condition}, "
            f"{n.adresse or n.id_mutation}) ?"
        )
        confirm = typer.confirm("Confirmer ?")
        if not confirm:
            console.print("[dim]Annulé.[/]")
            return

    if delete_note(note_id):
        console.print(f"[green]Note #{note_id} supprimée.[/]")
    else:
        console.print(f"[red]Échec de la suppression de #{note_id}.[/]")


# ---------- Listings subcommands ----------


@listings_app.command("add")
def listings_add_cmd(
    url: str | None = typer.Option(
        None, "--url", "-u",
        help="Listing URL — the page will be fetched and parsed automatically.",
    ),
    html_file: Path | None = typer.Option(
        None, "--html-file", "-f",
        help="Path to a saved HTML file to parse (LBC, SeLoger, etc.).",
    ),
    price: float | None = typer.Option(None, "--price", "-p", help="Asking price (EUR)."),
    surface: float | None = typer.Option(None, "--surface", "-s", help="Surface (m²)."),
    rooms: int | None = typer.Option(None, "--rooms", "-r", help="Number of rooms."),
    type_local: str | None = typer.Option(
        None, "--type", "-t", help="'Maison' or 'Appartement'.",
    ),
    commune: str | None = typer.Option(None, "--commune", "-c", help="INSEE commune code."),
    address: str | None = typer.Option(None, "--address", "-a", help="Approximate address."),
    condition: str | None = typer.Option(
        None, "--condition",
        help="Property condition (brut/a_renover/partiel/renove). Omit to auto-detect from description.",
    ),
    source_name: str | None = typer.Option(
        None, "--source", help="Platform name (leboncoin/seloger/pap/autre).",
    ),
    title: str | None = typer.Option(None, "--title", help="Listing title."),
    description: str | None = typer.Option(None, "--description", "-d", help="Listing description text."),
    analyze_photos: bool = typer.Option(
        False, "--analyze-photos", "--vision",
        help="Use Claude Vision to detect condition from listing photos (requires API key).",
    ),
    note: str | None = typer.Option(None, "--note", "-n", help="Free-form observation."),
) -> None:
    """Capture a listing from a URL, saved HTML file, or manual fields.

    The simplest usage is just: listings add --url <paste-url> --commune 04112
    """
    parsed_html_source: str | None = None
    parsed_description: str | None = None
    raw_html: str | None = None
    parsed_lat: float | None = None
    parsed_lon: float | None = None
    parsed_images: list[str] = []

    # Mode 1: URL fetch — the simplest path.
    if url is not None and html_file is None:
        console.print(f"[cyan]Fetching[/] {url} ...")
        try:
            raw_html = fetch_listing_html(url)
        except FetchError as exc:
            console.print(f"[red]Fetch failed:[/] {exc}")
            console.print(
                "[dim]Tip: save the page as HTML and use --html-file instead.[/]"
            )
            raise typer.Exit(code=2) from exc
        parsed = parse_listing_html(raw_html)
        console.print(
            f"[green]Parsed[/] title={parsed.title!r}, price={parsed.price}, "
            f"surface={parsed.surface}, rooms={parsed.rooms}, "
            f"type={parsed.type_local}, source={parsed.source}"
        )
        price = price or parsed.price
        surface = surface or parsed.surface
        rooms = rooms if rooms is not None else parsed.rooms
        type_local = type_local or parsed.type_local
        address = address or parsed.address
        title = title or parsed.title
        parsed_description = parsed.description
        parsed_html_source = parsed.source
        parsed_lat = parsed.lat
        parsed_lon = parsed.lon
        parsed_images = parsed.images

    # Mode 2: local HTML file.
    elif html_file is not None:
        if not html_file.exists():
            console.print(f"[red]File not found:[/] {html_file}")
            raise typer.Exit(code=1)
        raw_html = html_file.read_text(encoding="utf-8", errors="replace")
        parsed = parse_listing_html(raw_html)
        console.print(
            f"[green]Parsed[/] {html_file.name}: "
            f"title={parsed.title!r}, price={parsed.price}, "
            f"surface={parsed.surface}, rooms={parsed.rooms}, "
            f"type={parsed.type_local}, source={parsed.source}"
        )
        price = price or parsed.price
        surface = surface or parsed.surface
        rooms = rooms if rooms is not None else parsed.rooms
        type_local = type_local or parsed.type_local
        address = address or parsed.address
        title = title or parsed.title
        parsed_description = parsed.description
        parsed_html_source = parsed.source
        parsed_lat = parsed.lat
        parsed_lon = parsed.lon
        parsed_images = parsed.images

    # Mode 3: fully manual — no parsing needed.

    lat = parsed_lat
    lon = parsed_lon

    final_description = description or parsed_description
    final_source = source_name or parsed_html_source or "autre"

    # Auto-detect condition from description if not provided.
    cond_val = condition
    cond_source = "manual" if condition else None
    cond_confidence = 1.0 if condition else None
    cond_rationale: str | None = None
    if not cond_val and final_description:
        detection = detect_condition(final_description)
        cond_val = detection.condition
        cond_source = "keywords"
        cond_confidence = detection.confidence
        cond_rationale = detection.rationale
        if cond_val != "inconnu":
            console.print(
                f"[cyan]Condition auto-détectée:[/] {cond_val} "
                f"(confiance {cond_confidence:.0%}) — {cond_rationale}"
            )
        else:
            console.print(f"[dim]Condition non détectée: {cond_rationale}[/]")

    # Vision analysis: override/improve keyword detection when photos are available.
    if analyze_photos and parsed_images and not condition:
        console.print(
            f"[cyan]Analyse photo Claude Vision[/] ({len(parsed_images)} image(s) trouvées)…"
        )
        try:
            vision_result = run_vision_analysis(
                parsed_images,
                description=final_description,
            )
            vision_det = vision_to_condition_detection(vision_result)
            # Vision takes priority over keywords when it's more confident.
            if (
                vision_det.condition != "inconnu"
                and (cond_val in (None, "inconnu") or vision_det.confidence > (cond_confidence or 0))
            ):
                cond_val = vision_det.condition
                cond_source = "vision"
                cond_confidence = vision_det.confidence
                cond_rationale = vision_det.rationale
            console.print(
                f"[green]Vision:[/] {vision_result.condition} "
                f"(confiance {vision_result.confidence:.0%}, "
                f"{vision_result.photos_analyzed} photo(s)) — {vision_result.rationale}"
            )
        except VisionError as exc:
            console.print(f"[yellow]Vision non disponible:[/] {exc}")
    elif analyze_photos and not parsed_images:
        console.print("[yellow]--analyze-photos: aucune photo trouvée dans l'annonce.[/]")

    try:
        listing = Listing(
            source=final_source,
            url=url,
            title=title,
            description=final_description,
            price_asked=price,
            surface=surface,
            rooms=rooms,
            type_local=type_local,
            commune=commune,
            adresse_approx=address,
            lat=lat,
            lon=lon,
            condition=cond_val,
            condition_source=cond_source,
            condition_confidence=cond_confidence,
            condition_rationale=cond_rationale,
            raw_html=raw_html,
            notes=note,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    saved = add_listing(listing)
    console.print(
        f"[green]Listing #{saved.id} ajouté[/] — "
        f"{saved.type_local or '?'} {saved.surface or '?'} m², "
        f"{saved.price_asked:,.0f} €".replace(",", " ")
        if saved.price_asked else
        f"[green]Listing #{saved.id} ajouté[/]"
    )


@listings_app.command("list")
def listings_list_cmd(
    commune: str | None = typer.Option(None, "--commune", "-c", help="Filter by commune."),
    condition: str | None = typer.Option(None, "--condition", help="Filter by condition."),
    source: str | None = typer.Option(None, "--source", help="Filter by platform."),
    matched: bool = typer.Option(False, "--matched", help="Only show DVF-matched listings."),
    unmatched: bool = typer.Option(False, "--unmatched", help="Only show unmatched listings."),
    limit: int = typer.Option(50, "--limit", "-n", help="Max results."),
) -> None:
    """List captured listings."""
    results = list_listings(
        commune=commune, condition=condition, source=source,
        matched_only=matched, unmatched_only=unmatched, limit=limit,
    )
    if not results:
        console.print("[yellow]Aucune annonce trouvée.[/]")
        return

    tbl = Table(title=f"Annonces ({len(results)})")
    tbl.add_column("#", justify="right")
    tbl.add_column("Source")
    tbl.add_column("Type")
    tbl.add_column("Surface", justify="right")
    tbl.add_column("Prix", justify="right")
    tbl.add_column("État")
    tbl.add_column("Commune")
    tbl.add_column("Adresse")
    tbl.add_column("DVF match")
    tbl.add_column("Vu le")

    def fmt_eur(v: float | None) -> str:
        return f"{v:,.0f} €".replace(",", " ") if v is not None else "-"

    for l in results:  # noqa: E741
        tbl.add_row(
            str(l.id),
            l.source or "-",
            l.type_local or "-",
            f"{l.surface:.0f} m²" if l.surface else "-",
            fmt_eur(l.price_asked),
            (l.condition or "?").replace("_", " "),
            l.commune or "-",
            (l.adresse_approx or "-")[:35],
            l.matched_mutation_id or "-",
            (l.first_seen or "")[:10],
        )
    console.print(tbl)


@listings_app.command("show")
def listings_show_cmd(
    listing_id: int = typer.Argument(..., help="Listing ID."),
) -> None:
    """Show detailed information about a listing."""
    l = get_listing(listing_id)  # noqa: E741
    if l is None:
        console.print(f"[red]Annonce #{listing_id} introuvable.[/]")
        raise typer.Exit(code=1)

    tbl = Table(title=f"Annonce #{l.id}", show_header=False)
    tbl.add_column("Field")
    tbl.add_column("Value")

    if l.title:
        tbl.add_row("Titre", l.title)
    tbl.add_row("Source", l.source or "-")
    if l.url:
        tbl.add_row("URL", l.url)
    if l.type_local:
        tbl.add_row("Type", l.type_local)
    if l.surface:
        tbl.add_row("Surface", f"{l.surface:.0f} m²")
    if l.rooms:
        tbl.add_row("Pièces", str(l.rooms))
    if l.price_asked:
        tbl.add_row("Prix demandé", f"{l.price_asked:,.0f} €".replace(",", " "))
    if l.condition:
        conf = f" ({l.condition_confidence:.0%})" if l.condition_confidence else ""
        tbl.add_row("État", f"{l.condition.replace('_', ' ')}{conf} [{l.condition_source}]")
    if l.condition_rationale:
        tbl.add_row("Rationale", l.condition_rationale)
    if l.commune:
        tbl.add_row("Commune", l.commune)
    if l.adresse_approx:
        tbl.add_row("Adresse", l.adresse_approx)
    if l.lat is not None and l.lon is not None:
        tbl.add_row("Coordonnées", f"{l.lat:.5f}, {l.lon:.5f}")
    if l.matched_mutation_id:
        tbl.add_row("DVF match", f"{l.matched_mutation_id} (score {l.match_score:.2f})")
    tbl.add_row("Premier vu", l.first_seen or "-")
    tbl.add_row("Dernier vu", l.last_seen or "-")
    if l.disappeared_at:
        tbl.add_row("Disparu le", l.disappeared_at)
    if l.description:
        desc = l.description[:300] + ("..." if len(l.description) > 300 else "")
        tbl.add_row("Description", desc)
    if l.notes:
        tbl.add_row("Notes", l.notes)
    tbl.add_row("Créé le", l.created_at or "-")
    tbl.add_row("Mis à jour", l.updated_at or "-")
    console.print(tbl)


@listings_app.command("delete")
def listings_delete_cmd(
    listing_id: int = typer.Argument(..., help="Listing ID to delete."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete a captured listing."""
    l = get_listing(listing_id)  # noqa: E741
    if l is None:
        console.print(f"[red]Annonce #{listing_id} introuvable.[/]")
        raise typer.Exit(code=1)

    if not yes:
        console.print(
            f"Supprimer l'annonce #{listing_id} ({l.type_local or '?'}, "
            f"{l.adresse_approx or l.title or '?'}) ?"
        )
        confirm = typer.confirm("Confirmer ?")
        if not confirm:
            console.print("[dim]Annulé.[/]")
            return

    if delete_listing(listing_id):
        console.print(f"[green]Annonce #{listing_id} supprimée.[/]")
    else:
        console.print(f"[red]Échec de la suppression de #{listing_id}.[/]")


@listings_app.command("match")
def listings_match_cmd(
    commune: str | None = typer.Option(None, "--commune", "-c", help="Limit matching to this commune."),
    listing_id: int | None = typer.Option(None, "--id", help="Match a single listing by ID."),
    auto_only: bool = typer.Option(
        False, "--auto", help="Only apply auto-matches (score ≥ 0.80), skip review.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Accept all suggested matches without prompting."),
) -> None:
    """Match unmatched listings against DVF transactions.

    Without --id, runs on all unmatched listings (optionally filtered by commune).
    Shows candidates and lets you confirm or skip each suggested match.
    """
    if listing_id is not None:
        # Single-listing mode.
        lst = get_listing(listing_id)
        if lst is None:
            console.print(f"[red]Annonce #{listing_id} introuvable.[/]")
            raise typer.Exit(code=1)
        if lst.matched_mutation_id:
            console.print(
                f"[yellow]Annonce #{listing_id} déjà matchée[/] → {lst.matched_mutation_id} "
                f"(score {lst.match_score:.2f})"
            )
            return
        results = [match_listing(lst)]
    else:
        console.print("[cyan]Recherche de matches DVF[/] pour les annonces non matchées…")
        results = match_all_unmatched(commune=commune)

    if not results:
        console.print("[yellow]Aucun match trouvé.[/]")
        return

    applied = 0
    skipped = 0

    for mr in results:
        if mr.best is None:
            continue

        best = mr.best
        lst = get_listing(mr.listing_id)
        if lst is None:
            continue

        # Display the match.
        console.print()
        console.print(
            f"[bold]Annonce #{mr.listing_id}[/] — "
            f"{lst.type_local or '?'} {lst.surface or '?'} m², "
            + (f"{lst.price_asked:,.0f} €".replace(",", " ") if lst.price_asked else "prix ?")
            + f" ({lst.commune or '?'})"
        )

        tbl = Table(title=f"{len(mr.candidates)} candidat(s) DVF")
        tbl.add_column("Score", justify="right")
        tbl.add_column("Date")
        tbl.add_column("Prix DVF", justify="right")
        tbl.add_column("Surface", justify="right")
        tbl.add_column("Δ prix", justify="right")
        tbl.add_column("Délai", justify="right")
        tbl.add_column("Mutation")

        def fmt_eur(v: float | None) -> str:
            return f"{v:,.0f} €".replace(",", " ") if v is not None else "-"

        for i, cand in enumerate(mr.candidates[:5]):
            score_color = "green" if cand.score >= AUTO_MATCH_THRESHOLD else (
                "yellow" if cand.score >= SUGGEST_THRESHOLD else "dim"
            )
            delta = f"{cand.price_delta_pct:+.1f}%" if cand.price_delta_pct is not None else "-"
            days = f"{cand.days_to_sale}j" if cand.days_to_sale is not None else "-"
            marker = " ★" if i == 0 else ""
            tbl.add_row(
                f"[{score_color}]{cand.score:.2f}{marker}[/{score_color}]",
                cand.date_mutation,
                fmt_eur(cand.valeur_fonciere),
                f"{cand.surface:.0f} m²",
                delta,
                days,
                cand.id_mutation[:20],
            )
        console.print(tbl)

        # Decision logic.
        if mr.auto_matched:
            console.print(
                f"[green]Auto-match[/] score={best.score:.2f} ≥ {AUTO_MATCH_THRESHOLD}"
            )
            if yes or auto_only:
                accept = True
            else:
                accept = typer.confirm("Accepter ce match ?", default=True)
        elif auto_only:
            console.print(f"[dim]Score {best.score:.2f} < {AUTO_MATCH_THRESHOLD} — ignoré (--auto)[/]")
            skipped += 1
            continue
        else:
            console.print(
                f"[yellow]Match suggéré[/] score={best.score:.2f} "
                f"(seuil auto={AUTO_MATCH_THRESHOLD})"
            )
            accept = True if yes else typer.confirm("Accepter ce match ?", default=False)

        if accept:
            _update_listing(
                mr.listing_id,
                matched_mutation_id=best.id_mutation,
                match_score=best.score,
            )
            console.print(
                f"  [green]✓[/] Annonce #{mr.listing_id} → {best.id_mutation} "
                f"(Δ prix {best.price_delta_pct:+.1f}%, délai {best.days_to_sale}j)"
                if best.price_delta_pct is not None and best.days_to_sale is not None
                else f"  [green]✓[/] Annonce #{mr.listing_id} → {best.id_mutation}"
            )
            applied += 1
        else:
            skipped += 1
            console.print("  [dim]Ignoré.[/]")

    console.print()
    console.print(
        f"[bold]Résultat:[/] {applied} match(es) appliqué(s), {skipped} ignoré(s)."
    )


@listings_app.command("stats")
def listings_stats_cmd(
    commune: str | None = typer.Option(None, "--commune", "-c", help="Filter by commune."),
    type_local: str | None = typer.Option(
        None, "--type", "-t", help="Filter: 'Maison' or 'Appartement'.",
    ),
) -> None:
    """Show aggregate listing stats by property condition.

    Displays count, median asking price, €/m², negotiation margin,
    and time-on-market for each condition bucket (brut, à rénover,
    partiel, rénové, inconnu).
    """
    stats = compute_listing_stats(commune=commune, type_local=type_local)

    if stats.total_listings == 0:
        console.print("[yellow]Aucune annonce trouvée.[/]")
        return

    title = "Statistiques par état"
    if commune:
        title += f" — commune {commune}"
    if type_local:
        title += f" — {type_local}"
    title += f" ({stats.total_listings} annonces, {stats.total_matched} matchées DVF)"

    def fmt_eur(v: float | None) -> str:
        return f"{v:,.0f} €".replace(",", " ") if v is not None else "-"

    def fmt_pct(v: float | None) -> str:
        if v is None:
            return "-"
        color = "green" if v < 0 else "red"
        return f"[{color}]{v:+.1f}%[/{color}]"

    def fmt_days(v: int | None) -> str:
        if v is None:
            return "-"
        return f"{v}j"

    _CONDITION_LABELS = {
        "brut": "Brut",
        "a_renover": "À rénover",
        "partiel": "Partiel",
        "renove": "Rénové",
        "inconnu": "Inconnu",
    }

    tbl = Table(title=title)
    tbl.add_column("État")
    tbl.add_column("N", justify="right")
    tbl.add_column("Matchées", justify="right")
    tbl.add_column("Prix demandé\n(médian)", justify="right")
    tbl.add_column("€/m² demandé\n(médian)", justify="right")
    tbl.add_column("€/m² vendu\n(médian)", justify="right")
    tbl.add_column("Négo\n(médian)", justify="right")
    tbl.add_column("Délai\n(médian)", justify="right")

    _CONDITION_COLORS = {
        "brut": "red",
        "a_renover": "dark_orange",
        "partiel": "yellow",
        "renove": "green",
    }

    for b in stats.buckets:
        label = _CONDITION_LABELS.get(b.condition, b.condition)
        color = _CONDITION_COLORS.get(b.condition, "dim")
        tbl.add_row(
            f"[{color}]{label}[/{color}]",
            str(b.count),
            str(b.matched_count),
            fmt_eur(b.median_price_asked),
            fmt_eur(b.median_prix_m2_asked),
            fmt_eur(b.median_prix_m2_sold),
            fmt_pct(b.median_price_delta_pct),
            fmt_days(b.median_days_to_sale),
        )
    console.print(tbl)

    # Summary insight.
    matched_buckets = [b for b in stats.buckets if b.matched_count >= 2]
    if len(matched_buckets) >= 2:
        by_delta = sorted(
            matched_buckets,
            key=lambda b: b.median_price_delta_pct or 0,
        )
        best = by_delta[0]
        worst = by_delta[-1]
        if best.median_price_delta_pct is not None and worst.median_price_delta_pct is not None:
            console.print(
                f"\n[bold]Insight:[/] Les biens [green]{_CONDITION_LABELS.get(best.condition, best.condition)}[/green] "
                f"se négocient à {best.median_price_delta_pct:+.1f}% vs demandé, "
                f"contre {worst.median_price_delta_pct:+.1f}% pour les "
                f"[red]{_CONDITION_LABELS.get(worst.condition, worst.condition)}[/red]."
            )


@app.command("info")
def info() -> None:
    """Show resolved configuration (paths, URLs)."""
    settings = get_settings()
    console.print("[bold]Shadow Tester[/] — resolved config")
    console.print(f"  default_commune = [cyan]{settings.default_commune}[/]")
    console.print(f"  cache_dir       = {settings.cache_dir}")
    console.print(f"  db_path         = {settings.db_path}")
    console.print(f"  dvf_base_url    = {settings.dvf_base_url}")


if __name__ == "__main__":
    app()
