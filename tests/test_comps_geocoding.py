"""Tests for comps.geocoding — uses httpx.MockTransport, never hits BAN."""

from __future__ import annotations

import json

import httpx
import pytest


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


def _ban_response(features: list[dict]) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps({"type": "FeatureCollection", "features": features}),
    )


def _housenumber_feature(
    lat: float, lon: float, label: str = "12 Rue des Alpes 04100 Manosque"
) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "label": label,
            "score": 0.97,
            "type": "housenumber",
            "citycode": "04112",
            "city": "Manosque",
            "postcode": "04100",
        },
    }


def test_geocode_returns_result_on_hit(isolated_db):
    from shadow_tester.comps.geocoding import BANClient, geocode

    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _ban_response([_housenumber_feature(43.8298, 5.7846)])

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    ban = BANClient(client=mock_client)

    result = geocode("12 rue des Alpes, 04100 Manosque", citycode="04112", client=ban)
    assert result is not None
    assert result.lat == pytest.approx(43.8298)
    assert result.lon == pytest.approx(5.7846)
    assert result.feature_type == "housenumber"
    assert result.is_precise is True
    assert result.score == pytest.approx(0.97)
    assert len(calls) == 1
    assert "q=" in str(calls[0].url)
    assert "citycode=04112" in str(calls[0].url)


def test_geocode_uses_cache_on_second_call(isolated_db):
    from shadow_tester.comps.geocoding import BANClient, geocode

    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _ban_response([_housenumber_feature(43.83, 5.78)])

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    ban = BANClient(client=mock_client)

    query = "12 rue des Alpes, Manosque"
    r1 = geocode(query, citycode="04112", client=ban)
    r2 = geocode(query, citycode="04112", client=ban)
    assert r1 is not None and r2 is not None
    assert r1.lat == r2.lat == pytest.approx(43.83)
    # Second call must not hit the mock.
    assert len(calls) == 1


def test_geocode_returns_none_on_zero_features(isolated_db):
    from shadow_tester.comps.geocoding import BANClient, geocode

    def handler(request: httpx.Request) -> httpx.Response:
        return _ban_response([])

    ban = BANClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert geocode("address that does not exist", citycode="04112", client=ban) is None


def test_geocode_raises_on_http_error(isolated_db):
    from shadow_tester.comps.geocoding import BANClient, GeocodingError, geocode

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"boom")

    ban = BANClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(GeocodingError):
        geocode("anything", citycode="04112", client=ban, use_cache=False)
