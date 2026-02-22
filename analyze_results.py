#!/usr/bin/env python3
"""
Analyze experiment results.
Generates a CSV summary and ASCII/matplotlib box plots.

Usage:
    python analyze_results.py --input-dir results
    python analyze_results.py --input-dir results --plot
"""

import argparse
import csv
import json
import math
from pathlib import Path


def load_results(input_dir: str) -> dict[str, list[float]]:
    """Load all trial JSON files and return energy readings per config."""
    data: dict[str, list[float]] = {}
    input_path = Path(input_dir)

    for config_dir in sorted(input_path.iterdir()):
        if not config_dir.is_dir():
            continue
        config_name = config_dir.name
        energies = []
        for trial_file in sorted(config_dir.glob("trial_*.json")):
            with open(trial_file) as f:
                trial = json.load(f)
            if trial.get("success") and trial.get("energy_data"):
                e = trial["energy_data"].get("total_energy_joules")
                if e is not None:
                    energies.append(e)
        if energies:
            data[config_name] = energies

    return data


def statistics(values: list[float]) -> dict:
    n = len(values)
    if n == 0:
        return {}
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1) if n > 1 else 0
    std = math.sqrt(variance)
    sorted_v = sorted(values)
    median = sorted_v[n // 2] if n % 2 else (sorted_v[n // 2 - 1] + sorted_v[n // 2]) / 2
    return {
        "n": n,
        "mean_J": round(mean, 4),
        "median_J": round(median, 4),
        "std_J": round(std, 4),
        "min_J": round(sorted_v[0], 4),
        "max_J": round(sorted_v[-1], 4),
        "cv_pct": round(100 * std / mean, 2) if mean else None,
    }


def print_table(stats_by_config: dict):
    headers = ["Config", "N", "Mean (J)", "Median (J)", "Std (J)", "Min (J)", "Max (J)", "CV%"]
    rows = []
    for config, s in stats_by_config.items():
        rows.append([
            config, s["n"], s["mean_J"], s["median_J"],
            s["std_J"], s["min_J"], s["max_J"],
            s["cv_pct"] if s.get("cv_pct") is not None else "N/A",
        ])

    col_widths = [max(len(str(r[i])) for r in rows + [headers]) + 2 for i in range(len(headers))]
    # ensure all row values are strings so format() doesn't choke on None
    rows = [[str(v) for v in row] for row in rows]
    fmt = "".join(f"{{:<{w}}}" for w in col_widths)
    sep = "-" * sum(col_widths)

    print("\n" + sep)
    print(fmt.format(*headers))
    print(sep)
    for row in rows:
        print(fmt.format(*row))
    print(sep + "\n")


def save_csv(stats_by_config: dict, output_path: str):
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["config", "n", "mean_J", "median_J", "std_J", "min_J", "max_J", "cv_pct"])
        writer.writeheader()
        for config, s in stats_by_config.items():
            writer.writerow({"config": config, **s})
    print(f"CSV saved to {output_path}")


def ascii_boxplot(values: list[float], width: int = 50) -> str:
    """Render a simple ASCII box-and-whisker plot."""
    if not values:
        return "(no data)"
    sorted_v = sorted(values)
    n = len(sorted_v)
    q1 = sorted_v[n // 4]
    q3 = sorted_v[3 * n // 4]
    median = sorted_v[n // 2]
    lo, hi = sorted_v[0], sorted_v[-1]
    span = hi - lo if hi != lo else 1

    def pos(v):
        return int((v - lo) / span * (width - 1))

    line = [" "] * width
    # whiskers
    for i in range(pos(lo), pos(hi) + 1):
        line[i] = "-"
    # box
    for i in range(pos(q1), pos(q3) + 1):
        line[i] = "="
    # median
    line[pos(median)] = "|"
    # ends
    line[pos(lo)] = "["
    line[pos(hi)] = "]"
    return "".join(line)


def plot_matplotlib(data: dict[str, list[float]], output_path: str):
    try:
        import matplotlib.pyplot as plt
        import numpy as np

        fig, ax = plt.subplots(figsize=(14, 6))
        configs = list(data.keys())
        values_list = [data[c] for c in configs]

        ax.boxplot(values_list, labels=configs, vert=True, patch_artist=True)
        ax.set_ylabel("Energy (Joules)")
        ax.set_title("Podcast Web Player Energy Consumption by Configuration")
        plt.xticks(rotation=30, ha="right")
        plt.tight_layout()
        plt.savefig(output_path, dpi=150)
        print(f"Plot saved to {output_path}")
    except ImportError:
        print("matplotlib not installed; skipping plot. Install with: pip install matplotlib")


def main():
    parser = argparse.ArgumentParser(description="Analyze experiment results")
    parser.add_argument("--input-dir", default="results", help="Results directory")
    parser.add_argument("--plot", action="store_true", help="Generate matplotlib box plots")
    parser.add_argument("--output-csv", default="results/analysis_summary.csv")
    parser.add_argument("--output-plot", default="results/boxplot.png")
    args = parser.parse_args()

    data = load_results(args.input_dir)

    if not data:
        print("No results found. Run the experiment first.")
        return

    stats_by_config = {c: statistics(v) for c, v in data.items()}

    print_table(stats_by_config)

    # ASCII box plots
    print("ASCII Box Plots (energy in Joules):\n")
    for config, values in data.items():
        s = stats_by_config[config]
        bar = ascii_boxplot(values)
        print(f"  {config:<30}  {bar}")
        print(f"    mean={s['mean_J']}J  std={s['std_J']}J  n={s['n']}")
    print()

    save_csv(stats_by_config, args.output_csv)

    if args.plot:
        plot_matplotlib(data, args.output_plot)


if __name__ == "__main__":
    main()
