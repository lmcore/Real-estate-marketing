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
