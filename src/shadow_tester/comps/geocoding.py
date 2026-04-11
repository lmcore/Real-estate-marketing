"""Geocoding via the French Base Adresse Nationale (BAN).

API: https://adresse.data.gouv.fr/api-doc/adresse
Endpoint: https://api-adresse.data.gouv.fr/search/

No API key, no auth, public dataset of every French address. Results are
cached in SQLite so the same query never hits the network twice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from shadow_tester.storage import connect

logger = logging.getLogger(__name__)

_BAN_URL = "https://api-adresse.data.gouv.fr/search/"


class GeocodingError(RuntimeError):
    """Raised when a BAN lookup fails for reasons other than zero results."""


@dataclass
class GeocodingResult:
    query: str
    citycode: str | None
    lat: float
    lon: float
    label: str
    score: float
    feature_type: str       # 'housenumber' | 'street' | 'locality' | 'municipality' | ...

    @property
    def is_precise(self) -> bool:
        """True when BAN found a specific housenumber or street."""
        return self.feature_type in {"housenumber", "street"}


def _cache_get(query: str, citycode: str | None) -> GeocodingResult | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT query, citycode, lat, lon, label, score, feature_type
            FROM ban_cache
            WHERE query = ? AND COALESCE(citycode, '') = COALESCE(?, '')
            """,
            (query, citycode),
        ).fetchone()
    if row is None:
        return None
    if row["lat"] is None or row["lon"] is None:
        # Cached miss — we remember it to avoid re-trying a useless lookup.
        return None
    return GeocodingResult(
        query=row["query"],
        citycode=row["citycode"],
        lat=row["lat"],
        lon=row["lon"],
        label=row["label"] or "",
        score=row["score"] or 0.0,
        feature_type=row["feature_type"] or "",
    )


def _cache_put(
    query: str,
    citycode: str | None,
    result: GeocodingResult | None,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO ban_cache
                (query, citycode, lat, lon, label, score, feature_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                query,
                citycode,
                result.lat if result else None,
                result.lon if result else None,
                result.label if result else None,
                result.score if result else None,
                result.feature_type if result else None,
            ),
        )


class BANClient:
    """Thin httpx wrapper around the BAN /search endpoint."""

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.timeout = timeout
        self._external_client = client

    def _client(self) -> httpx.Client:
        return self._external_client or httpx.Client(timeout=self.timeout)

    def search(
        self,
        query: str,
        *,
        citycode: str | None = None,
        limit: int = 1,
    ) -> GeocodingResult | None:
        params: dict[str, str | int] = {
            "q": query,
            "limit": limit,
            "autocomplete": 0,
        }
        if citycode:
            params["citycode"] = citycode

        try:
            client = self._client()
            if self._external_client is None:
                with client:
                    response = client.get(_BAN_URL, params=params)
            else:
                response = client.get(_BAN_URL, params=params)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise GeocodingError(f"BAN lookup failed for {query!r}: {exc}") from exc

        features = data.get("features") or []
        if not features:
            return None

        feat = features[0]
        lon, lat = feat["geometry"]["coordinates"]
        props = feat.get("properties", {})
        return GeocodingResult(
            query=query,
            citycode=citycode,
            lat=float(lat),
            lon=float(lon),
            label=props.get("label", ""),
            score=float(props.get("score", 0.0)),
            feature_type=props.get("type", ""),
        )


def geocode(
    query: str,
    *,
    citycode: str | None = None,
    client: BANClient | None = None,
    use_cache: bool = True,
) -> GeocodingResult | None:
    """Geocode ``query`` via the BAN, using SQLite cache by default.

    Returns ``None`` if BAN knows no such address; raises
    :class:`GeocodingError` on a network / protocol failure.
    """
    query = query.strip()
    if not query:
        return None

    if use_cache:
        cached = _cache_get(query, citycode)
        if cached is not None:
            logger.debug("BAN cache hit for %r", query)
            return cached

    client = client or BANClient()
    result = client.search(query, citycode=citycode)

    if use_cache:
        _cache_put(query, citycode, result)

    if result is None:
        logger.info("BAN: no result for %r (citycode=%s)", query, citycode)
    else:
        logger.info("BAN: %r → %s (score=%.2f, type=%s)", query, result.label, result.score, result.feature_type)
    return result
