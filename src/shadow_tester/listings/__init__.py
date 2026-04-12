"""Listings capture module — user-initiated saving of real-estate listings."""

from shadow_tester.listings.condition import ConditionDetection, detect_condition
from shadow_tester.listings.fetch import FetchError, fetch_listing_html
from shadow_tester.listings.matcher import (
    MatchCandidate,
    MatchResult,
    match_all_unmatched,
    match_listing,
)
from shadow_tester.listings.models import Listing
from shadow_tester.listings.parsers import ParsedListing, parse_listing_html
from shadow_tester.listings.repo import (
    add_listing,
    delete_listing,
    get_listing,
    list_listings,
    update_listing,
)
from shadow_tester.listings.stats import ConditionBucket, ListingStats, compute_listing_stats

__all__ = [
    "ConditionBucket",
    "ConditionDetection",
    "FetchError",
    "Listing",
    "ListingStats",
    "MatchCandidate",
    "MatchResult",
    "ParsedListing",
    "add_listing",
    "compute_listing_stats",
    "delete_listing",
    "detect_condition",
    "fetch_listing_html",
    "get_listing",
    "list_listings",
    "match_all_unmatched",
    "match_listing",
    "parse_listing_html",
    "update_listing",
]
