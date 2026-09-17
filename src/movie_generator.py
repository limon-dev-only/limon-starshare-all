"""
movie_generator.py

Generates a single playlist containing every movie across every VOD
category on the Xtream account — a full mirror of the account's whole
Movies section, not a hand-picked subset of categories.

Each movie keeps its own original Xtream VOD category as its M3U
group-title (via build_category_lookup + per-item group_title
annotation), so the single output file still folds into per-category
folders in the player, matching Xtream's native Movies browsing
structure — it's just delivered as one file instead of many.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from xtream import XtreamClient
from writer import build_m3u_entries, write_validated_bulk_playlist, build_category_lookup

DEFAULT_OUTPUT_NAME = "all-movie.m3u"


def generate(
    client: XtreamClient,
    categories: List[Dict[str, Any]],
    streams: List[Dict[str, Any]],
    config: Dict[str, Any],
    output_dir: str,
) -> List[str]:
    """
    Generate the single "all movies" playlist. The output filename comes
    from config/movies.json's top-level "output" key, defaulting to
    "all-movie.m3u" if not set.

    Returns [basename] if the file was written, otherwise [] (meaning the
    existing file was left untouched, or nothing changed).
    """
    output_name = config.get("output") or DEFAULT_OUTPUT_NAME
    validation_cfg = config.get("validation", {})

    category_names = build_category_lookup(categories)
    annotated_streams = [
        {**stream, "group_title": category_names.get(str(stream.get("category_id")), "Uncategorized")}
        for stream in streams
    ]
    entries = build_m3u_entries(annotated_streams, "Movies", client.build_vod_url)

    output_path = os.path.join(output_dir, output_name)
    written = write_validated_bulk_playlist(
        output_path=output_path, entries=entries, validation_cfg=validation_cfg
    )
    return [written] if written else []
