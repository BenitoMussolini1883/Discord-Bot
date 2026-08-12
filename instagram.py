"""Instagram API wrapper using instagrapi — session-ID login."""

import logging
import os
from pathlib import Path
from urllib.parse import unquote

from instagrapi import Client
from instagrapi.exceptions import ClientError, LoginRequired

log = logging.getLogger(__name__)

BOT_DIR = Path(__file__).parent
SESSION_FILE = BOT_DIR / "session.json"


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
            # Inject sessionid directly into instagrapi settings to prevent 467 Client Error
            self.cl.set_settings({
                "uuids": {
                    "phone_id": "00000000-0000-0000-0000-000000000000",
                    "uuid": "00000000-0000-0000-0000-000000000000",
                    "client_session_id": "00000000-0000-0000-0000-000000000000",
                    "advertising_id": "00000000-0000-0000-0000-000000000000",
                    "device_id": "android-0000000000000000"
                },
                "cookies": {
                    "sessionid": session_id
                }
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
    # User ID cache
    # ------------------------------------------------------------------

    def _get_user_id(self, username: str) -> str:
        """Fetch user ID with fallbacks to avoid datacenter IP bans."""
        if username not in self._user_id_cache:
            try:
                # Try public web endpoint first
                user_info = self.cl.user_info_by_username_v1(username)
                self._user_id_cache[username] = str(user_info.pk)
            except Exception:
                # Fallback to standard private endpoint lookup
                self._user_id_cache[username] = str(self.cl.user_id_from_username(username))
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
            
    def _get_user_id(self, username: str) -> str:
        """Fetch user ID using web_profile_info to avoid broken endpoints and 467 errors."""
        username = username.lstrip("@").strip()
        
        if username not in self._user_id_cache:
            try:
                # Use modern GraphQL web profile scraper (does not use deprecated ?__a=1)
                info = self.cl.user_info_by_username_gql(username)
                self._user_id_cache[username] = str(info.pk)
                log.info("Successfully fetched ID for @%s: %s", username, info.pk)
            except Exception as e1:
                log.warning("GQL lookup failed for @%s: %s. Trying direct user ID lookup...", username, e1)
                try:
                    self._user_id_cache[username] = str(self.cl.user_id_from_username(username))
                except Exception as e2:
                    log.error("All user ID lookup methods failed for @%s: %s", username, e2)
                    raise
                    
        return self._user_id_cache[username]
