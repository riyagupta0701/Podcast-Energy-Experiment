# Podcast Energy Experiment

Measures and compares the energy consumption of **Spotify** and **Apple Podcasts** web players across two browsers (Chrome, Firefox) and two playback speeds (1×, 2×) — 8 configurations × 30 runs each.

---

## Project Structure

```
podcast-energy-experiment/
├── login_session.py         # Run ONCE to log into Spotify and save session
├── run_experiment.py        # Main runner — executes all configs
├── test_single_config.py    # Smoke-test one config (run this first)
├── analyze_results.py       # Parse results & print/plot statistics
├── browser_controller.py    # Playwright automation (navigate, play, set speed)
├── energy_profiler.py       # EnergyBridge wrapper
├── results_manager.py       # Saves per-trial JSON + CSV energy files
├── config.py                # All 8 configs, URLs, credentials, timing settings
├── .env.example             # Template — copy to .env and fill in
├── requirements.txt
└── results/                 # Created at runtime
```

---

## Prerequisites

### 1. Python 3.11+

```bash
python --version
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium firefox
# Linux only:
playwright install-deps
```

### 3. Install EnergyBridge

Download from https://github.com/tdurieux/energibridge/releases and place on PATH.

```bash
# Linux
chmod +x energibridge-linux-amd64
sudo mv energibridge-linux-amd64 /usr/local/bin/energibridge

# Verify
energibridge --version
```

**Linux — RAPL permissions:**
```bash
echo -1 | sudo tee /proc/sys/kernel/perf_event_paranoid
```

**Windows:** Run terminal as Administrator.

**macOS:** Run with `sudo python run_experiment.py`.

### 4. Configure credentials and URLs

```bash
cp .env.example .env
```

Edit `.env`:

```
SPOTIFY_EMAIL=you@example.com
SPOTIFY_PASSWORD=yourpassword
SPOTIFY_EPISODE_URL=https://open.spotify.com/episode/3XkQeKZBGcqO6kbFiLHKLr
APPLE_EPISODE_URL=https://podcasts.apple.com/us/podcast/the-daily/id1200361736?i=1000692801217
```

> Use a **long episode** (>= 2 minutes). Pick any public episode — both platforms work without Premium for playback.

---

## Setup: One-Time Spotify Login

The real Spotify web player (`open.spotify.com`) requires a login to play audio. To avoid logging in on every run, the session is saved once and reused:

```bash
python login_session.py
```

This opens Chrome, logs in automatically using your `.env` credentials, and saves the session to `spotify_session.json`. If Spotify shows a CAPTCHA or device verification prompt, complete it manually in the browser window.

**You only need to do this once.** All 30 × 4 Spotify runs will reuse the saved session. If the session expires (typically after a few weeks), re-run `login_session.py`.

Apple Podcasts does **not** require login.

---

## Steps to Test One Configuration

Always test a single config before running everything.

### Step 1 — Dry run (browser automation only, no EnergyBridge)

```bash
python test_single_config.py --config chrome_spotify_1x --dry-run
```

Watch the browser window — you should see:
1. Chrome opens, Spotify loads (already logged in via session)
2. The episode page appears
3. Any cookie banner is dismissed
4. The play button is clicked, audio starts
5. The speed button in the bottom bar is clicked and 1x is selected

### Step 2 — Live run with EnergyBridge

```bash
python test_single_config.py --config chrome_spotify_1x
```

Check that `results_test/chrome_spotify_1x/energy_run_00.csv` is populated.

### Step 3 — Test Apple Podcasts

```bash
python test_single_config.py --config firefox_apple_2x --dry-run
```

### Troubleshooting

| Symptom | Fix |
|---|---|
| `spotify_session.json not found` | Run `python login_session.py` first |
| Session expired / redirected to login | Re-run `python login_session.py` |
| Play button not found | Increase `page_load_wait` in `config.py` |
| Speed not changing | Speed button only appears after playback starts; increase `playback_start_wait` in `config.py` |
| `EnergyBridge not found` | Set `ENERGIBRIDGE_PATH` in `.env` |
| Permission denied (Linux RAPL) | `echo -1 \| sudo tee /proc/sys/kernel/perf_event_paranoid` |

---

## Running the Full Experiment

```bash
# All 8 configs × 30 runs (~36 hours total)
python run_experiment.py

# Single config only
python run_experiment.py --config firefox_spotify_2x --runs 30

# Dry run (test orchestration, no EnergyBridge)
python run_experiment.py --dry-run --runs 2
```

Results are saved after every trial — a crash won't lose prior data.

---

## Analyzing Results

```bash
python analyze_results.py --input-dir results
python analyze_results.py --input-dir results --plot
```

---

## Configuration Reference

| Config name | Browser | Platform | Speed |
|---|---|---|---|
| `chrome_apple_1x` | Chrome | Apple Podcasts | 1× |
| `chrome_apple_2x` | Chrome | Apple Podcasts | 2× |
| `chrome_spotify_1x` | Chrome | Spotify | 1× |
| `chrome_spotify_2x` | Chrome | Spotify | 2× |
| `firefox_apple_1x` | Firefox | Apple Podcasts | 1× |
| `firefox_apple_2x` | Firefox | Apple Podcasts | 2× |
| `firefox_spotify_1x` | Firefox | Spotify | 1× |
| `firefox_spotify_2x` | Firefox | Spotify | 2× |

---

## Experiment Design Notes

- **Spotify speed control** appears in the bottom player bar only for podcast episodes, after playback starts. If the UI button is not found, speed is set via `audio.playbackRate` JS injection (fully equivalent).
- **Session reuse** — `spotify_session.json` stores cookies and localStorage. Playwright loads it via `storage_state` — no re-login per run.
- **Measurement duration** — 120 s of active playback per trial. Adjust `measurement_duration_seconds` in `config.py`.
- **Cooldown** — 30 s idle between runs to let CPU/thermal state stabilize.
- **Same episode** — using the same URL across all runs controls for content variance (bitrate, artwork loading, chapters).

### Confounds to control

| Factor | Control |
|---|---|
| Episode content | Same URL for all runs of each platform |
| Network | Wired connection; close other apps |
| Background processes | Close everything non-essential |
| Screen brightness | Fixed; prevent screen sleep |
| Power source | AC power only (no battery) |
| Thermal state | 30 s cooldown between runs |

---

## Platform Notes

**Linux:** Set `perf_event_paranoid=-1`. For headless server, use Xvfb:
```bash
Xvfb :99 -screen 0 1280x800x24 &
export DISPLAY=:99
python run_experiment.py
```

**Windows:** Run as Administrator.

**macOS:** `sudo python run_experiment.py`
