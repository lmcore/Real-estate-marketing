"""Extract structured listing data from saved HTML files.

Uses only the Python stdlib (``html.parser`` + ``json``). The primary
strategy is to find JSON-LD (``<script type="application/ld+json">``)
or inline JS data blobs, which are far more stable than CSS selectors.
Falls back to ``<title>`` + ``<meta>`` tags for basic metadata.

This module does NOT fetch URLs — the user must provide saved HTML. This
avoids any TOS issue and keeps the tool firmly in "personal note-taking"
territory.
"""

from __future__ import annotations

import contextlib
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser


@dataclass
class ParsedListing:
    """Raw data extracted from HTML, before normalisation into a Listing."""

    title: str | None = None
    description: str | None = None
    price: float | None = None
    surface: float | None = None
    rooms: int | None = None
    type_local: str | None = None
    address: str | None = None
    city: str | None = None
    postal_code: str | None = None
    lat: float | None = None
    lon: float | None = None
    images: list[str] = field(default_factory=list)
    source: str | None = None    # detected platform


class _JSONLDExtractor(HTMLParser):
    """Find all <script type="application/ld+json"> blocks."""

    def __init__(self) -> None:
        super().__init__()
        self._in_jsonld = False
        self._buf: list[str] = []
        self.json_ld_blocks: list[dict] = []
        self._title_buf: list[str] = []
        self._in_title = False
        self.title: str | None = None
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        if tag == "script" and attr_dict.get("type") == "application/ld+json":
            self._in_jsonld = True
            self._buf = []
        if tag == "title":
            self._in_title = True
            self._title_buf = []
        if tag == "meta":
            name = attr_dict.get("name") or attr_dict.get("property", "")
            content = attr_dict.get("content", "")
            if name and content:
                self.meta[name.lower()] = content

    def handle_data(self, data: str) -> None:
        if self._in_jsonld:
            self._buf.append(data)
        if self._in_title:
            self._title_buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            raw = "".join(self._buf).strip()
            if raw:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        self.json_ld_blocks.extend(parsed)
                    else:
                        self.json_ld_blocks.append(parsed)
                except json.JSONDecodeError:
                    pass
        if tag == "title" and self._in_title:
            self._in_title = False
            self.title = "".join(self._title_buf).strip() or None


def _detect_source(html: str) -> str | None:
    """Guess which platform this HTML came from."""
    lower = html[:5000].lower()
    if "leboncoin" in lower:
        return "leboncoin"
    if "seloger" in lower:
        return "seloger"
    if "pap.fr" in lower:
        return "pap"
    if "bienici" in lower or "bien-ici" in lower:
        return "bienici"
    return None


def _extract_from_jsonld(blocks: list[dict]) -> ParsedListing:
    """Parse schema.org RealEstateListing / Product / Residence from JSON-LD."""
    result = ParsedListing()

    for block in blocks:
        block_type = block.get("@type", "")

        # LeBonCoin uses Product, SeLoger uses RealEstateListing or Residence.
        if block_type in ("Product", "RealEstateListing", "Residence", "Apartment", "House"):
            result.title = result.title or block.get("name")
            result.description = result.description or block.get("description")

            # Price
            offers = block.get("offers") or block.get("offer")
            if isinstance(offers, dict):
                price = offers.get("price") or offers.get("lowPrice")
                if price is not None:
                    with contextlib.suppress(ValueError, TypeError):
                        result.price = float(price)
            elif "price" in block:
                with contextlib.suppress(ValueError, TypeError):
                    result.price = float(block["price"])

            # Floor area
            area = block.get("floorSize")
            if isinstance(area, dict):
                val = area.get("value")
                if val is not None:
                    with contextlib.suppress(ValueError, TypeError):
                        result.surface = float(val)
            elif isinstance(area, (int, float)):
                result.surface = float(area)

            # Rooms
            rooms = block.get("numberOfRooms")
            if rooms is not None:
                with contextlib.suppress(ValueError, TypeError):
                    result.rooms = int(rooms)

            # Address / location
            addr = block.get("address")
            if isinstance(addr, dict):
                result.address = addr.get("streetAddress")
                result.city = addr.get("addressLocality")
                result.postal_code = addr.get("postalCode")

            geo = block.get("geo")
            if isinstance(geo, dict):
                with contextlib.suppress(ValueError, TypeError):
                    result.lat = float(geo.get("latitude", 0)) or None
                    result.lon = float(geo.get("longitude", 0)) or None

            # Images
            images = block.get("image")
            if isinstance(images, list):
                for img in images:
                    if isinstance(img, str):
                        result.images.append(img)
                    elif isinstance(img, dict) and "url" in img:
                        result.images.append(img["url"])
            elif isinstance(images, str):
                result.images.append(images)

    return result


def _extract_from_meta(meta: dict[str, str], result: ParsedListing) -> None:
    """Fill gaps from <meta> tags (og:title, og:description, etc.)."""
    if not result.title:
        result.title = meta.get("og:title")
    if not result.description:
        result.description = meta.get("og:description") or meta.get("description")
    if not result.lat:
        lat_str = meta.get("place:location:latitude")
        if lat_str:
            with contextlib.suppress(ValueError):
                result.lat = float(lat_str)
    if not result.lon:
        lon_str = meta.get("place:location:longitude")
        if lon_str:
            with contextlib.suppress(ValueError):
                result.lon = float(lon_str)


def _extract_price_from_text(text: str) -> float | None:
    """Try to find a price in free text (title, description)."""
    # Match patterns like "270 000 €", "270000€", "270,000 EUR".
    pattern = re.compile(r"(\d[\d\s,.]*)\s*(?:€|EUR\b|euros?\b)", re.I)
    m = pattern.search(text)
    if not m:
        return None
    raw = m.group(1).replace(" ", "").replace(",", "").replace(".", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _extract_surface_from_text(text: str) -> float | None:
    """Try to find a surface in free text."""
    pattern = re.compile(r"(\d+(?:[.,]\d+)?)\s*m[²2]\b", re.I)
    m = pattern.search(text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def _extract_rooms_from_text(text: str) -> int | None:
    """Try to find room count in free text."""
    pattern = re.compile(r"(\d+)\s*(?:pièces?|pi[èe]ces?|pieces?|p\.)\b", re.I)
    m = pattern.search(text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def parse_listing_html(html: str) -> ParsedListing:
    """Extract structured listing data from an HTML string.

    The parser tries JSON-LD first, then falls back to meta tags and
    regex patterns on the text. It never assumes a specific platform
    structure — any valid HTML with listing information should work.
    """
    extractor = _JSONLDExtractor()
    extractor.feed(html)

    result = _extract_from_jsonld(extractor.json_ld_blocks)
    _extract_from_meta(extractor.meta, result)

    result.source = _detect_source(html)

    if not result.title:
        result.title = extractor.title

    # Fill gaps from text.
    full_text = (result.title or "") + " " + (result.description or "")
    if not result.price:
        result.price = _extract_price_from_text(full_text)
    if not result.surface:
        result.surface = _extract_surface_from_text(full_text)
    if not result.rooms:
        result.rooms = _extract_rooms_from_text(full_text)

    # Guess type_local from text if not set.
    if not result.type_local and full_text:
        lower = full_text.lower()
        if "maison" in lower or "villa" in lower or "pavillon" in lower:
            result.type_local = "Maison"
        elif "appartement" in lower or "studio" in lower or "f1" in lower:
            result.type_local = "Appartement"

    return result
