import argparse
import logging
import sys

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")

from config import CONFIGS
from run_experiment import run_single_trial


def main():
    parser = argparse.ArgumentParser(description="Test a single configuration")
    parser.add_argument(
        "--config",
        required=True,
        help=f"Config name. Options: {[c['name'] for c in CONFIGS]}",
    )
    parser.add_argument("--dry-run", action="store_true", help="Skip EnergyBridge")
    parser.add_argument("--output-dir", default="results_test")
    args = parser.parse_args()

    matched = [c for c in CONFIGS if c["name"] == args.config]
    if not matched:
        print(f"Unknown config: {args.config}")
        print(f"Available: {[c['name'] for c in CONFIGS]}")
        sys.exit(1)

    config = matched[0]
    print(f"\nTesting: {config['name']}")
    print(f"  Browser:  {config['browser']}")
    print(f"  Platform: {config['platform']}")
    print(f"  Speed:    {config['speed']}x")
    print(f"  URL:      {config['url']}")
    print(f"  Dry run:  {args.dry_run}\n")

    result = run_single_trial(config, run_id=0, dry_run=args.dry_run, output_dir=args.output_dir)

    print("\n── Result ──────────────────────────────────")
    print(f"  Success:  {result['success']}")
    if result.get("energy_data"):
        print(f"  Energy:   {result['energy_data']}")
    if result.get("error"):
        print(f"  Error:    {result['error']}")
    print("────────────────────────────────────────────\n")

    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
