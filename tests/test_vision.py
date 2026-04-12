"""Tests for the Claude Vision photo analysis module."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import httpx
import pytest

from shadow_tester.listings.vision import (
    VisionError,
    _build_image_block,
    _parse_vision_response,
    analyze_photos,
    vision_to_condition_detection,
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
    monkeypatch.setenv("SHADOW_ANTHROPIC_API_KEY", "test-key-xxx")
    cfg._settings = None
    yield db_path
    cfg._settings = None


def _make_mock_anthropic(response_text: str) -> MagicMock:
    """Create a mock Anthropic client that returns the given text."""

    @dataclass
    class TextBlock:
        text: str
        type: str = "text"

    @dataclass
    class MockResponse:
        content: list

    mock_client = MagicMock()
    mock_client.messages.create.return_value = MockResponse(
        content=[TextBlock(text=response_text)]
    )
    return mock_client


def _make_image_transport(content_type: str = "image/jpeg") -> httpx.MockTransport:
    """Transport that returns a tiny fake image for any request."""
    # 1x1 red JPEG — smallest valid JPEG.
    fake_jpeg = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n"
        b"\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d"
        b"\x1a\x1c\x1c $.\' \",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0\x00"
        b"\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01"
        b"\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02"
        b"\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xd9"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=fake_jpeg,
            headers={"content-type": content_type},
        )

    return httpx.MockTransport(handler)


# ── Unit tests: response parsing ─────────────────────────────────────────


class TestParseVisionResponse:
    def test_valid_json(self):
        raw = '{"condition": "a_renover", "confidence": 0.85, "rationale": "Cuisine datée, papier peint usé"}'
        result = _parse_vision_response(raw, photos_analyzed=3)
        assert result.condition == "a_renover"
        assert result.confidence == pytest.approx(0.85)
        assert "Cuisine datée" in result.rationale
        assert result.photos_analyzed == 3

    def test_json_with_markdown_fences(self):
        raw = '```json\n{"condition": "renove", "confidence": 0.9, "rationale": "Tout est neuf"}\n```'
        result = _parse_vision_response(raw, photos_analyzed=2)
        assert result.condition == "renove"

    def test_invalid_condition_falls_back(self):
        raw = '{"condition": "moyen", "confidence": 0.5, "rationale": "Pas clair"}'
        result = _parse_vision_response(raw, photos_analyzed=1)
        assert result.condition == "inconnu"

    def test_non_json_raises_error(self):
        with pytest.raises(VisionError, match="non-JSON"):
            _parse_vision_response("I can see a house", photos_analyzed=1)

    def test_missing_fields_use_defaults(self):
        raw = '{"condition": "brut"}'
        result = _parse_vision_response(raw, photos_analyzed=1)
        assert result.condition == "brut"
        assert result.confidence == 0.5
        assert result.photos_analyzed == 1

    def test_confidence_clamped(self):
        raw = '{"condition": "renove", "confidence": 1.5, "rationale": "Certain"}'
        result = _parse_vision_response(raw, photos_analyzed=1)
        assert result.confidence == 1.0

        raw2 = '{"condition": "renove", "confidence": -0.5, "rationale": "Hmm"}'
        result2 = _parse_vision_response(raw2, photos_analyzed=1)
        assert result2.confidence == 0.0


# ── Unit tests: image block ──────────────────────────────────────────────


class TestBuildImageBlock:
    def test_base64_encoding(self):
        data = b"fake-image-bytes"
        block = _build_image_block(data, "image/jpeg")
        assert block["type"] == "image"
        assert block["source"]["type"] == "base64"
        assert block["source"]["media_type"] == "image/jpeg"
        # Verify it's valid base64.
        import base64

        decoded = base64.standard_b64decode(block["source"]["data"])
        assert decoded == data


# ── Unit tests: vision_to_condition_detection ────────────────────────────


class TestVisionToConditionDetection:
    def test_conversion(self):
        from shadow_tester.listings.vision import VisionResult

        vr = VisionResult(
            condition="a_renover",
            confidence=0.8,
            rationale="Salle de bain vétuste",
            photos_analyzed=2,
        )
        det = vision_to_condition_detection(vr)
        assert det.condition == "a_renover"
        assert det.confidence == 0.8
        assert "Vision 2 photo(s)" in det.rationale
        assert "Salle de bain vétuste" in det.rationale


# ── Integration tests: analyze_photos with mocked API ────────────────────


class TestAnalyzePhotos:
    def test_success(self, isolated_db):
        """Full flow: download images → call API → parse response."""
        mock_api = _make_mock_anthropic(
            '{"condition": "a_renover", "confidence": 0.85, "rationale": "Papier peint décollé"}'
        )
        http_client = httpx.Client(transport=_make_image_transport())

        result = analyze_photos(
            ["https://example.com/photo1.jpg", "https://example.com/photo2.jpg"],
            description="Maison ancienne",
            http_client=http_client,
            anthropic_client=mock_api,
        )
        assert result.condition == "a_renover"
        assert result.confidence == pytest.approx(0.85)
        assert result.photos_analyzed == 2

        # Verify the API was called with image blocks.
        call_args = mock_api.messages.create.call_args
        messages = call_args.kwargs["messages"]
        content = messages[0]["content"]
        image_blocks = [b for b in content if b["type"] == "image"]
        assert len(image_blocks) == 2

    def test_no_urls_raises(self, isolated_db):
        mock_api = _make_mock_anthropic("{}")
        with pytest.raises(VisionError, match="Aucune URL"):
            analyze_photos([], anthropic_client=mock_api)

    def test_no_api_key_raises(self, tmp_path, monkeypatch):
        """Without API key and no injected client, should raise."""
        from shadow_tester import config as cfg

        monkeypatch.setenv("SHADOW_DB_PATH", str(tmp_path / "test.sqlite"))
        monkeypatch.setenv("SHADOW_CACHE_DIR", str(tmp_path / "cache"))
        monkeypatch.delenv("SHADOW_ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        (tmp_path / "cache").mkdir(exist_ok=True)
        cfg._settings = None

        try:
            with pytest.raises(VisionError, match="Clé API"):
                analyze_photos(["https://example.com/photo.jpg"])
        finally:
            cfg._settings = None

    def test_download_failure_skips_image(self, isolated_db):
        """If one image fails to download, it's skipped."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(404, text="Not Found")
            return httpx.Response(
                200, content=b"\x89PNG\r\n", headers={"content-type": "image/png"},
            )

        http_client = httpx.Client(transport=httpx.MockTransport(handler))
        mock_api = _make_mock_anthropic(
            '{"condition": "renove", "confidence": 0.7, "rationale": "OK"}'
        )

        result = analyze_photos(
            ["https://example.com/bad.jpg", "https://example.com/good.jpg"],
            http_client=http_client,
            anthropic_client=mock_api,
        )
        assert result.photos_analyzed == 1

    def test_all_downloads_fail_raises(self, isolated_db):
        """If ALL images fail, raise VisionError."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Error")

        http_client = httpx.Client(transport=httpx.MockTransport(handler))
        mock_api = _make_mock_anthropic("{}")

        with pytest.raises(VisionError, match="Impossible de télécharger"):
            analyze_photos(
                ["https://example.com/fail.jpg"],
                http_client=http_client,
                anthropic_client=mock_api,
            )

    def test_respects_max_photos(self, isolated_db):
        """Only fetches up to vision_max_photos images."""
        mock_api = _make_mock_anthropic(
            '{"condition": "partiel", "confidence": 0.6, "rationale": "Mix ancien/neuf"}'
        )
        http_client = httpx.Client(transport=_make_image_transport())

        urls = [f"https://example.com/photo{i}.jpg" for i in range(10)]
        result = analyze_photos(
            urls,
            http_client=http_client,
            anthropic_client=mock_api,
        )
        # Default max is 4.
        assert result.photos_analyzed <= 4

    def test_description_included_in_prompt(self, isolated_db):
        """Description text should be appended to the user message."""
        mock_api = _make_mock_anthropic(
            '{"condition": "renove", "confidence": 0.9, "rationale": "Neuf"}'
        )
        http_client = httpx.Client(transport=_make_image_transport())

        analyze_photos(
            ["https://example.com/photo.jpg"],
            description="Maison entièrement rénovée en 2024",
            http_client=http_client,
            anthropic_client=mock_api,
        )

        call_args = mock_api.messages.create.call_args
        messages = call_args.kwargs["messages"]
        text_blocks = [b for b in messages[0]["content"] if b["type"] == "text"]
        assert any("Maison entièrement rénovée" in b["text"] for b in text_blocks)


# ── Parser image extraction tests ────────────────────────────────────────


class TestParserImageExtraction:
    def test_jsonld_images(self):
        from shadow_tester.listings.parsers import parse_listing_html

        html = """
        <html><head><script type="application/ld+json">
        {"@type": "Product", "name": "Test", "image": [
            "https://img.example.com/1.jpg",
            "https://img.example.com/2.jpg"
        ]}
        </script></head><body></body></html>
        """
        result = parse_listing_html(html)
        assert len(result.images) == 2
        assert result.images[0] == "https://img.example.com/1.jpg"

    def test_og_image_fallback(self):
        from shadow_tester.listings.parsers import parse_listing_html

        html = """
        <html><head>
        <meta property="og:image" content="https://img.example.com/og.jpg">
        <title>Test</title>
        </head><body></body></html>
        """
        result = parse_listing_html(html)
        assert len(result.images) == 1
        assert result.images[0] == "https://img.example.com/og.jpg"

    def test_img_tag_fallback(self):
        from shadow_tester.listings.parsers import parse_listing_html

        html = """
        <html><head><title>Test</title></head><body>
        <img src="https://img.example.com/a.jpg">
        <img src="https://img.example.com/b.jpg">
        <img src="/relative/ignored.jpg">
        </body></html>
        """
        result = parse_listing_html(html)
        assert len(result.images) == 2

    def test_img_deduplication(self):
        from shadow_tester.listings.parsers import parse_listing_html

        html = """
        <html><head><title>Test</title></head><body>
        <img src="https://img.example.com/a.jpg">
        <img src="https://img.example.com/a.jpg">
        <img src="https://img.example.com/b.jpg">
        </body></html>
        """
        result = parse_listing_html(html)
        assert len(result.images) == 2
