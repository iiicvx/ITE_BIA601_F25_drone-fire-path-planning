"""اختبارات إحصاءات التجارب النهائية (simulation/stats.py).

تستخدم الفحوص قيمًا محسوبة يدويًا، واختبار ويلكوكسون دقيقًا مكتوبًا باستقلال
(كل أنماط الإشارة 2^n)، وتجارب اصطناعية فيها فائز معروف مسبقًا.
"""
import itertools
import json

import numpy as np
import pandas as pd
import pytest
from scipy.stats import wilcoxon

from simulation import stats as S


# إحصاءات صغيرة
def test_holm_known_answer():
    p = [0.01, 0.04, 0.03, 0.005]
    # بعد الترتيب: 0.005*4 = 0.02، 0.01*3 = 0.03، 0.03*2 = 0.06، 0.04*1 = 0.04 -> مع الحفاظ على التزايد: 0.06
    assert np.allclose(S.holm(p), [0.03, 0.06, 0.06, 0.02])
    assert np.allclose(S.holm([0.5, 0.9]), [1.0, 1.0])                       # محدودة بالقيمة 1
    out = S.holm([0.01, np.nan, 0.02])
    assert np.isnan(out[1]) and np.allclose(out[[0, 2]], [0.02, 0.02])       # تُستبعد NaN من مجموعة المقارنات


def test_holm_never_below_the_raw_p_and_keeps_the_order():
    rng = np.random.default_rng(0)
    for _ in range(50):
        p = rng.uniform(0, 0.2, 6)
        h = S.holm(p)
        assert (h >= p - 1e-15).all() and (h <= 1).all()
        assert (np.diff(h[np.argsort(p)]) >= -1e-15).all()


def test_a12_known_answers():
    assert S.a12([1, 2], [3, 4]) == 1.0                    # الأولى أقل دائمًا (أفضل)
    assert S.a12([3, 4], [1, 2]) == 0.0
    assert S.a12([1, 2], [1, 2]) == 0.5
    assert S.a12([1, 2], [1.5, 3]) == 0.75                 # 1<1.5, 1<3, 2>1.5, 2<3


def exact_wilcoxon(d):
    """مرجع مستقل: قيمة p دقيقة ثنائية الطرف بسرد كل أنماط الإشارة (بلا تعادلات ولا أصفار)."""
    r = pd.Series(np.abs(d)).rank().values
    w_obs = r[np.asarray(d) > 0].sum()
    n = len(d)
    mean = n * (n + 1) / 4
    total = 0
    count = 0
    for signs in itertools.product([0, 1], repeat=n):
        w = r[np.array(signs, bool)].sum()
        total += 1
        count += abs(w - mean) >= abs(w_obs - mean) - 1e-12
    return count / total


@pytest.mark.parametrize("seed", range(5))
def test_wilcoxon_matches_an_exact_test_written_by_hand(seed):
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 1, 9)
    y = x + rng.normal(0.3, 1, 9)
    t = S.wilcoxon_paired(x, y)
    assert t["p"] == pytest.approx(exact_wilcoxon(x - y), rel=1e-9)
    assert t["p"] == pytest.approx(wilcoxon(x, y).pvalue, rel=1e-12)


def test_wilcoxon_edge_cases():
    t = S.wilcoxon_paired(np.arange(10.0), np.arange(10.0) + np.arange(1, 11) / 10)   # أقل دائمًا
    assert t["p"] == pytest.approx(2 / 2 ** 10) and t["wins_first"] == 10 and t["wins_second"] == 0
    t = S.wilcoxon_paired([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])                          # نتائج متطابقة
    assert t["p"] == 1.0 and t["ties"] == 3 and t["n_nonzero"] == 0
    t = S.wilcoxon_paired([1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.5])                # يختلف زوج واحد
    assert t["p"] == 1.0 and t["ties"] == 3
    t = S.wilcoxon_paired([1, 2, 3, 4, 5, 6, 7], [1, 2.5, 3.2, 4.4, 5.1, 6.6, 7.7])  # تُحذف الأصفار
    assert t["n_nonzero"] == 6 and t["p"] == pytest.approx(2 / 2 ** 6)


# تجارب اصطناعية
def synthetic(n_seeds=20, seed=0):
    """GA ~ 1.6، وPSO = GA + 0.1 (أسوأ دائمًا)، وACO = GA - 0.05 (أفضل دائمًا)، وDP ثابتة 1.58."""
    rng = np.random.default_rng(seed)
    rows = []
    for size in ("small", "medium"):
        base = 1.6 + rng.normal(0, 0.02, n_seeds)
        for s in range(n_seeds):
            for alg, F in (("GA", base[s]), ("PSO", base[s] + 0.1 + abs(rng.normal(0, 0.01))),
                           ("ACO", base[s] - 0.05 - abs(rng.normal(0, 0.01)))):
                rows.append({"size": size, "city": size, "seed": s, "algorithm": alg, "F": F, "valid": True})
        rows.append({"size": size, "city": size, "seed": 0, "algorithm": "DP", "F": 1.58, "valid": True})
    df = pd.DataFrame(rows)
    df["algorithm"] = pd.Categorical(df["algorithm"], S.ORDER, ordered=True)
    return df


def test_pairwise_finds_the_planted_winner():
    w = S.pairwise(synthetic(), "seed")
    assert len(w) == 12                                           # 6 أزواج × حجمان
    get = lambda a, b: w[(w["size"] == "small") & (w["first"] == a) & (w["second"] == b)].iloc[0]  # noqa: E731
    assert get("GA", "PSO")["verdict"] == "GA better" and get("GA", "PSO")["wins_first"] == 20
    assert get("GA", "ACO")["verdict"] == "ACO better" and get("GA", "ACO")["A12"] < 0.3
    assert get("ACO", "DP")["verdict"] == "ACO better"            # تشغيل DP الوحيد يُقرن بكل بذرة
    assert get("ACO", "DP")["n"] == 20
    assert (w["p_holm"] >= w["p"]).all()


def test_pairwise_with_no_difference_says_so():
    df = synthetic()
    df.loc[df["algorithm"] == "PSO", "F"] = df.loc[df["algorithm"] == "GA", "F"].values + \
        np.random.default_rng(3).normal(0, 0.02, (df["algorithm"] == "PSO").sum())
    w = S.pairwise(df, "seed")
    r = w[(w["size"] == "small") & (w["first"] == "GA") & (w["second"] == "PSO")].iloc[0]
    assert r["verdict"] == "no significant difference" and 0.2 < r["A12"] < 0.8


def test_summarize():
    df = synthetic().assign(time_s=1.0, cpu_s=1.0, memory_mb=10.0, agree=True, first_feasible_fe=5,
                            length_m=100.0, mission_time_s=10.0, energy_kj=2.0, min_clearance_m=6.0,
                            max_hazard=0.1, min_separation_m=np.nan, budget=10000)
    s = S.summarize(df)
    ga = s[(s["size"] == "small") & (s["algorithm"] == "GA")].iloc[0]
    F = df[(df["size"] == "small") & (df["algorithm"] == "GA")]["F"]
    assert ga["runs"] == 20 and ga["mean_F"] == pytest.approx(F.mean()) and ga["std_F"] == pytest.approx(F.std(ddof=1))
    assert ga["best_F"] == F.min() and ga["worst_F"] == F.max() and ga["success_rate"] == 1.0
    dp = s[(s["size"] == "small") & (s["algorithm"] == "DP")].iloc[0]
    assert dp["runs"] == 1 and dp["std_F"] == 0.0


def random_like():
    rows = []
    for c in range(10):
        for alg, F in (("GA", 1.7 + 0.01 * c), ("PSO", 1.8 + 0.01 * c), ("ACO", 1.5 + 0.01 * c), ("DP", 1.6)):
            rows.append({"size": "medium", "city": f"medium_r{c + 1:02d}", "seed": 0, "algorithm": alg,
                         "F": F if not (alg == "PSO" and c == 0) else 150.0, "valid": not (alg == "PSO" and c == 0),
                         "time_s": 1.0, "cpu_s": 1.0, "memory_mb": 5.0})
    df = pd.DataFrame(rows)
    df["algorithm"] = pd.Categorical(df["algorithm"], S.ORDER, ordered=True)
    return df


def test_random_city_ranks_gaps_and_friedman():
    df = random_like()
    r = S.random_summary(df).set_index("algorithm")
    assert r.loc["ACO", "mean_rank"] == 1.0 and r.loc["ACO", "wins"] == 10
    assert r.loc["PSO", "mean_rank"] == 4.0 and r.loc["PSO", "safe"] == 9
    assert r.loc["DP", "median_gap_to_dp_pct"] == 0.0
    assert r.loc["ACO", "median_gap_to_dp_pct"] == pytest.approx((1.545 / 1.6 - 1) * 100)
    f = S.friedman(df).iloc[0]
    assert f["cities"] == 10 and f["p"] < 1e-5                 # ترتيب متسق تمامًا
    w = S.pairwise(df, "city")
    assert (w["verdict"] != "no significant difference").all() and np.allclose(w["p"], 2 / 2 ** 10)


# الحساسية
def test_sensitivity_from_a_parameter_study(tmp_path):
    rows = [("default", "default", 1000 + s, 1.6 + 0.01 * s) for s in range(3)]
    rows += [("p_mut", "0.5", 1000 + s, 1.8 + 0.01 * s) for s in range(3)]
    rows += [("p_mut", "0.1", 1000 + s, 1.55 + 0.01 * s) for s in range(3)]
    rows += [("restart_stall", "", 1000 + s, 1.7) for s in range(3)]              # تُكتب None كنص فارغ
    pd.DataFrame(rows, columns=["parameter", "value", "seed", "best_f"]).assign(
        feasible=True, first_feasible_fe=1, fe_used=1, time_s=1).to_csv(tmp_path / "ga_medium_runs.csv", index=False)
    (tmp_path / "ga_medium_defaults.json").write_text(json.dumps({"p_mut": 0.25, "restart_stall": 20, "_budget": None}))
    dp = pd.DataFrame([{"city": "small", "grid_res": g, "prune": p, "F": F, "time_s": 0.1, "memory_mb": 1.0}
                       for g, p, F in ((20, True, 1.7), (10, True, 1.6), (5, True, 1.58), (10, False, 2.4),
                                       (20, False, 2.0), (5, False, 2.5))])
    s = S.sensitivity(tmp_path, dp)
    pm = s[s["parameter"] == "p_mut"]
    assert list(pm["value"]) == ["0.1", "0.25", "0.5"]                             # الأرقام بالترتيب
    assert pm["is_default"].tolist() == [False, True, False]
    assert pm["spread_pct"].iloc[0] == pytest.approx((1.81 - 1.56) / 1.61 * 100)
    assert pm[pm["value"] == "0.5"]["worse_seeds"].iloc[0] == 3
    rs = s[s["parameter"] == "restart_stall"]
    assert list(rs["value"]) == ["20", "None"]                                     # None في الأخير
    pr = s[(s["study"] == "DP small") & (s["parameter"] == "line-of-sight pruning (10 m grid)")]
    assert list(pr["value"]) == ["off", "on"] and pr["change_pct"].iloc[0] == pytest.approx(50.0)
    grid = s[(s["study"] == "DP small") & (s["parameter"] == "grid cell size (m), pruned")]
    assert list(grid["value"]) == ["20", "10", "5"] and grid["spread_pct"].iloc[0] == pytest.approx(7.5)


def test_markdown_tables_are_complete():
    df = synthetic().assign(time_s=1.0, cpu_s=1.0, memory_mb=10.0, agree=True, first_feasible_fe=5,
                            length_m=100.0, mission_time_s=10.0, energy_kj=2.0, min_clearance_m=6.0,
                            max_hazard=0.1, min_separation_m=np.nan, budget=10000)
    md = S.markdown_tables(S.summarize(df), S.pairwise(df, "seed"), S.random_summary(random_like()),
                           S.friedman(random_like()), S.pairwise(random_like(), "city"), pd.DataFrame())
    assert md.count("### ") == 2 and "| ACO vs DP |" in md and "Friedman" in md
    assert "**" in md                                                              # أفضل متوسط F بخط عريض
