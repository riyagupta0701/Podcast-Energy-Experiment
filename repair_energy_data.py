import json
import csv
from pathlib import Path


def parse_csv_force_cpu_energy(csv_path: Path) -> dict:
    rows = []

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    if not rows:
        raise ValueError(f"No rows in {csv_path}")

    headers = rows[0].keys()

    if "CPU_ENERGY (J)" not in headers:
        raise ValueError(f"'CPU_ENERGY (J)' not found in {csv_path}")

    # Extract cumulative CPU energy values
    energy_values = []
    for row in rows:
        try:
            energy_values.append(float(row["CPU_ENERGY (J)"]))
        except (ValueError, KeyError):
            pass

    if len(energy_values) < 2:
        raise ValueError(f"Not enough energy samples in {csv_path}")

    total_energy = energy_values[-1] - energy_values[0]

    # Duration (if Time column exists)
    duration_s = None
    if "Time" in headers:
        try:
            ts = [float(r["Time"]) for r in rows if r.get("Time")]
            if len(ts) >= 2:
                duration_s = (ts[-1] - ts[0]) / 1000.0
        except Exception:
            pass

    mean_power = (
        total_energy / duration_s
        if duration_s and duration_s > 0
        else None
    )

    return {
        "samples": len(rows),
        "total_energy_joules": round(total_energy, 4),
        "energy_column_used": "CPU_ENERGY (J)",
        "duration_seconds": round(duration_s, 2) if duration_s else None,
        "mean_power_watts": round(mean_power, 4) if mean_power else None,
        "raw_power_readings": energy_values[:5],
    }


def repair_all_trials(results_dir: str):
    base = Path(results_dir)

    for config_dir in base.iterdir():
        if not config_dir.is_dir():
            continue

        print(f"\nProcessing config: {config_dir.name}")

        for json_file in config_dir.glob("trial_*.json"):
            trial_number = json_file.stem.split("_")[-1]  # X
            csv_file = config_dir / f"energy_run_{trial_number}.csv"

            if not csv_file.exists():
                print(f"  ⚠ CSV missing for trial_{trial_number}")
                continue

            try:
                new_energy_data = parse_csv_force_cpu_energy(csv_file)

                with open(json_file) as f:
                    trial_data = json.load(f)

                trial_data["energy_data"] = new_energy_data

                with open(json_file, "w") as f:
                    json.dump(trial_data, f, indent=2)

                print(f"  ✓ Fixed trial_{trial_number}")

            except Exception as e:
                print(f"  ✗ Failed trial_{trial_number}: {e}")


if __name__ == "__main__":
    repair_all_trials("results")