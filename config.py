"""
Experiment configurations and settings.

Spotify: uses the REAL web player (open.spotify.com).
  - Requires a Spotify account (free works).
  - Login is done ONCE interactively via `python login_session.py`,
    which saves browser storage state to spotify_session.json.
  - All 30 experiment runs reuse that saved session — no repeated login.

Apple Podcasts: regular episode URLs, no login needed.

Set credentials via environment variables or a .env file.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Credentials (Spotify only) ─────────────────────────────────────────────────
SPOTIFY_EMAIL    = os.getenv("SPOTIFY_EMAIL", "")
SPOTIFY_PASSWORD = os.getenv("SPOTIFY_PASSWORD", "")

# Path where Playwright saves the logged-in browser session
SPOTIFY_SESSION_FILE = os.getenv("SPOTIFY_SESSION_FILE", "spotify_session.json")

# ── Episode URLs ───────────────────────────────────────────────────────────────
# Use a long episode (>= measurement_duration_seconds).
# Spotify: standard open.spotify.com/episode/<id> URL
SPOTIFY_EPISODE_URL = os.getenv(
    "SPOTIFY_EPISODE_URL",
    "https://open.spotify.com/episode/18IGzOgfs3Bmcr5JZapdEt?trackId=7uRNuBCVQYxPX1ZcyIBAug",
)
APPLE_EPISODE_URL = os.getenv(
    "APPLE_EPISODE_URL",
    "https://podcasts.apple.com/us/podcast/open-retrieve-expand-load/id617416468?i=1000746253334",
)

# ── Experiment settings ────────────────────────────────────────────────────────
EXPERIMENT_SETTINGS = {
    "runs_per_config": 30,
    "measurement_duration_seconds": 45,   # 2 minutes of active playback per run
    "cooldown_seconds": 30,                # idle pause between runs
    "browser_startup_wait": 5,             # seconds after browser opens
    "page_load_wait": 10,                  # seconds after navigating to episode URL
    "playback_start_wait": 3,              # seconds to wait after clicking play
}

# ── Eight configurations ───────────────────────────────────────────────────────
CONFIGS = [
    {"name": "chrome_spotify_1x", "browser": "chrome", "platform": "spotify", "speed": 1.0, "url": SPOTIFY_EPISODE_URL},
    {"name": "chrome_spotify_2x", "browser": "chrome", "platform": "spotify", "speed": 2.0, "url": SPOTIFY_EPISODE_URL},

    {"name": "brave_spotify_1x", "browser": "brave", "platform": "spotify", "speed": 1.0, "url": SPOTIFY_EPISODE_URL},
    {"name": "brave_spotify_2x", "browser": "brave", "platform": "spotify", "speed": 2.0, "url": SPOTIFY_EPISODE_URL},

    {"name": "chrome_apple_1x", "browser": "chrome", "platform": "apple", "speed": 1.0, "url": APPLE_EPISODE_URL},
    {"name": "chrome_apple_2x", "browser": "chrome", "platform": "apple", "speed": 2.0, "url": APPLE_EPISODE_URL},

    {"name": "brave_apple_1x", "browser": "brave", "platform": "apple", "speed": 1.0, "url": APPLE_EPISODE_URL},
    {"name": "brave_apple_2x", "browser": "brave", "platform": "apple", "speed": 2.0, "url": APPLE_EPISODE_URL},
]
