"""تشغيل التجارب الشاملة للخوارزميات الأربع تحت نفس الشروط وحفظ النتائج الإحصائية."""
from __future__ import annotations

import argparse
import copy
import json
import multiprocessing as mp
import os
import re
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import yaml

from .scenarios import load_scenario
from .aco_dp import ACO, DP
from .ga_pso import GA, PSO
from .fitness import Problem, RandomSearch, load_fitness_config, run_once

ROOT = Path(__file__).resolve().parent

# كل خوارزمية تستطيع التجارب والواجهة البرمجية المباشرة تشغيلها.
ALGORITHMS = {"ga": GA, "pso": PSO, "aco": ACO, "dp": DP, "random": RandomSearch}

CONFIG = ROOT / "config" / "experiments.yaml"
OUT = ROOT / "results" / "experiments"
PARTS = ("main", "random", "timing", "dp_sensitivity", "tuning", "special")

# ثوانٍ لكل تشغيل مقيسة سابقًا (تشغيلان في الوقت نفسه)؛ تُستخدم فقط لبدء أطول التشغيلات أولًا
EST = {"small": {"ga": 4, "pso": 4, "aco": 11, "dp": 0.1},
       "medium": {"ga": 41, "pso": 42, "aco": 110, "dp": 1},
       "large": {"ga": 195, "pso": 177, "aco": 593, "dp": 4}}


def city_path(name: str) -> Path:
    """'medium' -> scenarios/medium.json، و'medium_r03' -> scenarios/random/medium_r03.json،
    'special_maze' -> scenarios/special/special_maze.json."""
    for sub in ("", "random", "special"):
        p = ROOT / "scenarios" / sub / f"{name}.json"
        if p.exists():
            return p
    return ROOT / "scenarios" / "random" / f"{name}.json"


def run_job(job: dict) -> dict:
    """تشغيل واحد. job = {alg, city, seed, params, budget (None = ميزانية المدينة)، fitness (تعديلات)،
    world (تعديلات إعدادات عالم المدينة، مثل {"grid_res": 5} لدراسة شبكة DP)}."""
    scn = load_scenario(city_path(job["city"]))
    scn.world = {**scn.world, **(job.get("world") or {})}
    cfg = load_fitness_config()
    for key, value in (job.get("fitness") or {}).items():     # مثلًا {"init.mode": "uniform"}
        section, name = key.split(".")
        cfg[section][name] = value
    problem = Problem(scn, cfg=cfg, budget=job.get("budget"))
    alg = ALGORITHMS[job["alg"]](**(job.get("params") or {}))
    r = run_once(alg, scn, job["seed"], problem=problem)
    out = r.to_dict()
    out["job"] = copy.deepcopy(job)
    return out


def run_jobs(jobs: list[dict], n_jobs: int | None = None) -> list[dict]:
    n = n_jobs or max(1, (os.cpu_count() or 2))
    if n == 1 or len(jobs) == 1:
        return [run_job(j) for j in jobs]
    with Pool(n) as pool:
        return pool.map(run_job, jobs, chunksize=1)


def save_json(obj, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def load_config(path: Path = CONFIG) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


# المهام
def job_name(job: dict) -> str:
    if job.get("world") or "prune" in (job.get("params") or {}):
        g = (job.get("world") or {}).get("grid_res", 10)
        return f"{job['alg']}_{job['city']}_g{g}_{'pruned' if job['params'].get('prune', True) else 'raw'}"
    return f"{job['alg']}_{job['city']}_s{job['seed']}"


def make_jobs(part: str, cfg: dict, trial: bool = False) -> list[dict]:
    algs = cfg["algorithms"]
    budget = 300 if trial else None
    jobs = []
    if part in ("main", "timing"):
        c = cfg[part]
        for city in c["cities"]:
            for alg in algs:
                for seed in ([0] if alg == "dp" else range(c["seeds"])):
                    jobs.append({"alg": alg, "city": city, "seed": seed, "params": {}, "budget": budget})
    elif part == "random":
        c = cfg["random"]
        for size in c["sizes"]:
            for i in range(1, c["cities"] + 1):
                for alg in algs:
                    for seed in ([0] if alg == "dp" else range(c["seeds"])):
                        jobs.append({"alg": alg, "city": f"{size}_r{i:02d}", "seed": seed, "params": {},
                                     "budget": budget})
    elif part == "dp_sensitivity":
        c = cfg["dp_sensitivity"]
        for city in c["cities"]:
            for g in c["grid_res"]:
                for prune in c["prune"]:
                    jobs.append({"alg": "dp", "city": city, "seed": 0, "params": {"prune": prune},
                                 "budget": budget, "world": {"grid_res": g}})
    else:
        raise ValueError(f"unknown part {part!r}")
    return jobs


def expected_seconds(job: dict) -> float:
    size = job["city"].split("_")[0]
    t = EST[size][job["alg"]]
    g = (job.get("world") or {}).get("grid_res", 10)
    return t * (10 / g) ** 3                      # شبكة أدق: خلايا أكثر


# تشغيل واحد مقيس
def _status_mb(field: str):
    try:
        text = Path("/proc/self/status").read_text()
    except OSError:
        return None
    m = re.search(rf"{field}:\s+(\d+) kB", text)
    return int(m.group(1)) / 1024 if m else None


def memory_start():
    """بدء القياس: إعادة ضبط علامة ذروة الذاكرة لهذه العملية (Linux) وإعادة (خط الأساس بالميغابايت، الطريقة)."""
    try:
        Path("/proc/self/clear_refs").write_text("5")          # يعيد VmHWM إلى قيمة VmRSS الحالية
        return _status_mb("VmRSS"), "linux_peak_rss"
    except OSError:
        pass
    try:
        import resource
        scale = 1 / 1024 if sys.platform != "darwin" else 1 / 2 ** 20   # بالكيلوبايت على Linux وبالبايت على macOS
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * scale, "ru_maxrss"
    except ImportError:                                          # Windows: لا يُقاس
        return None, None


def memory_peak(method):
    if method == "linux_peak_rss":
        return _status_mb("VmHWM")
    if method == "ru_maxrss":
        import resource
        scale = 1 / 1024 if sys.platform != "darwin" else 1 / 2 ** 20
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * scale
    return None


def execute(task) -> dict:
    """تشغيل مهمة واحدة في هذه العملية (الجديدة)، وقياسها، وفحصها بالمدقق، وحفظها."""
    job, path = task
    from . import grid as gridpath
    from .validator import check_plan
    gridpath._GRAPHS.clear()                                     # كل تشغيل يبني شبكته الخاصة
    base, method = memory_start()
    c0 = time.process_time()
    r = run_job(job)
    r["cpu_s"] = time.process_time() - c0
    peak = memory_peak(method)
    r["memory_mb"] = None if base is None or peak is None else max(peak - base, 0.0)
    r["memory_method"] = method
    v = check_plan(load_scenario(city_path(job["city"])), r["paths"])
    r["validator"] = {k: v[k] for k in ("valid", "checks", "problems", "min_clearance_m", "min_margin_linf_m",
                                         "max_hazard", "min_separation_m")}
    r["validator"]["agrees_with_fitness"] = v["valid"] == r["feasible"]
    save_json(r, Path(path))
    return {"name": Path(path).stem, "best_f": r["best_f"], "valid": v["valid"], "time_s": r["time_s"],
            "memory_mb": r["memory_mb"]}


def saved_job(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("job")
    except (OSError, ValueError):
        return None


def run_part(part: str, cfg: dict, out: Path, jobs_n: int | None = None, trial: bool = False):
    folder = out / "runs" / part
    folder.mkdir(parents=True, exist_ok=True)
    todo = []
    jobs = make_jobs(part, cfg, trial)
    for job in jobs:
        path = folder / f"{job_name(job)}.json"
        if saved_job(path) != job:                               # مفقود، أو محفوظ بإعدادات أخرى
            todo.append((job, str(path)))
    print(f"{part}: {len(jobs)} runs, {len(jobs) - len(todo)} already saved, {len(todo)} to do", flush=True)
    if not todo:
        return
    todo.sort(key=lambda t: -expected_seconds(t[0]))             # الأطول أولًا: أقصر زمن إجمالي
    n = jobs_n or mp.cpu_count() or 1
    t0 = time.perf_counter()
    ctx = mp.get_context("fork") if "fork" in mp.get_all_start_methods() else mp.get_context()
    with ctx.Pool(min(n, len(todo)), maxtasksperchild=1) as pool:   # عملية جديدة لكل تشغيل
        for i, row in enumerate(pool.imap_unordered(execute, todo, chunksize=1), 1):
            el = time.perf_counter() - t0
            mem = "-" if row["memory_mb"] is None else f"{row['memory_mb']:.0f} MB"
            print(f"[{part} {i}/{len(todo)}] {row['name']:<26} F {row['best_f']:9.4f}  "
                  f"{'safe' if row['valid'] else 'UNSAFE'}  {row['time_s']:6.1f} s  {mem:>7}  "
                  f"elapsed {el / 60:5.1f} min", flush=True)


def run_tuning(cfg: dict, jobs_n=None):
    from .tune import run_study
    for st in cfg["tuning"]:
        if (ROOT / "results" / "tuning" / f"{st['alg']}_{st['city']}_runs.csv").exists():
            print(f"tuning {st['alg']} {st['city']}: already saved")
            continue
        run_study(st["alg"], st["city"], st["seeds"], st["budget"], jobs_n)


def run_special(cfg: dict, jobs_n=None):
    from . import special
    if (ROOT / "results" / "special" / "summary.csv").exists():
        print("special cases: already saved")
        return
    special.run(cfg["special"]["seeds"], jobs_n)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--part", action="append", choices=PARTS, help="run only these parts (repeatable)")
    ap.add_argument("--jobs", type=int, default=None, help="runs at the same time (default: all cores)")
    ap.add_argument("--stats", action="store_true", help="only statistics, tables and figures from saved runs")
    ap.add_argument("--no-stats", action="store_true", help="only the runs")
    ap.add_argument("--trial", action="store_true", help="short budget, 2 seeds, into results/trial")
    a = ap.parse_args(argv)
    cfg = load_config()
    out = OUT
    if a.trial:
        cfg["main"]["seeds"], cfg["random"]["cities"], cfg["timing"]["seeds"] = 2, 1, 1
        cfg["dp_sensitivity"] = {"cities": ["small"], "grid_res": [20, 10], "prune": [True, False]}
        out = ROOT / "results" / "trial"
    if not a.stats:
        for part in a.part or (PARTS if not a.trial else ("main", "random", "timing", "dp_sensitivity")):
            if part == "tuning":
                run_tuning(cfg, a.jobs)
            elif part == "special":
                run_special(cfg, a.jobs)
            else:
                run_part(part, cfg, out, a.jobs, a.trial)
    if not a.no_stats:
        from .stats import build_all
        build_all(out, cfg, figures=ROOT / "figures" / ("experiments" if not a.trial else "trial"))


if __name__ == "__main__":
    main()
