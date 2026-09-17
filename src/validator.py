"""
validator.py

Safety checks that stop a bad Xtream response (renamed category,
transient outage, partial API glitch) from overwriting a previously good
playlist file.

Two validation modes:
    - validate_playlist: used by Live TV, which is still generated per
      configured category, so a missing category is itself a reason to
      reject the update.
    - validate_bulk_playlist: used by Movies/Series, which are now
      generated as one file spanning every category on the account — with
      no single category to check existence for, this only guards against
      an empty or abnormally collapsed result.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Outcome of validating one candidate playlist before it's written."""

    is_valid: bool
    reason: str
    channel_count: int


def category_exists(category_name: str, categories: List[Dict[str, Any]]) -> bool:
    """Case-insensitive check that `category_name` is present in `categories`."""
    target = category_name.strip().lower()
    names = {(c.get("category_name") or "").strip().lower() for c in categories}
    return target in names


def count_existing_channels(filepath: str) -> int:
    """Count #EXTINF lines in an existing playlist file (0 if it doesn't exist yet)."""
    if not os.path.isfile(filepath):
        return 0
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        return content.count("#EXTINF")
    except OSError as exc:
        logger.warning("Could not read existing playlist '%s' for comparison: %s", filepath, exc)
        return 0


def validate_playlist(
    category_name: str,
    categories: List[Dict[str, Any]],
    channel_count: int,
    min_channels: int,
    keep_old_if_empty: bool,
    keep_old_if_category_missing: bool,
    previous_channel_count: Optional[int] = None,
    max_drop_ratio: float = 0.5,
) -> ValidationResult:
    """
    Run the configured validation rules for one category-scoped playlist
    (Live TV).

    Rule 1 — the configured category must exist in the current Xtream
             response, or the previous file is kept.
    Rule 2 — the channel count must be non-trivial and must not have
             collapsed abnormally versus the last successful run.
    """
    if not category_exists(category_name, categories):
        if keep_old_if_category_missing:
            return ValidationResult(
                is_valid=False,
                reason=f"Category '{category_name}' not found in Xtream response",
                channel_count=channel_count,
            )
        logger.warning(
            "Category '%s' missing but keep_old_if_category_missing=False; proceeding anyway", category_name
        )

    if channel_count < min_channels:
        if keep_old_if_empty:
            return ValidationResult(
                is_valid=False,
                reason=f"Channel count ({channel_count}) is below minimum_channels ({min_channels})",
                channel_count=channel_count,
            )
        logger.warning(
            "Channel count %d below minimum for '%s' but keep_old_if_empty=False; proceeding anyway",
            channel_count, category_name,
        )

    if previous_channel_count and previous_channel_count > 0:
        drop_ratio = 1 - (channel_count / previous_channel_count)
        if drop_ratio > max_drop_ratio:
            return ValidationResult(
                is_valid=False,
                reason=(
                    f"Abnormal drop for '{category_name}': previous={previous_channel_count}, "
                    f"new={channel_count} ({drop_ratio:.0%} drop, limit={max_drop_ratio:.0%})"
                ),
                channel_count=channel_count,
            )

    return ValidationResult(is_valid=True, reason="OK", channel_count=channel_count)


def validate_bulk_playlist(
    channel_count: int,
    min_channels: int,
    keep_old_if_empty: bool,
    previous_channel_count: Optional[int] = None,
    max_drop_ratio: float = 0.5,
) -> ValidationResult:
    """
    Validation for a playlist that spans every category of a content type
    at once (the "all movies" / "all series" files), where there's no
    single configured category name to check existence for. Only guards
    against an empty or abnormally collapsed result versus the previous
    run.
    """
    if channel_count < min_channels:
        if keep_old_if_empty:
            return ValidationResult(
                is_valid=False,
                reason=f"Channel count ({channel_count}) is below minimum_channels ({min_channels})",
                channel_count=channel_count,
            )
        logger.warning(
            "Channel count %d below minimum but keep_old_if_empty=False; proceeding anyway", channel_count
        )

    if previous_channel_count and previous_channel_count > 0:
        drop_ratio = 1 - (channel_count / previous_channel_count)
        if drop_ratio > max_drop_ratio:
            return ValidationResult(
                is_valid=False,
                reason=(
                    f"Abnormal drop: previous={previous_channel_count}, new={channel_count} "
                    f"({drop_ratio:.0%} drop, limit={max_drop_ratio:.0%})"
                ),
                channel_count=channel_count,
            )

    return ValidationResult(is_valid=True, reason="OK", channel_count=channel_count)
