"""Send Instagram posts and stories to a Discord channel via webhook."""

import os
import logging
import requests

log = logging.getLogger(__name__)

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
IG_PINK = 0xE1306C   # Instagram post colour
IG_ORANGE = 0xF77737  # Instagram story colour


def _send(payload: dict) -> bool:
    """POST a payload to the Discord webhook. Returns True on success."""
    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=15)
        if resp.status_code not in (200, 204):
            log.error("Discord webhook error %s: %s", resp.status_code, resp.text[:200])
            return False
        return True
    except requests.RequestException as exc:
        log.error("Discord webhook request failed: %s", exc)
        return False


def send_post(username: str, post: dict) -> None:
    """Send a new feed post (photo / video / carousel) to Discord."""
    caption = (post.get("caption") or "").strip()
    post_url = post.get("url", f"https://www.instagram.com/{username}/")
    images: list[str] = post.get("images", [])
    timestamp: str = post.get("timestamp", "")[:10]
    media_type: int = post.get("media_type", 1)

    type_label = {1: "📸 Photo", 2: "🎬 Video", 8: "🖼️ Album"}.get(media_type, "📸 Post")

    # Truncate caption to Discord embed limit
    description = caption[:2048] if caption else "*No caption*"

    first_embed: dict = {
        "title": f"{type_label} from @{username}",
        "url": post_url,
        "description": description,
        "color": IG_PINK,
        "footer": {"text": f"Instagram • {timestamp}"},
    }
    if images:
        first_embed["image"] = {"url": images[0]}

    _send({"embeds": [first_embed]})

    # Extra album images — Discord allows up to 10 embeds per message.
    # Group remaining images 9 per message so they display as a gallery.
    extras = images[1:10]
    if extras:
        extra_embeds = [
            {"url": post_url, "color": IG_PINK, "image": {"url": img}}
            for img in extras
        ]
        _send({"embeds": extra_embeds})


def send_story(username: str, story: dict) -> None:
    """Send a new story (photo or video) to Discord."""
    image_url: str | None = story.get("image_url")
    video_url: str | None = story.get("video_url")
    timestamp: str = story.get("timestamp", "")[:10]
    media_type: int = story.get("media_type", 1)

    type_label = "📸 Story" if media_type == 1 else "🎬 Story Video"
    profile_url = f"https://www.instagram.com/{username}/"

    description = f"[Open @{username}'s profile]({profile_url})"
    if video_url:
        description += f"\n🎬 [Direct video link]({video_url})"

    embed: dict = {
        "title": f"{type_label} from @{username}",
        "description": description,
        "color": IG_ORANGE,
        "footer": {"text": f"Instagram Story • {timestamp}"},
    }
    if image_url:
        embed["image"] = {"url": image_url}

    _send({"embeds": [embed]})
