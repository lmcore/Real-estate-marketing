"""Tests for listings module — condition detection, HTML parsing, and CRUD."""

from __future__ import annotations

import pytest

from shadow_tester.listings.condition import detect_condition
from shadow_tester.listings.models import Listing
from shadow_tester.listings.parsers import parse_listing_html

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


# ── Condition detection tests ────────────────────────────────────────────

class TestConditionDetection:
    def test_empty_text(self):
        r = detect_condition("")
        assert r.condition == "inconnu"
        assert r.confidence == 0.0

    def test_none_text(self):
        r = detect_condition(None)
        assert r.condition == "inconnu"

    def test_no_keywords(self):
        r = detect_condition("Belle vue sur la montagne, quartier calme.")
        assert r.condition == "inconnu"
        assert r.confidence == 0.0

    def test_detects_a_renover(self):
        r = detect_condition("Maison à rénover entièrement, travaux à prévoir.")
        assert r.condition == "a_renover"
        assert r.confidence >= 0.5
        assert len(r.matched_keywords) >= 1

    def test_detects_renove(self):
        r = detect_condition("Appartement entièrement rénové, clé en main.")
        assert r.condition == "renove"
        assert r.confidence >= 0.7

    def test_detects_partiel(self):
        r = detect_condition("Quelques travaux de rafraîchissement à prévoir.")
        assert r.condition == "partiel"
        assert r.confidence >= 0.5

    def test_detects_brut(self):
        r = detect_condition("Local brut, gros œuvre uniquement, tout est à faire.")
        assert r.condition == "brut"
        assert r.confidence >= 0.7

    def test_conflicting_signals_returns_inconnu(self):
        # Both a_renover (travaux à prévoir) and renove (entièrement rénové)
        # have comparable weight → ambiguous.
        r = detect_condition("Maison à rénover, travaux à prévoir. Cuisine entièrement rénovée, refaite à neuf.")
        assert r.condition == "inconnu"
        assert r.confidence <= 0.3

    def test_case_insensitive(self):
        r = detect_condition("ENTIÈREMENT RÉNOVÉ")
        assert r.condition == "renove"

    def test_accent_variations(self):
        r = detect_condition("A renover completement")
        assert r.condition == "a_renover"


# ── HTML parser tests ────────────────────────────────────────────────────

_JSONLD_HTML = """
<!DOCTYPE html>
<html>
<head>
<title>Maison 4 pièces 100m² - Manosque - LeBonCoin</title>
<meta property="og:description" content="Belle maison à rénover dans quartier calme">
<script type="application/ld+json">
{
  "@type": "Product",
  "name": "Maison 4 pièces 100m²",
  "description": "Belle maison à rénover, travaux à prévoir, 100m² habitables, 4 pièces.",
  "offers": {"price": "270000", "priceCurrency": "EUR"},
  "floorSize": {"value": 100, "unitCode": "MTK"},
  "numberOfRooms": 4,
  "address": {
    "streetAddress": "12 Rue des Alpes",
    "addressLocality": "Manosque",
    "postalCode": "04100"
  },
  "geo": {"latitude": 43.83, "longitude": 5.78}
}
</script>
</head>
<body>
<p>www.leboncoin.fr annonce</p>
</body>
</html>
"""


class TestHTMLParser:
    def test_parse_jsonld_product(self):
        result = parse_listing_html(_JSONLD_HTML)
        assert result.title == "Maison 4 pièces 100m²"
        assert result.price == pytest.approx(270000)
        assert result.surface == pytest.approx(100)
        assert result.rooms == 4
        assert result.address == "12 Rue des Alpes"
        assert result.city == "Manosque"
        assert result.postal_code == "04100"
        assert result.lat == pytest.approx(43.83)
        assert result.lon == pytest.approx(5.78)
        assert result.source == "leboncoin"

    def test_detect_type_from_text(self):
        result = parse_listing_html(_JSONLD_HTML)
        assert result.type_local == "Maison"

    def test_empty_html(self):
        result = parse_listing_html("")
        assert result.title is None
        assert result.price is None

    def test_meta_fallback(self):
        html = """
        <html><head>
        <title>Appartement T3 72m²</title>
        <meta property="og:description" content="Bel appartement rénové">
        </head><body></body></html>
        """
        result = parse_listing_html(html)
        assert result.title == "Appartement T3 72m²"
        assert result.description == "Bel appartement rénové"
        assert result.type_local == "Appartement"

    def test_price_extraction_from_text(self):
        html = """
        <html><head><title>Maison 270 000 € - 100m²</title></head>
        <body></body></html>
        """
        result = parse_listing_html(html)
        assert result.price == pytest.approx(270000)
        assert result.surface == pytest.approx(100)

    def test_rooms_extraction_from_text(self):
        html = """
        <html><head><title>Maison 5 pièces - Manosque</title></head>
        <body></body></html>
        """
        result = parse_listing_html(html)
        assert result.rooms == 5

    def test_source_detection_seloger(self):
        html = "<html><head><title>Test</title></head><body>seloger.com</body></html>"
        result = parse_listing_html(html)
        assert result.source == "seloger"

    def test_source_detection_pap(self):
        html = "<html><head><title>Test</title></head><body>pap.fr annonce</body></html>"
        result = parse_listing_html(html)
        assert result.source == "pap"


# ── Listing model tests ─────────────────────────────────────────────────

class TestListingModel:
    def test_zero_pads_commune(self):
        lst = Listing(commune="4112", price_asked=100000)
        assert lst.commune == "04112"

    def test_validates_type_local(self):
        with pytest.raises(ValueError, match="type_local"):
            Listing(type_local="Chateau")

    def test_validates_price(self):
        with pytest.raises(ValueError, match="price_asked"):
            Listing(price_asked=-1)

    def test_normalises_condition(self):
        lst = Listing(condition="à rénover")
        assert lst.condition == "a_renover"

    def test_sets_first_seen_default(self):
        lst = Listing()
        assert lst.first_seen is not None

    def test_last_seen_defaults_to_first_seen(self):
        lst = Listing(first_seen="2024-01-15")
        assert lst.last_seen == "2024-01-15"


# ── Repo CRUD tests ─────────────────────────────────────────────────────

class TestListingRepo:
    def test_add_and_get(self, isolated_db):
        from shadow_tester.listings import add_listing, get_listing

        lst = Listing(
            source="leboncoin",
            price_asked=270000,
            surface=100,
            rooms=4,
            type_local="Maison",
            commune="04112",
            condition="a_renover",
            condition_source="manual",
            condition_confidence=1.0,
        )
        saved = add_listing(lst)
        assert saved.id is not None
        assert saved.price_asked == 270000

        fetched = get_listing(saved.id)
        assert fetched is not None
        assert fetched.surface == 100
        assert fetched.condition == "a_renover"

    def test_list_empty(self, isolated_db):
        from shadow_tester.listings import list_listings

        assert list_listings() == []

    def test_list_filters_by_commune(self, isolated_db):
        from shadow_tester.listings import add_listing, list_listings

        add_listing(Listing(commune="04112", price_asked=100000))
        add_listing(Listing(commune="13055", price_asked=200000))

        results = list_listings(commune="04112")
        assert len(results) == 1
        assert results[0].commune == "04112"

    def test_list_filters_by_condition(self, isolated_db):
        from shadow_tester.listings import add_listing, list_listings

        add_listing(Listing(commune="04112", condition="renove"))
        add_listing(Listing(commune="04112", condition="a_renover"))

        results = list_listings(condition="renove")
        assert len(results) == 1
        assert results[0].condition == "renove"

    def test_delete(self, isolated_db):
        from shadow_tester.listings import add_listing, delete_listing, get_listing

        saved = add_listing(Listing(price_asked=100000))
        assert delete_listing(saved.id)
        assert get_listing(saved.id) is None

    def test_delete_nonexistent(self, isolated_db):
        from shadow_tester.listings import delete_listing

        assert not delete_listing(9999)

    def test_update(self, isolated_db):
        from shadow_tester.listings import add_listing, update_listing

        saved = add_listing(Listing(price_asked=270000, commune="04112"))
        updated = update_listing(saved.id, price_asked=265000, condition="partiel")
        assert updated is not None
        assert updated.price_asked == 265000
        assert updated.condition == "partiel"

    def test_list_matched_only(self, isolated_db):
        from shadow_tester.listings import add_listing, list_listings, update_listing

        l1 = add_listing(Listing(commune="04112", price_asked=100000))
        add_listing(Listing(commune="04112", price_asked=200000))
        update_listing(l1.id, matched_mutation_id="m1", match_score=0.85)

        matched = list_listings(matched_only=True)
        assert len(matched) == 1
        assert matched[0].matched_mutation_id == "m1"

        unmatched = list_listings(unmatched_only=True)
        assert len(unmatched) == 1
        assert unmatched[0].matched_mutation_id is None


# ── Integration: HTML parse → condition detect → save ────────────────────

class TestEndToEnd:
    def test_html_to_listing_with_condition(self, isolated_db):
        """Simulate what the CLI does: parse HTML, detect condition, save."""
        from shadow_tester.listings import add_listing, detect_condition

        parsed = parse_listing_html(_JSONLD_HTML)
        detection = detect_condition(parsed.description)

        listing = Listing(
            source=parsed.source,
            title=parsed.title,
            description=parsed.description,
            price_asked=parsed.price,
            surface=parsed.surface,
            rooms=parsed.rooms,
            type_local=parsed.type_local,
            commune="04112",
            adresse_approx=parsed.address,
            lat=parsed.lat,
            lon=parsed.lon,
            condition=detection.condition,
            condition_source="keywords",
            condition_confidence=detection.confidence,
            condition_rationale=detection.rationale,
        )
        saved = add_listing(listing)
        assert saved.id is not None
        assert saved.condition == "a_renover"
        assert saved.price_asked == 270000
        assert saved.surface == 100
        assert saved.source == "leboncoin"
