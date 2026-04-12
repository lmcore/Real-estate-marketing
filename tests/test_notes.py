"""Tests for the notes module — models, repo CRUD, and integration with comps."""

from __future__ import annotations

import pytest

from shadow_tester.notes.models import (
    ALLOWED_CONDITIONS,
    ALLOWED_SOURCES,
    PropertyNote,
    normalise_condition,
    normalise_source,
)

# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.sqlite"
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    from shadow_tester import config as cfg

    monkeypatch.setenv("SHADOW_DB_PATH", str(db_path))
    monkeypatch.setenv("SHADOW_CACHE_DIR", str(cache_dir))
    cfg._settings = None
    yield db_path
    cfg._settings = None


# ── Model validation tests ───────────────────────────────────────────────

class TestNormaliseCondition:
    def test_canonical_values(self):
        for cond in ALLOWED_CONDITIONS:
            assert normalise_condition(cond) == cond

    def test_french_aliases(self):
        assert normalise_condition("à rénover") == "a_renover"
        assert normalise_condition("rénové") == "renove"
        assert normalise_condition("rafraîchissement") == "partiel"

    def test_english_aliases(self):
        assert normalise_condition("raw") == "brut"
        assert normalise_condition("unknown") == "inconnu"

    def test_case_insensitive(self):
        assert normalise_condition("A_RENOVER") == "a_renover"
        assert normalise_condition("BRUT") == "brut"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown condition"):
            normalise_condition("chateau")

    def test_none_raises(self):
        with pytest.raises(ValueError):
            normalise_condition(None)


class TestNormaliseSource:
    def test_canonical_values(self):
        for src in ALLOWED_SOURCES:
            assert normalise_source(src) == src

    def test_aliases(self):
        assert normalise_source("visit") == "visite"
        assert normalise_source("listing") == "annonce"
        assert normalise_source("lbc") == "annonce"
        assert normalise_source("estimate") == "estimation"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown source"):
            normalise_source("telepathy")


class TestPropertyNote:
    def test_valid_note(self):
        n = PropertyNote(
            condition="a_renover",
            source="visite",
            adresse="12 rue des Alpes",
            commune="4112",
        )
        assert n.condition == "a_renover"
        assert n.commune == "04112"  # zero-padded

    def test_requires_anchor(self):
        with pytest.raises(ValueError, match="at least one"):
            PropertyNote(condition="brut", source="visite")

    def test_negative_travaux_raises(self):
        with pytest.raises(ValueError, match="travaux_estime"):
            PropertyNote(
                condition="brut", source="visite",
                adresse="test", travaux_estime=-1,
            )

    def test_zero_prix_annonce_raises(self):
        with pytest.raises(ValueError, match="prix_annonce"):
            PropertyNote(
                condition="brut", source="visite",
                adresse="test", prix_annonce=0,
            )

    def test_normalises_aliases(self):
        n = PropertyNote(
            condition="à rénover", source="lbc",
            adresse="somewhere",
        )
        assert n.condition == "a_renover"
        assert n.source == "annonce"


# ── Repo CRUD tests ─────────────────────────────────────────────────────

class TestRepoCRUD:
    def test_add_and_get(self, isolated_db):
        from shadow_tester.notes import add_note, get_note

        n = PropertyNote(
            condition="renove", source="visite",
            adresse="12 rue test", commune="04112",
            travaux_estime=5000, note="petit rafraîchissement",
        )
        saved = add_note(n)
        assert saved.id is not None
        assert saved.created_at is not None
        assert saved.condition == "renove"

        fetched = get_note(saved.id)
        assert fetched is not None
        assert fetched.adresse == "12 rue test"
        assert fetched.travaux_estime == 5000

    def test_get_nonexistent_returns_none(self, isolated_db):
        from shadow_tester.notes import get_note

        assert get_note(9999) is None

    def test_list_empty(self, isolated_db):
        from shadow_tester.notes import list_notes

        assert list_notes() == []

    def test_list_filters_by_commune(self, isolated_db):
        from shadow_tester.notes import add_note, list_notes

        add_note(PropertyNote(
            condition="brut", source="visite",
            adresse="A", commune="04112",
        ))
        add_note(PropertyNote(
            condition="renove", source="visite",
            adresse="B", commune="13055",
        ))

        manosque = list_notes(commune="04112")
        assert len(manosque) == 1
        assert manosque[0].commune == "04112"

        marseille = list_notes(commune="13055")
        assert len(marseille) == 1

    def test_list_filters_by_condition(self, isolated_db):
        from shadow_tester.notes import add_note, list_notes

        add_note(PropertyNote(
            condition="brut", source="visite", adresse="A",
        ))
        add_note(PropertyNote(
            condition="renove", source="visite", adresse="B",
        ))

        brut = list_notes(condition="brut")
        assert len(brut) == 1
        assert brut[0].condition == "brut"

    def test_delete(self, isolated_db):
        from shadow_tester.notes import add_note, delete_note, get_note

        saved = add_note(PropertyNote(
            condition="partiel", source="annonce", adresse="X",
        ))
        assert delete_note(saved.id)
        assert get_note(saved.id) is None

    def test_delete_nonexistent_returns_false(self, isolated_db):
        from shadow_tester.notes import delete_note

        assert not delete_note(9999)

    def test_update(self, isolated_db):
        from shadow_tester.notes import add_note, update_note

        saved = add_note(PropertyNote(
            condition="partiel", source="estimation",
            adresse="Y", commune="04112",
        ))
        updated = update_note(saved.id, condition="renove", travaux_estime=15000)
        assert updated is not None
        assert updated.condition == "renove"
        assert updated.travaux_estime == 15000
        assert updated.updated_at >= saved.updated_at

    def test_update_nonexistent_returns_none(self, isolated_db):
        from shadow_tester.notes import update_note

        assert update_note(9999, condition="brut") is None

    def test_find_notes_for_mutations(self, isolated_db):
        from shadow_tester.notes import add_note
        from shadow_tester.notes.repo import find_notes_for_mutations

        add_note(PropertyNote(
            condition="a_renover", source="visite",
            id_mutation="m1", adresse="A",
        ))
        add_note(PropertyNote(
            condition="renove", source="annonce",
            id_mutation="m2", adresse="B",
        ))

        result = find_notes_for_mutations(["m1", "m2", "m3"])
        assert "m1" in result
        assert "m2" in result
        assert "m3" not in result
        assert result["m1"].condition == "a_renover"
        assert result["m2"].condition == "renove"

    def test_find_notes_for_mutations_returns_latest(self, isolated_db):
        from shadow_tester.notes import add_note
        from shadow_tester.notes.repo import find_notes_for_mutations

        add_note(PropertyNote(
            condition="a_renover", source="estimation",
            id_mutation="m1", adresse="A",
        ))
        # Add a second note for the same mutation — more recent should win.
        add_note(PropertyNote(
            condition="renove", source="visite",
            id_mutation="m1", adresse="A",
        ))

        result = find_notes_for_mutations(["m1"])
        assert result["m1"].condition == "renove"

    def test_find_notes_empty_input(self, isolated_db):
        from shadow_tester.notes.repo import find_notes_for_mutations

        assert find_notes_for_mutations([]) == {}


# ── Integration with comps engine ────────────────────────────────────────

# Reuse the seed data from test_comps_engine.
_SEED_ROWS = [
    ("m1", 1, 0, "2024-03-10", 270_000, "04100", "04112", "Maison",  100, 4, "RUE DES ALPES",   "12", 2700.0, 2024, 43.8300, 5.7846),
    ("m2", 1, 0, "2024-05-18", 295_000, "04100", "04112", "Maison",  110, 5, "RUE DES ALPES",   "24", 2681.8, 2024, 43.8305, 5.7850),
    ("m5", 1, 0, "2022-07-14", 215_000, "04100", "04112", "Maison",   85, 3, "RUE DES ALPES",   "45", 2529.4, 2022, 43.8295, 5.7840),
    ("m7", 1, 0, "2024-09-05", 250_000, "04100", "04112", "Maison",   90, 4, "AVENUE JEAN GIONO","8", 2777.8, 2024, 43.8312, 5.7901),
]

_INSERT_SQL = """
INSERT OR REPLACE INTO dvf_transactions (
    id_mutation, disposition, row_idx,
    date_mutation, nature_mutation, valeur_fonciere,
    code_postal, code_commune, nom_commune, code_departement,
    type_local, surface_reelle_bati, nombre_pieces_principales, surface_terrain,
    adresse_numero, adresse_nom_voie, id_parcelle,
    longitude, latitude,
    prix_m2, year
) VALUES (
    :id_mutation, :disposition, :row_idx,
    :date_mutation, 'Vente', :valeur_fonciere,
    :code_postal, :code_commune, 'Manosque', '04',
    :type_local, :surface_reelle_bati, :nombre_pieces_principales, NULL,
    :adresse_numero, :adresse_nom_voie, NULL,
    :longitude, :latitude,
    :prix_m2, :year
)
"""


def _seed(db_path):
    from shadow_tester.storage import connect

    records = []
    for row in _SEED_ROWS:
        records.append({
            "id_mutation": row[0], "disposition": row[1], "row_idx": row[2],
            "date_mutation": row[3], "valeur_fonciere": row[4],
            "code_postal": row[5], "code_commune": row[6],
            "type_local": row[7], "surface_reelle_bati": row[8],
            "nombre_pieces_principales": row[9], "adresse_nom_voie": row[10],
            "adresse_numero": row[11], "prix_m2": row[12], "year": row[13],
            "latitude": row[14], "longitude": row[15],
        })
    with connect() as conn:
        conn.executemany(_INSERT_SQL, records)


class TestCompsIntegration:
    def test_comps_show_condition_from_notes(self, isolated_db):
        """Notes condition should appear on matched comps."""
        from shadow_tester.comps import Target, find_comparables
        from shadow_tester.notes import add_note

        _seed(isolated_db)

        # Add a note for m1.
        add_note(PropertyNote(
            condition="renove", source="visite",
            id_mutation="m1", adresse="12 RUE DES ALPES",
            commune="04112",
        ))

        target = Target(
            commune="04112", type_local="Maison", surface=100,
            surface_tol=0.30, max_years_old=5,
        )
        result = find_comparables(target)

        m1_comp = next((c for c in result.comps if c.id_mutation == "m1"), None)
        assert m1_comp is not None
        assert m1_comp.condition == "renove"
        assert m1_comp.condition_source == "visite"

    def test_comps_without_notes_have_no_condition(self, isolated_db):
        """Comps without notes should have condition=None."""
        from shadow_tester.comps import Target, find_comparables

        _seed(isolated_db)

        target = Target(
            commune="04112", type_local="Maison", surface=100,
            surface_tol=0.30, max_years_old=5,
        )
        result = find_comparables(target)
        assert result.comps
        for c in result.comps:
            assert c.condition is None
            assert c.condition_source is None
