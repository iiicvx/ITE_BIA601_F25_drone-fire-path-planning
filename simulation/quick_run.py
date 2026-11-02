"""تشغيل سريع لإحدى الخوارزميات على أحجام المدن الثلاثة ورسم النتائج."""
from __future__ import annotations

import argparse
import csv
import time

import numpy as np

from .scenarios import load_scenario
from .fitness import Problem, climb_over_plan
from .experiments import ROOT, run_jobs, save_json

SIZES = ("small", "medium", "large")


def summary_rows(results):
    rows = []
    for size in SIZES:
        rs = [r for r in results if r["job"]["city"] == size]
        if not rs:
            continue
        F = np.array([r["best_f"] for r in rs])
        scn = load_scenario(ROOT / "scenarios" / f"{size}.json")
        ref = Problem(scn).evaluate_paths(climb_over_plan(scn), count=False)[0]
        rows.append({"city": size, "runs": len(rs), "mean_F": F.mean(), "std_F": F.std(ddof=1) if len(F) > 1 else 0.0,
                     "best_F": F.min(), "worst_F": F.max(), "median_F": float(np.median(F)),
                     "success_rate": float(np.mean([r["feasible"] for r in rs])),
                     "mean_first_feasible_fe": float(np.mean([r["first_feasible_fe"] for r in rs
                                                               if r["first_feasible_fe"] is not None] or [np.nan])),
                     "mean_time_s": float(np.mean([r["time_s"] for r in rs])),
                     "budget": rs[0]["budget"], "reference_F": ref})
    return rows


def plot_convergence(results, alg, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from .figures import INK, INK2, MUTED, GRID, SURFACE

    accent = "#2a78d6"
    fig, axs = plt.subplots(1, 3, figsize=(15, 4.4), facecolor=SURFACE)
    for ax, size in zip(axs, SIZES):
        rs = [r for r in results if r["job"]["city"] == size]
        if not rs:
            ax.axis("off")
            continue
        n_it = min(len(r["iter_history"]) for r in rs)
        curves = np.array([[b for _, _, b in r["iter_history"][:n_it]] for r in rs])
        it = np.arange(n_it)
        ax.set_facecolor(SURFACE)
        ax.fill_between(it, curves.min(0), curves.max(0), color=accent, alpha=0.15, lw=0, label="range over seeds")
        ax.plot(it, np.median(curves, 0), color=accent, lw=2, label="median")
        scn = load_scenario(ROOT / "scenarios" / f"{size}.json")
        ref = Problem(scn).evaluate_paths(climb_over_plan(scn), count=False)[0]
        ax.axhline(ref, color=MUTED, ls=(0, (4, 3)), lw=1.2, label=f"climb-over reference ({ref:.2f})")
        if max(curves.max(), ref) / curves.min() > 10:      # خطط غير آمنة (F > 100) في البداية: مقياس لوغاريتمي
            ax.set_yscale("log")
            ax.set_ylabel("best F so far (log scale)", color=INK2)
        else:                                                 # كل الخطط آمنة من البداية: مقياس خطي
            ax.set_ylabel("best F so far", color=INK2)
        ax.set_xlabel("iteration (generation)", color=INK2)
        ax.set_title(f"{size} city  ·  {len(rs)} seeds  ·  final median {np.median(curves[:, -1]):.3f}",
                     loc="left", fontsize=10.5, color=INK)
        ax.grid(color=GRID, lw=0.6, which="both")
        ax.set_axisbelow(True)
        ax.tick_params(colors=MUTED, labelsize=8.5)
        for s in ax.spines.values():
            s.set_color("#c3c2b7")
        ax.legend(frameon=False, fontsize=8.5, labelcolor=INK2)
    fig.suptitle(f"{alg.upper()} convergence: Iteration → Best Fitness  (lower is better; values above 100 are "
                 f"unsafe plans)",
                 x=0.01, ha="left", fontsize=12.5, color=INK, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=140, facecolor=SURFACE)
    plt.close(fig)


def plot_dp_sweeps(results, out):
    """لا مجتمع في DP: تقاربها هو استقرار جدول الكلفة، دورة بعد دورة."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from .figures import DRONES, INK, INK2, MUTED, GRID, SURFACE

    fig, axs = plt.subplots(2, 3, figsize=(15, 7.2), facecolor=SURFACE, sharex="col")
    for col, size in enumerate(SIZES):
        rs = [r for r in results if r["job"]["city"] == size]
        top, bottom = axs[0, col], axs[1, col]
        if not rs:
            top.axis("off")
            bottom.axis("off")
            continue
        e = rs[0]["extra"]                                          # حتمي: كل التشغيلات متطابقة
        for k, (changed, goal) in enumerate(zip(e["changed_per_sweep"], e["goal_cost_per_sweep"])):
            c = DRONES[k % len(DRONES)]
            sw = np.arange(1, len(changed) + 1)
            top.plot(sw, np.maximum(changed, 0.8), color=c, lw=1.6, label=f"drone {k + 1}")
            g = np.array([np.nan if v is None else v for v in goal], float)
            bottom.plot(sw, g, color=c, lw=1.6)
        for ax in (top, bottom):
            ax.set_facecolor(SURFACE)
            ax.grid(color=GRID, lw=0.6)
            ax.set_axisbelow(True)
            ax.tick_params(colors=MUTED, labelsize=8.5)
            for sp in ax.spines.values():
                sp.set_color("#c3c2b7")
        top.set_yscale("log")
        top.set_title(f"{size} city\nstable after {max(e['sweeps'])} sweeps  ·  "
                      f"{sum(e['relaxed_edges']) / 1e6:.1f} M edges relaxed", loc="left", fontsize=10.5, color=INK)
        top.legend(frameon=False, fontsize=8, labelcolor=INK2, ncol=len(e["sweeps"]), loc="lower left")
        bottom.set_xlabel("sweep", color=INK2)
    axs[0, 0].set_ylabel("cells improved in the sweep (log)", color=INK2)
    axs[1, 0].set_ylabel("best cost to the target so far", color=INK2)
    fig.suptitle("DP (Bellman-Ford): the cost table settles sweep by sweep; the target's cost drops, then stops "
                 "changing", x=0.01, ha="left", fontsize=12.5, color=INK, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=140, facecolor=SURFACE)
    plt.close(fig)


def plot_best_paths(results, alg, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize
    from .scenarios import load_config
    from .figures import DRONES, INK, INK2, MUTED, GRID, SURFACE, _top
    from . import geometry as G

    cfg = load_config()
    fig, axs = plt.subplots(2, 3, figsize=(16, 8.4), facecolor=SURFACE,
                            gridspec_kw={"height_ratios": [2.3, 1]})
    for col, size in enumerate(SIZES):
        rs = [r for r in results if r["job"]["city"] == size]
        if not rs:
            axs[0, col].axis("off")
            axs[1, col].axis("off")
            continue
        best = min(rs, key=lambda r: r["best_f"])
        scn = load_scenario(ROOT / "scenarios" / f"{size}.json")
        ax = axs[0, col]
        _top(ax, scn, Normalize(*cfg["sizes"][size]["height"]), labels=False, legend=False, straight=False)
        prof = axs[1, col]
        prof.set_facecolor(SURFACE)
        for k, p in enumerate(best["paths"]):
            p = np.array(p)
            c = DRONES[k % len(DRONES)]
            ax.plot(p[:, 0], p[:, 1], color=c, lw=2.0, zorder=7)
            ax.scatter(p[1:-1, 0], p[1:-1, 1], color=c, s=10, zorder=8, ec=SURFACE, lw=0.4)
            s = G.cumulative_length(p)
            prof.plot(s, p[:, 2], color=c, lw=1.8, label=f"drone {k + 1}")
        rep = best["report"]
        ax.set_title(f"{size}: F = {best['best_f']:.3f}, {'safe' if best['feasible'] else 'UNSAFE'}\n"
                     f"min clearance {rep['min_clearance_m']:.1f} m"
                     + ("" if rep["min_separation_m"] is None else f", min separation {rep['min_separation_m']:.1f} m"),
                     loc="left", fontsize=10, color=INK)
        prof.set_xlabel("distance flown (m)", color=INK2)
        prof.set_ylabel("height (m)", color=INK2)
        prof.grid(color=GRID, lw=0.6)
        prof.tick_params(colors=MUTED, labelsize=8.5)
        for sp in prof.spines.values():
            sp.set_color("#c3c2b7")
        prof.legend(frameon=False, fontsize=8, labelcolor=INK2, ncol=len(best["paths"]),
                    loc="lower left", bbox_to_anchor=(0.0, 1.0), borderaxespad=0.2)
    fig.suptitle(f"{alg.upper()}: best plan found in each main city (top view and height profile)",
                 x=0.01, ha="left", fontsize=12.5, color=INK, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, facecolor=SURFACE)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--alg", default="ga")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--cities", default="small,medium,large")
    ap.add_argument("--jobs", type=int, default=None)
    ap.add_argument("--replot", action="store_true", help="redraw the figures from results/quick/*.json")
    a = ap.parse_args()
    if a.replot:
        import json
        results = [json.loads(f.read_text()) for f in sorted((ROOT / "results" / "quick").glob(f"{a.alg}_*_s*.json"))]
        if a.alg == "dp":
            plot_dp_sweeps(results, ROOT / "figures" / "dp" / "convergence.png")
        else:
            plot_convergence(results, a.alg, ROOT / "figures" / a.alg / "convergence.png")
        plot_best_paths(results, a.alg, ROOT / "figures" / a.alg / "best_paths.png")
        return
    jobs = [{"alg": a.alg, "city": c, "seed": s, "params": {}, "budget": None}
            for c in a.cities.split(",") for s in range(a.seeds)]
    jobs.sort(key=lambda j: -SIZES.index(j["city"]))          # أطول التشغيلات أولًا
    t0 = time.perf_counter()
    results = run_jobs(jobs, a.jobs)
    print(f"{len(jobs)} runs in {time.perf_counter() - t0:.0f} s")
    for r in results:
        save_json(r, ROOT / "results" / "quick" / f"{a.alg}_{r['job']['city']}_s{r['seed']}.json")
    rows = summary_rows(results)
    with open(ROOT / "results" / "quick" / f"{a.alg}_summary.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        for row in rows:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items()})
    if a.alg == "dp":
        plot_dp_sweeps(results, ROOT / "figures" / "dp" / "convergence.png")
    else:
        plot_convergence(results, a.alg, ROOT / "figures" / a.alg / "convergence.png")
    plot_best_paths(results, a.alg, ROOT / "figures" / a.alg / "best_paths.png")
    for row in rows:
        print(f"{row['city']:<7} F mean {row['mean_F']:.3f} ± {row['std_F']:.3f}  best {row['best_F']:.3f}  "
              f"worst {row['worst_F']:.3f}  safe {100 * row['success_rate']:.0f} %  time {row['mean_time_s']:.0f} s  "
              f"(climb-over reference {row['reference_F']:.3f})")


if __name__ == "__main__":
    main()
