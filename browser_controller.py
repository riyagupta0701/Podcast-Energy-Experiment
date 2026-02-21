"""
Browser automation for Spotify and Apple Podcasts web players.

Core insight: Both platforms block synthetic click events due to autoplay
policy. But Chromium is launched with --autoplay-policy=no-user-gesture-required,
which means we can call audio.play() directly from JavaScript WITHOUT any
user gesture. So the strategy is:

  1. Navigate to the episode page
  2. Wait for the page + audio element to load
  3. Call audio.play() + set audio.playbackRate via JS
  4. No button clicking needed at all

For pages where <audio> is not immediately present (Spotify, Apple Podcasts
lazy-load it), we first click the play button to trigger the player
initialization, THEN call audio.play() to actually start playback.
"""

import logging
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from config import EXPERIMENT_SETTINGS, SPOTIFY_SESSION_FILE

log = logging.getLogger(__name__)

COOKIE_SELECTORS = [
    '[data-testid="consent-banner-accept"]',
    '#onetrust-accept-btn-handler',
    'button:has-text("Accept All")',
    'button:has-text("Accept Cookies")',
    'button:has-text("Accept")',
    'button:has-text("I Accept")',
    'button:has-text("Agree")',
    'button:has-text("OK")',
]


class BrowserController:
    def __init__(self, config: dict):
        self.config       = config
        self.browser_name = config["browser"]
        self.platform     = config["platform"]
        self.speed        = config["speed"]
        self.url          = config["url"]

        self._playwright = None
        self._browser    = None
        self._context    = None
        self._page       = None

    # ── Public API ──────────────────────────────────────────────────────────────

    def setup(self):
        self._playwright = sync_playwright().start()

        if self.browser_name == "chrome":
            self._browser = self._playwright.chromium.launch(
                headless=False,
                args=self._chromium_args(),
            )
        else:
            self._browser = self._playwright.firefox.launch(
            headless=False,
            firefox_user_prefs={
                    "media.autoplay.default": 0,
                    "media.autoplay.blocking_policy": 0,
                    "media.autoplay.allow-muted": True,
                },
            )

        context_opts = {"viewport": {"width": 1280, "height": 800}}
        if self.platform == "spotify":
            session_path = Path(SPOTIFY_SESSION_FILE)
            if not session_path.exists():
                raise FileNotFoundError(
                    f"'{SPOTIFY_SESSION_FILE}' not found. Run: python login_session.py"
                )
            context_opts["storage_state"] = str(session_path)
            log.info(f"    Loaded Spotify session from '{SPOTIFY_SESSION_FILE}'.")

        self._context = self._browser.new_context(**context_opts)
        self._page = self._context.new_page()

        log.info(f"    Navigating to: {self.url}")
        self._page.goto(self.url, wait_until="domcontentloaded")
        time.sleep(EXPERIMENT_SETTINGS["page_load_wait"])

        self._dismiss_cookies()

    def start_playback(self):
        if self.platform == "spotify":
            self._play_and_set_speed_spotify()
        else:
            self._play_and_set_speed_apple()

    def teardown(self):
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
        finally:
            if self._playwright:
                self._playwright.stop()
        self._page = self._browser = self._context = self._playwright = None

    # ── Apple Podcasts ──────────────────────────────────────────────────────────
    def _dismiss_apple_locale_modal(self):
        """Apple Podcasts often shows a locale modal (Nederland/Continue/Close) that blocks the player."""
        try:
            # Close button
            close = self._page.locator('[data-testid="close-button"], button[aria-label="Close"]').first
            if close.is_visible(timeout=1000):
                close.click()
                log.info("    Apple: closed locale modal.")
                time.sleep(0.8)
                return

            # Or click Continue if shown
            cont = self._page.locator('[data-testid="select-button"]:has-text("Continue"), button:has-text("Continue")').first
            if cont.is_visible(timeout=1000):
                cont.click()
                log.info("    Apple: confirmed locale modal (Continue).")
                time.sleep(1.0)
                return
        except Exception:
            pass

    def _wait_for_apple_playing(self, timeout: int = 15) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                # If UI flips to "Pause", we're playing
                if self._page.locator('button:has-text("Pause"), [data-testid="button-base"]:has-text("Pause")').count() > 0:
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False
    
    def _play_and_set_speed_apple(self):
        """
        Step 1: Click play button to trigger Apple's player initialization
                (this creates the <audio> element).
        Step 2: Once <audio> exists, call .play() directly via JS —
                this bypasses autoplay policy because of our Chromium flag.
        Step 3: Set playbackRate.
        """
        log.info("    Apple: clicking play button to initialize player...")
        self._dismiss_apple_locale_modal()
        self._click_play_button_apple()

        log.info("    Apple: waiting for playback to start...")
        if not self._wait_for_apple_playing(timeout=15):
            log.warning("    Apple: playback not confirmed. Retrying: dismiss modal + click Play again...")
            self._dismiss_apple_locale_modal()
            self._click_play_button_apple()
            self._wait_for_apple_playing(timeout=10)

        # Now force-play via JS
        if self._page.evaluate("() => !!document.querySelector('audio')"):
            log.info("    Apple: calling audio.play() via JS...")
            self._js_play_and_set_speed()
        else:
            log.info("    Apple: no <audio> element exposed; relying on UI-driven playback.")

    def _click_play_button_apple(self):
        """Click the play button to trigger player init — not to actually play."""
        result = self._page.evaluate("""
            () => {
                // 1) Grab candidate buttons using valid CSS selectors
                const candidates = [
                    ...document.querySelectorAll('[data-testid="button-base"]'),
                    ...document.querySelectorAll('button'),
                ];

                // 2) Click the first visible button whose text is exactly "Play"
                for (const btn of candidates) {
                    const txt = (btn.innerText || "").trim().toLowerCase();
                    if (txt !== "play") continue;
                    const r = btn.getBoundingClientRect();
                    if (r.width < 20 || r.height < 20) continue;
                    btn.scrollIntoView({block: 'center'});
                    btn.click();
                    return {
                        sel: "text==play",
                        text: btn.innerText.trim(),
                        aria: btn.getAttribute("aria-label"),
                        testid: btn.getAttribute("data-testid"),
                        x: Math.round(r.x), y: Math.round(r.y),
                        w: Math.round(r.width), h: Math.round(r.height)
                    };
                }

                // 3) Fallback: aria-label contains play (if Apple changes markup)
                const buttons = [...document.querySelectorAll("button")];
                for (const btn of buttons) {
                    const aria = (btn.getAttribute("aria-label") || "").toLowerCase();
                    if (!aria.includes("play")) continue;
                    const r = btn.getBoundingClientRect();
                    if (r.width < 20 || r.height < 20) continue;
                    btn.scrollIntoView({block: 'center'});
                    btn.click();
                    return {
                        sel: "aria~play",
                        aria: btn.getAttribute("aria-label"),
                        testid: btn.getAttribute("data-testid"),
                        x: Math.round(r.x), y: Math.round(r.y),
                        w: Math.round(r.width), h: Math.round(r.height)
                    };
                }

                return null;
            }
        """)
        if result:
            log.info(
                f"    Apple: clicked ({result.get('sel')}) "
                f"text='{result.get('text')}' aria='{result.get('aria')}' "
                f"at ({result['x']}, {result['y']}) size={result['w']}×{result['h']}"
            )
        else:
            log.warning("    Apple: no play button found in DOM — dumping buttons:")
            self._debug_dump_buttons()

    # ── Spotify ─────────────────────────────────────────────────────────────────

    def _play_and_set_speed_spotify(self):
        """
        Same strategy as Apple: click play to init the player,
        then call audio.play() via JS.
        Skips sidebar buttons (x < 200).
        """
        log.info("    Spotify: clicking play button to initialize player...")
        result = self._page.evaluate("""
            () => {
                const candidates = [...document.querySelectorAll(
                    '[data-testid="play-button"], button[aria-label^="Play"]'
                )];
                for (const btn of candidates) {
                    const r = btn.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) continue;
                    if (r.x < 200) continue;  // skip sidebar
                    btn.scrollIntoView({block: 'center'});
                    btn.click();
                    return {aria: btn.getAttribute('aria-label'),
                            testid: btn.getAttribute('data-testid'),
                            x: Math.round(r.x), y: Math.round(r.y),
                            w: Math.round(r.width), h: Math.round(r.height)};
                }
                return null;
            }
        """)

        if result:
            log.info(f"    Spotify: clicked '{result['aria'] or result['testid']}' at "
                     f"({result['x']}, {result['y']}) size={result['w']}×{result['h']}")
        else:
            log.warning("    Spotify: no play button found outside sidebar — dumping buttons:")
            self._debug_dump_buttons()

        log.info("    Spotify: waiting for <audio> element...")
        if not self._wait_for_audio(timeout=15):
            log.warning("    Spotify: <audio> not found. Session may be expired.")
            log.warning("    Re-run: python login_session.py")

        log.info("    Spotify: calling audio.play() via JS...")
        self._js_play_and_set_speed()

    # ── JS audio control (core of the playback strategy) ───────────────────────

    def _js_play_and_set_speed(self):
        """
        Directly control the HTML5 <audio> element via JavaScript.
        Works because Chromium is launched with:
          --autoplay-policy=no-user-gesture-required
        which allows audio.play() from JS without any user gesture.
        """
        result = self._page.evaluate(f"""
            async () => {{
                const audio = document.querySelector('audio');
                if (!audio) return 'no_audio';

                audio.playbackRate = {self.speed};

                try {{
                    await audio.play();
                    return 'playing';
                }} catch (e) {{
                    return 'error: ' + e.message;
                }}
            }}
        """)

        if result == "playing":
            log.info(f"    audio.play() succeeded. Speed={self.speed}x. Playback is running.")
        elif result == "no_audio":
            log.warning("    audio.play(): no <audio> element found.")
        else:
            log.warning(f"    audio.play() result: {result}")

    # ── Cookie dismissal ────────────────────────────────────────────────────────

    def _dismiss_cookies(self):
        for sel in COOKIE_SELECTORS:
            try:
                btn = self._page.locator(sel).first
                if btn.is_visible(timeout=2_000):
                    btn.click()
                    log.info(f"    Cookie banner dismissed ({sel})")
                    time.sleep(0.8)
                    return
            except Exception:
                pass
        log.debug("    No cookie banner found.")

    # ── Helpers ─────────────────────────────────────────────────────────────────

    def _wait_for_audio(self, timeout: int = 15) -> bool:
        """Poll for <audio> element. Returns True when found."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._page.evaluate("() => !!document.querySelector('audio')"):
                return True
            time.sleep(0.5)
        return False

    def _debug_dump_buttons(self):
        """Log all visible buttons to help diagnose missing play button."""
        buttons = self._page.evaluate("""
            () => [...document.querySelectorAll('button')].map(b => {
                const r = b.getBoundingClientRect();
                return {
                    aria: b.getAttribute('aria-label'),
                    testid: b.getAttribute('data-testid'),
                    text: b.innerText.trim().slice(0, 30),
                    x: Math.round(r.x), y: Math.round(r.y),
                    w: Math.round(r.width), h: Math.round(r.height)
                };
            }).filter(b => b.w > 0 && b.h > 0)
        """)
        for b in buttons:
            log.warning(f"      x={b['x']:4d} y={b['y']:4d} "
                        f"w={b['w']:3d} h={b['h']:3d} "
                        f"aria='{b['aria']}' "
                        f"testid='{b['testid']}' "
                        f"text='{b['text']}'")

    @staticmethod
    def _chromium_args() -> list[str]:
        return [
            "--autoplay-policy=no-user-gesture-required",
            "--disable-features=PreloadMediaEngagementData",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows",
        ]
