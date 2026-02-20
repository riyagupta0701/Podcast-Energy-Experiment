"""
Results persistence: saves individual trial JSON files and
aggregates them for analysis.
"""

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


class ResultsManager:
    def __init__(self, output_dir: str = "results"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def energy_filepath(self, config_name: str, run_id: int) -> str:
        path = self.output_dir / config_name
        path.mkdir(parents=True, exist_ok=True)
        return str(path / f"energy_run_{run_id:02d}.csv")

    def save_trial(self, result: dict):
        config_name = result["config"]
        run_id = result["run_id"]
        path = self.output_dir / config_name / f"trial_{run_id:02d}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(result, f, indent=2)
        log.debug(f"    Saved trial result: {path}")
