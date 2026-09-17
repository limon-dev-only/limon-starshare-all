"""
series_generator.py

Generates a single playlist containing every episode of every series
across every Series category on the Xtream account — a verbatim mirror
of the account's whole Series section, not a hand-picked subset and not
a custom reorganization.

Each episode's group-title is the series' own real Xtream category name
(e.g. "Chorki/Bangla"), and each episode's name follows Xtream's own
native naming convention ("<series name> S<season>E<episode> - <title>"),
exactly matching what Xtream's own Series section looks like — nothing
regrouped or renamed by us.

A failure fetching one series' episodes (network hiccup, malformed
response) is logged and skipped without failing the whole run.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from logger import get_logger
from xtream import XtreamClient, XtreamAPIError
from writer import build_m3u_entries, write_validated_bulk_playlist, build_category_lookup, PlaylistEntry

logger = get_logger(__name__)

DEFAULT_OUTPUT_NAME = "all-series.m3u"


def generate(
    client: XtreamClient,
    categories: List[Dict[str, Any]],
    series_list: List[Dict[str, Any]],
    config: Dict[str, Any],
    output_dir: str,
) -> List[str]:
    """
    Generate the single "all series" playlist covering every series on
    the account, grouped exactly as Xtream itself groups them (by their
    real category). The output filename comes from config/series.json's
    top-level "output" key, defaulting to "all-series.m3u" if not set.

    Returns [basename] if the file was written, otherwise [].
    """
    output_name = config.get("output") or DEFAULT_OUTPUT_NAME
    validation_cfg = config.get("validation", {})

    category_names = build_category_lookup(categories)
    entries = _build_entries_for_all_series(client, series_list, category_names)

    output_path = os.path.join(output_dir, output_name)
    written = write_validated_bulk_playlist(
        output_path=output_path, entries=entries, validation_cfg=validation_cfg
    )
    return [written] if written else []


def _build_entries_for_all_series(
    client: XtreamClient, series_list: List[Dict[str, Any]], category_names: Dict[str, str]
) -> List[PlaylistEntry]:
    """
    Fetch and build M3U entries for every series on the account. Each
    series' episodes are annotated with that series' own real Xtream
    category name as group_title, so grouping matches Xtream verbatim
    rather than any custom scheme. A failure on one series is logged and
    skipped without affecting the rest.
    """
    entries: List[PlaylistEntry] = []
    for series in series_list:
        series_id = series.get("series_id")
        series_name = series.get("name") or "Unknown series"
        if series_id is None:
            continue

        category_name = category_names.get(str(series.get("category_id")), "Uncategorized")

        try:
            episodes = client.get_series_episodes(series_id, series_name)
        except XtreamAPIError as exc:
            logger.warning(
                "Could not fetch episodes for series '%s' (id=%s): %s. Skipping this series only.",
                series_name, series_id, exc,
            )
            continue

        annotated = [{**ep, "group_title": category_name} for ep in episodes]
        entries.extend(build_m3u_entries(annotated, category_name, client.build_series_episode_url))
    return entries
