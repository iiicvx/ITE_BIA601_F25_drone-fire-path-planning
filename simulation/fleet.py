"""بناء وتشغيل سيناريوهات أسطول المُسيَّرات (2 / 4 / 6 مُسيَّرات) والتحقق من خطط الطيران."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml

from simulation.fitness import run_once
from simulation.scenarios import generate_city, load_config, load_scenario
from simulation.experiments import ALGORITHMS
from simulation.validator import check_plan

ROOT = Path(__file__).resolve().parent
SCENARIOS = ROOT / "scenarios" / "fleet"
RESULTS = ROOT / "results" / "fleet"
SIZES = ("small", "medium", "large")


def fleet_config():
    fleet = yaml.safe_load((ROOT / "config" / "fleet.yaml").read_text(encoding="utf-8"))
    cfg = load_config()
    for size, count in fleet["drones"].items():
        cfg["sizes"][size].update(n_drones=count, n_fires=count)
    return fleet, cfg


def build():
    fleet, cfg = fleet_config()
    for size in SIZES:
        path = SCENARIOS / f"{size}.json"
        if not path.exists():
            scn = generate_city(size, fleet["seed"], cfg, name=f"fleet_{size}")
            scn.save(path)
        scn = load_scenario(path)
        if len(scn.missions) != fleet["drones"][size]:
            raise ValueError(f"stale fleet scenario: {path}")
        print(f"{size}: {len(scn.missions)} drones, {len(scn.fires)} fires", flush=True)


def run(seeds):
    build()
    RESULTS.mkdir(parents=True, exist_ok=True)
    fleet, _ = fleet_config()
    # تبدأ المهام الكبيرة أولًا؛ وتُحفظ كل نتيجة مكتملة فورًا.
    for size in reversed(SIZES):
        path = SCENARIOS / f"{size}.json"
        fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
        scn = load_scenario(path)
        for alg in ("dp", "ga", "pso", "aco"):
            for seed in ([0] if alg == "dp" else seeds):
                out = RESULTS / f"{alg}_{size}_s{seed}.json"
                if out.exists():
                    saved = json.loads(out.read_text(encoding="utf-8"))
                    if saved.get("scenario_sha256") == fingerprint:
                        continue
                    raise ValueError(f"scenario changed since {out}; use a new revision")
                print(f"running {alg}/{size}/s{seed} …", flush=True)
                r = run_once(ALGORITHMS[alg](), scn, seed).to_dict()
                v = check_plan(scn, r["paths"])
                r.update(validator=v, revision=fleet["revision"], scenario_sha256=fingerprint)
                r["validator"]["agrees_with_fitness"] = v["valid"] == r["feasible"]
                out.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"{alg}/{size}: F={r['best_f']:.6f}, safe={v['valid']}, "
                      f"agreement={v['valid'] == r['feasible']}, {r['time_s']:.1f}s", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--seeds", nargs="+", type=int, default=[0])
    args = ap.parse_args()
    if args.run:
        run(args.seeds)
    else:
        build()
