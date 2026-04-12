-- Shadow Tester SQLite schema.
-- Designed to hold DVF transactions and derived analytics.

CREATE TABLE IF NOT EXISTS dvf_transactions (
    -- Composite primary key: the DVF id_mutation can group several lines
    -- (one per parcel / lot), so we include disposition + row_idx to stay unique.
    id_mutation            TEXT    NOT NULL,
    disposition            INTEGER NOT NULL DEFAULT 1,
    row_idx                INTEGER NOT NULL DEFAULT 0,

    date_mutation          TEXT    NOT NULL,  -- ISO yyyy-mm-dd
    nature_mutation        TEXT,              -- Vente, VEFA, Echange, Adjudication...
    valeur_fonciere        REAL,              -- total transaction value (EUR)

    code_postal            TEXT,
    code_commune           TEXT    NOT NULL,  -- INSEE code, e.g. 04112
    nom_commune            TEXT,
    code_departement       TEXT,

    type_local             TEXT,              -- Maison, Appartement, Local, Dépendance
    surface_reelle_bati    REAL,              -- m²
    nombre_pieces_principales INTEGER,
    surface_terrain        REAL,              -- m²

    adresse_numero         TEXT,
    adresse_nom_voie       TEXT,
    id_parcelle            TEXT,

    longitude              REAL,
    latitude               REAL,

    -- Derived convenience fields (nullable when not computable)
    prix_m2                REAL,
    year                   INTEGER,

    ingested_at            TEXT    NOT NULL DEFAULT (datetime('now')),

    PRIMARY KEY (id_mutation, disposition, row_idx)
);

CREATE INDEX IF NOT EXISTS idx_dvf_commune       ON dvf_transactions (code_commune);
CREATE INDEX IF NOT EXISTS idx_dvf_commune_year  ON dvf_transactions (code_commune, year);
CREATE INDEX IF NOT EXISTS idx_dvf_commune_type  ON dvf_transactions (code_commune, type_local);
CREATE INDEX IF NOT EXISTS idx_dvf_date          ON dvf_transactions (date_mutation);

-- Tracks which (commune, year) pairs have already been ingested so we can
-- avoid redundant downloads and make `ingest` idempotent.
CREATE TABLE IF NOT EXISTS dvf_ingest_log (
    code_commune TEXT    NOT NULL,
    year         INTEGER NOT NULL,
    rows_loaded  INTEGER NOT NULL,
    source_url   TEXT    NOT NULL,
    ingested_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (code_commune, year)
);

-- INSEE "Dossier complet" commune-level indicators.
-- One row per (code_commune, millesime). Millesime = vintage year of the dataset
-- (e.g. 2020 for the RP 2020 / FILOSOFI 2020 release).
CREATE TABLE IF NOT EXISTS insee_commune (
    code_commune            TEXT    NOT NULL,
    millesime               INTEGER NOT NULL,

    nom_commune             TEXT,
    code_departement        TEXT,
    code_region             TEXT,

    -- Démographie
    population              REAL,     -- habitants
    superficie_km2          REAL,     -- km²
    densite_hab_km2         REAL,     -- hab/km²

    -- Logement
    logements_total         REAL,
    residences_principales  REAL,
    residences_secondaires  REAL,
    logements_vacants       REAL,
    taux_vacance            REAL,     -- %
    taux_residences_sec     REAL,     -- %
    part_proprietaires      REAL,     -- %

    -- Revenus (FILOSOFI)
    revenu_median_uc        REAL,     -- EUR / unité de consommation / an
    taux_pauvrete           REAL,     -- % à 60 %

    -- Emploi
    pop_active_1564         REAL,
    taux_chomage_1564       REAL,     -- %

    source_url              TEXT,
    ingested_at             TEXT    NOT NULL DEFAULT (datetime('now')),

    PRIMARY KEY (code_commune, millesime)
);

CREATE INDEX IF NOT EXISTS idx_insee_commune ON insee_commune (code_commune);
CREATE INDEX IF NOT EXISTS idx_insee_dep     ON insee_commune (code_departement);

CREATE TABLE IF NOT EXISTS insee_ingest_log (
    source_url     TEXT    NOT NULL,
    millesime      INTEGER NOT NULL,
    rows_loaded    INTEGER NOT NULL,
    ingested_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (source_url, millesime)
);

-- Cache for BAN (Base Adresse Nationale) geocoding lookups.
-- The raw query string is the key so we can remember misses too.
CREATE TABLE IF NOT EXISTS ban_cache (
    query         TEXT    NOT NULL,
    citycode      TEXT,                -- optional INSEE commune filter
    lat           REAL,
    lon           REAL,
    label         TEXT,
    score         REAL,                -- BAN confidence 0..1
    feature_type  TEXT,                -- housenumber, street, locality, ...
    cached_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (query, citycode)
);

-- User-maintained notes on individual properties.
-- This is the "ground truth" layer: anything the user has personally seen on
-- a bien (visit, listing, estimate) lives here and overrides any automatic
-- proxy (DPE, listings heuristics, vision). Rows can be anchored to a DVF
-- mutation (via id_mutation) and/or to a free-form address.
CREATE TABLE IF NOT EXISTS property_notes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Optional anchors — at least one of (id_mutation, adresse) must be set.
    id_mutation     TEXT,               -- DVF mutation id if known
    adresse         TEXT,               -- free-form address otherwise
    commune         TEXT,               -- INSEE code, always zero-padded
    lat             REAL,
    lon             REAL,

    -- Core payload
    condition       TEXT    NOT NULL,   -- brut / a_renover / partiel / renove / inconnu
    source          TEXT    NOT NULL,   -- visite / annonce / estimation / autre
    travaux_estime  REAL,               -- € TTC estimated renovation cost
    prix_annonce    REAL,               -- asking price if source = annonce
    note            TEXT,               -- free-form text

    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_property_notes_mutation ON property_notes (id_mutation);
CREATE INDEX IF NOT EXISTS idx_property_notes_commune  ON property_notes (commune);

-- User-captured real-estate listings (LBC, SeLoger, PAP, etc.).
-- Each row represents a listing the user personally consulted and fed into
-- the system. The tool NEVER scrapes — this is user-initiated capture only.
CREATE TABLE IF NOT EXISTS listings (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Source metadata
    source                 TEXT,               -- leboncoin / seloger / pap / autre
    url                    TEXT,
    title                  TEXT,
    description            TEXT,

    -- Structured fields
    price_asked            REAL,               -- asking price (EUR)
    surface                REAL,               -- m²
    rooms                  INTEGER,
    type_local             TEXT,               -- Maison / Appartement

    -- Location
    commune                TEXT,               -- INSEE code (zero-padded)
    adresse_approx         TEXT,               -- free-form address as shown in listing
    lat                    REAL,
    lon                    REAL,

    -- Condition (detected or manual)
    condition              TEXT,               -- brut / a_renover / partiel / renove / inconnu
    condition_source       TEXT,               -- manual / keywords / vision
    condition_confidence   REAL,               -- 0..1 (1 = manual or certain)
    condition_rationale    TEXT,               -- short explanation of why this condition

    -- Temporal tracking
    first_seen             TEXT,               -- when user first saw this listing
    last_seen              TEXT,               -- last time user checked it was still live
    disappeared_at         TEXT,               -- when the listing was no longer online

    -- DVF matching (populated by Phase C matcher)
    matched_mutation_id    TEXT,               -- FK to dvf_transactions.id_mutation
    match_score            REAL,               -- 0..1 confidence of the match

    -- Archive
    raw_html               TEXT,               -- optional saved HTML for re-parsing

    notes                  TEXT,
    created_at             TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at             TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_listings_commune   ON listings (commune);
CREATE INDEX IF NOT EXISTS idx_listings_matched   ON listings (matched_mutation_id);
CREATE INDEX IF NOT EXISTS idx_listings_condition ON listings (condition);

-- Saved forecaster scenarios: buy-renovate-sell profit projections.
-- Each row is a self-contained snapshot of a forecast run so the user can
-- compare scenarios side by side.
CREATE TABLE IF NOT EXISTS forecasts (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    label                  TEXT,               -- user-chosen scenario name

    -- Property inputs
    commune                TEXT    NOT NULL,
    type_local             TEXT    NOT NULL,
    surface                REAL    NOT NULL,
    rooms                  INTEGER,
    surface_terrain        REAL,
    lat                    REAL,
    lon                    REAL,

    -- Financial inputs
    prix_achat             REAL    NOT NULL,
    travaux                REAL    NOT NULL DEFAULT 0,
    condition_achat        TEXT,
    condition_revente      TEXT,
    frais_notaire_pct      REAL,
    tva_marge_pct          REAL,
    portage_mois           INTEGER,
    portage_mensuel_pct    REAL,
    frais_agence_pct       REAL,

    -- Results (snapshot)
    prix_revente_low       REAL,
    prix_revente_mid       REAL,
    prix_revente_high      REAL,
    prix_m2_median         REAL,
    n_comps                INTEGER,
    confidence             TEXT,

    frais_notaire          REAL,
    frais_portage          REAL,
    total_investissement   REAL,
    frais_agence           REAL,
    tva_sur_marge          REAL,
    marge_brute            REAL,
    marge_nette            REAL,
    marge_nette_low        REAL,
    marge_nette_high       REAL,
    roi_pct                REAL,
    roi_annualise_pct      REAL,
    verdict                TEXT,

    created_at             TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_forecasts_commune ON forecasts (commune);
