# Energy Consumption for Online Podcast Playback

Measures and compares the energy consumption of **Spotify** and **Apple Podcasts** web players across two browsers (Chrome, Brave) and two playback speeds (1×, 2×) — 8 configurations × 30 runs each.


## Prerequisites

### 1. Python 3.11+

```bash
python --version
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Install EnergyBridge

Download from https://github.com/tdurieux/energibridge/releases and place on PATH.

```bash
# macOS
chmod +x energibridge-macos
sudo mv energibridge-macos /usr/local/bin/energibridge

# Verify
energibridge --version
```

> **macOS:** EnergyBridge uses `powermetrics` internally and requires `sudo`:
> ```bash
> python run_experiment.py
> ```

> **Linux:** Grant RAPL access once:
> ```bash
> echo -1 | sudo tee /proc/sys/kernel/perf_event_paranoid
> ```

> **Binary name:** The profiler auto-detects both `energibridge` and `energybridge` spellings so either works. Override with `ENERGIBRIDGE_PATH` in `.env` if needed.

### 4. Install Brave Browser

Download from https://brave.com. The experiment auto-detects the path per OS:
- **macOS:** `/Applications/Brave Browser.app/Contents/MacOS/Brave Browser`
- **Linux:** `/usr/bin/brave-browser`
- **Windows:** `%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe`

### 5. Configure credentials and URLs

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Spotify credentials (used once by login_session.py)
SPOTIFY_EMAIL=you@example.com
SPOTIFY_PASSWORD=yourpassword

# Episode URLs — use long episodes (>= 2 minutes)
SPOTIFY_EPISODE_URL=https://open.spotify.com/episode/18IGzOgfs3Bmcr5JZapdEt?trackId=7uRNuBCVQYxPX1ZcyIBAug
APPLE_EPISODE_URL=https://podcasts.apple.com/us/podcast/open-retrieve-expand-load/id617416468?i=1000746253334

# Optional overrides
# ENERGIBRIDGE_PATH=energibridge
# SPOTIFY_SESSION_FILE=spotify_session.json
```


## Setup: One-Time Spotify Login

Spotify requires a login to stream audio. Run this once to save the session:

```bash
python login_session.py
```

A browser window opens. Log in manually (Spotify blocks automated login with CAPTCHAs). Once you can see the Spotify web player, press Enter in the terminal. The session is saved to `spotify_session.json` and reused for all Spotify runs.

Re-run `login_session.py` if the session expires (typically after a few weeks).

Apple Podcasts does **not** require login.


## Configurations

| Config name | Browser | Platform | Speed |
|---|---|---|---|
| `chrome_spotify_1x` | Chrome | Spotify | 1× |
| `chrome_spotify_2x` | Chrome | Spotify | 2× |
| `brave_spotify_1x` | Brave | Spotify | 1× |
| `brave_spotify_2x` | Brave | Spotify | 2× |
| `chrome_apple_1x` | Chrome | Apple Podcasts | 1× |
| `chrome_apple_2x` | Chrome | Apple Podcasts | 2× |
| `brave_apple_1x` | Brave | Apple Podcasts | 1× |
| `brave_apple_2x` | Brave | Apple Podcasts | 2× |


## Workflow

### Step 1 — Dry run a single config (no EnergyBridge)

Always do this first to confirm playback works before measuring energy.

```bash
python test_single_config.py --config chrome_apple_1x --dry-run
```

Watch the browser window. You should see:
1. Browser opens and navigates to the episode page
2. Any cookie or locale modal is dismissed
3. The play button is clicked — audio starts
4. Speed is set via `audio.playbackRate`
5. After the measurement duration the browser closes

### Step 2 — Single trial with EnergyBridge

```bash
python test_single_config.py --config chrome_apple_1x
```

Expected result output:
```
── Result ──────────────────────────────────
  Success:  True
  Energy:   {'samples': 90, 'total_energy_joules': 412.5, 'mean_power_watts': 9.17, ...}
────────────────────────────────────────────
```

Energy CSV saved to: `results_test/chrome_apple_1x/energy_run_00.csv`

### Step 3 — Test all configs before the full run

```bash
python test_single_config.py --config chrome_apple_2x
python test_single_config.py --config brave_apple_1x
python test_single_config.py --config chrome_spotify_1x
python test_single_config.py --config brave_spotify_2x
# repeat for remaining configs
```

### Step 4 — Full experiment

```bash
# All 8 configs × 30 runs
python run_experiment.py

# Single config, all 30 runs
python run_experiment.py --config brave_apple_2x

# Single config, specific number of runs
python run_experiment.py --config chrome_apple_1x --runs 5

# Dry run (test orchestration only)
python run_experiment.py --dry-run --runs 2
```

Results are saved after every trial — a crash won't lose prior data.

### Step 5 — Analyse results

```bash
python report_data_analysis.py --input-dir results
```
## Playback Implementation Notes

### Apple Podcasts
- No login required
- A locale/region modal may appear on first visit — dismissed via the Close (X) button or Escape; re-navigates to the episode if redirected
- Playwright `locator.click()` triggers the play button — a trusted browser gesture that satisfies the autoplay policy
- Once `<audio>` appears in the DOM, `audio.play()` and `audio.playbackRate` are set via JS

### Spotify
- Requires a saved login session (`spotify_session.json`) — run `login_session.py` once
- Play button selection filters out sidebar buttons by x-position (x > 200)
- Same `audio.play()` + `audio.playbackRate` JS approach once `<audio>` appears
- If `<audio>` is never found, the session has likely expired — re-run `login_session.py`

### Speed setting
Speed is set via `audio.playbackRate = N` on the HTML5 audio element directly — equivalent to using the UI speed button and works reliably across all configurations.
If the audio element is not found, it falls back to using the UI speed button to set the playback rate.


## Energy Measurement Notes

EnergyBridge output format varies by platform:

| Platform | Column | Unit | Parser strategy |
|---|---|---|---|
| macOS | `SYSTEM_POWER (Watts)` | Watts (instantaneous) | $\sum$(power × Δt) |
| Linux (AMD) | `CPU_ENERGY (J)` | Joules (cumulative) | last − first |
| Linux (Intel) | `PACKAGE_ENERGY (J)` | Joules (cumulative) | last − first |

The `Delta` column (cumulative ms since start) is used to compute per-sample Δt on macOS. Falls back to `ENERGIBRIDGE_INTERVAL_MS` (default 500ms) if timing columns are absent.

### Experiment settings (config.py)

| Setting | Default | Description |
|---|---|---|
| `runs_per_config` | 30 | Trials per configuration |
| `measurement_duration_seconds` | 90 | Active playback duration per trial |
| `cooldown_seconds` | 30 | Idle pause between runs |
| `page_load_wait` | 10 | Seconds to wait after navigation |

### Controlled Variables

| Factor | Control |
|---|---|
| Episode content | Same URL for all runs per platform |
| Network | Wired connection preferred; close other apps |
| Volume | Constant volume across all runs using the same speaker |
| Background processes | Close everything non-essential |
| Screen brightness | Fix brightness; disable auto-brightness |
| Power source | AC power only |
| Thermal state | 30s cooldown between runs |
| Room temperature | Keep roughly constant |


## Troubleshooting

| Symptom | Fix |
|---|---|
| `logs/experiment.log` not found | Created automatically — just run the script |
| `spotify_session.json not found` | Run `python login_session.py` |
| Session expired / redirected to Spotify login | Re-run `python login_session.py` |
| `<audio>` not found on Spotify | Session stale — re-run `login_session.py` |
| Apple locale modal navigates away | Fixed automatically — script re-navigates to episode |
| `EnergyBridge not found` | Ensure `energibridge` is on PATH, or set `ENERGIBRIDGE_PATH` in `.env` |
| `total_energy_joules: 0.0` | Unknown CSV columns — run `head -2 results/<config>/energy_run_00.csv` and report headers |
| Permission denied (macOS) | Run with `sudo python ...` |
| Permission denied (Linux RAPL) | `echo -1 \| sudo tee /proc/sys/kernel/perf_event_paranoid` |
| Brave not found | Confirm Brave is installed; check path in `browser_controller.py` |
| Play button not found | Increase `page_load_wait` in `config.py` |
