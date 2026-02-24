import logging
import time
from pathlib import Path

import re
from playwright.sync_api import TimeoutError as PWTimeout

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

SPEED_LABEL_RE = re.compile(r"^\s*\d+(?:\.\d+)?x\s*$", re.I)



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
        import json
        import platform as _platform
        import os as _os
        import shutil as _shutil

        self._playwright = sync_playwright().start()

        context_args = {
            "headless": False,
            "viewport": {"width": 1280, "height": 800},
            "args": [
                *self._chromium_args(),
                "--no-default-browser-check",
            ]
        }

        if self.browser_name == "chrome":
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=".pw-chrome-profile",
                **context_args
            )
        elif self.browser_name == "brave":
            system = _platform.system()
            if system == "Darwin":
                brave_exe = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
            elif system == "Windows":
                brave_exe = _os.path.expandvars(
                    r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"
                )
            else:
                brave_exe = _shutil.which("brave-browser") or _shutil.which("brave")
                if not brave_exe:
                    brave_exe = "/usr/bin/brave-browser" if _os.path.exists("/usr/bin/brave-browser") else "/usr/bin/brave"

            context_args["executable_path"] = brave_exe
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=".pw-brave-profile",
                **context_args
            )

        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()

        if self.platform == "spotify":
            session_path = Path(SPOTIFY_SESSION_FILE)
            if not session_path.exists():
                raise FileNotFoundError(f"'{SPOTIFY_SESSION_FILE}' not found. Run: python login_session.py")
            
            with open(session_path, "r") as f:
                state = json.load(f)
            
            # Inject cookies
            if "cookies" in state:
                self._context.add_cookies(state["cookies"])
            
            # Inject localStorage
            if "origins" in state:
                self._page.goto("https://open.spotify.com", wait_until="commit")
                for origin_data in state["origins"]:
                    for item in origin_data["localStorage"]:
                        self._page.evaluate(
                            "([key, value]) => window.localStorage.setItem(key, value)",
                            [item['name'], item['value']]
                        )
            
            log.info(f"    Injected Spotify session from '{SPOTIFY_SESSION_FILE}'.")

        # Navigate to the actual episode URL
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
       
        # after play click + a short wait for controls
        self._page.wait_for_timeout(800)

        ok = self._set_apple_speed_via_ui(self.speed)
        if not ok:
            log.warning("Apple: failed to set speed via UI.")

    # ── Spotify ─────────────────────────────────────────────────────────────────

    def _play_and_set_speed_spotify(self):
        log.info("    Spotify: ensure playback is started (click Play if needed)...")

        # Only click if we see a Play button
        clicked = self._page.evaluate("""
        () => {
            const btns = [...document.querySelectorAll('button')];
            // Prefer the control bar play button
            const play = btns.find(b => (b.getAttribute('aria-label') || '').trim() === 'Play');
            if (play) { play.click(); return 'clicked_play'; }
            return 'no_play_button';
        }
        """)
        log.info(f"    Spotify: {clicked}")

        # Time to render the speed control
        self._page.wait_for_timeout(800)

        ok = self._set_spotify_speed_via_ui_in_player_bar(self.speed)
        if not ok:
            log.warning("    Spotify: failed to set speed via UI.")

    # ── JS audio control (core of the playback strategy) ───────────────────────

    def _js_play_and_set_speed(self):
        media_loc = None
        
        # Find the media element using Playwright
        if self._page.locator("audio, video").count() > 0:
            media_loc = self._page.locator("audio, video").first
        else:
            for frame in self._page.frames:
                if frame.locator("audio, video").count() > 0:
                    media_loc = frame.locator("audio, video").first
                    break

        if not media_loc:
            log.warning("    media.play(): no <audio> or <video> element found.")
            return

        result = media_loc.evaluate(f"""
            async (media) => {{
                // Set the speed
                media.playbackRate = {self.speed};

                // Ensure it is playing
                try {{
                    await media.play();
                    return 'playing';
                }} catch (e) {{
                    return 'error: ' + e.message;
                }}
            }}
        """)

        if result == "playing":
            log.info(f"    media.play() succeeded. Speed={self.speed}x. Playback is running.")
        else:
            log.warning(f"    media.play() result: {result}")


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
            if self._page.locator("audio, video").count() > 0:
                return True
                
            # Check frames just in case
            for frame in self._page.frames:
                if frame.locator("audio, video").count() > 0:
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


    def _set_apple_speed_via_ui(self, target_speed: float, timeout_ms: int = 12000) -> bool:
        page = self._page
        target_label = f"{target_speed:g}x"

        def norm(s: str) -> str:
            return (s or "").strip().lower().replace("×", "x").replace(" ", "")

        speed_re = re.compile(r"^\d+(?:\.\d+)?[x×]$", re.I)

        # --- Find current "Nx" label ---
        deadline = time.time() + timeout_ms / 1000
        current = None

        while time.time() < deadline:
            current = page.evaluate("""
            () => {
                const norm = s => (s||'').replace(/\\s+/g,' ').trim();

                // Apple Podcasts playback controls area tends to contain the speed control.
                // Try a few plausible roots first to avoid matching random "2x" in content.
                const roots = [
                document.querySelector('.web-chrome-playback-controls'),
                document.querySelector('[data-testid*="playback" i]'),
                document.querySelector('footer'),
                document.body
                ].filter(Boolean);

                function findSpeed(root){
                const all = root.querySelectorAll('*');
                for (const el of all) {
                    const t = norm(el.textContent);
                    if (/^\\d+(?:\\.\\d+)?[x×]$/i.test(t)) {
                    const r = el.getBoundingClientRect?.();
                    if (r && r.width > 2 && r.height > 2) return t;
                    }
                }
                return null;
                }

                for (const r of roots) {
                const t = findSpeed(r);
                if (t) return t;
                }
                return null;
            }
            """)
            if current and speed_re.match(current):
                break
            page.wait_for_timeout(250)

        if not current:
            log.warning("Apple UI speed: no 'Nx' label found near playback controls.")
            return False

        if norm(current) == norm(target_label):
            log.info(f"Apple UI speed: already at {target_label}.")
            return True

        # --- Click the current speed label to open the menu ---
        clicked = page.evaluate("""
        (label) => {
            const norm = s => (s||'').replace(/\\s+/g,' ').trim();
            const roots = [
            document.querySelector('.web-chrome-playback-controls'),
            document.querySelector('[data-testid*="playback" i]'),
            document.querySelector('footer'),
            document.body
            ].filter(Boolean);

            function clickWithin(root){
            const all = Array.from(root.querySelectorAll('*'));
            const matches = all.filter(el => norm(el.textContent) === label);
            if (!matches.length) return false;

            matches.sort((a,b) => b.getBoundingClientRect().y - a.getBoundingClientRect().y);
            const el = matches[0];

            // Climb to a clickable element
            let cur = el;
            for (let i=0; i<6 && cur; i++){
                const cs = getComputedStyle(cur);
                const clickable =
                cur.tagName?.toLowerCase() === 'button' ||
                cur.getAttribute?.('role') === 'button' ||
                cs.cursor === 'pointer' ||
                cur.onclick ||
                cur.tabIndex === 0;
                const r = cur.getBoundingClientRect();
                const visible = r.width>2 && r.height>2;
                if (clickable && visible) { cur.click(); return true; }
                cur = cur.parentElement;
            }
            el.click();
            return true;
            }

            for (const r of roots) if (clickWithin(r)) return true;
            return false;
        }
        """, current)

        if not clicked:
            log.warning(f"Apple UI speed: found '{current}' but couldn't click it.")
            return False

        page.wait_for_timeout(200)

        # --- Click the target option (scroll inside the menu) ---
        ok = self._click_speed_option_in_open_menu(target_label)
        if ok:
            log.info(f"Apple UI speed: set to {target_label}.")
            return True

        log.warning(f"Apple UI speed: menu opened but option '{target_label}' not found/clickable.")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return False


    def _click_speed_option_in_open_menu(self, target_label: str) -> bool:
        page = self._page

        def norm(s: str) -> str:
            return (s or "").strip().lower().replace("×", "x").replace(" ", "")

        want = norm(target_label)

        # Try to locate a menu
        menu = page.locator('[role="menu"], [role="dialog"], [data-testid*="popover" i], [data-testid*="menu" i]').first

        def try_click() -> bool:
            # Look for any element whose visible text is exactly "Nx"
            loc = page.locator("text=/^\\s*\\d+(?:\\.\\d+)?[x×]\\s*$/i")
            try:
                n = loc.count()
            except Exception:
                n = 0
            for i in range(min(n, 200)):
                el = loc.nth(i)
                try:
                    if not el.is_visible():
                        continue
                    if norm(el.inner_text()) == want:
                        el.click()
                        return True
                except Exception:
                    continue
            return False

        # No-scroll attempt
        if try_click():
            return True

        # Scroll inside the menu if possible
        for _ in range(14):  # scroll up
            try:
                if menu.is_visible(timeout=200):
                    menu.evaluate("el => { el.scrollTop = Math.max(0, el.scrollTop - el.clientHeight * 0.9); }")
                else:
                    break
            except Exception:
                break
            page.wait_for_timeout(120)
            if try_click():
                return True

        for _ in range(14):  # scroll down
            try:
                if menu.is_visible(timeout=200):
                    menu.evaluate("el => { el.scrollTop = el.scrollTop + el.clientHeight * 0.9; }")
                else:
                    break
            except Exception:
                break
            page.wait_for_timeout(120)
            if try_click():
                return True

        return False


    def _set_spotify_speed_via_ui_in_player_bar(self, target_speed: float, timeout_ms: int = 12000) -> bool:
        page = self._page
        target_label = f"{target_speed:g}x"

        def norm_label(s: str) -> str:
            return (s or "").strip().lower().replace("×", "x").replace(" ", "")

        label_re = re.compile(r"^\d+(?:\.\d+)?[x×]$", re.I)

        deadline = time.time() + timeout_ms / 1000

        # Find the speed control
        while time.time() < deadline:
            current = page.evaluate("""
            () => {
                const norm = s => (s||'').replace(/\\s+/g,' ').trim();
                const playerRoots = [
                document.querySelector('[data-testid="now-playing-bar"]'),
                document.querySelector('footer'),
                // fallback: last fixed region near bottom
                [...document.querySelectorAll('*')].reverse().find(el => {
                    const cs = getComputedStyle(el);
                    if (!cs) return false;
                    if (cs.position !== 'fixed' && cs.position !== 'sticky') return false;
                    const r = el.getBoundingClientRect();
                    return r.height > 60 && r.y > window.innerHeight * 0.6;
                })
                ].filter(Boolean);

                function findSpeedEl(root){
                const all = root.querySelectorAll('*');
                for (const el of all) {
                    const t = norm(el.textContent);
                    if (/^\\d+(?:\\.\\d+)?[x×]$/i.test(t)) {
                    const r = el.getBoundingClientRect();
                    if (r.width > 2 && r.height > 2) return t;
                    }
                }
                return null;
                }

                for (const root of playerRoots) {
                const t = findSpeedEl(root);
                if (t) return t;
                }
                return null;
            }
            """)
            if current:
                current_n = norm_label(current)
                if label_re.match(current):
                    if current_n == norm_label(target_label):
                        log.info(f"Spotify UI speed: already at {target_label}.")
                        return True

                    # Click the current speed label
                    clicked = page.evaluate("""
                    (label) => {
                        const norm = s => (s||'').replace(/\\s+/g,' ').trim();
                        const roots = [
                        document.querySelector('[data-testid="now-playing-bar"]'),
                        document.querySelector('footer'),
                        ].filter(Boolean);

                        function clickWithin(root){
                        const all = Array.from(root.querySelectorAll('*'));
                        const matches = all.filter(el => norm(el.textContent) === label);
                        if (!matches.length) return false;

                        matches.sort((a,b) => b.getBoundingClientRect().y - a.getBoundingClientRect().y);
                        const el = matches[0];

                        // climb to clickable
                        let cur = el;
                        for (let i=0; i<6 && cur; i++){
                            const cs = getComputedStyle(cur);
                            const clickable =
                            cur.tagName?.toLowerCase() === 'button' ||
                            cur.getAttribute?.('role') === 'button' ||
                            cs.cursor === 'pointer' ||
                            cur.onclick ||
                            cur.tabIndex === 0;
                            const r = cur.getBoundingClientRect();
                            const visible = r.width>2 && r.height>2;
                            if (clickable && visible) { cur.click(); return true; }
                            cur = cur.parentElement;
                        }
                        el.click();
                        return true;
                        }

                        for (const r of roots) if (clickWithin(r)) return true;
                        return false;
                    }
                    """, current)
                    if not clicked:
                        log.warning(f"Spotify UI speed: found '{current}' but couldn't click it in player bar.")
                        return False

                    # Click the option (scroll inside menu)
                    return self._click_spotify_speed_option(target_label)

            page.wait_for_timeout(250)

        log.warning("Spotify UI speed: couldn't find speed label in player bar.")
        return False


    def _click_spotify_speed_option(self, target_label: str) -> bool:
        page = self._page

        def norm(s: str) -> str:
            return (s or "").strip().lower().replace("×", "x").replace(" ", "")

        # Find a scrollable menu
        menu = page.locator('[role="menu"], [data-testid*="context-menu" i], [data-testid*="popover" i], [role="dialog"]').first

        # Helper: click the option
        def try_click() -> bool:
            want = norm(target_label)
            loc = page.locator("text=/^\\s*\\d+(?:\\.\\d+)?[x×]\\s*$/i")
            try:
                count = loc.count()
            except Exception:
                count = 0
            for i in range(min(count, 200)):
                el = loc.nth(i)
                try:
                    if not el.is_visible():
                        continue
                    t = norm(el.inner_text())
                    if t == want:
                        el.click()
                        return True
                except Exception:
                    continue
            return False

        # Wait for menu animation
        page.wait_for_timeout(200)

        # Try without scrolling first
        if try_click():
            log.info(f"Spotify UI speed: set to {target_label}.")
            return True

        # Scroll up
        for _ in range(14):
            try:
                if menu.is_visible(timeout=200):
                    menu.evaluate("el => { el.scrollTop = Math.max(0, el.scrollTop - el.clientHeight * 0.9); }")
            except Exception:
                break
            page.wait_for_timeout(120)
            if try_click():
                log.info(f"Spotify UI speed: set to {target_label}.")
                return True

        # Scroll down
        for _ in range(14):
            try:
                if menu.is_visible(timeout=200):
                    menu.evaluate("el => { el.scrollTop = el.scrollTop + el.clientHeight * 0.9; }")
            except Exception:
                break
            page.wait_for_timeout(120)
            if try_click():
                log.info(f"Spotify UI speed: set to {target_label}.")
                return True

        log.warning(f"Spotify UI speed: menu opened, but option '{target_label}' not found/clickable.")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return False

    @staticmethod
    def _chromium_args() -> list[str]:
        return [
            "--autoplay-policy=no-user-gesture-required",
            "--disable-features=PreloadMediaEngagementData",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows",
        ]
