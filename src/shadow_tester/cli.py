"""Typer-based CLI for Shadow Tester."""

from __future__ import annotations

import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from shadow_tester.config import get_settings
from shadow_tester.dvf import compute_commune_stats, ingest_commune_years
from shadow_tester.insee import (
    ingest_from_file,
    ingest_from_url,
    load_commune,
    summarize_commune,
)

app = typer.Typer(
    help="Shadow Tester — demand analyzer for real-estate projects based on public data.",
    no_args_is_help=True,
)
dvf_app = typer.Typer(help="DVF (Demandes de Valeurs Foncières) commands.", no_args_is_help=True)
insee_app = typer.Typer(help="INSEE commune indicators commands.", no_args_is_help=True)
app.add_typer(dvf_app, name="dvf")
app.add_typer(insee_app, name="insee")

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
