# Shadow Tester — Demand Analyzer

Outil d'aide à la décision pour marchand de biens. Objectif : **valider la demande réelle**
sur un projet immobilier (acquisition, rénovation, revente) **avant** d'engager du capital,
en s'appuyant exclusivement sur des **données publiques et légales**.

> Zone cible initiale : Manosque (04100), extensible à toute commune française.

## Pourquoi cette approche

Plutôt que de publier des annonces fictives (illégal, contraire aux CGU des plateformes,
trompeur pour les particuliers), Shadow Tester exploite :

- **DVF** — *Demandes de Valeurs Foncières* (data.gouv.fr) : l'ensemble des transactions
  immobilières réelles en France depuis 2014, avec prix, surface, type de bien,
  géolocalisation.
- **INSEE** (à venir) : démographie, revenus médians, taux de vacance, tension locative.
- **Indices notariaux** (à venir) : évolution des prix sur 12 / 24 / 60 mois.

Ces sources donnent une image factuelle du marché, là où une fausse annonce ne donne
qu'un signal bruité et artificiel.

## État du projet

| Module | Statut |
|---|---|
| `dvf` — ingestion + parsing DVF | ✅ v1 |
| `storage` — SQLite | ✅ v1 |
| `market` — stats prix/m² | ✅ v1 (basique) |
| `insee` — indicateurs communaux | ⏳ à venir |
| `comps` — biens comparables | ⏳ à venir |
| `dashboard` — Streamlit | ⏳ à venir |
| `forecaster` — marge après travaux | ⏳ à venir |

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Utilisation rapide

```bash
# 1. Ingérer les transactions DVF pour Manosque sur 2022–2024
shadow-tester dvf ingest --commune 04112 --years 2022,2023,2024

# 2. Afficher les statistiques agrégées
shadow-tester dvf stats --commune 04112

# 3. Voir la distribution de prix/m² pour les appartements
shadow-tester dvf stats --commune 04112 --type Appartement --year 2024
```

Les données brutes sont mises en cache dans `data/cache/` et chargées dans
`data/shadow_tester.sqlite`.

## Structure

```
src/shadow_tester/
├── cli.py              # Typer entry point
├── config.py           # Settings (pydantic-settings)
├── dvf/
│   ├── client.py       # Téléchargement des fichiers DVF géo
│   ├── parser.py       # Parsing + nettoyage
│   ├── ingest.py       # Chargement en base
│   └── stats.py        # Requêtes agrégées
├── storage/
│   ├── db.py           # Connexion SQLite
│   └── schema.sql      # Schéma des tables
└── market/             # (à venir) analyse comparative
```

## Sources de données

- DVF Géo (Etalab) : https://files.data.gouv.fr/geo-dvf/latest/csv/
- Code commune Manosque : `04112`

## Licence

MIT.
