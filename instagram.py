"""
Instagram API wrapper using RapidAPI (Instagram Scraper Stable API).
Bypasses Instagram datacenter IP blocks and login challenges.
"""

import logging
import os
import requests

log = logging.getLogger(__name__)

RAPID_HOST = "instagram-scraper-stable-api.p.rapidapi.com"
BASE_URL = f"https://{RAPID_HOST}"


class InstagramClient:
    def __init__(self) -> None:
        self.api_key = os.environ.get("RAPIDAPI_KEY", "").strip()

    def login(self) -> None:
        """Validates that the RapidAPI key is present."""
        if not self.api_key:
            log.warning(
                "RAPIDAPI_KEY environment variable is not set. "
                "The bot will attempt unauthenticated public fetches."
            )
        else:
            log.info("RapidAPI key detected and configured.")

    def _headers(self) -> dict:
        return {
            "x-rapidapi-key": self.api_key,
            "x-rapidapi-host": RAPID_HOST,
            "Content-Type": "application/x-www-form-urlencoded",
        }

    # ------------------------------------------------------------------
    # Public API (Matches interface expected by main.py)
    # ------------------------------------------------------------------

    def get_recent_posts(self, account_entry: str, count: int = 8) -> list[dict]:
        """Fetch recent posts for a given username using RapidAPI POST endpoint."""
        username = account_entry.split(":")[0].lstrip("@").strip()
        url = f"{BASE_URL}/get_ig_user_posts_v2.php"
        
        # Form Data payload as required by Instagram Scraper Stable API
        payload = {
            "username_or_url": username,
            "amount": count
        }

        try:
            resp = requests.post(url, headers=self._headers(), data=payload, timeout=15)
            if resp.status_code != 200:
                log.error("RapidAPI error %s for @%s: %s", resp.status_code, username, resp.text[:200])
                return []

            data = resp.json()
            
            # Navigate typical response structures returned by the scraper API
            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = (
                    data.get("data", {}).get("items", [])
                    or data.get("items", [])
                    or data.get("data", [])
                    or []
                )

            posts = []
            for item in items[:count]:
                if isinstance(item, dict):
                    post_dict = self._parse_post(username, item)
                    if post_dict:
                        posts.append(post_dict)
            return posts

        except Exception as exc:
            log.error("Error fetching posts via RapidAPI for @%s: %s", username, exc)
            return []

    def get_stories(self, account_entry: str) -> list[dict]:
        """Fetch active stories for a given username using RapidAPI POST endpoint."""
        username = account_entry.split(":")[0].lstrip("@").strip()
        url = f"{BASE_URL}/get_ig_user_stories_v2.php"
        payload = {"username_or_url": username}

        try:
            resp = requests.post(url, headers=self._headers(), data=payload, timeout=15)
            if resp.status_code != 200:
                if resp.status_code != 404:
                    log.error("RapidAPI story error %s for @%s", resp.status_code, username)
                return []

            data = resp.json()
            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = (
                    data.get("data", {}).get("items", [])
                    or data.get("items", [])
                    or data.get("data", [])
                    or []
                )

            stories = []
            for item in items:
                if isinstance(item, dict):
                    story_dict = self._parse_story(item)
                    if story_dict:
                        stories.append(story_dict)
            return stories

        except Exception as exc:
            log.error("Error fetching stories via RapidAPI for @%s: %s", username, exc)
            return []

    # ------------------------------------------------------------------
    # Item Parsers
    # ------------------------------------------------------------------

    def _parse_post(self, username: str, item: dict) -> dict | None:
        try:
            post_id = str(item.get("id") or item.get("pk") or "")
            code = item.get("code") or item.get("shortcode") or ""
            caption_obj = item.get("caption") or {}
            caption_text = caption_obj.get("text", "") if isinstance(caption_obj, dict) else str(caption_obj)

            images = []
            video_url = None

            # Extract image URLs from carousel resources or root post object
            carousel_media = item.get("resources") or item.get("carousel_media") or []
            if carousel_media:
                for child in carousel_media:
                    img = self._extract_image_url(child)
                    if img:
                        images.append(img)
            else:
                img = self._extract_image_url(item)
                if img:
                    images.append(img)

            if item.get("video_url"):
                video_url = str(item.get("video_url"))

            return {
                "id": post_id,
                "caption": caption_text.strip(),
                "timestamp": str(item.get("taken_at") or ""),
                "url": f"https://www.instagram.com/p/{code}/" if code else f"https://www.instagram.com/{username}/",
                "media_type": item.get("media_type", 1),
                "images": images,
                "video_url": video_url,
            }
        except Exception as exc:
            log.warning("Failed to parse post item: %s", exc)
            return None

    def _parse_story(self, item: dict) -> dict | None:
        try:
            story_id = str(item.get("id") or item.get("pk") or "")
            image_url = self._extract_image_url(item)
            video_url = item.get("video_url")

            return {
                "id": story_id,
                "timestamp": str(item.get("taken_at") or ""),
                "media_type": item.get("media_type", 1),
                "image_url": image_url,
                "video_url": str(video_url) if video_url else None,
            }
        except Exception as exc:
            log.warning("Failed to parse story item: %s", exc)
            return None

    def _extract_image_url(self, item: dict) -> str | None:
        image_versions = item.get("image_versions2", {}).get("candidates", [])
        if image_versions:
            return image_versions[0].get("url")
        return item.get("thumbnail_url") or item.get("display_url")
