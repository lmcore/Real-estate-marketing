"""Detect property condition from listing description using keyword heuristics.

This is a deterministic, offline, zero-cost detector. It scans the listing
description for known French real-estate keywords and returns a condition
bucket + confidence + rationale.

The detector is deliberately conservative: it only emits a condition when
keywords are unambiguous. Mixed signals → ``inconnu``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Each rule: (compiled regex, condition, weight).
# Higher weight = stronger signal. We collect all matches then decide.

_BRUT_PATTERNS = [
    (re.compile(r"\bbrut(?:e)?\b", re.I), 3),
    (re.compile(r"\bgros[\s-]?œuvre\b", re.I), 3),
    (re.compile(r"\bgros[\s-]?oeuvre\b", re.I), 3),
    (re.compile(r"\btout\s+(?:est\s+)?(?:à|a)\s+(?:faire|refaire)\b", re.I), 3),
]

_A_RENOVER_PATTERNS = [
    (re.compile(r"\b(?:à|a)\s+rénover\b", re.I), 3),
    (re.compile(r"\b(?:à|a)\s+renover\b", re.I), 3),
    (re.compile(r"\btravaux\s+(?:à|a)\s+prévoir\b", re.I), 3),
    (re.compile(r"\btravaux\s+(?:à|a)\s+prevoir\b", re.I), 3),
    (re.compile(r"\bnécessite\s+(?:des\s+)?travaux\b", re.I), 2),
    (re.compile(r"\bbesoin\s+de\s+(?:gros\s+)?travaux\b", re.I), 3),
    (re.compile(r"\b(?:en\s+)?ruine\b", re.I), 3),
    (re.compile(r"\bvétuste\b", re.I), 2),
    (re.compile(r"\bà\s+restaurer\b", re.I), 3),
    (re.compile(r"\bà\s+réhabiliter\b", re.I), 3),
]

_PARTIEL_PATTERNS = [
    (re.compile(r"\brafra[iî]chissement\b", re.I), 2),
    (re.compile(r"\b(?:à|a)\s+moderniser\b", re.I), 2),
    (re.compile(r"\bquelques\s+travaux\b", re.I), 2),
    (re.compile(r"\bpartiellement\s+rénové\b", re.I), 3),
    (re.compile(r"\bpartiellement\s+renove\b", re.I), 3),
    (re.compile(r"\btravaux\s+de\s+rafra[iî]chissement\b", re.I), 2),
    (re.compile(r"\bpetits?\s+travaux\b", re.I), 2),
]

_RENOVE_PATTERNS = [
    (re.compile(r"\brénové(?:e)?\b", re.I), 3),
    (re.compile(r"\brenové(?:e)?\b", re.I), 3),
    (re.compile(r"\brenove(?:e)?\b", re.I), 3),
    (re.compile(r"\brefait(?:e)?\s+(?:à|a)\s+neuf\b", re.I), 3),
    (re.compile(r"\bentièrement\s+rénové\b", re.I), 4),
    (re.compile(r"\bclé\s+en\s+main\b", re.I), 3),
    (re.compile(r"\bcle\s+en\s+main\b", re.I), 3),
    (re.compile(r"\bneuf\b", re.I), 2),
    (re.compile(r"\bparfait\s+état\b", re.I), 2),
    (re.compile(r"\baucun\s+travaux?\b", re.I), 2),
    (re.compile(r"\bpas\s+de\s+travaux?\b", re.I), 2),
    (re.compile(r"\bétat\s+impeccable\b", re.I), 2),
    (re.compile(r"\bmove[\s-]?in\s+ready\b", re.I), 2),
]

_BUCKETS = [
    ("brut", _BRUT_PATTERNS),
    ("a_renover", _A_RENOVER_PATTERNS),
    ("partiel", _PARTIEL_PATTERNS),
    ("renove", _RENOVE_PATTERNS),
]


@dataclass
class ConditionDetection:
    """Result of keyword-based condition detection."""

    condition: str               # brut / a_renover / partiel / renove / inconnu
    confidence: float            # 0.0..1.0
    rationale: str               # human-readable explanation
    matched_keywords: list[str]  # the actual regex matches found


def detect_condition(text: str | None) -> ConditionDetection:
    """Analyse ``text`` and return the most likely condition bucket.

    Returns ``inconnu`` with confidence 0 when the text is empty, contains
    no recognised keywords, or contains conflicting signals.
    """
    if not text or not text.strip():
        return ConditionDetection(
            condition="inconnu",
            confidence=0.0,
            rationale="pas de description",
            matched_keywords=[],
        )

    scores: dict[str, int] = {}
    matches: dict[str, list[str]] = {}

    for bucket, patterns in _BUCKETS:
        total_weight = 0
        bucket_matches: list[str] = []
        for regex, weight in patterns:
            found = regex.findall(text)
            if found:
                total_weight += weight * len(found)
                bucket_matches.extend(found)
        if total_weight > 0:
            scores[bucket] = total_weight
            matches[bucket] = bucket_matches

    if not scores:
        return ConditionDetection(
            condition="inconnu",
            confidence=0.0,
            rationale="aucun mot-clé reconnu",
            matched_keywords=[],
        )

    # Sort by score descending.
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    best_bucket, best_score = ranked[0]

    # Check for conflicting signals: if second-best is close to best,
    # the signal is ambiguous.
    if len(ranked) >= 2:
        second_score = ranked[1][1]
        if second_score >= best_score * 0.7:
            all_kw = []
            for kws in matches.values():
                all_kw.extend(kws)
            return ConditionDetection(
                condition="inconnu",
                confidence=0.2,
                rationale=(
                    f"signaux contradictoires ({ranked[0][0]} vs {ranked[1][0]})"
                ),
                matched_keywords=all_kw,
            )

    # Compute confidence from score magnitude.
    if best_score >= 6:
        confidence = 0.9
    elif best_score >= 4:
        confidence = 0.7
    elif best_score >= 2:
        confidence = 0.5
    else:
        confidence = 0.3

    return ConditionDetection(
        condition=best_bucket,
        confidence=confidence,
        rationale=f"mots-clés détectés: {', '.join(matches[best_bucket])}",
        matched_keywords=matches[best_bucket],
    )
