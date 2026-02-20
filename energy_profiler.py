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

        # Try to find an energy column
        energy_col = None
        for candidate in [
            "package_energy", "PACKAGE_ENERGY (W)", "energy", "total_energy",
            "Package Energy (J)", "CPU Energy (J)",
        ]:
            if candidate in headers:
                energy_col = candidate
                break

        if energy_col is None:
            # Heuristic: first column with 'energy' in name
            for h in headers:
                if "energy" in h.lower():
                    energy_col = h
                    break

        total_energy = 0.0
        power_readings = []
        if energy_col:
            values = []
            for row in rows:
                try:
                    values.append(float(row[energy_col]))
                except (ValueError, KeyError):
                    pass
            # EnergyBridge may report cumulative or per-sample — detect by monotonicity
            if len(values) >= 2 and all(values[i] <= values[i+1] for i in range(len(values)-1)):
                # cumulative: total = last - first
                total_energy = values[-1] - values[0]
            else:
                # per-sample (Watts * interval_s → Joules)
                interval_s = SAMPLE_INTERVAL_MS / 1000.0
                total_energy = sum(v * interval_s for v in values)
            power_readings = values

        # Also capture timestamps if available
        duration_s = None
        for ts_col in ["timestamp", "Timestamp", "time"]:
            if ts_col in headers:
                try:
                    ts_vals = [float(r[ts_col]) for r in rows if r.get(ts_col)]
                    if len(ts_vals) >= 2:
                        duration_s = (ts_vals[-1] - ts_vals[0]) / 1000.0  # assume ms
                except Exception:
                    pass
                break

        return {
            "samples": len(rows),
            "total_energy_joules": round(total_energy, 4),
            "energy_column_used": energy_col,
            "duration_seconds": duration_s,
            "mean_power_watts": (
                round(total_energy / duration_s, 4) if duration_s and duration_s > 0 else None
            ),
            "raw_power_readings": power_readings[:5],  # first 5 for debug
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
