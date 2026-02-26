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
import cpuinfo

log = logging.getLogger(__name__)

ENERGIBRIDGE_BIN = os.getenv(
    "ENERGIBRIDGE_PATH",
    "energibridge",   # assumed to be on PATH
)

SAMPLE_INTERVAL_MS = int(os.getenv("ENERGIBRIDGE_INTERVAL_MS", "500"))


class EnergyProfiler:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self._proc: subprocess.Popen | None = None
        self._output_file: str | None = None

        if not dry_run:
            self._check_energibridge()

    # ── Public API ──────────────────────────────────────────────────────────────

    def detect_cpu(self):
        manufacturer = cpuinfo.get_cpu_info().get("brand_raw", "").lower()

        if "apple" in manufacturer or "m1" in manufacturer or "m2" in manufacturer:
            return "Apple"

        if "amd" in manufacturer or "ryzen" in manufacturer:
            return "AMD"

        if "intel" in manufacturer:
            return "Intel"

        return "Unknown"
    
    def start(self, output_csv: str):
        self._output_file = output_csv

        if self.dry_run:
            log.info("    [DRY-RUN] EnergyBridge skipped.")
            return

        cmd = [
            ENERGIBRIDGE_BIN,
            "--output", output_csv,
            "--interval", str(SAMPLE_INTERVAL_MS),
            "--",
            *self._idle_command(),
        ]

        if platform.system() == "Linux":
            cmd = ["sudo", "-n", *cmd]

        log.debug(f"    EnergyBridge cmd: {' '.join(cmd)}")

        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        time.sleep(0.5)

        if self._proc.poll() is not None:
            stderr = self._proc.stderr.read().decode()
            raise RuntimeError(f"EnergyBridge failed to start: {stderr}")

    def stop(self, force: bool = False) -> dict | None:
        if self.dry_run:
            return {"dry_run": True, "total_energy_joules": None, "samples": 0}

        if self._proc is None:
            return None

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

        if self._output_file and Path(self._output_file).exists():
            return self._parse_csv(self._output_file)
        return None

    def _parse_csv(self, filepath: str) -> dict:
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

        energy_col = None
        power_col  = None
        
        # AMD - CPU_ENERGY, INTEL - PACKAGE_ENERGY, APPLE M1 - SYSTEM_POWER
        cpu_type = self.detect_cpu()

        if cpu_type == "AMD":
            if "CPU_ENERGY (J)" in headers:
                energy_col = "CPU_ENERGY (J)"

        elif cpu_type == "Intel":
            if "PACKAGE_ENERGY (J)" in headers:
                energy_col = "PACKAGE_ENERGY (J)"
            elif "PP0_ENERGY (J)" in headers:
                energy_col = "PP0_ENERGY (J)"
            elif "SYSTEM_POWER (Watts)" in headers:
                energy_col = "SYSTEM_POWER (Watts)"

        elif cpu_type == "Apple":
            if "SYSTEM_POWER (Watts)" in headers:
                energy_col = "SYSTEM_POWER (Watts)"

        if energy_col is None:
            raise RuntimeError(f"No energy column found for CPU: {cpu_type}")

        duration_s  = None
        delta_times = []

        if "Delta" in headers:
            try:
                deltas_ms = [float(r["Delta"]) for r in rows if r.get("Delta")]
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

        if not delta_times:
            interval_s = SAMPLE_INTERVAL_MS / 1000.0
            delta_times = [interval_s] * max(0, len(rows) - 1)
            duration_s  = interval_s * len(rows)

        total_energy  = 0.0
        power_readings = []

        if energy_col:
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
                total_energy = sum(values)
            power_readings = values
            used_col = energy_col

        elif power_col:
            power_vals = []
            for row in rows:
                try:
                    power_vals.append(float(row[power_col]))
                except (ValueError, KeyError):
                    pass
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

    @staticmethod
    def _idle_command():
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
