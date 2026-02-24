import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from config import CONFIGS, EXPERIMENT_SETTINGS
from browser_controller import BrowserController
from energy_profiler import EnergyProfiler
from results_manager import ResultsManager

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/experiment.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Podcast Energy Experiment")
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Run a specific config by name (e.g. 'chrome_apple_1x'). Runs all if omitted.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=EXPERIMENT_SETTINGS["runs_per_config"],
        help="Number of runs per configuration (default: 30)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Launch browser but skip EnergyBridge (for testing)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="results",
        help="Directory to save results",
    )
    return parser.parse_args()


def run_single_trial(config: dict, run_id: int, dry_run: bool, output_dir: str) -> dict:
    config_name = config["name"]
    log.info(f"  Trial {run_id + 1} | {config_name}")

    results_mgr = ResultsManager(output_dir)
    profiler = EnergyProfiler(dry_run=dry_run)
    controller = BrowserController(config)

    result = {
        "config": config_name,
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "success": False,
        "energy_data": None,
        "error": None,
    }

    try:
        log.info("    Launching browser...")
        controller.setup()

        log.info("    Starting EnergyBridge...")
        energy_file = results_mgr.energy_filepath(config_name, run_id)
        profiler.start(energy_file)

        log.info("    Starting playback...")
        controller.start_playback()

        duration = EXPERIMENT_SETTINGS["measurement_duration_seconds"]
        log.info(f"    Recording for {duration}s...")
        time.sleep(duration)

        log.info("    Stopping EnergyBridge...")
        energy_data = profiler.stop()
        result["energy_data"] = energy_data
        result["success"] = True

    except Exception as e:
        log.error(f"    Trial failed: {e}", exc_info=True)
        result["error"] = str(e)
        profiler.stop(force=True)

    finally:
        try:
            controller.teardown()
        except Exception:
            pass

    results_mgr.save_trial(result)

    cooldown = EXPERIMENT_SETTINGS["cooldown_seconds"]
    log.info(f"    Cooling down {cooldown}s...")
    time.sleep(cooldown)

    return result


def main():
    args = parse_args()

    Path(args.output_dir).mkdir(exist_ok=True)

    configs_to_run = CONFIGS
    if args.config:
        configs_to_run = [c for c in CONFIGS if c["name"] == args.config]
        if not configs_to_run:
            log.error(f"Config '{args.config}' not found. Available: {[c['name'] for c in CONFIGS]}")
            sys.exit(1)

    log.info(f"Starting experiment: {len(configs_to_run)} config(s) x {args.runs} runs each")

    summary = []
    for config in configs_to_run:
        log.info(f"\n{'='*60}")
        log.info(f"Config: {config['name']}")
        log.info(f"{'='*60}")

        config_results = []
        for run_id in range(args.runs):
            result = run_single_trial(config, run_id, args.dry_run, args.output_dir)
            config_results.append(result)

        successes = sum(1 for r in config_results if r["success"])
        log.info(f"Config {config['name']} done: {successes}/{args.runs} successful")
        summary.append({"config": config["name"], "successes": successes, "runs": args.runs})

    summary_path = Path(args.output_dir) / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    log.info(f"\nExperiment complete. Results in '{args.output_dir}/'")
    log.info(f"Run: python report_data_analysis.py --input-dir {args.output_dir}")


if __name__ == "__main__":
    main()
