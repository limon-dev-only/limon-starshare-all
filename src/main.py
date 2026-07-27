"""
main.py

Entry point for the multi-content-type IPTV playlist generator.

Flow:
    1. Read Xtream credentials from environment variables (GitHub Actions
       Secrets — never hardcoded).
    2. Load config/live.json, config/movies.json, config/series.json.
    3. Authenticate with the Xtream server.
    4. Fetch Live, Movie, and Series categories + streams in one pass.
    5. Delegate to live_generator / movie_generator / series_generator,
       each of which matches configured categories, validates the result,
       and writes only what's safe and actually changed.
    6. Log a summary. The GitHub Actions workflow commits only the files
       that were written, since unchanged files are never touched.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from logger import get_logger  # noqa: E402
from xtream import XtreamClient, XtreamAPIError, XtreamAuthenticationError  # noqa: E402
import live_generator  # noqa: E402
import movie_generator  # noqa: E402
import series_generator  # noqa: E402

logger = get_logger("main")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(REPO_ROOT, "config")
OUTPUT_DIR = os.path.join(REPO_ROOT, "output")

CONTENT_SUBDIRS = ("live", "movies", "series")


def load_json_config(filename: str) -> Dict[str, Any]:
    """
    Load a JSON config file from config/. Returns an empty dict (meaning
    "nothing configured for this content type") if the file is missing,
    but exits on malformed JSON since that's a config authoring mistake.
    """
    path = os.path.join(CONFIG_DIR, filename)
    if not os.path.isfile(path):
        logger.warning("Config file '%s' not found; skipping that content type.", filename)
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        logger.error("Config file '%s' is not valid JSON: %s", filename, exc)
        sys.exit(1)


def get_env_credentials() -> Tuple[str, str, str]:
    """Read Xtream credentials from environment variables (GitHub Actions Secrets)."""
    host = os.environ.get("XTREAM_HOST")
    username = os.environ.get("XTREAM_USERNAME")
    password = os.environ.get("XTREAM_PASSWORD")

    missing = [
        name
        for name, value in (
            ("XTREAM_HOST", host),
            ("XTREAM_USERNAME", username),
            ("XTREAM_PASSWORD", password),
        )
        if not value
    ]
    if missing:
        logger.error(
            "Missing required environment variable(s): %s. Set these as GitHub Actions Secrets.",
            ", ".join(missing),
        )
        sys.exit(1)

    return host, username, password  # type: ignore[return-value]


def main() -> None:
    """Run one full generation pass across Live, Movies, and Series."""
    logger.info("=== IPTV Playlist Generator starting ===")

    host, username, password = get_env_credentials()

    live_cfg = load_json_config("live.json")
    movies_cfg = load_json_config("movies.json")
    series_cfg = load_json_config("series.json")

    for sub in CONTENT_SUBDIRS:
        os.makedirs(os.path.join(OUTPUT_DIR, sub), exist_ok=True)

    client = XtreamClient(host, username, password)

    try:
        client.authenticate()
    except XtreamAuthenticationError as exc:
        logger.error("Xtream authentication failed: %s", exc)
        sys.exit(1)

    try:
        live_categories = client.get_live_categories()
        live_streams = client.get_live_streams()
        movie_categories = client.get_vod_categories()
        movie_streams = client.get_vod_streams()
        series_categories = client.get_series_categories()
        series_list = client.get_series()
    except XtreamAPIError as exc:
        logger.error("Failed to fetch data from Xtream API: %s", exc)
        sys.exit(1)

    logger.info(
        "Fetched live(%d categories / %d streams), movies(%d categories / %d streams), "
        "series(%d categories / %d titles)",
        len(live_categories), len(live_streams),
        len(movie_categories), len(movie_streams),
        len(series_categories), len(series_list),
    )

    updated_live = live_generator.generate(
        client, live_categories, live_streams, live_cfg, os.path.join(OUTPUT_DIR, "live")
    )
    updated_movies = movie_generator.generate(
        client, movie_categories, movie_streams, movies_cfg, os.path.join(OUTPUT_DIR, "movies")
    )
    updated_series = series_generator.generate(
        client, series_categories, series_list, series_cfg, os.path.join(OUTPUT_DIR, "series")
    )

    total_updated = updated_live + updated_movies + updated_series
    if total_updated:
        logger.info("=== Done. Updated files: %s ===", ", ".join(total_updated))
    else:
        logger.info("=== Done. No playlist files were changed. ===")


if __name__ == "__main__":
    main()
