"""Analyse listing photos with Claude Vision to detect property condition.

Sends up to N photos to the Anthropic API and asks Claude to assess:
- Overall condition bucket (brut / a_renover / partiel / renove)
- Confidence level
- Short rationale in French

The module handles image download, resizing (to stay within API limits),
and prompt construction. It is entirely optional — requires an Anthropic
API key to function.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass

import httpx

from shadow_tester.config import get_settings
from shadow_tester.listings.condition import ConditionDetection

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────

_ALLOWED_CONDITIONS = ("brut", "a_renover", "partiel", "renove", "inconnu")

_SYSTEM_PROMPT = """\
Tu es un expert immobilier français spécialisé dans l'estimation de l'état \
des biens résidentiels. On te montre des photos d'un bien immobilier issu \
d'une annonce de vente.

Analyse les photos et détermine l'état du bien parmi ces catégories :
- **brut** : murs béton/parpaing nus, pas de second œuvre, local commercial \
ou industriel non aménagé, chantier en cours.
- **a_renover** : habitable mais vétuste. Signes : papier peint décollé, \
carrelage fissuré, cuisine/salle de bain très datées (années 70-80), \
traces d'humidité, menuiseries anciennes, électricité apparente.
- **partiel** : partiellement rénové. Certaines pièces sont refaites \
(cuisine neuve par ex.) mais d'autres restent à reprendre. Mélange de \
finitions récentes et anciennes.
- **renove** : entièrement rénové ou neuf. Finitions soignées, matériaux \
récents, cuisine équipée moderne, salle de bain contemporaine, sol en \
bon état, peintures fraîches.
- **inconnu** : pas assez d'éléments visuels pour trancher (photos \
extérieures uniquement, trop floues, etc.).

Réponds UNIQUEMENT avec un JSON valide, sans markdown ni texte autour :
{"condition": "<valeur>", "confidence": <0.0-1.0>, "rationale": "<1-2 phrases en français>"}
"""

_USER_PROMPT = (
    "Voici les photos de l'annonce. Analyse l'état général du bien "
    "et réponds avec le JSON demandé."
)

# Max bytes per image sent to the API (resize if larger).
_MAX_IMAGE_BYTES = 1_500_000  # ~1.5 MB


# ── Public API ───────────────────────────────────────────────────────────

class VisionError(Exception):
    """Raised when vision analysis fails."""


@dataclass
class VisionResult:
    """Result of Claude Vision photo analysis."""

    condition: str
    confidence: float
    rationale: str
    photos_analyzed: int


def _download_image(url: str, client: httpx.Client | None = None) -> tuple[bytes, str]:
    """Download an image and return (bytes, media_type)."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
    }
    if client is not None:
        resp = client.get(url, headers=headers, timeout=15.0, follow_redirects=True)
    else:
        with httpx.Client() as c:
            resp = c.get(url, headers=headers, timeout=15.0, follow_redirects=True)
    resp.raise_for_status()

    content_type = resp.headers.get("content-type", "image/jpeg")
    # Normalise to Anthropic-accepted media types.
    if "png" in content_type:
        media_type = "image/png"
    elif "webp" in content_type:
        media_type = "image/webp"
    elif "gif" in content_type:
        media_type = "image/gif"
    else:
        media_type = "image/jpeg"

    return resp.content, media_type


def _build_image_block(data: bytes, media_type: str) -> dict:
    """Build an Anthropic API image_content block from raw bytes."""
    encoded = base64.standard_b64encode(data).decode("ascii")
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": encoded,
        },
    }


def analyze_photos(
    image_urls: list[str],
    *,
    description: str | None = None,
    http_client: httpx.Client | None = None,
    anthropic_client: object | None = None,
) -> VisionResult:
    """Analyze listing photos with Claude Vision.

    Parameters
    ----------
    image_urls:
        URLs of listing photos to analyze.
    description:
        Optional listing description text (added as context).
    http_client:
        Injectable httpx.Client for downloading images (testing).
    anthropic_client:
        Injectable Anthropic client (testing).

    Returns
    -------
    VisionResult with condition, confidence, rationale.

    Raises
    ------
    VisionError
        If the API key is missing, download fails, or API call fails.
    """
    settings = get_settings()

    if not settings.anthropic_api_key and anthropic_client is None:
        raise VisionError(
            "Clé API Anthropic requise pour l'analyse photo. "
            "Définir SHADOW_ANTHROPIC_API_KEY ou ANTHROPIC_API_KEY."
        )

    max_photos = settings.vision_max_photos
    urls_to_fetch = image_urls[:max_photos]

    if not urls_to_fetch:
        raise VisionError("Aucune URL de photo fournie.")

    # Download images.
    image_blocks: list[dict] = []
    for url in urls_to_fetch:
        try:
            data, media_type = _download_image(url, client=http_client)
            if len(data) > _MAX_IMAGE_BYTES:
                logger.info("Image too large (%d bytes), skipping: %s", len(data), url)
                continue
            image_blocks.append(_build_image_block(data, media_type))
        except (httpx.HTTPError, httpx.RequestError) as exc:
            logger.warning("Failed to download %s: %s", url, exc)
            continue

    if not image_blocks:
        raise VisionError("Impossible de télécharger les photos.")

    # Build the message content.
    content: list[dict] = list(image_blocks)

    user_text = _USER_PROMPT
    if description:
        user_text += f"\n\nDescription de l'annonce : {description[:500]}"

    content.append({"type": "text", "text": user_text})

    # Call the API.
    if anthropic_client is not None:
        client_api = anthropic_client
    else:
        import anthropic

        client_api = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    try:
        response = client_api.messages.create(
            model=settings.vision_model,
            max_tokens=300,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
    except Exception as exc:
        raise VisionError(f"Erreur API Anthropic : {exc}") from exc

    # Parse the response.
    raw_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            raw_text += block.text

    return _parse_vision_response(raw_text, photos_analyzed=len(image_blocks))


def _parse_vision_response(raw: str, photos_analyzed: int) -> VisionResult:
    """Parse the JSON response from Claude Vision."""
    import json

    # Strip markdown fences if present.
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise VisionError(
            f"Réponse Claude non-JSON : {raw[:200]}"
        ) from exc

    condition = data.get("condition", "inconnu")
    if condition not in _ALLOWED_CONDITIONS:
        condition = "inconnu"

    confidence = 0.5
    try:
        confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
    except (ValueError, TypeError):
        pass

    rationale = str(data.get("rationale", "Analyse photo Claude Vision"))

    return VisionResult(
        condition=condition,
        confidence=confidence,
        rationale=rationale,
        photos_analyzed=photos_analyzed,
    )


def vision_to_condition_detection(result: VisionResult) -> ConditionDetection:
    """Convert a VisionResult to a ConditionDetection for unified handling."""
    return ConditionDetection(
        condition=result.condition,
        confidence=result.confidence,
        rationale=f"[Vision {result.photos_analyzed} photo(s)] {result.rationale}",
        matched_keywords=[],
    )
