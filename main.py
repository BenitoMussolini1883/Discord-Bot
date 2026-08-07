"""
Instagram → Discord bot
Watches accounts listed in accounts.txt and forwards new posts + stories
to a Discord channel via webhook.

Edit accounts.txt to add/remove accounts — changes are picked up each cycle.
"""

import json
import logging
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import time
from pathlib import Path

from discord_notify import send_post, send_story
from instagram import InstagramClient

import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


# Dummy server so Replit detects an active port and keeps the process alive 24/7
class HealthCheck(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is online")

    def log_message(self, format, *args):
        return


def run_health_check():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheck)
    server.serve_forever()


threading.Thread(target=run_health_check, daemon=True).start()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BOT_DIR = Path(__file__).parent
SEEN_FILE = BOT_DIR / "seen.json"
ACCOUNTS_FILE = BOT_DIR / "accounts.txt"

POLL_INTERVAL = 300  # seconds between full sweeps (5 minutes)
INTER_ACCOUNT_DELAY = 3  # seconds between accounts within a sweep
MAX_SEEN_PER_ACCOUNT = 100  # cap stored IDs to avoid unbounded growth


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def load_seen() -> dict:
    if SEEN_FILE.exists():
        try:
            with open(SEEN_FILE) as f:
                data = json.load(f)
                # Ensure both keys exist
                data.setdefault("posts", {})
                data.setdefault("stories", {})
                return data
        except (json.JSONDecodeError, OSError):
            log.warning("Couldn't read seen.json — starting fresh.")
    return {"posts": {}, "stories": {}}


def save_seen(seen: dict) -> None:
    with open(SEEN_FILE, "w") as f:
        json.dump(seen, f, indent=2)


def load_accounts() -> list[str]:
    if not ACCOUNTS_FILE.exists():
        log.warning("accounts.txt not found — create it and add Instagram usernames.")
        return []
    accounts = []
    with open(ACCOUNTS_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                accounts.append(line)
    return accounts


# ---------------------------------------------------------------------------
# Core check loop
# ---------------------------------------------------------------------------


def check_account(ig: InstagramClient, username: str, seen: dict) -> None:
    # ---- Posts ----
    posts = ig.get_recent_posts(username, count=8)
    seen_post_ids: set[str] = set(seen["posts"].get(username, []))

    new_posts = [p for p in posts if str(p["id"]) not in seen_post_ids]
    # Oldest first so Discord chronology is correct
    for post in reversed(new_posts):
        log.info("  ✨ New post from @%s (id=%s)", username, post["id"])
        send_post(username, post)
        seen_post_ids.add(str(post["id"]))
        time.sleep(1)

    # Trim to cap
    seen["posts"][username] = list(seen_post_ids)[-MAX_SEEN_PER_ACCOUNT:]

    # ---- Stories ----
    stories = ig.get_stories(username)
    seen_story_ids: set[str] = set(seen["stories"].get(username, []))

    new_stories = [s for s in stories if str(s["id"]) not in seen_story_ids]
    for story in new_stories:
        log.info("  📖 New story from @%s (id=%s)", username, story["id"])
        send_story(username, story)
        seen_story_ids.add(str(story["id"]))
        time.sleep(1)

    seen["stories"][username] = list(seen_story_ids)[-MAX_SEEN_PER_ACCOUNT:]


def run_sweep(ig: InstagramClient, seen: dict) -> None:
    accounts = load_accounts()
    if not accounts:
        log.warning(
            "No accounts found in accounts.txt. "
            "Add Instagram usernames (one per line) and they'll be picked up next cycle."
        )
        return

    log.info("── Sweep started (%d account(s)) ──", len(accounts))
    for username in accounts:
        try:
            log.info("Checking @%s…", username)
            check_account(ig, username, seen)
            save_seen(seen)
        except Exception as exc:
            log.error("Unexpected error checking @%s: %s", username, exc, exc_info=True)
        time.sleep(INTER_ACCOUNT_DELAY)
    log.info("── Sweep done. Next check in %ds ──", POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    log.info("=" * 60)
    log.info("Instagram → Discord bot starting up")
    log.info("Accounts file : %s", ACCOUNTS_FILE)
    log.info("Poll interval : %ds", POLL_INTERVAL)
    log.info("=" * 60)

    ig = InstagramClient()
    ig.login()

    seen = load_seen()

    while True:
        try:
            run_sweep(ig, seen)
        except Exception as exc:
            log.error("Sweep crashed: %s", exc, exc_info=True)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()

