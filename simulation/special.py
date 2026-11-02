"""بناء الحالات الخاصة العشر وتشغيلها: مدينة خالية، وحريق على الخط المستقيم، وشارع ضيق، وهدف خلف برج مرتفع،
ومتاهة، وهدف محاط بالأبراج، وهدف قرب الحريق، ومساران متقاطعان، وبطارية صغيرة، وبطارية صغيرة جدًا."""
from __future__ import annotations

import argparse
import copy
import csv
import json
import time
from pathlib import Path

import numpy as np

from .scenarios import Building, Fire, Mission, Scenario, load_scenario

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "scenarios" / "special"


# بناء الحالات
def _base(name: str) -> Scenario:
    scn = copy.deepcopy(load_scenario(ROOT / "scenarios" / "small.json"))      # إعدادات الحجم الصغير
    scn.name, scn.seed, scn.seed_used = f"special_{name}", 0, 0
    scn.buildings, scn.fires, scn.missions = [], [], []
    return scn


def _finish(scn: Scenario, missions, buildings=(), fires=()):
    scn.buildings = [Building(i, *map(float, b)) for i, b in enumerate(buildings)]
    scn.fires = list(fires)
    scn.missions = [Mission(k, f, list(map(float, S)), list(map(float, G))) for k, (S, G, f) in enumerate(missions)]
    scn.staging = {"edge": "W", "points": [list(map(float, S)) for S, _, _ in missions]}
    K, N = len(missions), scn.problem["n_waypoints"]
    scn.problem = dict(scn.problem, n_drones=K, n_variables=3 * K * N)
    return scn


def _fire(i, b, face, c, R=15.0, I=1.0):
    normal = {"E": [1.0, 0.0, 0.0], "W": [-1.0, 0.0, 0.0], "N": [0.0, 1.0, 0.0], "S": [0.0, -1.0, 0.0]}[face]
    return Fire(id=i, building=b, face=face, c=list(map(float, c)), normal=normal, R=R, I=I, Hf=80.0)


def build_cases() -> dict:
    """كل الحالات الخاصة: الاسم -> (Scenario، التوقع)."""
    cases = {}

    s = _base("empty_city")
    cases["empty_city"] = (_finish(s, [((30, 150, 10), (270, 150, 60), -1)]), {
        "expect": "feasible", "known_F": 1.5,
        "what": "no towers and no fires: the straight line is optimal and scores exactly 1.5"})

    tower = (130, 100, 170, 200, 120)
    s = _base("behind_tall_tower")
    cases["behind_tall_tower"] = (_finish(s, [((30, 150, 10), (270, 150, 40), -1)], [tower]), {
        "expect": "feasible", "route": "around",
        "what": "a 120 m tower hides the target: flying round it is cheaper than climbing 120 m over it"})

    s = _base("narrow_street")
    street = [(100, 85, 200, 140, 140), (100, 165, 200, 220, 140)]          # شارع عرضه 25 م، y من 140 إلى 165
    cases["narrow_street"] = (_finish(s, [((30, 100, 10), (270, 205, 30), -1)], street), {
        "expect": "feasible",
        "what": "two long 140 m towers with a 25 m street between them (15 m after the 5 m margins)"})

    s = _base("fire_on_line")
    b = (140, 180, 180, 230, 100)
    f = _fire(0, 0, "S", (160, 180, 60))
    cases["fire_on_line"] = (_finish(s, [((30, 172, 10), (280, 172, 110), -1)], [b], [f]), {
        "expect": "feasible",
        "what": "the straight line from S to G passes through the fire core; the plan must go round it"})

    s = _base("target_near_fire")
    b = (180, 120, 230, 180, 110)
    f = _fire(0, 0, "W", (180, 150, 70))
    G = (180 - 1.1 * 15, 150, 65)
    cases["target_near_fire"] = (_finish(s, [((30, 150, 10), G, 0)], [b], [f]), {
        "expect": "feasible",
        "what": "release point only 1.1 R from the burning facade (normally 1.6 R): reach versus safety"})

    s = _base("crossing_drones")
    cases["crossing_drones"] = (_finish(s, [((30, 135, 10), (270, 215, 60), -1),
                                            ((30, 165, 10), (270, 85, 60), -1)]), {
        "expect": "feasible", "dp": "may_fail_separation",
        "what": "two drones whose straight lines cross at the same moment; DP plans them separately"})

    # المتاهة: 4 × 4 كتل بطول 45 م، وشوارع 25 م، أعلى من السقف؛ وبعض الشوارع مغلقة بجدران
    blocks = [(x, y, x + 45, y + 45, 170) for x in (20, 90, 160, 230) for y in (20, 90, 160, 230)]
    walls = [(65, 90, 90, 135, 170),     # يغلق الشارع بين الكتلتين (0,1) و(1,1)
             (135, 160, 160, 205, 170),  # يغلق الشارع بين الكتلتين (1,2) و(2,2)
             (160, 65, 205, 90, 170),    # يغلق الشارع غرب الهدف
             (205, 90, 230, 135, 170),   # يغلق الشارع شمال الهدف
             (205, 160, 230, 205, 170),  # يغلق الشارع بين الكتلتين (2,2) و(3,2)
             (90, 205, 135, 230, 170)]   # يغلق الشارع بين الكتلتين (1,2) و(1,3)
    s = _base("maze")
    cases["maze"] = (_finish(s, [((8, 147.5, 10), (217.5, 77.5, 40), -1)], blocks + walls), {
        "expect": "feasible",
        "what": "towers taller than the flight ceiling with walled-off streets: the drone must find its way"})

    s = _base("enclosed_target")
    G = (150, 150, 60)
    ring = [(100, 100, 200, 120, 170), (100, 180, 200, 200, 170), (100, 120, 120, 180, 170), (180, 120, 200, 180, 170)]
    cases["enclosed_target"] = (_finish(s, [((30, 150, 10), G, -1)], ring), {
        "expect": "infeasible",
        "what": "the target is inside a courtyard of towers taller than the ceiling: no safe plan exists"})

    s = _base("small_battery")
    s.drone = dict(s.drone, battery_kj=12.5)                       # 80% متاحة = 10 kJ
    cases["small_battery"] = (_finish(s, [((30, 150, 10), (270, 150, 40), -1)], [tower]), {
        "expect": "feasible", "route": "around",
        "what": "10 kJ usable: enough to go round the tower (about 8.7 kJ), not to climb over it (about 20 kJ)"})

    s = _base("tiny_battery")
    s.drone = dict(s.drone, battery_kj=6.25)                       # 80% متاحة = 5 kJ
    cases["tiny_battery"] = (_finish(s, [((30, 150, 10), (270, 150, 40), -1)], [tower]), {
        "expect": "infeasible",
        "what": "5 kJ usable, less than even the straight line needs (about 7.8 kJ): the mission is impossible"})
    return cases


def build(out: Path = OUT) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    index = {}
    for name, (scn, exp) in build_cases().items():
        scn.save(out / f"{scn.name}.json")
        index[scn.name] = {"case": name, **exp}
    (out / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    return index


def load_index() -> dict:
    return json.loads((OUT / "index.json").read_text(encoding="utf-8"))


# التشغيل
def route_over_or_around(scn, path) -> str:
    """لحالات البرج المرتفع: هل عبر المسار مسقط البرج (فوقه) أم لا (حوله)؟"""
    b = scn.buildings[0]
    P = np.array(path)
    t = np.linspace(0, 1, 400)[:, None]
    pts = np.vstack([a + t * (c - a) for a, c in zip(P[:-1], P[1:])])
    inside = (pts[:, 0] >= b.x0) & (pts[:, 0] <= b.x1) & (pts[:, 1] >= b.y0) & (pts[:, 1] <= b.y1)
    return "over" if inside.any() else "around"


def outcome_of(exp: dict, algorithm: str, best_f: float, valid: bool, route: str = "", no_path=()) -> str:
    """الحكم على تشغيل واحد لحالة واحدة.

    'correct'  الخطة صالحة وتوجد خطة صالحة (مع F المعروفة والمسار المتوقع إذا كانا
               للحالة)، أو لا توجد خطة صالحة وتبلّغ الخوارزمية عن خطة غير آمنة
               (F > 100) بدل الادعاء
    'missed'   توجد خطة صالحة لكن الخوارزمية لم تجدها (ضعف في الخوارزمية،
               مثل عجز DP عن تنسيق المسيّرات، وتيه GA / PSO في المتاهة)
    'error'    قبول خطة في حالة لا خطة صالحة لها، أو عدم تصريح DP بعدم وجود مسار
               لهدف لا يمكن بلوغه (خطأ برمجي)
    """
    exists = exp["expect"] == "feasible"
    if valid:
        outcome = "correct" if exists else "error"
    else:
        outcome = "missed" if exists else ("correct" if best_f > 100 else "error")
    if outcome == "correct" and "known_F" in exp:                       # إجابة معروفة: F = 1.5
        tol = 1e-9 if algorithm in ("DP", "ACO") else 0.01               # طرق الشبكة تبلغها بالضبط
        outcome = "correct" if best_f - exp["known_F"] <= tol else "missed"
    if outcome == "correct" and "route" in exp and route != exp["route"]:
        outcome = "missed"
    if exp["case"] == "enclosed_target" and algorithm == "DP" and list(no_path) != [0]:
        outcome = "error"                                                # يجب أن تقول DP: لا يوجد مسار
    return outcome


def run(seeds: int = 3, jobs: int | None = None):
    from .experiments import run_jobs
    from .validator import check_plan

    index = load_index()
    algs = ["ga", "pso", "aco", "dp"]
    joblist = [{"alg": a, "city": name, "seed": s, "params": {}, "budget": None}
               for name in index for a in algs for s in (range(seeds) if a != "dp" else [0])]
    t0 = time.perf_counter()
    results = run_jobs(joblist, jobs)
    print(f"{len(joblist)} runs in {time.perf_counter() - t0:.0f} s")

    rows, keep = [], []
    for r in results:
        name = r["scenario"]
        scn = load_scenario(OUT / f"{name}.json")
        exp = index[name]
        v = check_plan(scn, r["paths"])
        row = {"case": exp["case"], "algorithm": r["algorithm"], "seed": r["seed"], "F": r["best_f"],
               "fitness_feasible": r["feasible"], "validator_valid": v["valid"],
               "agree": r["feasible"] == v["valid"], "expected": exp["expect"],
               "min_clearance_m": v["min_clearance_m"], "max_hazard": v["max_hazard"],
               "min_separation_m": v["min_separation_m"],
               "energy_kj": sum(d.get("energy_kj", 0.0) for d in v["drones"]),
               "route": route_over_or_around(scn, r["paths"][0]) if "route" in exp else "",
               "no_path": r["extra"].get("no_path", ""), "problems": " | ".join(v["problems"])}
        row["outcome"] = outcome_of(exp, r["algorithm"], r["best_f"], v["valid"], row["route"], row["no_path"])
        rows.append(row)
        keep.append({k: r[k] for k in ("algorithm", "scenario", "seed", "best_f", "feasible", "paths", "extra")})

    out = ROOT / "results" / "special"
    out.mkdir(parents=True, exist_ok=True)
    (out / "runs.json").write_text(json.dumps(keep), encoding="utf-8")
    with open(out / "summary.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        for row in sorted(rows, key=lambda r: (r["case"], r["algorithm"], r["seed"])):
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items()})
    plot_cases(keep, index)
    return rows


# الصور
def plot_cases(runs, index):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize
    from matplotlib.patches import Circle, Rectangle
    from .figures import FIRE, GRID, INK, INK2, MUTED, SURFACE, TOWERS

    colors = {"GA": "#2a78d6", "PSO": "#eb6834", "ACO": "#1baf7a", "DP": "#4a3aa7"}
    names = list(index)
    ncol = 5
    nrow = int(np.ceil(len(names) / ncol))
    fig, axs = plt.subplots(nrow, ncol, figsize=(4.1 * ncol, 4.5 * nrow), facecolor=SURFACE, squeeze=False)
    norm = Normalize(30, 170)
    for ax, name in zip(axs.ravel(), names):
        scn = load_scenario(OUT / f"{name}.json")
        ax.set_facecolor(SURFACE)
        ax.set_xlim(0, 300)
        ax.set_ylim(0, 300)
        ax.set_aspect("equal")
        ax.grid(color=GRID, lw=0.5)
        ax.set_axisbelow(True)                                           # خطوط الشبكة تحت الأبراج
        ax.tick_params(colors=MUTED, labelsize=7)
        d = scn.world["d_safe"]
        for b in scn.buildings:
            ax.add_patch(Rectangle((b.x0 - d, b.y0 - d), b.x1 - b.x0 + 2 * d, b.y1 - b.y0 + 2 * d, fill=False,
                                   ls=(0, (2, 2)), lw=0.5, ec=MUTED))
            ax.add_patch(Rectangle((b.x0, b.y0), b.x1 - b.x0, b.y1 - b.y0, fc=TOWERS(norm(b.h)), ec=SURFACE, lw=0.6))
        for f in scn.fires:
            ax.add_patch(Circle(f.c[:2], f.R, fc=FIRE, alpha=0.18, ec=FIRE, lw=0.8))
            ax.scatter(*f.c[:2], marker="*", s=90, color=FIRE, zorder=6)
        for alg, col in colors.items():
            rs = [r for r in runs if r["scenario"] == name and r["algorithm"] == alg]
            if not rs:
                continue
            best = min(rs, key=lambda r: r["best_f"])
            for p in best["paths"]:
                p = np.array(p)
                ax.plot(p[:, 0], p[:, 1], color=col, lw=1.6, alpha=0.9, zorder=5,
                        label=f"{alg} {best['best_f']:.2f}{'' if best['feasible'] else ' unsafe'}")
        for m in scn.missions:
            ax.scatter(*m.S[:2], marker="^", s=40, color=INK, zorder=7)
            ax.scatter(*m.G[:2], marker="X", s=50, color=INK, zorder=7)
        h, lab = ax.get_legend_handles_labels()
        uniq = dict(zip(lab, h))
        leg = ax.legend(uniq.values(), uniq.keys(), fontsize=6.5, loc="upper left", labelcolor=INK2,
                        frameon=True, facecolor=SURFACE, edgecolor=GRID, framealpha=0.92)
        leg.set_zorder(10)
        ax.set_title(f"{index[name]['case']}  (expect: {index[name]['expect']})", loc="left", fontsize=9.5, color=INK)
    for ax in axs.ravel()[len(names):]:
        ax.axis("off")
    fig.suptitle("Special cases: best plan of each algorithm (top view; ▲ take-off, ✕ target; F after the name)",
                 x=0.01, ha="left", fontsize=12, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    out = ROOT / "figures" / "special" / "cases.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, facecolor=SURFACE)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--jobs", type=int, default=None)
    ap.add_argument("--plot", action="store_true", help="redraw the figure from results/special/runs.json")
    a = ap.parse_args()
    if a.plot:
        plot_cases(json.loads((ROOT / "results" / "special" / "runs.json").read_text(encoding="utf-8")), load_index())
        return
    if a.build or not a.run:
        idx = build()
        print(f"{len(idx)} special cases written to scenarios/special/")
    if a.run:
        rows = run(a.seeds, a.jobs)
        for r in sorted(rows, key=lambda r: (r["case"], r["algorithm"], r["seed"])):
            print(f"{r['outcome']:<8}{r['case']:<18}{r['algorithm']:<4} s{r['seed']}  "
                  f"F {r['F']:9.3f}  valid {str(r['validator_valid']):<5}  agree {str(r['agree']):<5} "
                  f"{r['route']:<7}{r['problems'][:80]}")
        n = len(rows)
        print(f"\n{n} runs: {sum(r['outcome'] == 'correct' for r in rows)} correct, "
              f"{sum(r['outcome'] == 'missed' for r in rows)} missed (a valid plan exists but was not found), "
              f"{sum(r['outcome'] == 'error' for r in rows)} errors; "
              f"{sum(r['agree'] for r in rows)} / {n} validator verdicts agree with F")


if __name__ == "__main__":
    main()
