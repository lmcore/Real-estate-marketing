"""Typer-based CLI for Shadow Tester."""

from __future__ import annotations

import logging

import typer
from rich.console import Console
from rich.table import Table

from shadow_tester.config import get_settings
from shadow_tester.dvf import compute_commune_stats, ingest_commune_years

app = typer.Typer(
    help="Shadow Tester — demand analyzer for real-estate projects based on public data.",
    no_args_is_help=True,
)
dvf_app = typer.Typer(help="DVF (Demandes de Valeurs Foncières) commands.", no_args_is_help=True)
app.add_typer(dvf_app, name="dvf")

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
