"""
movie_generator.py

Generates Movie (VOD) playlists by matching config/movies.json rules
against Xtream VOD categories/streams. A thin wrapper around the shared
writer.generate_simple_playlists loop.
"""

from __future__ import annotations

from typing import Any, Dict, List

from xtream import XtreamClient
from writer import generate_simple_playlists


def generate(
    client: XtreamClient,
    categories: List[Dict[str, Any]],
    streams: List[Dict[str, Any]],
    config: Dict[str, Any],
    output_dir: str,
) -> List[str]:
    """
    Generate every Movie (VOD) playlist configured in config/movies.json.

    Returns the basenames of playlist files that were actually written.
    """
    return generate_simple_playlists(
        categories=categories,
        streams=streams,
        config=config,
        output_dir=output_dir,
        url_builder=client.build_vod_url,
        content_label="movie",
    )
