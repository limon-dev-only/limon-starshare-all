"""
xtream.py

Xtream Codes "player_api.php" client covering all three content types:
Live TV, Movies (VOD), and Series.

Design notes:
    - No stream_id / episode_id mapping table is kept locally. Every
      playable URL is built directly from the identifiers Xtream returns
      on the current run:

          Live:   {host}/live/{user}/{pass}/{stream_id}.{extension}
          Movie:  {host}/movie/{user}/{pass}/{stream_id}.{extension}
          Series: {host}/series/{user}/{pass}/{episode_id}.{extension}

      This is the server's own addressing scheme, not a custom mapping —
      channel/episode identity is always sourced fresh from the API.
    - No format conversion is performed. Whatever container_extension
      Xtream reports (e.g. "m3u8", "ts", "mp4") is preserved as-is.
    - If a panel supplies a 'direct_source' URL for an item, that raw URL
      is used verbatim instead of being reconstructed — it IS the
      provider's real link.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class XtreamAuthenticationError(Exception):
    """Raised when Xtream credentials are rejected or the server is unreachable during login."""


class XtreamAPIError(Exception):
    """Raised when an authenticated Xtream API call fails or returns an unexpected payload."""


class XtreamClient:
    """Thin, dependency-light wrapper around the Xtream Codes player_api.php endpoint."""

    def __init__(self, host: str, username: str, password: str, timeout: int = 30) -> None:
        if not host:
            raise ValueError("Xtream host must not be empty")
        self.host = host.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self.session = requests.Session()

    # ------------------------------------------------------------------ #
    # Low-level request helpers
    # ------------------------------------------------------------------ #

    def _player_api_url(self) -> str:
        return f"{self.host}/player_api.php"

    def _request(self, params: Dict[str, Any]) -> Any:
        try:
            response = self.session.get(self._player_api_url(), params=params, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise XtreamAPIError(f"Network error contacting Xtream server: {exc}") from exc

        try:
            return response.json()
        except ValueError as exc:
            raise XtreamAPIError(f"Xtream server returned invalid JSON: {exc}") from exc

    def _get_list_action(self, action: str, extra_params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Run a player_api action expected to return a JSON list."""
        params: Dict[str, Any] = {
            "username": self.username,
            "password": self.password,
            "action": action,
        }
        if extra_params:
            params.update(extra_params)

        data = self._request(params)
        if not isinstance(data, list):
            raise XtreamAPIError(f"Unexpected response format for action '{action}'")
        return data

    # ------------------------------------------------------------------ #
    # Authentication
    # ------------------------------------------------------------------ #

    def authenticate(self) -> Dict[str, Any]:
        """
        Perform a login call and verify the account is active.
        Returns the 'user_info' block on success; raises
        XtreamAuthenticationError otherwise.
        """
        params = {"username": self.username, "password": self.password}
        try:
            data = self._request(params)
        except XtreamAPIError as exc:
            raise XtreamAuthenticationError(str(exc)) from exc

        if not isinstance(data, dict):
            raise XtreamAuthenticationError("Unexpected authentication response format")

        user_info = data.get("user_info") or {}
        if user_info.get("auth") != 1:
            raise XtreamAuthenticationError(
                f"Xtream authentication failed (status={user_info.get('status', 'unknown')})"
            )

        logger.info("Authenticated with Xtream server as '%s'", self.username)
        return user_info

    # ------------------------------------------------------------------ #
    # Live TV
    # ------------------------------------------------------------------ #

    def get_live_categories(self) -> List[Dict[str, Any]]:
        """Fetch all Live TV categories/groups."""
        return self._get_list_action("get_live_categories")

    def get_live_streams(self) -> List[Dict[str, Any]]:
        """Fetch all Live TV channels across every category."""
        return self._get_list_action("get_live_streams")

    def build_live_url(self, stream: Dict[str, Any]) -> Optional[str]:
        """Build the playable URL for a Live TV stream dict."""
        direct = self._direct_source(stream)
        if direct:
            return direct
        return self._build_url("live", stream.get("stream_id"), stream.get("container_extension"))

    # ------------------------------------------------------------------ #
    # Movies (VOD)
    # ------------------------------------------------------------------ #

    def get_vod_categories(self) -> List[Dict[str, Any]]:
        """Fetch all Movie (VOD) categories/groups."""
        return self._get_list_action("get_vod_categories")

    def get_vod_streams(self) -> List[Dict[str, Any]]:
        """Fetch all movies across every VOD category."""
        return self._get_list_action("get_vod_streams")

    def build_vod_url(self, stream: Dict[str, Any]) -> Optional[str]:
        """Build the playable URL for a Movie (VOD) stream dict."""
        direct = self._direct_source(stream)
        if direct:
            return direct
        return self._build_url("movie", stream.get("stream_id"), stream.get("container_extension"))

    # ------------------------------------------------------------------ #
    # Series
    # ------------------------------------------------------------------ #

    def get_series_categories(self) -> List[Dict[str, Any]]:
        """Fetch all Series categories/groups."""
        return self._get_list_action("get_series_categories")

    def get_series(self) -> List[Dict[str, Any]]:
        """Fetch the series catalogue (metadata only — no episodes yet)."""
        return self._get_list_action("get_series")

    def get_series_info(self, series_id: Any) -> Dict[str, Any]:
        """Fetch season/episode details for a single series_id."""
        params = {
            "username": self.username,
            "password": self.password,
            "action": "get_series_info",
            "series_id": series_id,
        }
        data = self._request(params)
        if not isinstance(data, dict):
            raise XtreamAPIError(f"Unexpected response format for get_series_info(series_id={series_id})")
        return data

    def get_series_episodes(self, series_id: Any, series_name: str) -> List[Dict[str, Any]]:
        """
        Fetch and flatten every episode of one series into playlist-ready
        dicts shaped like a stream item: {id, container_extension, name,
        stream_icon, epg_channel_id}.

        `name` is pre-formatted as "<series name> SxxExx - <episode title>"
        so downstream playlist code can treat it like any other channel.
        """
        info = self.get_series_info(series_id)
        episodes_by_season = info.get("episodes") or {}
        series_cover = (info.get("info") or {}).get("cover", "")

        flattened: List[Dict[str, Any]] = []
        for season_key, episode_list in episodes_by_season.items():
            if not isinstance(episode_list, list):
                continue
            for ep in episode_list:
                flattened.append(self._flatten_episode(ep, season_key, series_name, series_cover))
        return flattened

    @staticmethod
    def _flatten_episode(
        ep: Dict[str, Any], season_key: Any, series_name: str, series_cover: str
    ) -> Dict[str, Any]:
        season_num = ep.get("season", season_key)
        try:
            season_num = int(season_num)
        except (TypeError, ValueError):
            season_num = 0

        try:
            episode_num = int(ep.get("episode_num", 0))
        except (TypeError, ValueError):
            episode_num = 0

        title = str(ep.get("title") or "").strip()
        display_name = f"{series_name} S{season_num:02d}E{episode_num:02d}"
        if title:
            display_name += f" - {title}"

        ep_info = ep.get("info") or {}
        return {
            "id": ep.get("id"),
            "container_extension": ep.get("container_extension"),
            "name": display_name,
            "stream_icon": ep_info.get("movie_image") or series_cover,
            "epg_channel_id": "",
        }

    def build_series_episode_url(self, episode: Dict[str, Any]) -> Optional[str]:
        """Build the playable URL for a flattened series episode dict."""
        return self._build_url("series", episode.get("id"), episode.get("container_extension"))

    # ------------------------------------------------------------------ #
    # Shared URL builder
    # ------------------------------------------------------------------ #

    @staticmethod
    def _direct_source(item: Dict[str, Any]) -> Optional[str]:
        """
        Some Xtream panels populate a 'direct_source' field with the
        provider's own raw stream URL for a specific channel/movie,
        bypassing the standard /live//movie/ path entirely. When present,
        that URL must be used verbatim — it IS the provider's real link,
        not something we should reconstruct or alter.
        """
        direct = item.get("direct_source")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        return None

    def _build_url(self, section: str, item_id: Optional[Any], extension: Optional[str]) -> Optional[str]:
        """
        Build a `{host}/{section}/{user}/{pass}/{id}.{ext}` URL using
        *exactly* the container_extension Xtream reports for this item —
        never a guessed default. Live, Movie, and Series entries can each
        legitimately be served as .ts, .m3u8, .mp4, .mkv, or anything else
        the provider actually uses, so no extension is assumed.

        Returns None if the item_id or extension is missing, so callers
        skip the item (with a logged warning) instead of emitting a
        playlist entry with a made-up, possibly wrong extension.
        """
        if item_id is None:
            return None
        ext = str(extension).strip().lstrip(".") if extension else ""
        if not ext:
            return None
        return f"{self.host}/{section}/{self.username}/{self.password}/{item_id}.{ext}"
