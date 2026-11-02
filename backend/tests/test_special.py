"""اختبارات الحالات الخاصة في simulation/special.py.

* الملفات المجمدة مطابقة تمامًا لما يبنيه المولد (قابلة للإعادة)
* تُفحص التوقعات بخطط مرجعية وإجابات معروفة وحد للطاقة وملء فيضاني بالعينات
* تُفحص نتائج DP الحتمية منفصلة، ومنها إخفاقها في حالة المسيّرتين المتقاطعتين
* لا خطأ في التشغيل المحفوظ للخوارزميات الأربع، وكل حكم من F يطابق المدقق
* تتكرر تشغيلات محفوظة مختارة ضمن السماح العددي للاختبار
"""
import csv
import json
import math
from collections import deque
from pathlib import Path

import numpy as np
import pytest

from simulation.fitness import run_once
from simulation.aco_dp import DP
from simulation.scenarios import load_scenario
from simulation.experiments import run_job
from simulation.fitness import Problem, climb_over_plan
from simulation import special
from simulation.special import build, build_cases, load_index, outcome_of, route_over_or_around
from simulation.validator import _hazard, _outside_vector, check_plan

INDEX = load_index()
CASES = {v["case"]: name for name, v in INDEX.items()}
SUMMARY = special.ROOT / "results/special/summary.csv"
RUNS = special.ROOT / "results/special/runs.json"


def case(name):
    return load_scenario(special.OUT / f"{CASES[name]}.json")


def straight(scn):
    return [np.array([m.S, m.G], float) for m in scn.missions]


# الملفات
def test_ten_cases_with_an_expectation_each():
    assert len(INDEX) == 10 and set(CASES) == set(build_cases())
    for name, exp in INDEX.items():
        assert exp["expect"] in ("feasible", "infeasible") and exp["what"]
        assert (special.OUT / f"{name}.json").exists()
    assert sorted(v["case"] for v in INDEX.values() if v["expect"] == "infeasible") == \
        ["enclosed_target", "tiny_battery"]


def test_frozen_files_are_exactly_what_the_builder_makes(tmp_path):
    index = build(tmp_path)
    assert index == INDEX
    for name in INDEX:
        assert json.loads((tmp_path / f"{name}.json").read_text()) == \
            json.loads((special.OUT / f"{name}.json").read_text())


@pytest.mark.parametrize("name", list(CASES))
def test_every_case_is_a_well_formed_city(name):
    scn = case(name)
    K, N = len(scn.missions), scn.problem["n_waypoints"]
    assert scn.problem["n_drones"] == K and scn.problem["n_variables"] == 3 * K * N
    assert scn.world["W"] == 300 and scn.world["z_max"] == 150                      # إعدادات الحجم الصغير
    towers = np.array([[b.x0, b.y0, 0, b.x1, b.y1, b.h] for b in scn.buildings], float).reshape(-1, 6)
    for m in scn.missions:                                                           # النقطتان S وG آمنتان بذاتهما
        for p in (m.S, m.G):
            p = np.array([p], float)
            if len(towers):
                assert _outside_vector(p, towers).max(axis=2).min() >= scn.world["d_safe"]
            assert _hazard(p, scn.fires, scn.hazard["k"])[0] < scn.hazard["tau_core"]
            assert 0 <= p[0, 0] <= 300 and 0 <= p[0, 1] <= 300 and 10 <= p[0, 2] <= 150


# كل توقع مثبت يدويًا
def test_empty_city_known_answer():
    scn = case("empty_city")
    plan = straight(scn)
    assert check_plan(scn, plan)["valid"]
    F, info = Problem(scn).evaluate_paths(plan, count=False)
    assert F == pytest.approx(1.5, abs=1e-12) and info["feasible"]                  # w_T * 1 + w_E * 1


def test_behind_tall_tower_and_battery_cases():
    """الخط المستقيم يخترق البرج؛ والصعود فوقه آمن لكنه يكلف ~20 kJ؛ والالتفاف حوله يكلف أقل
    من 10 kJ. بطاقة متاحة 10 kJ لا يبقى إلا الالتفاف، وبـ 5 kJ لا يبقى شيء (انظر أدناه)."""
    tall, small = case("behind_tall_tower"), case("small_battery")
    assert not check_plan(tall, straight(tall))["checks"]["towers"]
    over = climb_over_plan(tall)
    rep = check_plan(tall, over)
    assert rep["valid"] and rep["drones"][0]["energy_kj"] > 15
    assert route_over_or_around(tall, over[0]) == "over"
    rep_small = check_plan(small, over)
    assert not rep_small["valid"] and [k for k, ok in rep_small["checks"].items() if not ok] == ["battery"]


def test_tiny_battery_is_impossible_by_an_energy_bound():
    """أي مسار من S إلى G لا يقل طوله عن |G - S| ولا يقل صعوده عن G_z - S_z:
    E >= e_c |G - S| + e_up max(G_z - S_z, 0) = 7.8 kJ > 5 kJ المتاحة. لا يمكن وجود خطة."""
    scn = case("tiny_battery")
    m, dr = scn.missions[0], scn.drone
    S, G = np.array(m.S), np.array(m.G)
    bound = dr["e_c"] * np.linalg.norm(G - S) + dr["e_up"] * max(G[2] - S[2], 0.0)
    usable = dr["battery_kj"] * 1000 * dr["battery_usable"]
    assert usable == pytest.approx(5000) and bound > usable * 1.5


def test_fire_on_line_straight_line_enters_the_core():
    scn = case("fire_on_line")
    rep = check_plan(scn, straight(scn))
    assert not rep["valid"] and [k for k, ok in rep["checks"].items() if not ok] == ["fire_core"]
    assert rep["max_hazard"] > 0.6


def test_target_near_fire_is_close_but_outside_the_core():
    scn = case("target_near_fire")
    f, G = scn.fires[0], np.array([scn.missions[0].G])
    assert f.c[0] - G[0, 0] == pytest.approx(1.1 * f.R)                             # على بعد 16.5 م من الواجهة
    usual = G + [-(1.6 - 1.1) * f.R, 0, 0]                                          # نقطة 1.6R المعتادة
    near, normal = _hazard(np.vstack([G, usual]), scn.fires, scn.hazard["k"])
    assert near < scn.hazard["tau_core"] and near > 3 * normal                       # 0.19 مقابل 0.05


def test_crossing_drones_need_coordination():
    """يلتقي الخطان المستقيمان في المنتصف في اللحظة نفسها؛ وإذا صعدت المسيّرة 1 أولًا 20 م تتأخر
    بما يكفي لتمر على بعد 22 م، فتوجد خطة صالحة (لكن تخطيط كل مسيّرة وحدها يفوّتها)."""
    scn = case("crossing_drones")
    rep = check_plan(scn, straight(scn))
    assert rep["min_separation_m"] < 0.1 and not rep["valid"]
    S1 = np.array(scn.missions[1].S)
    plan = [straight(scn)[0], np.array([S1, S1 + [0, 0, 20], scn.missions[1].G])]
    rep = check_plan(scn, plan)
    assert rep["valid"] and rep["min_separation_m"] == pytest.approx(22.4, abs=0.05)
    assert Problem(scn).evaluate_paths(plan, count=False)[1]["feasible"]


def flood(scn, res=1.0):
    """ملء فيضاني ثنائي الأبعاد من S على شبكة نقطية بدقة res متر لمسقط المدينة. يصلح للمدن التي
    أبراجها كلها أعلى من السقف: فالمسألة هناك مستوية ولا تستطيع المسيّرة الطيران فوق أي شيء."""
    d = scn.world["d_safe"]
    assert all(b.h >= scn.world["z_max"] for b in scn.buildings)
    c = np.arange(res / 2, scn.world["W"], res)
    X, Y = np.meshgrid(c, c, indexing="ij")
    free = np.ones(X.shape, bool)
    for b in scn.buildings:
        free &= ~((X >= b.x0 - d) & (X <= b.x1 + d) & (Y >= b.y0 - d) & (Y <= b.y1 + d))
    idx = lambda p: (int(p[0] // res), int(p[1] // res))                            # noqa: E731
    seen = np.zeros_like(free)
    q = deque([idx(scn.missions[0].S)])
    seen[q[0]] = True
    while q:
        i, j = q.popleft()
        for a, b in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
            if 0 <= a < free.shape[0] and 0 <= b < free.shape[1] and free[a, b] and not seen[a, b]:
                seen[a, b] = True
                q.append((a, b))
    return seen[idx(scn.missions[0].G)]


def test_maze_has_a_way_through_and_the_enclosed_target_has_none():
    assert flood(case("maze"))
    assert not flood(case("enclosed_target"))


# DP على كل حالة
@pytest.fixture(scope="module")
def dp_runs():
    return {name: run_once(DP(), case(name), seed=0) for name in CASES}


@pytest.mark.parametrize("name", list(CASES))
def test_dp_on_every_case(dp_runs, name):
    """DP دقيقة على الشبكة وحتمية، فنتيجتها في كل حالة ثابتة."""
    r, scn, exp = dp_runs[name], case(name), INDEX[CASES[name]]
    v = check_plan(scn, r.paths)
    assert v["valid"] == r.feasible                                                  # F والمدقق متفقان
    route = route_over_or_around(scn, r.paths[0]) if "route" in exp else ""
    got = outcome_of(exp, "DP", r.best_f, v["valid"], route, r.extra["no_path"])
    if name == "crossing_drones":                                                    # تُخطط واحدة تلو الأخرى
        assert got == "missed" and not v["checks"]["separation"] and all(
            v["checks"][k] for k in ("towers", "fire_core", "battery"))
    else:
        assert got == "correct"
    if name == "empty_city":
        assert r.best_f == pytest.approx(1.5, abs=1e-9)
    if name == "enclosed_target":
        assert r.extra["no_path"] == [0] and r.best_f > 100
    if name == "tiny_battery":
        assert not v["checks"]["battery"] and r.best_f > 100
    if name == "small_battery":
        assert v["drones"][0]["energy_kj"] <= 10.0 and route == "around"


# قاعدة تصنيف النتيجة
def test_outcome_rule():
    feas, infeas = {"case": "x", "expect": "feasible"}, {"case": "x", "expect": "infeasible"}
    assert outcome_of(feas, "GA", 1.6, True) == "correct"
    assert outcome_of(feas, "GA", 348.0, False) == "missed"
    assert outcome_of(infeas, "GA", 1.6, True) == "error"                            # قبلت المستحيل
    assert outcome_of(infeas, "GA", 120.0, False) == "correct"                       # يُبلَّغ عنها كغير آمنة
    assert outcome_of(infeas, "GA", 99.0, False) == "error"                          # غير آمنة لكن F تقول إنها سليمة
    known = dict(feas, known_F=1.5)
    assert outcome_of(known, "DP", 1.5, True) == "correct"
    assert outcome_of(known, "DP", 1.5 + 1e-6, True) == "missed"                     # طرق الشبكة: دقيقة
    assert outcome_of(known, "PSO", 1.505, True) == "correct"                        # GA / PSO: 1%
    assert outcome_of(dict(feas, route="around"), "GA", 2.0, True, "over") == "missed"
    enc = {"case": "enclosed_target", "expect": "infeasible"}
    assert outcome_of(enc, "DP", 1101.0, False, "", [0]) == "correct"
    assert outcome_of(enc, "DP", 1101.0, False, "", []) == "error"                   # يجب أن تصرّح DP بذلك


# التشغيل المحفوظ
@pytest.fixture(scope="module")
def saved():
    if not SUMMARY.exists():
        pytest.skip("run python -m simulation.special --run first")
    with open(SUMMARY) as fh:
        return list(csv.DictReader(fh))


def test_saved_run_has_no_error_and_full_agreement(saved):
    assert len(saved) == 10 * (3 * 3 + 1)                                            # 3 بذور لكل من GA وPSO وACO + DP
    assert all(r["agree"] == "True" for r in saved)
    assert not [r for r in saved if r["outcome"] == "error"]
    for name, exp in INDEX.items():                                                  # في كل حالة قابلة للحل تنجح خوارزمية واحدة على الأقل
        rows = [r for r in saved if r["case"] == exp["case"]]
        assert any(r["outcome"] == "correct" for r in rows), exp["case"]


def test_saved_run_is_rejudged_the_same(saved):
    """يعيد فحص كل خطة محفوظة بالمدقق وقاعدة التصنيف: الأحكام نفسها الموجودة في CSV."""
    table = {(r["case"], r["algorithm"], int(r["seed"])): r for r in saved}
    for r in json.loads(RUNS.read_text()):
        exp, scn = INDEX[r["scenario"]], case(INDEX[r["scenario"]]["case"])
        v = check_plan(scn, r["paths"])
        route = route_over_or_around(scn, r["paths"][0]) if "route" in exp else ""
        row = table[(exp["case"], r["algorithm"], r["seed"])]
        assert str(v["valid"]) == row["validator_valid"]
        assert outcome_of(exp, r["algorithm"], r["best_f"], v["valid"], route, r["extra"].get("no_path", "")) == \
            row["outcome"]


@pytest.mark.parametrize("alg, name, seed", [("pso", "fire_on_line", 1), ("ga", "narrow_street", 2)])
def test_saved_runs_are_reproduced_across_platforms(alg, name, seed):
    if not RUNS.exists():
        pytest.skip("no saved special runs")
    old = next(r for r in json.loads(RUNS.read_text())
               if r["scenario"] == CASES[name] and r["algorithm"] == alg.upper() and r["seed"] == seed)
    new = run_job({"alg": alg, "city": CASES[name], "seed": seed, "params": {}, "budget": None})
    # حُسب الأرشيف على Linux بإصدار مختلف من NumPy. قد يختلف ناتج اختزال
    # بوحدة ULP واحدة على Windows (لوحظ 2.22e-16 في F) دون أن يتغير
    # الحل. أما الحتمية الحرفية داخل العملية نفسها فتختبرها test_ga وtest_pso.
    assert new["best_f"] == pytest.approx(old["best_f"], rel=0, abs=1e-12)
    assert len(new["paths"]) == len(old["paths"])
    for actual, expected in zip(new["paths"], old["paths"]):
        np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-10)
    assert new["feasible"] == old["feasible"]
    assert math.isfinite(new["best_f"])
