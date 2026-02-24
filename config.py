import os
from dotenv import load_dotenv

load_dotenv()

SPOTIFY_EMAIL    = os.getenv("SPOTIFY_EMAIL", "")
SPOTIFY_PASSWORD = os.getenv("SPOTIFY_PASSWORD", "")

SPOTIFY_SESSION_FILE = os.getenv("SPOTIFY_SESSION_FILE", "spotify_session.json")

SPOTIFY_EPISODE_URL = os.getenv(
    "SPOTIFY_EPISODE_URL",
    "https://open.spotify.com/episode/18IGzOgfs3Bmcr5JZapdEt?trackId=7uRNuBCVQYxPX1ZcyIBAug",
)
APPLE_EPISODE_URL = os.getenv(
    "APPLE_EPISODE_URL",
    "https://podcasts.apple.com/us/podcast/open-retrieve-expand-load/id617416468?i=1000746253334",
)

EXPERIMENT_SETTINGS = {
    "runs_per_config": 30,
    "measurement_duration_seconds": 90,
    "cooldown_seconds": 30,
    "browser_startup_wait": 5,
    "page_load_wait": 10,
    "playback_start_wait": 3,
}

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
