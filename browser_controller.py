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
        # else:
        elif self.browser_name == "brave":
            import platform as _platform
            import os as _os
            system = _platform.system()
            if system == "Darwin":
                brave_exe = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
            elif system == "Windows":
                brave_exe = _os.path.expandvars(
                    r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"
                )
            else:
                brave_exe = "/usr/bin/brave-browser"

            brave_profile = ".pw-brave-profile"
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=brave_profile,
                executable_path=brave_exe,
                headless=False,
                viewport={"width": 1280, "height": 800},
                args=[
                    *self._chromium_args(),
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            )

            self._page = self._context.pages[0] if self._context.pages else self._context.new_page()

            log.info(f"    Navigating to: {self.url}")
            self._page.goto(self.url, wait_until="domcontentloaded")
            time.sleep(EXPERIMENT_SETTINGS["page_load_wait"])
            self._dismiss_cookies()
            return
        
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
        finally:
            if self._playwright:
                self._playwright.stop()
        self._page = self._browser = self._context = self._playwright = None

    # ── Apple Podcasts ──────────────────────────────────────────────────────────

    def _dismiss_apple_locale_modal(self):
        episode_url = self.url
        try:
            close = self._page.locator(
                '[data-testid="close-button"], button[aria-label="Close"], button[aria-label="close"]'
            ).first
            if close.is_visible(timeout=2000):
                close.click()
                log.info("    Apple: closed locale modal via X button.")
                time.sleep(1.0)
                if episode_url not in self._page.url:
                    log.info("    Apple: redirected after close — re-navigating to episode.")
                    self._page.goto(episode_url, wait_until="domcontentloaded")
                    time.sleep(EXPERIMENT_SETTINGS["page_load_wait"])
                return

            cont = self._page.locator(
                '[data-testid="select-button"]:has-text("Continue"), button:has-text("Continue")'
            ).first
            if cont.is_visible(timeout=1000):
                log.info("    Apple: locale modal found — pressing Escape to dismiss.")
                self._page.keyboard.press("Escape")
                time.sleep(0.8)
                if episode_url not in self._page.url:
                    log.info("    Apple: still redirected — re-navigating to episode.")
                    self._page.goto(episode_url, wait_until="domcontentloaded")
                    time.sleep(EXPERIMENT_SETTINGS["page_load_wait"])
                return
        except Exception as e:
            log.debug(f"    Apple locale modal: {e}")

    def _play_and_set_speed_apple(self):
        self._dismiss_apple_locale_modal()

        play_selectors = [
            '[data-testid="button-base"]:has-text("Play")',
            'button:has-text("Play")',
            'button[aria-label="Play"]',
            'button[aria-label="Play Episode"]',
            'button[aria-label*="Play"]',
            '.web-chrome-playback-controls__play',
        ]

        clicked = None
        for sel in play_selectors:
            try:
                loc = self._page.locator(sel).first
                loc.wait_for(state="visible", timeout=4_000)
                loc.click()
                clicked = sel
                log.info(f"    Apple: play clicked via Playwright locator '{sel}'.")
                break
            except Exception:
                continue

        if not clicked:
            log.warning("    Apple: no play selector matched — dumping all buttons:")
            self._debug_dump_buttons()

        log.info("    Apple: waiting for <audio> element...")
        if not self._wait_for_audio(timeout=15):
            log.warning("    Apple: <audio> not found after 15s — retrying click...")
            self._dismiss_apple_locale_modal()
            for sel in play_selectors:
                try:
                    loc = self._page.locator(sel).first
                    loc.wait_for(state="visible", timeout=3_000)
                    loc.click()
                    log.info(f"    Apple: retry click via '{sel}'.")
                    break
                except Exception:
                    continue
            self._wait_for_audio(timeout=10)

        if self._page.evaluate("() => !!document.querySelector('audio')"):
            log.info("    Apple: <audio> found — calling audio.play() via JS...")
            self._js_play_and_set_speed()
        else:
            log.warning("    Apple: <audio> still not present. Check browser window.")

    # ── Spotify ─────────────────────────────────────────────────────────────────

    def _play_and_set_speed_spotify(self):
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
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._page.evaluate("() => !!document.querySelector('audio')"):
                return True
            time.sleep(0.5)
        return False

    def _debug_dump_buttons(self):
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
