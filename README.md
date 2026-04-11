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
| `insee` — indicateurs communaux + affordability | ✅ v1 |
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

# 2. Ingérer les indicateurs INSEE (à récupérer sur https://www.insee.fr/fr/statistiques/2011101)
shadow-tester insee ingest <url_ou_chemin_csv> --millesime 2020 --commune 04112

# 3. Voir les stats DVF pures
shadow-tester dvf stats --commune 04112
shadow-tester dvf stats --commune 04112 --type Appartement --year 2024

# 4. Voir les indicateurs INSEE
shadow-tester insee show --commune 04112

# 5. Synthèse croisée DVF + INSEE + indice d'affordability
shadow-tester summary --commune 04112
```

Exemple de sortie `summary` :

```
Shadow Tester — synthèse marché Manosque (04112)
┌───────────────────────┬─────────────┐
│ Population            │      22 400 │
│ Densité               │ 392 hab/km² │
│ Revenu médian / UC    │    19 520 € │
│ Taux de vacance       │       6.6 % │
│ Part propriétaires    │      55.0 % │
│ Taux de chômage 15-64 │      14.0 % │
└───────────────────────┴─────────────┘
┏━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Type        ┃ Médian €/m² ┃ Prix médian ┃    Affordability ┃
┣━━━━━━━━━━━━━╋━━━━━━━━━━━━━╋━━━━━━━━━━━━━╋━━━━━━━━━━━━━━━━━━┫
│ Maison      │     2 632 € │   320 000 € │ 10.25x revenu/an │
│ Appartement │     2 952 € │   195 000 € │  6.24x revenu/an │
└─────────────┴─────────────┴─────────────┴──────────────────┘
→ marché très tendu (> 9x revenu annuel)
```

L'indice d'*affordability* correspond au ratio **prix médian du bien / revenu
médian annuel du ménage** (revenu FILOSOFI par UC × 1.6 UC/ménage). C'est le
même indicateur que celui utilisé par l'OCDE et par les rapports annuels des
notaires pour classer la tension des marchés.

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
├── insee/
│   ├── client.py       # Téléchargement + extraction ZIP du Dossier Complet
│   ├── mapping.py      # Mapping colonnes INSEE → champs internes
│   ├── parser.py       # Parsing + indicateurs dérivés (densité, vacance, …)
│   ├── ingest.py       # Chargement en base
│   └── indicators.py   # Synthèse croisée DVF + INSEE (affordability)
└── storage/
    ├── db.py           # Connexion SQLite
    └── schema.sql      # Schéma des tables
```

## Sources de données

- **DVF Géo** (Etalab) : https://files.data.gouv.fr/geo-dvf/latest/csv/
- **INSEE Dossier Complet** : https://www.insee.fr/fr/statistiques/2011101
- Code commune Manosque : `04112`

## Licence

MIT.
