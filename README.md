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
- **INSEE Dossier Complet** : démographie, revenus médians, taux de vacance, tension
  locative.
- **BAN** — *Base Adresse Nationale* : géocodeur officiel français, utilisé pour
  transformer une adresse exacte en lat/lon et comparer les biens par proximité.
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
| `comps` — biens comparables + géocodage BAN | ✅ v1 |
| `notes` — annotations état du bien (condition, travaux) | ✅ v1 |
| `listings` — capture d'annonces + matching DVF | ⏳ à venir |
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

# 6. Trouver les biens comparables à un projet d'acquisition
#    — ancrage par adresse exacte (géocodage BAN)
shadow-tester comps find \
    --commune 04112 --type Maison --surface 100 --rooms 4 \
    --address "12 rue des Alpes, Manosque" \
    --budget 280000

#    — ou par coordonnées directes (plus rapide, pas de réseau)
shadow-tester comps find \
    --commune 04112 --type Maison --surface 100 \
    --lat 43.8300 --lon 5.7846 --radius 2

#    — ou par mot-clé de voie (filtre dur sur adresse_nom_voie)
shadow-tester comps find \
    --commune 04112 --type Maison --surface 100 --street alpes

# 7. Annoter l'état d'un bien (visite, annonce, estimation)
shadow-tester notes add \
    --condition "à rénover" --source visite \
    --id-mutation 2024-123456 --commune 04112 \
    --travaux 80000 --note "toiture + électricité à refaire"

shadow-tester notes add \
    --condition renove --source annonce \
    --address "12 rue des Alpes, Manosque" \
    --prix-annonce 285000

# Lister / afficher / supprimer les notes
shadow-tester notes list --commune 04112
shadow-tester notes show 1
shadow-tester notes delete 1
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

### Biens comparables (`comps find`)

Pour valider un prix d'acquisition, `comps find` cherche dans DVF les
transactions réellement comparables au bien visé (même commune, même type,
surface dans la tolérance, année dans la fenêtre), calcule un score de
similarité et en déduit une fourchette €/m² + un verdict vs budget.

Exemple de sortie :

```
Cible
┌──────────────┬───────────────────────────┐
│ Commune      │ 04112                     │
│ Type         │ Maison                    │
│ Surface      │ 100 m²  (±25%)            │
│ Pièces       │ 4                         │
│ Budget       │ 280 000 €                 │
│ Ancre        │ 43.8300, 5.7846 (2.0 km)  │
│ Fenêtre      │ 5 dernières années        │
└──────────────┴───────────────────────────┘
Top 4 comparables
┏━━━━━━┳━━━━━━━━━━━━┳━━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━┓
┃ Score┃ Date       ┃   Dist┃ Surf ┃ Piè. ┃ Adresse           ┃     Prix  ┃  €/m²  ┃
┣━━━━━━╋━━━━━━━━━━━━╋━━━━━━━╋━━━━━━╋━━━━━━╋━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━━━╋━━━━━━━━┫
│ 1.00 │ 2024-03-10 │ 0.0km │ 100  │  4   │ 12 RUE DES ALPES  │ 270 000 € │ 2 700  │
│ 0.93 │ 2024-05-18 │ 0.1km │ 110  │  5   │ 24 RUE DES ALPES  │ 295 000 € │ 2 682  │
│ 0.82 │ 2024-09-05 │ 0.5km │  90  │  4   │ 8 AV. JEAN GIONO  │ 250 000 € │ 2 778  │
│ 0.75 │ 2022-07-14 │ 0.1km │  85  │  3   │ 45 RUE DES ALPES  │ 215 000 € │ 2 529  │
└──────┴────────────┴───────┴──────┴──────┴───────────────────┴───────────┴────────┘
Fourchette marché (P25 / médiane / P75)
┌──────────────┬─────────────┬─────────────┐
│       2 644 €│     2 691 € │     2 719 € │
│ 264 400 €    │  269 100 €  │  271 900 €  │
└──────────────┴─────────────┴─────────────┘
→ Budget au-dessus de la fourchette — risque de payer trop cher vs marché.
```

Trois modes d'ancrage géographique sont supportés :

- `--address "12 rue des Alpes, Manosque"` : géocodage exact via BAN (résultat
  mis en cache dans SQLite, pas de re-requête à chaque run).
- `--lat / --lon` + `--radius` : ancrage direct par coordonnées, utile quand
  on n'a pas de réseau ou qu'on veut tester une zone plutôt qu'un point.
- `--street alpes` : filtre dur sur un mot-clé de voie — pratique quand on
  n'a pas de numéro de rue et qu'on veut juste rester "dans le quartier".

Le score de chaque comp est une moyenne pondérée :
**surface 35% + distance 30% + récence 20% + pièces 15%**. Les poids sont
volontairement visibles (`scoring.py`) et faciles à tuner.

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
├── comps/
│   ├── models.py       # Target, Comp, CompResult (dataclasses)
│   ├── geocoding.py    # Client BAN + cache SQLite (ban_cache)
│   ├── scoring.py      # Haversine + sous-scores + pondération
│   └── engine.py       # find_comparables (SQL + ranking + fourchette)
├── notes/
│   ├── models.py       # PropertyNote + validation condition/source
│   └── repo.py         # CRUD SQLite (add, list, get, delete, update)
└── storage/
    ├── db.py           # Connexion SQLite
    └── schema.sql      # Schéma des tables
```

## Sources de données

- **DVF Géo** (Etalab) : https://files.data.gouv.fr/geo-dvf/latest/csv/
- **INSEE Dossier Complet** : https://www.insee.fr/fr/statistiques/2011101
- **BAN — Base Adresse Nationale** : https://adresse.data.gouv.fr/ (API
  `api-adresse.data.gouv.fr`, libre, sans authentification)
- Code commune Manosque : `04112`

## Licence

MIT.
