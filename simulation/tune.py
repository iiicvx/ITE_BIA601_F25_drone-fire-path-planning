"""دراسة حساسية المعاملات (Hyperparameters Tuning) للخوارزميات."""
from __future__ import annotations

import argparse
import csv
import time

import numpy as np

from .fitness import algorithm_params
from .experiments import ROOT, run_jobs

# القيم المجربة لكل معامل (تُضمَّن القيمة الافتراضية دائمًا)
STUDIES = {
    "ga": {
        "pop_size": [30, 60, 100],
        "crossover": ["sbx", "segment", "drone", "drone+segment+sbx"],
        "p_c": [0.6, 0.9, 1.0],
        "tournament_k": [2, 3, 5],
        "p_mut": [0.1, 0.25, 0.5, 1.0],
        "mut_width": [0, 1.5, 2.5, 4],
        "sigma_start": [0.05, 0.1, 0.2],
        "init.mode": ["uniform", "via"],           # المجتمع الابتدائي (مشترك مع PSO)
    },
    "pso": {
        "pop_size": [30, 60, 100],
        "w": [0.4, 0.6, 0.7298, 0.9],
        "c1": [1.0, 1.49618, 2.0],
        "c2": [1.0, 1.49618, 2.0],
        "v_max": [0.05, 0.1, 0.2, 0.5],
        "topology": ["global", "ring"],
        "r_mode": ["dimension", "waypoint", "particle"],
        "restart_stall": [None, 10, 20, 40],
        "init.mode": ["uniform", "via"],           # المجتمع الابتدائي (مشترك مع GA)
    },
    "aco": {
        "pop_size": [30, 60, 100],
        "alpha": [0.5, 1.0, 2.0],
        "beta": [1.0, 2.0, 4.0],
        "rho": [0.02, 0.1, 0.3],
        "lambda_h": [0.0, 3.0, 10.0],
        "gb_every": [1, 5, 25],
        "conflict_margin": [0, 5, 15],
        "prune": [True, False],
    },
}
FITNESS_DEFAULTS = {"init.mode": "via"}


def _parse(v: str):
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    if v in ("True", "true", "False", "false"):
        return v in ("True", "true")
    return None if v in ("null", "None", "") else v


def build_jobs(alg: str, city: str, seeds: int, study: dict, budget):
    size = city.split("_")[0]
    defaults = {**algorithm_params(alg, size), **FITNESS_DEFAULTS}
    configs = [("default", "default", {}, {})]
    for name, values in study.items():
        for v in values:
            if v == defaults.get(name):
                continue
            params, fitness = ({}, {name: v}) if "." in name else ({name: v}, {})
            configs.append((name, v, params, fitness))
    jobs = []
    for name, v, params, fitness in configs:
        for s in range(seeds):
            jobs.append({"alg": alg, "city": city, "seed": 1000 + s, "params": params, "fitness": fitness,
                         "budget": budget, "tag": [name, v]})
    return jobs, defaults


def summarise(results, study, defaults):
    by = {}
    for r in results:
        by.setdefault(tuple(r["job"]["tag"]), []).append(r)
    base = by[("default", "default")]
    rows = []
    for name, values in study.items():
        for v in values:
            rs = base if v == defaults.get(name) else by.get((name, v), [])
            if not rs:
                continue
            F = np.array([r["best_f"] for r in rs])
            ff = [r["first_feasible_fe"] for r in rs if r["first_feasible_fe"] is not None]
            rows.append({
                "parameter": name, "value": v, "is_default": v == defaults.get(name),
                "runs": len(rs), "mean_F": F.mean(), "std_F": F.std(ddof=1) if len(F) > 1 else 0.0,
                "best_F": F.min(), "worst_F": F.max(), "median_F": float(np.median(F)),
                "success_rate": float(np.mean([r["feasible"] for r in rs])),
                "mean_first_feasible_fe": float(np.mean(ff)) if ff else None,
                "mean_time_s": float(np.mean([r["time_s"] for r in rs])),
                "F_values": [float(x) for x in F],
            })
    return rows


def plot(rows, alg, city, out, budget=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    surface, ink, ink2, muted, grid = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
    accent, other = "#2a78d6", "#a8a79f"
    params = list(dict.fromkeys(r["parameter"] for r in rows))
    ncol = 4
    nrow = int(np.ceil(len(params) / ncol))
    fig, axs = plt.subplots(nrow, ncol, figsize=(4.0 * ncol, 3.1 * nrow + 0.8), sharey=True,
                            facecolor=surface, squeeze=False)
    all_f = np.concatenate([r["F_values"] for r in rows] + [[r["mean_F"] - r["std_F"], r["mean_F"] + r["std_F"]]
                                                            for r in rows])
    lo, hi = all_f.min(), all_f.max()
    for ax, name in zip(axs.ravel(), params):
        rs = [r for r in rows if r["parameter"] == name]
        ax.set_facecolor(surface)
        for i, r in enumerate(rs):
            col = accent if r["is_default"] else other
            ax.scatter(np.full(len(r["F_values"]), i) + np.linspace(-0.12, 0.12, len(r["F_values"])),
                       r["F_values"], s=14, color=col, alpha=0.55, lw=0, zorder=3)
            ax.errorbar(i, r["mean_F"], yerr=r["std_F"], fmt="o", color=col, ms=7, capsize=4, lw=1.6, zorder=4)
        ax.set_xticks(range(len(rs)))
        ax.set_xticklabels([str(r["value"]).replace("+", "+\n") for r in rs], fontsize=8, color=ink2)
        ax.set_title(name, loc="left", fontsize=10, color=ink)
        ax.grid(axis="y", color=grid, lw=0.6)
        ax.set_axisbelow(True)
        for s in ax.spines.values():
            s.set_color("#c3c2b7")
        ax.tick_params(colors=muted, labelsize=8)
        ax.set_ylim(lo - 0.05 * (hi - lo), hi + 0.08 * (hi - lo))
    for ax in axs.ravel()[len(params):]:
        ax.axis("off")
    for ax in axs[:, 0]:
        ax.set_ylabel("best F (lower is better)", color=ink2, fontsize=9)
    n = rows[0]["runs"]
    budget_note = "full budget" if budget is None else f"short budget of {budget:,} evaluations"
    fig.suptitle(f"{alg.upper()} parameter study on the {city} city ({budget_note}): one parameter changed at a "
                 f"time, {n} seeds per value  ·  blue = default, grey = alternative, bars = mean ± std",
                 x=0.01, ha="left", fontsize=11.5, color=ink)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=140, facecolor=surface)
    plt.close(fig)


def replot(alg, city, study):
    """إعادة رسم الشكل من results/tuning/<alg>_<city>_runs.csv دون تشغيل أي شيء.
    تُستخدم القيم الافتراضية المحفوظة مع الدراسة (فقد تكون الإعدادات تغيرت بعدها)."""
    import json
    size = city.split("_")[0]
    saved = ROOT / "results" / "tuning" / f"{alg}_{city}_defaults.json"
    defaults = json.loads(saved.read_text()) if saved.exists() else {**algorithm_params(alg, size), **FITNESS_DEFAULTS}
    budget = defaults.pop("_budget", None)
    results = []
    with open(ROOT / "results" / "tuning" / f"{alg}_{city}_runs.csv") as fh:
        for row in csv.DictReader(fh):
            v = row["value"] if row["parameter"] == "default" else _parse(row["value"])
            ff = row["first_feasible_fe"]
            results.append({"job": {"tag": [row["parameter"], v]}, "best_f": float(row["best_f"]),
                            "feasible": row["feasible"] == "True", "time_s": float(row["time_s"]),
                            "first_feasible_fe": int(ff) if ff not in ("", "None") else None})
    if saved.exists():                                   # القيم التي جُربت فعلًا
        study = {}
        for r in results:
            name, v = r["job"]["tag"]
            if name != "default" and v not in study.setdefault(name, [defaults.get(name)]):
                study[name].append(v)
        study = {k: sorted(v, key=lambda x: (x is None, str(type(x)), x if x is not None else 0))
                 for k, v in study.items()}
    plot(summarise(results, study, defaults), alg, city, ROOT / "figures" / alg / f"tuning_{city}.png", budget)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--alg", default="ga", choices=sorted(STUDIES))
    ap.add_argument("--city", default="medium")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--budget", type=int, default=None, help="default: the city's own budget")
    ap.add_argument("--param", action="append", default=[], help="name=v1,v2,... (replaces the default study)")
    ap.add_argument("--jobs", type=int, default=None)
    ap.add_argument("--replot", action="store_true", help="redraw the figure from the saved runs CSV")
    a = ap.parse_args()
    study = STUDIES[a.alg]
    if a.replot:
        replot(a.alg, a.city, study)
        return
    if a.param:
        study = {p.split("=")[0]: [_parse(v) for v in p.split("=")[1].split(",")] for p in a.param}
    run_study(a.alg, a.city, a.seeds, a.budget, a.jobs, study)


def run_study(alg: str, city: str, seeds: int = 5, budget=None, jobs=None, study: dict | None = None):
    """تشغيل دراسة معامل واحدة وكتابة ملفات CSV والشكل الخاص بها (تستخدمها experiments.py أيضًا)."""
    import json
    study = study or STUDIES[alg]
    job_list, defaults = build_jobs(alg, city, seeds, study, budget)
    out = ROOT / "results" / "tuning"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{alg}_{city}_defaults.json").write_text(json.dumps({**defaults, "_budget": budget}, indent=1))
    print(f"{len(job_list)} runs ...", flush=True)
    t0 = time.perf_counter()
    results = run_jobs(job_list, jobs)
    print(f"done in {time.perf_counter() - t0:.0f} s")
    rows = summarise(results, study, defaults)
    stem = f"{alg}_{city}"
    with open(out / f"{stem}_runs.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["parameter", "value", "seed", "best_f", "feasible", "first_feasible_fe", "fe_used", "time_s"])
        for r in results:
            w.writerow([*r["job"]["tag"], r["seed"], r["best_f"], r["feasible"], r["first_feasible_fe"],
                        r["fe_used"], round(r["time_s"], 2)])
    with open(out / f"{stem}_summary.csv", "w", newline="") as fh:
        keys = [k for k in rows[0] if k != "F_values"]
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items() if k in keys})
    plot(rows, alg, city, ROOT / "figures" / alg / f"tuning_{city}.png", budget)
    for r in rows:
        mark = "*" if r["is_default"] else " "
        print(f"{mark} {r['parameter']:<16}{str(r['value']):<20} mean {r['mean_F']:.3f} ± {r['std_F']:.3f}  "
              f"best {r['best_F']:.3f}  worst {r['worst_F']:.3f}  safe {100 * r['success_rate']:.0f} %")
    return rows


if __name__ == "__main__":
    main()
