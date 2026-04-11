"""Mapping between raw INSEE column names and our normalised schema.

The INSEE "Dossier Complet" uses variable names suffixed with the RP / FILOSOFI
vintage year (e.g. ``P20_POP`` for the 2020 population census, ``MED20`` for
the 2020 median disposable income). Because the suffix changes each annual
release, we store the year-suffixed name as a template with ``{yy}`` and let
:class:`INSEEMapping` resolve it against a concrete year.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class INSEEMapping:
    """A mapping from our internal field names to INSEE column templates.

    Each template may contain ``{yy}`` (two-digit year) or ``{yyyy}`` (four-digit)
    placeholders which are resolved against :meth:`for_year`.

    ``field_map`` values are *lists* of fallback column names: the first column
    that exists in the loaded CSV is used. This is how we survive INSEE's
    occasional column renames between releases.
    """

    field_map: dict[str, list[str]]
    metadata_columns: dict[str, str] = field(
        default_factory=lambda: {
            "code_commune": "CODGEO",
            "nom_commune": "LIBGEO",
            "code_departement": "DEP",
            "code_region": "REG",
        }
    )
    superficie_column: str = "SUPERF"

    def for_year(self, year: int) -> INSEEMapping:
        """Resolve ``{yy}`` / ``{yyyy}`` placeholders against ``year``."""
        yy = f"{year % 100:02d}"
        yyyy = str(year)

        resolved: dict[str, list[str]] = {}
        for key, templates in self.field_map.items():
            resolved[key] = [t.format(yy=yy, yyyy=yyyy) for t in templates]
        return INSEEMapping(
            field_map=resolved,
            metadata_columns=dict(self.metadata_columns),
            superficie_column=self.superficie_column,
        )


# Default mapping for the "Dossier Complet" commune file.
# Each entry lists primary + legacy column names so that releases 2018–2024
# can all be parsed without modification.
DEFAULT_MAPPING = INSEEMapping(
    field_map={
        # Population
        "population":            ["P{yy}_POP"],
        # Logement
        "logements_total":       ["P{yy}_LOG"],
        "residences_principales": ["P{yy}_RP"],
        "residences_secondaires": ["P{yy}_RSECOCC"],
        "logements_vacants":     ["P{yy}_LOGVAC"],
        "part_proprietaires_rp": ["P{yy}_RP_PROP"],
        # Revenus (FILOSOFI)
        "revenu_median_uc":      ["MED{yy}", "MEDIAN{yy}"],
        "taux_pauvrete":         ["TP60{yy}"],
        # Emploi
        "pop_active_1564":       ["P{yy}_ACT1564", "P{yy}_POP1564_ACT"],
        "chom_1564":             ["P{yy}_CHOM1564"],
        "pop_1564":              ["P{yy}_POP1564"],
    },
)
