"""حساب الإحصاءات الوصفية واختبارات ويلكوكسون وجداول المقارنة للتجارب."""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .experiments import ROOT

ORDER = ["GA", "PSO", "ACO", "DP"]
COLORS = {"GA": "#2a78d6", "PSO": "#eb6834", "ACO": "#1baf7a", "DP": "#4a3aa7"}
SIZES = ["small", "medium", "large"]
UNSAFE = 100.0                     # حد للرسم في هذا الأرشيف، لا معيار عام للسلامة


# قراءة التشغيلات
def run_row(r: dict, part: str) -> dict:
    rep, v = r["report"], r.get("validator", {})
    drones = rep["drones"]
    job = r.get("job", {})
    terms = rep["terms"]
    return {
        "part": part, "algorithm": r["algorithm"], "city": r["scenario"], "size": r["scenario"].split("_")[0],
        "seed": r["seed"], "F": r["best_f"], "F_obj": rep["F_obj"], "feasible": r["feasible"],
        "valid": v.get("valid"), "agree": v.get("agrees_with_fitness"),
        "time_s": r["time_s"], "cpu_s": r.get("cpu_s"), "memory_mb": r.get("memory_mb"),
        "fe_used": r["fe_used"], "budget": r["budget"], "first_feasible_fe": r["first_feasible_fe"],
        "length_m": float(sum(d["length_m"] for d in drones)),
        "mission_time_s": rep["mission_time_s"],
        "energy_kj": float(sum(d["energy_kj"] for d in drones)),
        "battery_max_pct": float(max(d["battery_used_pct"] for d in drones)),
        "min_clearance_m": rep["min_clearance_m"],
        "max_hazard": float(max(d["max_hazard"] for d in drones)),
        "min_separation_m": rep["min_separation_m"],
        "J_T": float(np.mean(terms["J_T"])), "J_E": float(np.mean(terms["J_E"])),
        "J_H": float(np.mean(terms["J_H"])), "J_S": float(np.mean(terms["J_S"])),
        "grid_res": (job.get("world") or {}).get("grid_res", 10),
        "prune": (job.get("params") or {}).get("prune", r["params"].get("prune")),
    }


def load_runs(out: Path):
    """كل التشغيلات المحفوظة -> (DataFrame بصف لكل تشغيل، {(part, algorithm, city, seed): iter_history})."""
    rows, curves = [], {}
    for path in sorted((Path(out) / "runs").glob("*/*.json")):
        part = path.parent.name
        r = json.loads(path.read_text(encoding="utf-8"))
        row = run_row(r, part)
        row["file"] = path.name
        rows.append(row)
        if part in ("main", "random"):
            curves[(part, r["algorithm"], r["scenario"], r["seed"])] = r["iter_history"]
    df = pd.DataFrame(rows)
    if len(df):
        df["algorithm"] = pd.Categorical(df["algorithm"], ORDER, ordered=True)
    return df, curves


# الإحصاءات
def holm(p) -> np.ndarray:
    """قيم p معدلة بطريقة هولم-بونفيروني (تنازليًا، متزايدة، ومحدودة بـ 1). وتُستبعد قيم NaN."""
    p = np.asarray(p, float)
    out = np.full(len(p), np.nan)
    ok = np.flatnonzero(~np.isnan(p))
    m = len(ok)
    if m == 0:
        return out
    order = ok[np.argsort(p[ok], kind="stable")]
    running = 0.0
    for i, idx in enumerate(order):
        running = max(running, min(1.0, (m - i) * p[idx]))
        out[idx] = running
    return out


def a12(x, y) -> float:
    """مقياس Vargha-Delaney A12 للتصغير: P(X < Y) + 0.5 P(X = Y) عبر كل أزواج التشغيلات."""
    x, y = np.asarray(x, float)[:, None], np.asarray(y, float)[None, :]
    return float(((x < y).sum() + 0.5 * (x == y).sum()) / (x.size * y.size))


def wilcoxon_paired(x, y) -> dict:
    """اختبار ويلكوكسون للرتب ذات الإشارة ثنائي الطرف لـ x - y (تُحذف الأزواج المتساوية)."""
    from scipy.stats import wilcoxon
    d = np.asarray(x, float) - np.asarray(y, float)
    nz = d[d != 0]
    res = {"n": len(d), "n_nonzero": len(nz), "median_diff": float(np.median(d)) if len(d) else np.nan,
           "wins_first": int((d < 0).sum()), "wins_second": int((d > 0).sum()), "ties": int((d == 0).sum())}
    if len(nz) < 2:
        res.update(statistic=np.nan, p=1.0)                    # أقل من زوجين غير صفريين لا يظهران فرقًا
    else:
        t = wilcoxon(nz, zero_method="wilcox", alternative="two-sided")
        res.update(statistic=float(t.statistic), p=float(t.pvalue))
    return res


def verdict(first, second, p_holm, median_diff, alpha):
    if np.isnan(p_holm) or p_holm >= alpha:
        return "no significant difference"
    return f"{first} better" if median_diff < 0 else f"{second} better"


def summarize(df: pd.DataFrame, by=("size", "algorithm")) -> pd.DataFrame:
    """المتوسط والانحراف المعياري (n - 1) والوسيط والأفضل والأسوأ لـ F، ونسبة النجاح والكلف، لكل مجموعة."""
    g = df.groupby(list(by), observed=True)
    out = g.agg(runs=("F", "size"), mean_F=("F", "mean"), std_F=("F", "std"), median_F=("F", "median"),
                best_F=("F", "min"), worst_F=("F", "max"),
                success_rate=("valid", "mean"), agree_rate=("agree", "mean"),
                mean_time_s=("time_s", "mean"), std_time_s=("time_s", "std"), mean_cpu_s=("cpu_s", "mean"),
                std_cpu_s=("cpu_s", "std"),
                mean_memory_mb=("memory_mb", "mean"), max_memory_mb=("memory_mb", "max"),
                mean_first_safe_fe=("first_feasible_fe", "mean"),
                mean_length_m=("length_m", "mean"), mean_mission_time_s=("mission_time_s", "mean"),
                mean_energy_kj=("energy_kj", "mean"), min_clearance_m=("min_clearance_m", "min"),
                max_hazard=("max_hazard", "max"), min_separation_m=("min_separation_m", "min"),
                budget=("budget", "first")).reset_index()
    out["std_F"] = out["std_F"].fillna(0.0)                     # DP: تشغيل واحد
    out["std_time_s"] = out["std_time_s"].fillna(0.0)
    out["std_cpu_s"] = out["std_cpu_s"].fillna(0.0)
    if "size" in out and set(out["size"]) <= set(SIZES):                 # صغيرة ومتوسطة وكبيرة (لا ترتيب أبجدي)
        out = out.iloc[np.lexsort((out["algorithm"].cat.codes if hasattr(out["algorithm"], "cat") else
                                   out["algorithm"].map(ORDER.index), out["size"].map(SIZES.index)))]
        out = out.reset_index(drop=True)
    return out


def pairwise(df: pd.DataFrame, block: str, alpha: float = 0.05) -> pd.DataFrame:
    """ويلكوكسون لكل زوج من الخوارزميات داخل كل حجم، مقرونًا بـ `block` ('seed' أو 'city').
    والخوارزمية ذات التشغيل الواحد لكل حجم (DP في المدينة الأساسية) تُقرن بكل كتلة."""
    rows = []
    for size in [s for s in SIZES if s in set(df["size"])]:
        d = df[df["size"] == size]
        algs = [a for a in ORDER if a in set(d["algorithm"])]
        piv = d.pivot_table(index=block, columns="algorithm", values="F", aggfunc="first", observed=True)
        fam = []
        for A, B in itertools.combinations(algs, 2):
            xa, xb = piv[A], piv[B]
            if xa.notna().sum() == 1:                           # حتمية بتشغيل واحد: تُقرن بكل كتلة
                xa = pd.Series(xa.dropna().iloc[0], index=piv.index)
            if xb.notna().sum() == 1:
                xb = pd.Series(xb.dropna().iloc[0], index=piv.index)
            both = xa.notna() & xb.notna()
            t = wilcoxon_paired(xa[both].values, xb[both].values)
            fam.append({"size": size, "first": A, "second": B, **t,
                        "A12": a12(d.loc[d["algorithm"] == A, "F"], d.loc[d["algorithm"] == B, "F"])})
        adj = holm([r["p"] for r in fam])
        for r, ph in zip(fam, adj):
            r["p_holm"] = ph
            r["verdict"] = verdict(r["first"], r["second"], ph, r["median_diff"], alpha)
        rows += fam
    return pd.DataFrame(rows)


def random_summary(df: pd.DataFrame) -> pd.DataFrame:
    """لكل حجم وخوارزمية عبر المدن العشوائية: النجاح، ومتوسط الرتبة (1 = أفضل F في تلك المدينة)،
    والفرق عن DP (F / F_DP - 1، بالنسبة المئوية)، ووسيط F."""
    rows = []
    for size in [s for s in SIZES if s in set(df["size"])]:
        d = df[df["size"] == size]
        piv = d.pivot_table(index="city", columns="algorithm", values="F", aggfunc="mean", observed=True)
        ranks = piv.rank(axis=1, method="average")
        for alg in [a for a in ORDER if a in piv.columns]:
            dd = d[d["algorithm"] == alg]
            gap = (piv[alg] / piv["DP"] - 1) * 100 if "DP" in piv else pd.Series(np.nan, index=piv.index)
            rows.append({"size": size, "algorithm": alg, "cities": int(piv[alg].notna().sum()),
                         "safe": int(dd["valid"].sum()), "mean_rank": float(ranks[alg].mean()),
                         "wins": int((ranks[alg] == 1).sum()),
                         "median_F": float(dd["F"].median()), "median_gap_to_dp_pct": float(gap.median()),
                         "mean_gap_to_dp_pct_safe": float(gap[piv[alg] < UNSAFE].mean()),
                         "mean_time_s": float(dd["time_s"].mean()), "mean_cpu_s": float(dd["cpu_s"].mean()),
                         "mean_memory_mb": float(dd["memory_mb"].mean())})
    return pd.DataFrame(rows)


def friedman(df: pd.DataFrame) -> pd.DataFrame:
    from scipy.stats import friedmanchisquare
    rows = []
    for size in [s for s in SIZES if s in set(df["size"])]:
        piv = df[df["size"] == size].pivot_table(index="city", columns="algorithm", values="F",
                                                  aggfunc="mean", observed=True).dropna()
        cols = [a for a in ORDER if a in piv.columns]
        if len(piv) >= 2 and len(cols) >= 3:
            t = friedmanchisquare(*[piv[a].values for a in cols])
            rows.append({"size": size, "cities": len(piv), "statistic": float(t.statistic), "p": float(t.pvalue)})
        else:
            rows.append({"size": size, "cities": len(piv), "statistic": np.nan, "p": np.nan})
    return pd.DataFrame(rows)


# الحساسية
def _parse_value(v: str):
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return {"True": True, "False": False, "None": None, "": None}.get(v, v)


def sensitivity(tuning=ROOT / "results" / "tuning", dp: pd.DataFrame | None = None) -> pd.DataFrame:
    """صف لكل (دراسة، معامل، قيمة): متوسط F عبر البذور المقرونة، والتغير عن القيمة الافتراضية،
    وعدد البذور التي كانت فيها القيمة أسوأ من الافتراضية. و'spread_pct' (لكل معامل) هو
    (أكبر متوسط F - أصغر متوسط F) / متوسط F الافتراضي: مقدار أهمية هذا المعامل."""
    rows = []
    for runs in sorted(Path(tuning).glob("*_runs.csv")):
        alg, city = runs.stem.replace("_runs", "").split("_", 1)
        d = pd.read_csv(runs, dtype={"value": str}, keep_default_na=False)
        saved = runs.with_name(f"{alg}_{city}_defaults.json")
        defaults = json.loads(saved.read_text()) if saved.exists() else {}
        budget = defaults.pop("_budget", None)
        base = d[d["parameter"] == "default"].set_index("seed")["best_f"]
        study = f"{alg.upper()} {city}" + ("" if budget is None else f" ({budget:,} FE)")
        for name in [p for p in dict.fromkeys(d["parameter"]) if p != "default"]:
            vals = [(_parse_value(v), g.set_index("seed")["best_f"]) for v, g in d[d["parameter"] == name].groupby(
                "value", sort=False)]
            dv = defaults.get(name, "default")
            vals.append((dv, base))
            if all(v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)) for v, _ in vals):
                vals.sort(key=lambda t: (t[0] is None, t[0] or 0))   # الأرقام تصاعديًا، وNone في الأخير
            for v, F in vals:
                paired = F.reindex(base.index)
                rows.append({"study": study, "algorithm": alg.upper(), "city": city, "parameter": name,
                             "value": str(v), "is_default": v == dv, "runs": int(F.size),
                             "mean_F": float(F.mean()), "std_F": float(F.std(ddof=1)) if F.size > 1 else 0.0,
                             "change_pct": float((F.mean() / base.mean() - 1) * 100),
                             "worse_seeds": int((paired > base).sum()), "seeds": int(paired.notna().sum())})
    if dp is not None and len(dp):
        dp = dp.assign(prune=dp["prune"].astype(bool))
        for city, d in dp.groupby("city"):
            F = {(int(g), bool(pr)): float(r["F"].iloc[0]) for (g, pr), r in d.groupby(["grid_res", "prune"])}
            T = {(int(g), bool(pr)): float(r["time_s"].iloc[0]) for (g, pr), r in d.groupby(["grid_res", "prune"])}
            M = {(int(g), bool(pr)): r["memory_mb"].iloc[0] for (g, pr), r in d.groupby(["grid_res", "prune"])}
            studies = [("grid cell size (m), pruned", [(g, True) for g in sorted({g for g, _ in F}, reverse=True)],
                        (10, True), lambda k: f"{k[0]}"),
                       ("grid cell size (m), not pruned", [(g, False) for g in sorted({g for g, _ in F}, reverse=True)],
                        (10, False), lambda k: f"{k[0]}"),
                       ("line-of-sight pruning (10 m grid)", [(10, False), (10, True)], (10, True),
                        lambda k: "on" if k[1] else "off")]
            for name, keys, default, label in studies:
                keys = [k for k in keys if k in F]
                if default not in F or len(keys) < 2:
                    continue
                for k in keys:
                    rows.append({"study": f"DP {city}", "algorithm": "DP", "city": city, "parameter": name,
                                 "value": label(k), "is_default": k == default, "runs": 1, "mean_F": F[k],
                                 "std_F": 0.0, "change_pct": (F[k] / F[default] - 1) * 100,
                                 "worse_seeds": int(F[k] > F[default]), "seeds": 1,
                                 "time_s": T[k], "memory_mb": M[k]})
    out = pd.DataFrame(rows)
    if len(out):                                          # GA وPSO وACO وDP؛ الصغيرة قبل الكبيرة؛ ترتيب مستقر داخلها
        key = out["algorithm"].map(ORDER.index) * 10 + out["city"].map(lambda c: SIZES.index(c.split("_")[0]))
        out = out.iloc[np.argsort(key.values, kind="stable")].reset_index(drop=True)
        sp = out.groupby(["study", "parameter"])["mean_F"].agg(lambda s: s.max() - s.min())
        dm = out[out["is_default"]].groupby(["study", "parameter"])["mean_F"].first()
        out["spread_pct"] = [100 * sp[(s, p)] / dm.get((s, p), np.nan) for s, p in zip(out["study"], out["parameter"])]
    return out


# الجداول (Markdown)
def _fmt(x, nd=3):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    if isinstance(x, (float, np.floating)):
        return f"{x:.{nd}f}"
    return str(x)


def _p(p):
    if p is None or np.isnan(p):
        return "–"
    return f"{p:.1e}" if p < 1e-3 else f"{p:.3f}"


def markdown_tables(summary, wil, rsum, rtests, rwil, sens, timing=None) -> str:
    L = ["# Final experiments: tables", "",
          "Generated by `python -m simulation.experiments --stats` from `simulation/results/experiments/runs/`.",
          "Memory is the increase in peak RSS above the process baseline, in MiB (not total RAM).", ""]
    if len(summary):
        L += ["## Main cities: 20 seeds per algorithm (DP once, deterministic)", ""]
        for size in [s for s in SIZES if s in set(summary["size"])]:
            s = summary[summary["size"] == size]
            best = s["mean_F"].min()
            L += [f"### {size} city (budget {int(s['budget'].iloc[0]):,} evaluations)", "",
                  "| Algorithm | Runs | Mean F ± std | Median | Best | Worst | Safe | CPU time (s) | Extra peak RSS (MiB) "
                  "| First safe plan (FE) | Path length (m) | Mission time (s) | Min clearance (m) | Max hazard "
                  "| Min separation (m) |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
            for _, r in s.iterrows():
                mean = f"{r['mean_F']:.3f} ± {r['std_F']:.3f}"
                if np.isclose(r["mean_F"], best):
                    mean = f"**{mean}**"
                L.append(f"| {r['algorithm']} | {r['runs']} | {mean} | {r['median_F']:.3f} | {r['best_F']:.3f} | "
                         f"{r['worst_F']:.3f} | {100 * r['success_rate']:.0f} % | {r['mean_cpu_s']:.1f} | "
                         f"{_fmt(r['mean_memory_mb'], 0)} | {_fmt(r['mean_first_safe_fe'], 0)} | "
                         f"{r['mean_length_m']:.0f} | {r['mean_mission_time_s']:.1f} | {r['min_clearance_m']:.2f} | "
                         f"{r['max_hazard']:.3f} | {_fmt(r['min_separation_m'], 2)} |")
            L.append("")
    if timing is not None and len(timing):
        L += ["## Time and memory, measured in one sitting (seeds 0 and 1 of every algorithm, run again together)", "",
              "| City | Algorithm | Runs | CPU time (s) | Wall time (s) | Extra peak RSS (MiB) |", "|---|---|---|---|---|---|"]
        for _, r in timing.iterrows():
            L.append(f"| {r['size']} | {r['algorithm']} | {r['runs']} | {r['mean_cpu_s']:.1f} ± {r['std_cpu_s']:.1f} | "
                     f"{r['mean_time_s']:.1f} | {_fmt(r['mean_memory_mb'], 0)} |")
        L.append("")
    if len(wil):
        L += ["## Wilcoxon signed-rank tests, main cities (paired by seed, Holm-corrected per city)", "",
              "| City | Pair | Wins (first / second / ties) | Median ΔF | A12 | p | p (Holm) | Verdict |",
              "|---|---|---|---|---|---|---|---|"]
        for _, r in wil.iterrows():
            L.append(f"| {r['size']} | {r['first']} vs {r['second']} | {r['wins_first']} / {r['wins_second']} / "
                     f"{r['ties']} | {r['median_diff']:+.4f} | {r['A12']:.2f} | {_p(r['p'])} | {_p(r['p_holm'])} | "
                     f"{r['verdict']} |")
        L.append("")
    if len(rsum):
        L += ["## Random cities: one run per city (seed 0), 10 cities per size", "",
              "| Size | Algorithm | Safe | Mean rank | Best in | Median F | Median gap to DP | CPU time (s) |",
              "|---|---|---|---|---|---|---|---|"]
        for _, r in rsum.iterrows():
            L.append(f"| {r['size']} | {r['algorithm']} | {r['safe']} / {r['cities']} | {r['mean_rank']:.2f} | "
                     f"{r['wins']} | {r['median_F']:.3f} | {r['median_gap_to_dp_pct']:+.1f} % | "
                     f"{r['mean_cpu_s']:.1f} |")
        L.append("")
        if len(rtests):
            L += ["Friedman test (all four algorithms, blocks = cities): " +
                  "; ".join(f"{r['size']} p = {_p(r['p'])}" for _, r in rtests.iterrows()), ""]
        if len(rwil):
            L += ["| Size | Pair | Wins (first / second / ties) | Median ΔF | p | p (Holm) | Verdict |",
                  "|---|---|---|---|---|---|---|"]
            for _, r in rwil.iterrows():
                L.append(f"| {r['size']} | {r['first']} vs {r['second']} | {r['wins_first']} / {r['wins_second']} / "
                         f"{r['ties']} | {r['median_diff']:+.4f} | {_p(r['p'])} | {_p(r['p_holm'])} | "
                         f"{r['verdict']} |")
            L.append("")
    if len(sens):
        L += ["## Parameter sensitivity (one factor at a time; spread = (max − min mean F) / default mean F)", "",
              "| Study | Parameter | Values (mean F) | Spread |", "|---|---|---|---|"]
        for (study, par), g in sens.groupby(["study", "parameter"], sort=False):
            vals = ", ".join(("**" if d else "") + f"{v}: {m:.3f}" + ("**" if d else "")
                             for v, m, d in zip(g["value"], g["mean_F"], g["is_default"]))
            L.append(f"| {study} | {par} | {vals} | {g['spread_pct'].iloc[0]:.1f} % |")
        L.append("")
    return "\n".join(L)


# كل شيء
def build_all(out: Path, cfg: dict | None = None, figures: Path | None = None) -> dict:
    out = Path(out)
    alpha = (cfg or {}).get("alpha", 0.05)
    df, curves = load_runs(out)
    if not len(df):
        print("no saved runs in", out / "runs")
        return {}
    df.to_csv(out / "runs.csv", index=False)
    main = df[df["part"] == "main"]
    rnd = df[df["part"] == "random"]
    dps = df[df["part"] == "dp_sensitivity"]
    summary = summarize(main) if len(main) else pd.DataFrame()
    timing = df[df["part"] == "timing"]
    tsum = summarize(timing) if len(timing) else pd.DataFrame()
    wil = pairwise(main, "seed", alpha) if len(main) else pd.DataFrame()
    rsum = random_summary(rnd) if len(rnd) else pd.DataFrame()
    rtests = friedman(rnd) if len(rnd) else pd.DataFrame()
    rwil = pairwise(rnd, "city", alpha) if len(rnd) else pd.DataFrame()
    sens = sensitivity(dp=dps)
    for name, t in (("main_summary", summary), ("main_wilcoxon", wil), ("random_summary", rsum),
                    ("random_friedman", rtests), ("random_wilcoxon", rwil), ("sensitivity", sens),
                    ("timing_summary", tsum)):
        if len(t):
            t.to_csv(out / f"{name}.csv", index=False, float_format="%.6g")
    (out / "tables.md").write_text(markdown_tables(summary, wil, rsum, rtests, rwil, sens, tsum), encoding="utf-8")
    checks = {"runs": len(df), "unsafe_by_validator": int((df["valid"] == False).sum()),   # noqa: E712
              "validator_disagrees_with_F": int((df["agree"] == False).sum())}           # noqa: E712
    (out / "checks.json").write_text(json.dumps(checks, indent=1), encoding="utf-8")
    if figures is not None:
        from . import figures as figs
        figs.draw_all(df, curves, summary, wil, rsum, sens, Path(figures), runs_dir=out / "runs",
                      timing=tsum if len(tsum) else None)
    print(f"{checks['runs']} runs: {checks['unsafe_by_validator']} unsafe, "
          f"{checks['validator_disagrees_with_F']} validator disagreements; tables in {out / 'tables.md'}")
    return {"runs": df, "summary": summary, "wilcoxon": wil, "random_summary": rsum, "random_friedman": rtests,
            "random_wilcoxon": rwil, "sensitivity": sens, "timing": tsum, "checks": checks}
