"""إعادة تقييم المسارات المحفوظة والتحقق من سلامتها عبر المدقق المستقل."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from simulation.scenarios import load_scenario
from simulation.fitness import Problem
from simulation.validator import check_plan, scenario_path

ROOT = Path(__file__).resolve().parent


def audit():
    groups = {
        "published_135": sorted((ROOT / "results/experiments/runs").glob("*/*.json")),
        "fleet_246": sorted((ROOT / "results/fleet").glob("*_s*.json")),
        "quick_135": sorted((ROOT / "results/quick").glob("*_s*.json")),
        "special_cases": [ROOT / "results/special/runs.json"],
    }
    output = {"checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "hazard_step_m": .1, "separation_step_s": .01, "groups": {}, "failures": []}
    for group, files in groups.items():
        stats = {
            "runs": 0, "safe": 0, "unsafe": 0,
            "verdict_disagreements": 0, "score_mismatches": 0, "metric_mismatches": 0,
            "max_clearance_sampling_difference_m": 0.,
            "max_separation_sampling_difference_m": 0.,
        }
        entries = []
        for file in files:
            data = json.loads(file.read_text(encoding="utf-8"))
            entries.extend((file, result) for result in (data if isinstance(data, list) else [data]))

        for file, result in entries:
            scn_path = scenario_path(result["scenario"])
            scn = load_scenario(scn_path)
            F, info = Problem(scn).evaluate_paths(result["paths"], count=False)
            independent = check_plan(scn, result["paths"])
            stats["runs"] += 1
            stats["safe" if independent["valid"] else "unsafe"] += 1
            agreement = independent["valid"] == info["feasible"] == result["feasible"]
            matches = math.isclose(F, result["best_f"], rel_tol=0, abs_tol=1e-9)
            stats["verdict_disagreements"] += not agreement
            stats["score_mismatches"] += not matches
            metrics_ok = True
            if result.get("report"):
                report = result["report"]
                for saved, measured in zip(report["drones"], independent["drones"]):
                    for key, expected in {
                        "length_m": measured["length_m"],
                        "energy_kj": measured["energy_kj"],
                        "battery_used_pct": measured["battery_pct"],
                        "time_s": measured["length_m"] / scn.drone["speed"],
                    }.items():
                        metrics_ok &= math.isclose(saved[key], expected, rel_tol=1e-10, abs_tol=1e-9)
                expected_time = max(d["length_m"] / scn.drone["speed"] for d in independent["drones"])
                metrics_ok &= math.isclose(report["mission_time_s"], expected_time, rel_tol=1e-10, abs_tol=1e-9)

                clearance_difference = independent["min_clearance_m"] - report["min_clearance_m"]
                if math.isfinite(clearance_difference):
                    stats["max_clearance_sampling_difference_m"] = max(
                        stats["max_clearance_sampling_difference_m"], clearance_difference)
                    metrics_ok &= -1e-6 <= clearance_difference <= .050001
                if report["min_separation_m"] is not None:
                    separation_difference = independent["min_separation_m"] - report["min_separation_m"]
                    stats["max_separation_sampling_difference_m"] = max(
                        stats["max_separation_sampling_difference_m"], separation_difference)
                    metrics_ok &= -1e-6 <= separation_difference <= scn.drone["speed"] * .01 + 1e-6

            stats["metric_mismatches"] += not metrics_ok
            if not metrics_ok:
                output["failures"].append({
                    "file": str(file.relative_to(ROOT)), "scenario": result["scenario"],
                    "seed": result["seed"], "problem": "path metric mismatch",
                })
            if not agreement or not matches:
                output["failures"].append({"file": str(file.relative_to(ROOT)), "F": F,
                                           "saved_F": result["best_f"], "valid": independent["valid"]})
            if (result.get("scenario_sha256")
                    and result["scenario_sha256"] != hashlib.sha256(scn_path.read_bytes()).hexdigest()):
                output["failures"].append({"file": str(file.relative_to(ROOT)), "problem": "scenario hash changed"})
        output["groups"][group] = stats
        print(f"{group}: {stats}", flush=True)
    output["passed"] = not output["failures"]
    (ROOT / "results/verification.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output


if __name__ == "__main__":
    raise SystemExit(0 if audit()["passed"] else 1)
