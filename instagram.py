"""Instagram API wrapper using instagrapi — session-ID login."""

import logging
import os
import re
from pathlib import Path
from urllib.parse import unquote

import requests
from instagrapi import Client
from instagrapi.exceptions import ClientError, LoginRequired

log = logging.getLogger(__name__)

BOT_DIR = Path(__file__).parent
SESSION_FILE = BOT_DIR / "session.json"

# Standard desktop User-Agent to fetch public profile HTML without triggering blocks
WEB_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


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
        """Set session ID directly — bypasses cloud-IP verification blocks."""
        raw_session_id = os.environ.get("IG_SESSION_ID", "").strip()
        session_id = unquote(raw_session_id)

        if not session_id:
            raise RuntimeError(
                "IG_SESSION_ID environment variable is not set. "
                "See the bot README for instructions on how to get your session ID."
            )

        log.info("Setting Instagram session ID directly...")

        try:
            self.cl.set_settings({
                "uuids": {
                    "phone_id": "00000000-0000-0000-0000-000000000000",
                    "uuid": "00000000-0000-0000-0000-000000000000",
                    "client_session_id": "00000000-0000-0000-0000-000000000000",
                    "advertising_id": "00000000-0000-0000-0000-000000000000",
                    "device_id": "android-0000000000000000",
                },
                "cookies": {"sessionid": session_id},
            })
            log.info("Session ID set successfully.")
        except Exception as exc:
            log.error("Failed to initialize Instagram session: %s", exc)
            raise

    def relogin(self) -> None:
        """Re-initialise and set session again (called after LoginRequired)."""
        log.warning("Session expired — re-logging in…")
        SESSION_FILE.unlink(missing_ok=True)
        self._user_id_cache.clear()
        self.cl = _make_client()
        self.login()

    # ------------------------------------------------------------------
    # User ID Resolution (Custom Web Parser)
    # ------------------------------------------------------------------

    def _scrape_user_id_from_html(self, username: str) -> str:
        """Extract user ID directly from public web HTML to bypass instagrapi GQL/API blocks."""
        url = f"https://www.instagram.com/{username}/"
        resp = requests.get(url, headers=WEB_HEADERS, timeout=10)
        
        # Search HTML for profile_id / owner_id tags
        matches = re.findall(r'"profile_id":"(\d+)"', resp.text) or \
                  re.findall(r'"user_id":"(\d+)"', resp.text) or \
                  re.findall(r'"owner":{"id":"(\d+)"', resp.text)
                  
        if matches:
            return matches[0]
            
        raise ValueError(f"Could not parse User ID from HTML for @{username}")

    def _get_user_id(self, username: str) -> str:
        """Fetch user ID with web HTML scraping fallback."""
        username = username.lstrip("@").strip()

        if username not in self._user_id_cache:
            try:
                # 1. Direct Web HTML Scrape (Fastest & avoids instagrapi ?__a=1 calls)
                uid = self._scrape_user_id_from_html(username)
                self._user_id_cache[username] = uid
                log.info("Scraped user ID for @%s: %s", username, uid)
            except Exception as e1:
                log.warning("Web scrape failed for @%s: %s. Trying instagrapi fallback...", username, e1)
                try:
                    # 2. Fallback to instagrapi internal method
                    uid = str(self.cl.user_id_from_username(username))
                    self._user_id_cache[username] = uid
                except Exception as e2:
                    log.error("All user ID lookup methods failed for @%s: %s", username, e2)
                    raise

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
