"""تدقيق حسابي مستقل للجداول والملخصات الرقمية المعروضة في الواجهة."""
from __future__ import annotations

import csv
import itertools
import json
import math
import statistics as st
from collections import defaultdict
from pathlib import Path

from scipy.stats import wilcoxon

ROOT = Path(__file__).resolve().parent
EXP = ROOT / "results/experiments"
ALGS = ("GA", "PSO", "ACO", "DP")


def csv_rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def present(values):
    return [float(value) for value in values if value is not None and math.isfinite(float(value))]


def mean(values):
    values = present(values)
    return st.mean(values) if values else None


def std(values):
    values = present(values)
    return st.stdev(values) if len(values) > 1 else 0.


def summary(runs):
    values = [r["best_f"] for r in runs]
    report = {
        "runs": len(runs), "mean_F": st.mean(values), "std_F": std(values), "median_F": st.median(values),
        "best_F": min(values), "worst_F": max(values), "budget": runs[0]["budget"],
        "success_rate": st.mean(r["validator"]["valid"] for r in runs),
        "agree_rate": st.mean(r["validator"]["valid"] == r["feasible"] for r in runs),
        "mean_first_safe_fe": mean(r["first_feasible_fe"] for r in runs),
        "mean_length_m": mean(sum(d["length_m"] for d in r["report"]["drones"]) for r in runs),
        "mean_mission_time_s": mean(r["report"]["mission_time_s"] for r in runs),
        "mean_energy_kj": mean(sum(d["energy_kj"] for d in r["report"]["drones"]) for r in runs),
        "min_clearance_m": min(r["report"]["min_clearance_m"] for r in runs),
        "max_hazard": max(d["max_hazard"] for r in runs for d in r["report"]["drones"]),
    }
    separation = present(r["report"]["min_separation_m"] for r in runs)
    report["min_separation_m"] = min(separation) if separation else None
    for key, label in [("time_s", "time_s"), ("cpu_s", "cpu_s"), ("memory_mb", "memory_mb")]:
        values = [r.get(key) for r in runs]
        report[f"mean_{label}"] = mean(values)
        if key != "memory_mb":
            report[f"std_{label}"] = std(values)
        else:
            report["max_memory_mb"] = max(present(values), default=None)
    return report


def audit():
    output = {"checks": 0, "tables": {}, "failures": []}

    def compare(table, identity, column, saved, expected):
        output["checks"] += 1
        if isinstance(expected, bool):
            ok = str(saved).lower() == str(expected).lower()
        elif expected is None or isinstance(expected, float) and not math.isfinite(expected):
            ok = saved in ("", None, "nan", "inf")
        else:
            try:
                ok = math.isclose(float(saved), float(expected), rel_tol=6e-6, abs_tol=1e-10)
            except (ValueError, TypeError):
                ok = saved == expected
        if not ok:
            output["failures"].append({
                "table": table, "row": identity, "column": column, "saved": saved, "expected": expected,
            })

    # قراءة تشغيلات المصدر مرة واحدة، مفهرسة بمجموعة التجربة والملف.
    groups = defaultdict(list)
    raw_files = {}
    for path in sorted((EXP / "runs").glob("*/*.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        groups[(path.parent.name, run["scenario"], run["algorithm"])].append(run)
        raw_files[(path.parent.name, path.name)] = run

    # كل صف في جدول التشغيلات المجمع يجب أن يطابق نتيجته الأصلية.
    table = "runs.csv"
    rows = csv_rows(EXP / table)
    output["tables"][table] = len(rows)
    for row in rows:
        r = raw_files[(row["part"], row["file"])]
        rep = r["report"]
        drones = rep["drones"]
        expected = {
            "F": r["best_f"], "F_obj": rep["F_obj"], "feasible": r["feasible"], "valid": r["validator"]["valid"],
            "agree": r["validator"]["valid"] == r["feasible"],
            "time_s": r["time_s"], "cpu_s": r.get("cpu_s"), "memory_mb": r.get("memory_mb"),
            "fe_used": r["fe_used"], "budget": r["budget"], "first_feasible_fe": r["first_feasible_fe"],
            "length_m": sum(d["length_m"] for d in drones), "mission_time_s": rep["mission_time_s"],
            "energy_kj": sum(d["energy_kj"] for d in drones),
            "battery_max_pct": max(d["battery_used_pct"] for d in drones),
            "min_clearance_m": rep["min_clearance_m"], "max_hazard": max(d["max_hazard"] for d in drones),
            "min_separation_m": rep["min_separation_m"],
        }
        for key in ("J_T", "J_E", "J_H", "J_S"):
            expected[key] = st.mean(rep["terms"][key])
        for key, value in expected.items():
            compare(table, f"{row['part']}/{row['file']}", key, row[key], value)

    # ملخصات المدن الأساسية وجلسة الزمن تستخدم الحساب المستقل نفسه.
    for table, part in [("main_summary.csv", "main"), ("timing_summary.csv", "timing")]:
        rows = csv_rows(EXP / table)
        output["tables"][table] = len(rows)
        for row in rows:
            identity = f"{row['size']}/{row['algorithm']}"
            expected = summary(groups[(part, row["size"], row["algorithm"])])
            for key, value in expected.items():
                compare(table, identity, key, row[key], value)

    # اختبارات ويلكوكسون المقرونة وأحجام الأثر وتصحيحات هولم.
    table = "main_wilcoxon.csv"
    rows = csv_rows(EXP / table)
    output["tables"][table] = len(rows)
    for size in ("small", "medium", "large"):
        family = []
        for A, B in itertools.combinations(ALGS, 2):
            first = groups[("main", size, A)]
            second = groups[("main", size, B)]
            seeds = sorted({r["seed"] for r in first + second})

            def value(runs, seed):
                return runs[0]["best_f"] if len(runs) == 1 else next(
                    r["best_f"] for r in runs if r["seed"] == seed)

            differences = [value(first, seed) - value(second, seed) for seed in seeds]
            nonzero = [value for value in differences if value != 0]
            test = wilcoxon(nonzero, alternative="two-sided") if len(nonzero) > 1 else None
            pairs = [(x["best_f"], y["best_f"]) for x in first for y in second]
            expected = {
                "n": len(seeds), "n_nonzero": len(nonzero), "median_diff": st.median(differences),
                "wins_first": sum(value < 0 for value in differences),
                "wins_second": sum(value > 0 for value in differences),
                "ties": sum(value == 0 for value in differences),
                "statistic": float(test.statistic) if test else None,
                "p": float(test.pvalue) if test else 1.,
                "A12": sum(1 if x < y else .5 if x == y else 0 for x, y in pairs) / len(pairs),
            }
            family.append((A, B, expected))
        order = sorted(range(len(family)), key=lambda i: family[i][2]["p"])
        for rank, index in enumerate(order):
            family[index][2]["p_holm"] = min(1., max(
                (len(order) - j) * family[order[j]][2]["p"] for j in range(rank + 1)))
        for A, B, expected in family:
            row = next(r for r in rows if r["size"] == size and r["first"] == A and r["second"] == B)
            for key, value in expected.items():
                compare(table, f"{size}/{A}-{B}", key, row[key], value)
            verdict = ("no significant difference" if expected["p_holm"] >= .05
                       else f"{A if expected['median_diff'] < 0 else B} better")
            compare(table, f"{size}/{A}-{B}", "verdict", row["verdict"], verdict)

    # رتب المدن العشوائية والفروق النسبية عن DP.
    table = "random_summary.csv"
    rows = csv_rows(EXP / table)
    output["tables"][table] = len(rows)
    for row in rows:
        size, alg = row["size"], row["algorithm"]
        cities = sorted(city for part, city, A in groups
                        if part == "random" and A == alg and city.startswith(size + "_"))
        runs = [groups[("random", city, alg)][0] for city in cities]
        scores = {city: {A: groups[("random", city, A)][0]["best_f"] for A in ALGS} for city in cities}
        ranks = [
            1 + sum(F < scores[city][alg] for F in scores[city].values())
            + .5 * (sum(F == scores[city][alg] for F in scores[city].values()) - 1)
            for city in cities
        ]
        gaps = [100 * (scores[city][alg] / scores[city]["DP"] - 1) for city in cities]
        expected = {
            "cities": len(cities), "safe": sum(r["validator"]["valid"] for r in runs), "mean_rank": st.mean(ranks),
            "wins": sum(rank == 1 for rank in ranks), "median_F": st.median(r["best_f"] for r in runs),
            "median_gap_to_dp_pct": st.median(gaps),
            "mean_gap_to_dp_pct_safe": mean(gap for gap, r in zip(gaps, runs) if r["best_f"] < 100),
        }
        for key in ("time_s", "cpu_s", "memory_mb"):
            expected[f"mean_{key}"] = mean(r.get(key) for r in runs)
        for key, value in expected.items():
            compare(table, f"{size}/{alg}", key, row[key], value)

    # قيم الحساسية تأتي من سجلات DP أو الضبط الأصلية.
    table = "sensitivity.csv"
    rows = csv_rows(EXP / table)
    output["tables"][table] = len(rows)
    expected_rows = []
    tuning = {}
    for row in rows:
        alg, city, param = row["algorithm"], row["city"], row["parameter"]
        if alg == "DP":
            prune = "not pruned" not in param
            if param.startswith("line-of-sight"):
                resolution = 10
                prune = row["value"] == "on"
            else:
                resolution = int(row["value"])
            path = EXP / "runs/dp_sensitivity" / f"dp_{city}_g{resolution}_{'pruned' if prune else 'raw'}.json"
            run = json.loads(path.read_text())
            values = [run["best_f"]]
            baseline = json.loads((
                EXP / "runs/dp_sensitivity"
                / f"dp_{city}_g10_{'pruned' if (prune or param.startswith('line-of-sight')) else 'raw'}.json"
            ).read_text())["best_f"]
        else:
            key = (alg, city)
            if key not in tuning:
                tuning[key] = csv_rows(ROOT / "results/tuning" / f"{alg.lower()}_{city}_runs.csv")
            records = tuning[key]
            base = [float(r["best_f"]) for r in records if r["parameter"] == "default"]
            baseline = st.mean(base)

            def same(a, b):
                if a in ("", "None") and b in ("", "None"):
                    return True
                try:
                    return float(a) == float(b)
                except ValueError:
                    return a == b

            selected = [r for r in records if r["parameter"] == param and same(r["value"], row["value"])]
            values = base if row["is_default"] == "True" else [float(r["best_f"]) for r in selected]
        if not values:
            raise ValueError(f"No source records for {row['study']}/{param}/{row['value']}")
        expected = {
            "runs": len(values), "mean_F": st.mean(values), "std_F": std(values),
            "change_pct": 100 * (st.mean(values) / baseline - 1),
        }
        expected_rows.append((row, expected, baseline))
    for row, expected, baseline in expected_rows:
        peers = [value[1]["mean_F"] for value in expected_rows
                 if value[0]["study"] == row["study"] and value[0]["parameter"] == row["parameter"]]
        expected["spread_pct"] = 100 * (max(peers) - min(peers)) / baseline
        for key, value in expected.items():
            compare(table, f"{row['study']}/{row['parameter']}/{row['value']}", key, row[key], value)

    # نتائج الحالات الخاصة يجب أن تطابق توقعات المدن المجمدة.
    table = "special/summary.csv"
    rows = csv_rows(ROOT / "results" / table)
    output["tables"][table] = len(rows)
    archived = json.loads((ROOT / "results/special/runs.json").read_text())
    index = json.loads((ROOT / "scenarios/special/index.json").read_text())
    for row in rows:
        run = next(r for r in archived
                   if r["scenario"] == "special_" + row["case"] and r["algorithm"] == row["algorithm"]
                   and r["seed"] == int(row["seed"]))
        expected = index[run["scenario"]]["expect"]
        outcome = (
            "correct" if (expected == "feasible" and run["feasible"])
            or (expected == "infeasible" and not run["feasible"])
            else "missed" if expected == "feasible" else "error"
        )
        for key, value in {
            "F": round(run["best_f"], 4), "fitness_feasible": run["feasible"],
            "validator_valid": run["feasible"], "agree": True, "expected": expected, "outcome": outcome,
        }.items():
            compare(table, f"{row['case']}/{row['algorithm']}/{row['seed']}", key, row[key], value)

    output["passed"] = not output["failures"]
    (ROOT / "results/numerical-audit.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in output.items() if key != "failures"}, indent=2))
    if output["failures"]:
        print(json.dumps(output["failures"], indent=2))
    return output


if __name__ == "__main__":
    raise SystemExit(0 if audit()["passed"] else 1)
