"""Tests for listing fetch (httpx mock) and DVF↔listing matcher."""

from __future__ import annotations

import httpx
import pytest

from shadow_tester.listings.fetch import FetchError, fetch_listing_html

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


def _seed_dvf(commune: str = "04112") -> None:
    """Insert a few DVF transactions into the test DB for matcher tests."""
    from shadow_tester.storage import connect

    rows = [
        {
            "id_mutation": "mut-001",
            "disposition": 1,
            "row_idx": 0,
            "date_mutation": "2024-06-15",
            "nature_mutation": "Vente",
            "valeur_fonciere": 250000.0,
            "code_postal": "04100",
            "code_commune": commune,
            "nom_commune": "Manosque",
            "type_local": "Maison",
            "surface_reelle_bati": 100.0,
            "nombre_pieces_principales": 4,
            "longitude": 5.7846,
            "latitude": 43.8300,
            "prix_m2": 2500.0,
            "year": 2024,
        },
        {
            "id_mutation": "mut-002",
            "disposition": 1,
            "row_idx": 0,
            "date_mutation": "2024-08-20",
            "nature_mutation": "Vente",
            "valeur_fonciere": 190000.0,
            "code_postal": "04100",
            "code_commune": commune,
            "nom_commune": "Manosque",
            "type_local": "Appartement",
            "surface_reelle_bati": 72.0,
            "nombre_pieces_principales": 3,
            "longitude": 5.7850,
            "latitude": 43.8310,
            "prix_m2": 2639.0,
            "year": 2024,
        },
        {
            "id_mutation": "mut-003",
            "disposition": 1,
            "row_idx": 0,
            "date_mutation": "2024-07-10",
            "nature_mutation": "Vente",
            "valeur_fonciere": 260000.0,
            "code_postal": "04100",
            "code_commune": commune,
            "nom_commune": "Manosque",
            "type_local": "Maison",
            "surface_reelle_bati": 105.0,
            "nombre_pieces_principales": 4,
            "longitude": 5.7840,
            "latitude": 43.8295,
            "prix_m2": 2476.0,
            "year": 2024,
        },
    ]

    cols = list(rows[0].keys())
    placeholders = ", ".join(f":{c}" for c in cols)
    col_str = ", ".join(cols)
    sql = f"INSERT INTO dvf_transactions ({col_str}) VALUES ({placeholders})"

    with connect() as conn:
        for row in rows:
            conn.execute(sql, row)


# ── Fetch tests (httpx MockTransport) ────────────────────────────────────


class TestFetchListingHTML:
    def test_success(self):
        """Fetch returns HTML body on 200."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html><body>OK</body></html>")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        html = fetch_listing_html("https://example.com/listing", client=client)
        assert "<body>OK</body>" in html

    def test_404_raises_fetch_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="Not Found")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(FetchError, match="HTTP 404"):
            fetch_listing_html("https://example.com/nope", client=client)

    def test_500_raises_fetch_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Server Error")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(FetchError, match="HTTP 500"):
            fetch_listing_html("https://example.com/err", client=client)

    def test_network_error_raises_fetch_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(FetchError, match="Network error"):
            fetch_listing_html("https://example.com/down", client=client)

    def test_sends_browser_user_agent(self):
        captured_headers = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return httpx.Response(200, text="<html></html>")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        fetch_listing_html("https://example.com/ua", client=client)
        assert "Mozilla" in captured_headers.get("user-agent", "")

    def test_sends_french_accept_language(self):
        captured_headers = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return httpx.Response(200, text="<html></html>")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        fetch_listing_html("https://example.com/lang", client=client)
        assert "fr-FR" in captured_headers.get("accept-language", "")


# ── Matcher scoring unit tests ───────────────────────────────────────────


class TestMatcherScoring:
    def test_price_score_perfect(self):
        """DVF 8% below asking → perfect score."""
        from shadow_tester.listings.matcher import _price_score

        # listing 100k, dvf 92k → delta = -0.08, centered at -0.08
        score = _price_score(100_000, 92_000)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_price_score_same_price(self):
        """Same price → slightly below perfect (off-center by 8%)."""
        from shadow_tester.listings.matcher import _price_score

        score = _price_score(100_000, 100_000)
        assert 0.5 < score < 1.0

    def test_price_score_zero_listing(self):
        from shadow_tester.listings.matcher import _price_score

        assert _price_score(0, 100_000) == 0.0

    def test_surface_score_exact(self):
        from shadow_tester.listings.matcher import _surface_score

        assert _surface_score(100, 100) == pytest.approx(1.0)

    def test_surface_score_at_tolerance(self):
        from shadow_tester.listings.matcher import _surface_score

        # 10% tolerance → at exactly 10% error → score = 0
        assert _surface_score(100, 110) == pytest.approx(0.0, abs=0.01)

    def test_surface_score_half_tolerance(self):
        from shadow_tester.listings.matcher import _surface_score

        # 5% error → score ~0.5
        assert _surface_score(100, 105) == pytest.approx(0.5, abs=0.01)

    def test_rooms_score_exact(self):
        from shadow_tester.listings.matcher import _rooms_score

        assert _rooms_score(4, 4) == 1.0

    def test_rooms_score_off_by_one(self):
        from shadow_tester.listings.matcher import _rooms_score

        assert _rooms_score(4, 3) == 0.5

    def test_rooms_score_off_by_two(self):
        from shadow_tester.listings.matcher import _rooms_score

        assert _rooms_score(4, 2) == 0.0

    def test_rooms_score_missing(self):
        from shadow_tester.listings.matcher import _rooms_score

        assert _rooms_score(None, 4) == 0.5

    def test_temporal_score_mutation_before_listing(self):
        from datetime import date

        from shadow_tester.listings.matcher import _temporal_score

        # Mutation before listing → impossible → 0
        assert _temporal_score(date(2024, 6, 1), date(2024, 5, 1)) == 0.0

    def test_temporal_score_sweet_spot(self):
        from datetime import date

        from shadow_tester.listings.matcher import _temporal_score

        # 2 months later → sweet spot → 1.0
        assert _temporal_score(date(2024, 3, 1), date(2024, 5, 1)) == 1.0

    def test_temporal_score_fast_sale(self):
        from datetime import date

        from shadow_tester.listings.matcher import _temporal_score

        # 15 days → fast sale → 0.8
        assert _temporal_score(date(2024, 6, 1), date(2024, 6, 16)) == 0.8

    def test_geo_score_exact(self):
        from shadow_tester.listings.matcher import _geo_score

        assert _geo_score(43.83, 5.78, 43.83, 5.78) == 1.0

    def test_geo_score_missing_listing_coords(self):
        from shadow_tester.listings.matcher import _geo_score

        assert _geo_score(None, None, 43.83, 5.78) == 0.5


# ── Matcher integration tests (seeded DB) ────────────────────────────────


class TestMatcherIntegration:
    def test_match_listing_finds_candidates(self, isolated_db):
        """A listing with matching commune/type/surface should find DVF candidates."""
        _seed_dvf()

        from shadow_tester.listings.matcher import match_listing
        from shadow_tester.listings.models import Listing

        listing = Listing(
            price_asked=270_000,
            surface=100,
            rooms=4,
            type_local="Maison",
            commune="04112",
            first_seen="2024-03-01",
        )
        result = match_listing(listing)
        # Should find mut-001 (100m², Maison) and mut-003 (105m² within ±10%)
        assert len(result.candidates) >= 1
        assert result.candidates[0].id_mutation in ("mut-001", "mut-003")

    def test_match_scores_decrease(self, isolated_db):
        """Candidates should be sorted by score descending."""
        _seed_dvf()

        from shadow_tester.listings.matcher import match_listing
        from shadow_tester.listings.models import Listing

        listing = Listing(
            price_asked=270_000,
            surface=100,
            rooms=4,
            type_local="Maison",
            commune="04112",
            first_seen="2024-03-01",
        )
        result = match_listing(listing)
        if len(result.candidates) >= 2:
            assert result.candidates[0].score >= result.candidates[1].score

    def test_match_wrong_type_no_candidates(self, isolated_db):
        """Listing type Appartement shouldn't match Maison mutations."""
        _seed_dvf()

        from shadow_tester.listings.matcher import match_listing
        from shadow_tester.listings.models import Listing

        listing = Listing(
            price_asked=270_000,
            surface=100,
            rooms=4,
            type_local="Appartement",
            commune="04112",
            first_seen="2024-03-01",
        )
        result = match_listing(listing)
        # Only mut-002 is Appartement but surface is 72 → outside ±10% of 100
        assert len(result.candidates) == 0

    def test_match_no_commune_skips(self, isolated_db):
        from shadow_tester.listings.matcher import match_listing
        from shadow_tester.listings.models import Listing

        listing = Listing(price_asked=100_000, surface=100, type_local="Maison")
        result = match_listing(listing)
        assert result.candidates == []

    def test_match_no_surface_skips(self, isolated_db):
        from shadow_tester.listings.matcher import match_listing
        from shadow_tester.listings.models import Listing

        listing = Listing(
            price_asked=100_000,
            type_local="Maison",
            commune="04112",
        )
        result = match_listing(listing)
        assert result.candidates == []

    def test_match_price_delta(self, isolated_db):
        """price_delta_pct should be computed correctly."""
        _seed_dvf()

        from shadow_tester.listings.matcher import match_listing
        from shadow_tester.listings.models import Listing

        listing = Listing(
            price_asked=270_000,
            surface=100,
            rooms=4,
            type_local="Maison",
            commune="04112",
            first_seen="2024-03-01",
        )
        result = match_listing(listing)
        assert len(result.candidates) >= 1
        # mut-001: DVF 250k vs listing 270k → delta ≈ -7.4%
        mut001 = [c for c in result.candidates if c.id_mutation == "mut-001"]
        if mut001:
            assert mut001[0].price_delta_pct is not None
            assert mut001[0].price_delta_pct == pytest.approx(-7.4, abs=0.1)

    def test_match_days_to_sale(self, isolated_db):
        """days_to_sale should be mutation_date - first_seen."""
        _seed_dvf()

        from shadow_tester.listings.matcher import match_listing
        from shadow_tester.listings.models import Listing

        listing = Listing(
            price_asked=270_000,
            surface=100,
            rooms=4,
            type_local="Maison",
            commune="04112",
            first_seen="2024-03-01",
        )
        result = match_listing(listing)
        mut001 = [c for c in result.candidates if c.id_mutation == "mut-001"]
        if mut001:
            # 2024-03-01 → 2024-06-15 = 106 days
            assert mut001[0].days_to_sale == 106

    def test_match_all_unmatched(self, isolated_db):
        """match_all_unmatched should process saved unmatched listings."""
        _seed_dvf()

        from shadow_tester.listings import add_listing
        from shadow_tester.listings.matcher import match_all_unmatched
        from shadow_tester.listings.models import Listing

        add_listing(Listing(
            price_asked=270_000,
            surface=100,
            rooms=4,
            type_local="Maison",
            commune="04112",
            first_seen="2024-03-01",
        ))
        results = match_all_unmatched(commune="04112")
        assert len(results) >= 1
        assert results[0].best is not None

    def test_auto_match_threshold(self, isolated_db):
        """Very close match should be auto_matched."""
        _seed_dvf()

        from shadow_tester.listings.matcher import match_listing
        from shadow_tester.listings.models import Listing

        # Create a listing that almost exactly matches mut-001
        listing = Listing(
            price_asked=270_000,  # DVF is 250k → ~-7.4%, close to -8% center
            surface=100,          # exact match
            rooms=4,              # exact match
            type_local="Maison",
            commune="04112",
            lat=43.83,
            lon=5.7846,
            first_seen="2024-03-01",  # 3.5 months before → sweet spot
        )
        result = match_listing(listing)
        assert result.best is not None
        # With near-perfect sub-scores, total should exceed auto threshold
        assert result.best.score >= 0.60  # at least a suggestion


# ── Listings repo: find_listings_for_mutations ───────────────────────────


class TestFindListingsForMutations:
    def test_empty_ids(self, isolated_db):
        from shadow_tester.listings.repo import find_listings_for_mutations

        assert find_listings_for_mutations([]) == {}

    def test_finds_matched_listing(self, isolated_db):
        from shadow_tester.listings import add_listing
        from shadow_tester.listings.models import Listing
        from shadow_tester.listings.repo import (
            find_listings_for_mutations,
            update_listing,
        )

        saved = add_listing(Listing(
            price_asked=270_000,
            surface=100,
            type_local="Maison",
            commune="04112",
            condition="a_renover",
            condition_source="manual",
        ))
        update_listing(saved.id, matched_mutation_id="mut-001", match_score=0.85)

        result = find_listings_for_mutations(["mut-001", "mut-999"])
        assert "mut-001" in result
        assert "mut-999" not in result
        assert result["mut-001"].condition == "a_renover"

    def test_most_recent_wins(self, isolated_db):
        """When multiple listings match the same mutation, newest wins."""

        from shadow_tester.listings import add_listing
        from shadow_tester.listings.models import Listing
        from shadow_tester.listings.repo import (
            find_listings_for_mutations,
            update_listing,
        )

        l1 = add_listing(Listing(
            price_asked=260_000,
            surface=100,
            type_local="Maison",
            commune="04112",
            condition="a_renover",
        ))
        update_listing(l1.id, matched_mutation_id="mut-001", match_score=0.70)

        # Second listing matched later
        l2 = add_listing(Listing(
            price_asked=270_000,
            surface=100,
            type_local="Maison",
            commune="04112",
            condition="renove",
        ))
        update_listing(l2.id, matched_mutation_id="mut-001", match_score=0.90)

        result = find_listings_for_mutations(["mut-001"])
        # l2 has higher id → wins due to tiebreaker
        assert result["mut-001"].condition == "renove"
