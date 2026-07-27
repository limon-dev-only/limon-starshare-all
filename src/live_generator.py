"""
live_generator.py

Generates Live TV playlists by matching config/live.json rules against
Xtream live categories/streams. A thin wrapper around the shared
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
    Generate every Live TV playlist configured in config/live.json.

    Returns the basenames of playlist files that were actually written.
    """
    return generate_simple_playlists(
        categories=categories,
        streams=streams,
        config=config,
        output_dir=output_dir,
        url_builder=client.build_live_url,
        content_label="live",
    )
