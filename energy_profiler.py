"""
EnergyBridge wrapper.

EnergyBridge (https://github.com/tdurieux/energibridge) is a cross-platform
energy measurement tool that wraps a command and records RAPL / IPMI power
readings into a CSV file.

Usage model here: we start EnergyBridge as a subprocess that runs for the
measurement duration, writing to a CSV file. We then parse that CSV.

EnergyBridge CLI:  energibridge --output <file> --max-execution <seconds> -- <command>

When used in "measure a running process" mode we use:
    energibridge --output <file> --interval <ms> --max-execution <sec> -- sleep <sec>

This effectively records power for the given duration regardless of what
else is happening on the system — which is the correct methodology for a
web-player experiment (the power draw from the browser is captured as
background system load).

Platform notes:
  - Linux:   requires Intel RAPL or powercap; run as root or set perf_event_paranoid=-1
  - Windows: uses IPMI or HWiNFO64 backend (auto-detected by EnergyBridge)
  - macOS:   uses powermetrics backend
"""

import csv
import logging
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)

# Path to EnergyBridge binary — override with env var ENERGIBRIDGE_PATH
ENERGIBRIDGE_BIN = os.getenv(
    "ENERGIBRIDGE_PATH",
    "energibridge",   # assumed to be on PATH
)

# Sampling interval in milliseconds
SAMPLE_INTERVAL_MS = int(os.getenv("ENERGIBRIDGE_INTERVAL_MS", "500"))


class EnergyProfiler:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self._proc: subprocess.Popen | None = None
        self._output_file: str | None = None

        if not dry_run:
            self._check_energibridge()

    # ── Public API ──────────────────────────────────────────────────────────────

    def start(self, output_csv: str):
        """Start EnergyBridge recording to output_csv."""
        self._output_file = output_csv

        if self.dry_run:
            log.info("    [DRY-RUN] EnergyBridge skipped.")
            return

        # EnergyBridge command: record for a long time; we stop it ourselves.
        cmd = [
            ENERGIBRIDGE_BIN,
            "--output", output_csv,
            "--interval", str(SAMPLE_INTERVAL_MS),
            "--",
            *self._idle_command(),
        ]

        # On Linux/AMD, energy counters often require elevated privileges.
        # Run only EnergyBridge with sudo (non-interactive) so the rest of the experiment stays unprivileged.
        if platform.system() == "Linux":
            cmd = ["sudo", "-n", *cmd]

        log.debug(f"    EnergyBridge cmd: {' '.join(cmd)}")

        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        time.sleep(0.5)   # give it a moment to initialise

        if self._proc.poll() is not None:
            stderr = self._proc.stderr.read().decode()
            raise RuntimeError(f"EnergyBridge failed to start: {stderr}")

    def stop(self, force: bool = False) -> dict | None:
        """Stop EnergyBridge and parse the resulting CSV."""
        if self.dry_run:
            return {"dry_run": True, "total_energy_joules": None, "samples": 0}

        if self._proc is None:
            return None

        # Terminate EnergyBridge
        try:
            if platform.system() == "Windows":
                self._proc.terminate()
            else:
                self._proc.send_signal(signal.SIGINT)
            self._proc.wait(timeout=10)
        except Exception as e:
            log.warning(f"    Could not stop EnergyBridge cleanly: {e}")
            try:
                self._proc.kill()
            except Exception:
                pass
        finally:
            self._proc = None

        # Parse CSV
        if self._output_file and Path(self._output_file).exists():
            return self._parse_csv(self._output_file)
        return None

    # ── Parsing ─────────────────────────────────────────────────────────────────

    def _parse_csv(self, filepath: str) -> dict:
        """
        EnergyBridge CSV columns vary by backend, but common ones are:
          timestamp, package_energy (J), dram_energy (J), pp0_energy (J), ...
        We sum package_energy (or total_energy) across all rows.
        """
        rows = []
        try:
            with open(filepath, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append(row)
        except Exception as e:
            log.error(f"    Could not parse EnergyBridge CSV: {e}")
            return {"error": str(e), "samples": 0}

        if not rows:
            return {"samples": 0, "total_energy_joules": 0.0}

        headers = list(rows[0].keys())
        log.debug(f"    EnergyBridge CSV headers: {headers}")

        # ── Step 1: find a power or energy column ─────────────────────────────
        # EnergyBridge output varies by platform:
        #   macOS:  "SYSTEM_POWER (Watts)"  — instantaneous power in Watts
        #   Linux:  "PACKAGE_ENERGY (J)"    — cumulative energy in Joules
        #   Others: various spellings

        energy_col = None   # cumulative Joules column
        power_col  = None   # instantaneous Watts column

        # Explicit energy (Joules) candidates
        for candidate in ["PACKAGE_ENERGY (J)", "package_energy",
                          "Package Energy (J)", "CPU Energy (J)",
                          "energy", "total_energy"]:
            if candidate in headers:
                energy_col = candidate
                break

        # Explicit power (Watts) candidates — used when no energy col exists
        if energy_col is None:
            for candidate in ["SYSTEM_POWER (Watts)", "SYSTEM_POWER",
                              "CPU_POWER (Watts)", "CPU_POWER",
                              "PACKAGE_POWER (Watts)"]:
                if candidate in headers:
                    power_col = candidate
                    break

        # Fallback heuristics
        if energy_col is None and power_col is None:
            for h in headers:
                hl = h.lower()
                if "energy" in hl:
                    energy_col = h
                    break
                if "power" in hl:
                    power_col = h

        # ── Step 2: parse timestamps for Δt ───────────────────────────────────
        # "Time" column is Unix epoch in milliseconds; "Delta" is ms since start
        duration_s  = None
        delta_times = []   # per-sample Δt in seconds

        if "Delta" in headers:
            try:
                deltas_ms = [float(r["Delta"]) for r in rows if r.get("Delta")]
                # Delta is cumulative ms — diff consecutive values for per-sample Δt
                if len(deltas_ms) >= 2:
                    delta_times = [(deltas_ms[i+1] - deltas_ms[i]) / 1000.0
                                   for i in range(len(deltas_ms) - 1)]
                    duration_s = deltas_ms[-1] / 1000.0
            except Exception:
                pass
        elif "Time" in headers:
            try:
                ts_ms = [float(r["Time"]) for r in rows if r.get("Time")]
                if len(ts_ms) >= 2:
                    delta_times = [(ts_ms[i+1] - ts_ms[i]) / 1000.0
                                   for i in range(len(ts_ms) - 1)]
                    duration_s = (ts_ms[-1] - ts_ms[0]) / 1000.0
            except Exception:
                pass

        # Fallback: assume uniform sampling interval
        if not delta_times:
            interval_s = SAMPLE_INTERVAL_MS / 1000.0
            delta_times = [interval_s] * max(0, len(rows) - 1)
            duration_s  = interval_s * len(rows)

        # ── Step 3: compute total energy ──────────────────────────────────────
        total_energy  = 0.0
        power_readings = []

        if energy_col:
            # Cumulative Joules column — total = last - first
            values = []
            for row in rows:
                try:
                    values.append(float(row[energy_col]))
                except (ValueError, KeyError):
                    pass
            if len(values) >= 2 and all(v <= values[i+1]
                                        for i, v in enumerate(values[:-1])):
                total_energy = values[-1] - values[0]
            else:
                # Per-sample Joules — sum directly
                total_energy = sum(values)
            power_readings = values
            used_col = energy_col

        elif power_col:
            # Instantaneous Watts × Δt → Joules per sample, then sum
            power_vals = []
            for row in rows:
                try:
                    power_vals.append(float(row[power_col]))
                except (ValueError, KeyError):
                    pass
            # pair each power reading with the Δt that follows it
            n_pairs = min(len(power_vals), len(delta_times))
            total_energy = sum(power_vals[i] * delta_times[i]
                               for i in range(n_pairs))
            power_readings = power_vals
            used_col = power_col

        else:
            used_col = None

        return {
            "samples": len(rows),
            "total_energy_joules": round(total_energy, 4),
            "energy_column_used": used_col,
            "duration_seconds": round(duration_s, 2) if duration_s else None,
            "mean_power_watts": (
                round(total_energy / duration_s, 4)
                if duration_s and duration_s > 0 else None
            ),
            "raw_power_readings": power_readings[:5],
        }

    # ── Helpers ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _idle_command():
        """A long-running benign command for EnergyBridge to 'wrap'."""
        if platform.system() == "Windows":
            # Windows: ping loop
            return ["ping", "-n", "99999", "127.0.0.1"]
        else:
            return ["sleep", "99999"]

    @staticmethod
    def _check_energibridge():
        if shutil.which(ENERGIBRIDGE_BIN) is None and not Path(ENERGIBRIDGE_BIN).is_file():
            raise EnvironmentError(
                f"EnergyBridge binary not found: '{ENERGIBRIDGE_BIN}'.\n"
                "Install from https://github.com/tdurieux/energibridge and ensure it is on PATH,\n"
                "or set ENERGIBRIDGE_PATH env var to its full path."
            )
