"""
series_generator.py

Generates Series playlists. Unlike Live/VOD, Xtream's get_series only
returns series metadata (no episodes) — the episode list for each series
must be fetched individually via get_series_info. This module fetches
episodes only for series that fall under a configured category, keeping
API calls proportional to what's actually needed rather than pulling
every episode of every series on the account.

A failure fetching one series' episodes (network hiccup, malformed
response) is logged and skipped without failing the whole run.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from logger import get_logger
from xtream import XtreamClient, XtreamAPIError
from writer import build_m3u_entries, write_validated_playlist, index_by_category, find_category_id

logger = get_logger(__name__)


def generate(
    client: XtreamClient,
    categories: List[Dict[str, Any]],
    series_list: List[Dict[str, Any]],
    config: Dict[str, Any],
    output_dir: str,
) -> List[str]:
    """
    Generate every Series playlist configured in config/series.json.

    Returns the basenames of playlist files that were actually written.
    """
    rules = config.get("playlists", [])
    validation_cfg = config.get("validation", {})
    series_by_category = index_by_category(series_list)

    updated: List[str] = []
    for rule in rules:
        category_name = rule.get("category")
        output_name = rule.get("output")
        if not category_name or not output_name:
            logger.warning("Skipping malformed series playlist rule: %s", rule)
            continue

        category_id = find_category_id(category_name, categories)
        series_in_category = series_by_category.get(str(category_id), []) if category_id is not None else []

        episodes = _fetch_episodes(client, series_in_category)
        entries = build_m3u_entries(episodes, category_name, client.build_series_episode_url)

        output_path = os.path.join(output_dir, output_name)
        written = write_validated_playlist(
            output_path=output_path,
            category_name=category_name,
            categories=categories,
            entries=entries,
            validation_cfg=validation_cfg,
        )
        if written:
            updated.append(written)

    return updated


def _fetch_episodes(client: XtreamClient, series_in_category: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fetch and flatten episodes for every series in one category, skipping failures per-series."""
    episodes: List[Dict[str, Any]] = []
    for series in series_in_category:
        series_id = series.get("series_id")
        series_name = series.get("name") or "Unknown series"
        if series_id is None:
            continue
        try:
            episodes.extend(client.get_series_episodes(series_id, series_name))
        except XtreamAPIError as exc:
            logger.warning(
                "Could not fetch episodes for series '%s' (id=%s): %s. Skipping this series only.",
                series_name, series_id, exc,
            )
    return episodes
