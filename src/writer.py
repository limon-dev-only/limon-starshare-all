"""
writer.py

Shared logic reused by all three content-type generators:
    - Converting raw Xtream item dicts into M3U (EXTINF, URL) entries.
    - Rendering entries into full M3U file content.
    - Validating a candidate playlist and writing it only if it passes
      and its content actually changed.
    - The generic "one category -> one M3U file" loop used by the Live
      TV and Movie generators (Series has extra per-episode fetching and
      lives in its own module, but still calls the functions below).

Centralizing this here means live_generator.py and movie_generator.py
stay tiny, and any fix to validation/writing/rendering applies to every
content type at once.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from logger import get_logger
from validator import validate_playlist, count_existing_channels

logger = get_logger(__name__)

PlaylistEntry = Tuple[str, str]  # (EXTINF line, stream URL)


def _clean(value: Any) -> str:
    """Strip newlines/CR and surrounding whitespace so M3U lines stay well-formed."""
    if value is None:
        return ""
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def build_m3u_entries(
    items: List[Dict[str, Any]],
    group_title: str,
    url_builder: Callable[[Dict[str, Any]], Optional[str]],
) -> List[PlaylistEntry]:
    """
    Convert raw Xtream item dicts (live channel, movie, or a pre-flattened
    series episode) into (EXTINF, url) tuples.

    Preserves, whenever available: name, tvg-id (epg_channel_id),
    tvg-name, tvg-logo (stream_icon), and group-title.

    If an item carries its own "group_title" key (series episodes set
    this to "<series> - Season <n>" so each season gets its own folder
    instead of every season of a series being mixed together), that
    overrides the `group_title` argument for that item only. Live/VOD
    items don't set this key, so they always use `group_title` as-is.

    No deduplication is performed — multiple items sharing a display name
    (e.g. several "Sony HD" feeds, or the same movie in SD/HD) are kept,
    since they usually represent genuinely different sources.
    """
    entries: List[PlaylistEntry] = []
    skipped = 0

    for item in items:
        url = url_builder(item)
        if not url:
            skipped += 1
            continue

        name = _clean(item.get("name")) or "Unnamed"
        tvg_id = _clean(item.get("epg_channel_id"))
        tvg_logo = _clean(item.get("stream_icon"))
        clean_group = _clean(item.get("group_title")) or _clean(group_title)

        attrs = []
        if tvg_id:
            attrs.append(f'tvg-id="{tvg_id}"')
        if name:
            attrs.append(f'tvg-name="{name}"')
        if tvg_logo:
            attrs.append(f'tvg-logo="{tvg_logo}"')
        if clean_group:
            attrs.append(f'group-title="{clean_group}"')

        attrs_str = (" " + " ".join(attrs)) if attrs else ""
        entries.append((f"#EXTINF:-1{attrs_str},{name}", url))

    if skipped:
        logger.warning("Skipped %d item(s) with no resolvable stream URL (group '%s')", skipped, group_title)

    return entries


def render_m3u(entries: List[PlaylistEntry]) -> str:
    """Render a list of (EXTINF, URL) tuples into complete M3U file content."""
    lines = ["#EXTM3U"]
    for extinf_line, url in entries:
        lines.append(extinf_line)
        lines.append(url)
    return "\n".join(lines) + "\n"


def write_validated_playlist(
    *,
    output_path: str,
    category_name: str,
    categories: List[Dict[str, Any]],
    entries: List[PlaylistEntry],
    validation_cfg: Dict[str, Any],
) -> Optional[str]:
    """
    Validate a candidate playlist against the configured safety rules and,
    only if it passes AND its rendered content actually changed, write it
    to disk.

    Returns the file's basename if it was written; otherwise None, which
    means the existing file on disk was left untouched.
    """
    previous_count = count_existing_channels(output_path)

    result = validate_playlist(
        category_name=category_name,
        categories=categories,
        channel_count=len(entries),
        min_channels=validation_cfg.get("minimum_channels", 1),
        keep_old_if_empty=validation_cfg.get("keep_old_if_empty", True),
        keep_old_if_category_missing=validation_cfg.get("keep_old_if_category_missing", True),
        previous_channel_count=previous_count,
        max_drop_ratio=validation_cfg.get("max_drop_ratio", 0.5),
    )

    basename = os.path.basename(output_path)

    if not result.is_valid:
        logger.warning(
            "Validation failed for category '%s' -> %s: %s. Existing file kept.",
            category_name, basename, result.reason,
        )
        return None

    content = render_m3u(entries)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    if os.path.isfile(output_path):
        with open(output_path, "r", encoding="utf-8") as f:
            if f.read() == content:
                logger.info("No change for %s (%d entries, category '%s')", basename, len(entries), category_name)
                return None

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info("Wrote %s (%d entries, category '%s')", basename, len(entries), category_name)
    return basename


def index_by_category(items: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group stream/series dicts by their string category_id for O(1) lookup."""
    index: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        index.setdefault(str(item.get("category_id")), []).append(item)
    return index


def find_category_id(category_name: str, categories: List[Dict[str, Any]]) -> Optional[Any]:
    """Case-insensitive lookup of a category_id by its Xtream category_name."""
    target = category_name.strip().lower()
    for cat in categories:
        if (cat.get("category_name") or "").strip().lower() == target:
            return cat.get("category_id")
    return None


def generate_simple_playlists(
    categories: List[Dict[str, Any]],
    streams: List[Dict[str, Any]],
    config: Dict[str, Any],
    output_dir: str,
    url_builder: Callable[[Dict[str, Any]], Optional[str]],
    content_label: str,
) -> List[str]:
    """
    Shared "one category -> one M3U file" generation loop used by the Live
    TV and Movie (VOD) generators, which differ only in which Xtream
    action their data came from and how their stream URL is built.

    Returns the basenames of files that were actually written.
    """
    rules = config.get("playlists", [])
    validation_cfg = config.get("validation", {})
    streams_by_category = index_by_category(streams)

    updated: List[str] = []
    for rule in rules:
        category_name = rule.get("category")
        output_name = rule.get("output")
        if not category_name or not output_name:
            logger.warning("Skipping malformed %s playlist rule: %s", content_label, rule)
            continue

        category_id = find_category_id(category_name, categories)
        items = streams_by_category.get(str(category_id), []) if category_id is not None else []
        entries = build_m3u_entries(items, category_name, url_builder)

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
