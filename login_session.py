import argparse
import time
from playwright.sync_api import sync_playwright

from config import SPOTIFY_SESSION_FILE


def login(browser_name: str = "chrome"):
    print(f"Opening {browser_name} for Spotify login...")

    with sync_playwright() as pw:
        if browser_name == "chrome":
            browser = pw.chromium.launch(
                headless=False,
                args=["--autoplay-policy=no-user-gesture-required"],
            )
        else:
            browser = pw.firefox.launch(headless=False)

        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        page.goto("https://accounts.spotify.com/login", wait_until="domcontentloaded")
        time.sleep(1)

        print()
        print("=" * 60)
        print("ACTION REQUIRED — log in manually in the browser window:")
        print("  1. Enter your Spotify email and password")
        print("  2. Complete any CAPTCHA or verification if shown")
        print("  3. Wait until you can see the Spotify web player")
        print("  4. Return here and press Enter")
        print("=" * 60)
        input("\nPress Enter once you are fully logged in: ")

        current_url = page.url
        if "open.spotify.com" not in current_url and "spotify.com" not in current_url:
            print(f"⚠ Current URL is: {current_url}")
            print("  Make sure you are on the Spotify web player before saving.")
            input("  Press Enter again when ready: ")

        context.storage_state(path=SPOTIFY_SESSION_FILE)
        print(f"\n✓ Session saved to '{SPOTIFY_SESSION_FILE}'")
        print("  You can now run the experiment:")
        print("    python test_single_config.py --config chrome_spotify_1x --dry-run")
        print("    python run_experiment.py")

        time.sleep(1)
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="One-time Spotify login for experiment")
    parser.add_argument("--browser", choices=["chrome", "firefox"], default="chrome")
    args = parser.parse_args()
    login(args.browser)
