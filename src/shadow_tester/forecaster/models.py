"""Dataclasses for the forecaster — profit-margin calculation for buy-renovate-sell."""

from __future__ import annotations

from dataclasses import dataclass, field

# ── French MDB (marchand de biens) cost defaults ──────────────────────────
# When the MDB commits to reselling within 5 years, droits de mutation drop
# to ~0.715 % (instead of ~5.8 % for a particulier). Add notaire émoluments
# and administrative costs for a total of ~2.5 %.
DEFAULT_FRAIS_NOTAIRE_PCT = 0.025

# TVA sur marge: 20 % on (resale − purchase), applicable when the MDB is
# subject to VAT on the margin (régime de droit commun for ancien).
DEFAULT_TVA_MARGE_PCT = 0.20

# Monthly carrying cost as a percentage of total investment (purchase + frais
# + travaux). Covers loan interest, insurance, property tax pro-rata, and
# miscellaneous. Typical range: 0.3 %–0.8 % / month.
DEFAULT_PORTAGE_MENSUEL_PCT = 0.005

# Optional agency commission at resale (% of resale price). Set to 0 if
# selling directly (particulier à particulier) or via notaire.
DEFAULT_FRAIS_AGENCE_PCT = 0.0


@dataclass
class ForecastParams:
    """User-provided inputs for a profit forecast.

    Only ``commune``, ``type_local``, ``surface`` and ``prix_achat`` are
    strictly required. The rest have sensible defaults for a French MDB.
    """

    # Property identification
    commune: str
    type_local: str                          # Maison / Appartement
    surface: float                           # m² habitable
    prix_achat: float                        # purchase price (EUR)

    # Optional property details (for more accurate comps lookup)
    rooms: int | None = None
    surface_terrain: float | None = None     # lot size m² (Maison only)
    lat: float | None = None
    lon: float | None = None
    address: str | None = None
    street_keyword: str | None = None

    # Renovation
    condition_achat: str = "a_renover"       # current condition
    condition_revente: str = "renove"         # target condition after works
    travaux: float = 0.0                     # renovation cost TTC (EUR)

    # Cost parameters (MDB defaults)
    frais_notaire_pct: float = DEFAULT_FRAIS_NOTAIRE_PCT
    tva_marge_pct: float = DEFAULT_TVA_MARGE_PCT
    portage_mois: int = 12                   # expected holding period (months)
    portage_mensuel_pct: float = DEFAULT_PORTAGE_MENSUEL_PCT
    frais_agence_pct: float = DEFAULT_FRAIS_AGENCE_PCT

    # Comps tuning
    radius_km: float = 5.0
    max_years_old: int = 5
    comps_limit: int = 10

    # Metadata
    label: str | None = None                 # user-chosen name for this scenario

    def __post_init__(self) -> None:
        self.commune = self.commune.zfill(5)
        if self.type_local not in {"Maison", "Appartement"}:
            raise ValueError(
                f"Unsupported type_local {self.type_local!r} "
                "(expected Maison or Appartement)"
            )
        if self.surface <= 0:
            raise ValueError(f"Surface must be positive, got {self.surface}")
        if self.prix_achat <= 0:
            raise ValueError(f"Prix d'achat must be positive, got {self.prix_achat}")
        if self.travaux < 0:
            raise ValueError(f"Travaux must be >= 0, got {self.travaux}")
        if self.portage_mois < 0:
            raise ValueError(f"Portage months must be >= 0, got {self.portage_mois}")


@dataclass
class ForecastResult:
    """Full profit-margin breakdown for a buy-renovate-sell scenario."""

    params: ForecastParams

    # ── Investment breakdown ──
    prix_achat: float = 0.0
    frais_notaire: float = 0.0
    travaux: float = 0.0
    frais_portage: float = 0.0               # total carrying cost over holding period
    total_investissement: float = 0.0

    # ── Resale estimate (from comps engine) ──
    prix_revente_low: float | None = None    # P25 * surface
    prix_revente_mid: float | None = None    # median * surface
    prix_revente_high: float | None = None   # P75 * surface
    prix_m2_median: float | None = None      # median €/m² from comps
    n_comps: int = 0
    confidence: str = "low"

    # ── Margins (computed for the median scenario) ──
    frais_agence: float = 0.0                # agency fee at resale
    tva_sur_marge: float = 0.0               # TVA on (resale − purchase)
    marge_brute: float | None = None         # resale − total_investissement
    marge_nette: float | None = None         # brute − TVA − agence
    roi_pct: float | None = None             # marge_nette / total_investissement × 100
    roi_annualise_pct: float | None = None   # annualised ROI

    # ── Low / high scenarios ──
    marge_nette_low: float | None = None
    marge_nette_high: float | None = None

    # ── Verdict ──
    verdict: str | None = None

    # Persisted forecast ID (populated by repo)
    id: int | None = None
    created_at: str | None = None

    # Comps detail (not persisted — for display only)
    comps_detail: list = field(default_factory=list)
