"""Instagram API wrapper using instagrapi — session-ID login."""

import os
import time
import logging
from pathlib import Path
from urllib.parse import unquote

from instagrapi import Client
from instagrapi.exceptions import LoginRequired, ClientError

log = logging.getLogger(__name__)

BOT_DIR     = Path(__file__).parent
SESSION_FILE = BOT_DIR / "session.json"
CHALLENGE_CODE_FILE = BOT_DIR / "challenge_code.txt"


def _make_client() -> Client:
    cl = Client()
    cl.delay_range = [1, 3]
    return cl


class InstagramClient:
    def __init__(self) -> None:
        self.cl = _make_client()
        self._user_id_cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def login(self) -> None:
        """Login via browser session ID — bypasses cloud-IP blocks."""
        session_id = os.environ.get("IG_SESSION_ID", "").strip()
        if not session_id:
            raise RuntimeError(
                "IG_SESSION_ID environment variable is not set. "
                "See the bot README for instructions on how to get your session ID."
            )

        log.info("Logging in via session ID…")
        try:
            self.cl.login_by_sessionid(session_id)
            username = self.cl.username
            log.info("Logged in as @%s", username)
            self.cl.dump_settings(SESSION_FILE)
        except Exception as exc:
            log.error("Session ID login failed: %s", exc)
            raise

    def relogin(self) -> None:
        """Re-initialise and log in again (called after LoginRequired)."""
        log.warning("Session expired — re-logging in…")
        SESSION_FILE.unlink(missing_ok=True)
        self._user_id_cache.clear()
        self.cl = _make_client()
        self.login()

    # ------------------------------------------------------------------
    # User ID cache
    # ------------------------------------------------------------------

    def _get_user_id(self, username: str) -> str:
        if username not in self._user_id_cache:
            self._user_id_cache[username] = self.cl.user_id_from_username(username)
        return self._user_id_cache[username]

    # ------------------------------------------------------------------
    # Serialisers
    # ------------------------------------------------------------------

    def _media_to_dict(self, m) -> dict:
        images: list[str] = []
        video_url: str | None = None

        if m.media_type == 1:      # photo
            url = m.thumbnail_url or getattr(m, "url", None)
            if url:
                images.append(str(url))
        elif m.media_type == 2:    # video
            if m.thumbnail_url:
                images.append(str(m.thumbnail_url))
            if m.video_url:
                video_url = str(m.video_url)
        elif m.media_type == 8:    # carousel / album
            for res in m.resources:
                thumb = res.thumbnail_url or getattr(res, "url", None)
                if thumb:
                    images.append(str(thumb))

        return {
            "id": str(m.id),
            "caption": (m.caption_text or "").strip(),
            "timestamp": m.taken_at.isoformat() if m.taken_at else "",
            "url": f"https://www.instagram.com/p/{m.code}/",
            "media_type": m.media_type,
            "images": images,
            "video_url": video_url,
        }

    def _story_to_dict(self, s) -> dict:
        image_url: str | None = None
        video_url: str | None = None

        if s.media_type == 1:
            url = s.thumbnail_url or getattr(s, "url", None)
            if url:
                image_url = str(url)
        elif s.media_type == 2:
            if s.thumbnail_url:
                image_url = str(s.thumbnail_url)
            if s.video_url:
                video_url = str(s.video_url)

        return {
            "id": str(s.id),
            "timestamp": s.taken_at.isoformat() if s.taken_at else "",
            "media_type": s.media_type,
            "image_url": image_url,
            "video_url": video_url,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_recent_posts(self, username: str, count: int = 8) -> list[dict]:
        try:
            uid = self._get_user_id(username)
            return [self._media_to_dict(m) for m in self.cl.user_medias(uid, amount=count)]
        except LoginRequired:
            self.relogin()
            uid = self._get_user_id(username)
            return [self._media_to_dict(m) for m in self.cl.user_medias(uid, amount=count)]
        except ClientError as exc:
            log.error("Error fetching posts for @%s: %s", username, exc)
            return []

    def get_stories(self, username: str) -> list[dict]:
        try:
            uid = self._get_user_id(username)
            return [self._story_to_dict(s) for s in self.cl.user_stories(uid)]
        except LoginRequired:
            self.relogin()
            uid = self._get_user_id(username)
            return [self._story_to_dict(s) for s in self.cl.user_stories(uid)]
        except ClientError as exc:
            log.error("Error fetching stories for @%s: %s", username, exc)
            return []

    def login(self) -> None:
        """Login via browser session ID — bypasses cloud-IP blocks."""
        # unquote automatically converts %3A back to :
        session_id = unquote(os.environ.get("IG_SESSION_ID", "").strip())
        
        if not session_id:
            raise RuntimeError("IG_SESSION_ID environment variable is not set.")
    
        log.info("Logging in via session ID…")
        try:
            self.cl.login_by_sessionid(session_id)
            username = self.cl.username
            log.info("Logged in as @%s", username)
            self.cl.dump_settings(SESSION_FILE)
        except Exception as exc:
            log.error("Session ID login failed: %s", exc)
            raise
