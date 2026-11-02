"""اختبارات المدقق المستقل (simulation/validator.py).

ثلاثة أنواع من الاختبارات:
* إجابات معروفة  مدن يدوية يمكن حساب حكمها الصحيح وأرقامها على الورق؛
* مقارنات متقاطعة  المدقق ودالة اللياقة شيفرتان منفصلتان، ويجب أن تعطيا
                   الحكم نفسه على خطط كثيرة ليست على حد القيد تمامًا؛
* التشغيلات المحفوظة  كل خطة حفظتها التجارب تجتاز المدقق عندما تعدّها F آمنة.
"""
import ast
import copy
import glob
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from simulation.geometry import FireField
from simulation.scenarios import Building, Fire, Mission, load_scenario, ROOT as SIMULATION
from simulation.fitness import Problem, climb_over_plan
from simulation import validator as V
from simulation.validator import check_plan, check_result_file

MAIN = [SIMULATION / "scenarios/small.json", SIMULATION / "scenarios/medium.json", SIMULATION / "scenarios/large.json"]
ALL_CITIES = sorted(glob.glob(str(SIMULATION / "scenarios/*.json")) + glob.glob(str(SIMULATION / "scenarios/random/*.json")))
SAVED = sorted(f for f in glob.glob(str(SIMULATION / "results/quick/*.json")))


def world(buildings=(), fires=(), missions=(([20, 150, 10], [220, 150, 10]),), battery_kj=799):
    """مدينة يدوية بإعدادات الحجم الصغير (W 300، السقف 150، d_safe 5، d_sep 10)."""
    scn = copy.deepcopy(load_scenario(SIMULATION / "scenarios/small.json"))
    scn.buildings = [Building(i, *map(float, b)) for i, b in enumerate(buildings)]
    scn.fires = [Fire(i, 0, "E", list(map(float, c)), [1.0, 0.0, 0.0], R, I, 80.0)
                 for i, (c, R, I) in enumerate(fires)]
    scn.missions = [Mission(k, 0, list(map(float, s)), list(map(float, g))) for k, (s, g) in enumerate(missions)]
    scn.drone = dict(scn.drone, battery_kj=float(battery_kj))
    scn.problem = dict(scn.problem, n_drones=len(missions))
    return scn


def line(*pts):
    return np.array(pts, dtype=float)


def fitness_verdict(scn, paths):
    return Problem(scn, budget=10**9).evaluate_paths(paths, count=False)[1]


# إجابات معروفة
def test_straight_line_in_an_empty_city():
    scn = world(missions=(([20, 150, 10], [220, 150, 60]),))
    rep = check_plan(scn, [line([20, 150, 10], [220, 150, 60])])
    assert rep["valid"] and all(rep["checks"].values()) and rep["problems"] == []
    d = rep["drones"][0]
    L = math.hypot(200, 50)
    assert d["length_m"] == pytest.approx(L)
    assert d["energy_kj"] == pytest.approx((20 * L + 100 * 50) / 1000)            # e_c * L + e_up * الصعود
    assert d["battery_pct"] == pytest.approx(100 * (20 * L + 100 * 50) / 799000)
    assert rep["min_clearance_m"] == math.inf and rep["min_separation_m"] == math.inf
    assert rep["max_hazard"] == 0.0


def test_straight_line_through_a_tower():
    scn = world(buildings=((100, 130, 140, 170, 60),))
    rep = check_plan(scn, [line([20, 150, 10], [220, 150, 10])])
    assert not rep["valid"] and not rep["checks"]["towers"]
    assert rep["min_clearance_m"] == 0.0 and rep["min_margin_linf_m"] == 0.0
    assert "comes within 0.00 m of a tower" in rep["problems"][0]
    for name in ("endpoints", "bounds", "fire_core", "battery", "separation"):
        assert rep["checks"][name]                                               # قاعدة البرج وحدها تفشل


@pytest.mark.parametrize("gap, ok, f_ok", [(6.0, True, True), (5.0, True, False), (4.0, False, False)])
def test_tower_margin_beside_the_wall(gap, ok, f_ok):
    """الطيران بمحاذاة الجدار الشمالي (y = 170) على مسافة gap: القاعدة >= 5 م.

    الطيران على بعد 5 م بالضبط على طول الجدار هو الموضع الوحيد الذي يختلف فيه الفحصان عمدًا: F (وشبكة
    ACO / DP) تعامل الصندوق المضخم كصندوق مغلق، فالانزلاق على سطحه يُعد ملامسة له.
    فتكون F عندها أشد من القاعدة لا أكثر تساهلًا: لا يمكن أن تقبل خطة يرفضها المدقق."""
    y = 170 + gap
    scn = world(buildings=((100, 130, 140, 170, 60),), missions=(([20, y, 10], [220, y, 10]),))
    rep = check_plan(scn, [line([20, y, 10], [220, y, 10])])
    assert rep["valid"] is ok and rep["checks"]["towers"] is ok
    assert rep["min_margin_linf_m"] == pytest.approx(gap) and rep["min_clearance_m"] == pytest.approx(gap)
    assert fitness_verdict(scn, [line([20, y, 10], [220, y, 10])])["feasible"] is f_ok


@pytest.mark.parametrize("height, ok", [(66.0, True), (64.0, False)])
def test_tower_margin_above_the_roof(height, ok):
    """الصعود فوق سطح ارتفاعه 60 م: 6 م فوقه آمن، و4 م ليس آمنًا."""
    scn = world(buildings=((100, 130, 140, 170, 60),))
    plan = [line([20, 150, 10], [90, 150, height], [150, 150, height], [220, 150, 10])]
    rep = check_plan(scn, plan)
    assert rep["valid"] is ok
    assert rep["min_margin_linf_m"] == pytest.approx(height - 60)
    assert fitness_verdict(scn, plan)["feasible"] is ok


def test_tower_margin_at_a_corner_is_measured_like_the_grown_box():
    """على بعد 4 م من الجدارين عند الزاوية: المسافة المستقيمة 5.66 م، لكن النقطة داخل البرج المضخم
    بـ 5 م من كل جانب، فتخالف القاعدة (القاعدة نفسها في دالة اللياقة والشبكة)."""
    scn = world(buildings=((100, 130, 140, 170, 60),), missions=(([120, 200, 10], [170, 200, 10]),))
    plan = [line([120, 200, 10], [144, 174, 10], [170, 200, 10])]
    rep = check_plan(scn, plan)
    assert rep["min_margin_linf_m"] == pytest.approx(4.0)
    assert rep["min_clearance_m"] == pytest.approx(4 * math.sqrt(2))
    assert not rep["valid"] and not fitness_verdict(scn, plan)["feasible"]


FIRE = ([120, 150, 60], 15.0, 1.0)                      # المركز وR وI؛ H_f = 80 م وtau_core = 0.5


@pytest.mark.parametrize("d, ok", [(15.0, True), (12.0, False)])
def test_fire_beside_at_the_same_height(d, ok):
    """عند ارتفاع الحريق H = exp(-(d/R)^2): 0.368 عند d = R (آمن)، و0.527 عند d = 0.8 R (القلب)."""
    scn = world(fires=(FIRE,), missions=(([20, 150 + d, 60], [220, 150 + d, 60]),))
    plan = [line([20, 150 + d, 60], [220, 150 + d, 60])]
    rep = check_plan(scn, plan)
    assert rep["max_hazard"] == pytest.approx(math.exp(-(d / 15) ** 2), abs=1e-9)
    assert rep["valid"] is ok and rep["checks"]["fire_core"] is ok
    assert fitness_verdict(scn, plan)["feasible"] is ok


@pytest.mark.parametrize("dz, expected", [
    (-10, math.exp(-4 * 100 / 225)),            # تحت الحريق: يتلاشى بسرعة، H = exp(-(2 dz)^2 / R^2) = 0.169
    (40, math.exp(-40 / 80)),                   # فوق الحريق: H = exp(-dz / H_f) = 0.607 -> داخل القلب
    (60, math.exp(-60 / 80)),                   # أعلى: 0.472 -> آمن (قمة القلب = 80 ln 2 = 55.5 م)
])
def test_fire_directly_below_and_above(dz, expected):
    z = 60 + dz
    scn = world(fires=(FIRE,), missions=(([20, 150, z], [220, 150, z]),))
    plan = [line([20, 150, z], [220, 150, z])]
    rep = check_plan(scn, plan)
    assert rep["max_hazard"] == pytest.approx(expected, abs=1e-9)
    assert rep["valid"] is (expected < 0.5)
    assert fitness_verdict(scn, plan)["feasible"] is (expected < 0.5)


def test_two_fires_add_up():
    """كل حريق وحده يعطي 0.368 على الخط (آمن)، ومعًا 0.736: داخل القلب."""
    one = world(fires=(([120, 135, 60], 15.0, 1.0),), missions=(([20, 150, 60], [220, 150, 60]),))
    two = world(fires=(([120, 135, 60], 15.0, 1.0), ([120, 165, 60], 15.0, 1.0)),
                missions=(([20, 150, 60], [220, 150, 60]),))
    plan = [line([20, 150, 60], [220, 150, 60])]
    assert check_plan(one, plan)["valid"]
    rep = check_plan(two, plan)
    assert rep["max_hazard"] == pytest.approx(2 * math.exp(-1), abs=1e-9) and not rep["valid"]


SEP_CASES = [
    # (المسيّرة A، المسيّرة B، أقرب مسافة محسوبة على الورق)
    (([20, 150, 50], [220, 150, 50]), ([220, 150, 50], [20, 150, 50]), 0.0),          # وجهًا لوجه
    (([20, 150, 50], [220, 150, 50]), ([20, 162, 50], [220, 162, 50]), 12.0),         # جنبًا إلى جنب
    (([20, 150, 50], [220, 150, 50]), ([20, 158, 50], [220, 158, 50]), 8.0),
    # تقاطع بزاوية قائمة وB متأخرة 10 م: مربع المسافة = (100 - s)^2 + (s - 80)^2، أصغره عند s = 90
    (([20, 100, 50], [220, 100, 50]), ([120, 20, 50], [120, 220, 50]), math.sqrt(200)),
    (([20, 100, 50], [220, 100, 50]), ([120, 10, 50], [120, 210, 50]), math.sqrt(50)),
]


@pytest.mark.parametrize("a, b, d_min", SEP_CASES, ids=["head-on", "12m", "8m", "cross-14m", "cross-7m"])
def test_separation_known_answers(a, b, d_min):
    scn = world(missions=(a, b))
    plan = [line(*a), line(*b)]
    rep = check_plan(scn, plan)
    assert rep["min_separation_m"] == pytest.approx(d_min, abs=1e-3)
    assert rep["checks"]["separation"] is (d_min >= 10) and rep["valid"] is (d_min >= 10)
    info = fitness_verdict(scn, plan)                       # أقرب اقتراب دقيق في geometry.py
    assert info["d_min_m"] == pytest.approx(d_min, abs=1e-3) and info["feasible"] is (d_min >= 10)


def test_a_drone_that_has_arrived_hovers_at_its_target():
    """تصل A بعد 4 ث وتنتظر عند (60، 150، 50). تمر B على بعد 8 م من تلك النقطة عند t = 14 ث.
    أثناء حركتهما معًا لا تقتربان أبدًا، فلا يظهر التعارض إلا إذا بقيت A حائمة."""
    a, b = ([20, 150, 50], [60, 150, 50]), ([200, 158, 50], [20, 158, 50])
    scn = world(missions=(a, b))
    rep = check_plan(scn, [line(*a), line(*b)])
    assert rep["min_separation_m"] == pytest.approx(8.0, abs=1e-6) and not rep["valid"]
    assert "t = 14.0 s" in rep["problems"][0]
    assert fitness_verdict(scn, [line(*a), line(*b)])["d_min_m"] == pytest.approx(8.0)


def test_battery_limit_and_free_descent():
    scn = world(battery_kj=4.0, missions=(([20, 150, 10], [180, 150, 10]),))   # المتاح 3.2 kJ
    assert check_plan(scn, [line([20, 150, 10], [180, 150, 10])])["valid"]       # 160 م: بالضبط 3.2 kJ
    scn = world(battery_kj=4.0)
    rep = check_plan(scn, [line([20, 150, 10], [220, 150, 10])])                 # 200 م: 4.0 kJ
    assert not rep["checks"]["battery"] and "needs 4.0 kJ, the battery allows 3.2 kJ" in rep["problems"][0]
    hop = line([20, 150, 10], [120, 150, 110], [220, 150, 10])                   # 100 م صعودًا و100 م هبوطًا
    d = check_plan(world(), [hop])["drones"][0]
    assert d["energy_kj"] == pytest.approx((20 * 2 * math.hypot(100, 100) + 100 * 100) / 1000)


@pytest.mark.parametrize("path, rule", [
    ([[21, 150, 10], [220, 150, 10]], "endpoints"),         # تبدأ على بعد 1 م من S
    ([[20, 150, 10], [220, 150, 11]], "endpoints"),         # تنتهي أخفض من الهدف بـ 1 م
    ([[20, 150, 10], [120, 150, 151], [220, 150, 10]], "bounds"),     # فوق السقف
    ([[20, 150, 10], [120, 150, 9], [220, 150, 10]], "bounds"),       # تحت أدنى ارتفاع
    ([[20, 150, 10], [120, -1, 10], [220, 150, 10]], "bounds"),       # خارج المدينة
])
def test_endpoints_and_bounds(path, rule):
    rep = check_plan(world(), [line(*path)])
    assert not rep["valid"] and not rep["checks"][rule]
    assert [k for k, ok in rep["checks"].items() if not ok] == [rule]


@pytest.mark.parametrize("plan", [
    [line([20, 150, 10], [np.nan, 150, 10], [220, 150, 10])],
    [line([20, 150, 10])],
    [np.zeros((3, 2))],
    [],
    [line([20, 150, 10], [220, 150, 10])] * 2,
], ids=["nan", "one-point", "2d", "no-path", "too-many"])
def test_broken_plans_are_rejected_without_crashing(plan):
    rep = check_plan(world(), plan)
    assert not rep["valid"] and rep["problems"]


# المدقق نفسه
def test_validator_does_not_reuse_the_code_it_checks():
    """الاستقلال: الوحدة لا تستورد شيئًا من شيفرة الهندسة أو الخطر أو الشبكة أو اللياقة."""
    tree = ast.parse(Path(V.__file__).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    assert not any(bad in n for n in names for bad in ("geometry", "hazard", "grid", "fitness", "algorithms"))
    assert names <= {"__future__", "argparse", "json", "sys", "pathlib", "numpy", "scenarios"}


def test_loading_a_scenario_for_validation_does_not_import_the_planning_code():
    """محمّل المدن الموحد يُبقي الاستيرادات الخاصة بالتوليد محلية."""
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; from simulation.validator import check_result_file; "
         "from simulation.scenarios import load_scenario; "
         "assert load_scenario('simulation/scenarios/small.json').name == 'small'; "
         "assert not {'simulation.geometry', 'simulation.grid', 'simulation.fitness', 'simulation.ga_pso'}.intersection(sys.modules)"],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("path", ALL_CITIES)
def test_hazard_written_twice_gives_the_same_numbers(path):
    """نسخة المدقق الخاصة من نموذج العمود الحراري تساوي FireField عند نقاط عشوائية."""
    scn = load_scenario(path)
    rng = np.random.default_rng(1)
    W, top = scn.world["W"], scn.world["z_max"]
    near = np.concatenate([np.array(f.c) + rng.normal(0, 25, (400, 3)) for f in scn.fires])
    pts = np.vstack([rng.uniform([0, 0, 0], [W, W, top], (2000, 3)), near])
    mine = np.minimum(V._hazard(pts, scn.fires, scn.hazard["k"]), 1.0)
    assert np.allclose(mine, FireField.from_scenario(scn).H(pts), rtol=0, atol=1e-12)


def test_dense_sampling_has_converged():
    """تنصيف الخطوة خمس مرات يغير المسافات المقيسة بأقل من 1 سم."""
    scn = load_scenario(SIMULATION / "scenarios/medium.json")
    pb = Problem(scn, budget=10**9)
    plan = pb.decode(pb.initial_population(1, np.random.default_rng(3))[0])
    a, b = check_plan(scn, plan), check_plan(scn, plan, step=0.02, dt=0.002)
    for key in ("min_clearance_m", "min_margin_linf_m", "min_separation_m"):
        assert abs(a[key] - b[key]) < 0.01
    assert abs(a["max_hazard"] - b["max_hazard"]) < 1e-3 and a["valid"] == b["valid"]


def test_the_check_is_repeatable():
    scn = load_scenario(SIMULATION / "scenarios/medium.json")
    pb = Problem(scn, budget=10**9)
    plan = pb.decode(pb.initial_population(1, np.random.default_rng(5))[0])
    assert json.dumps(check_plan(scn, plan), default=str) == json.dumps(check_plan(scn, plan), default=str)


# الاتفاق مع F
def near_a_limit(rep, scn):
    """الخطط القريبة جدًا من حد قاعدة (قد يختلف أخذ العينات كل 0.1 م و2 م هناك): مستبعدة."""
    w, dr = scn.world, scn.drone
    e_max = dr["battery_kj"] * dr["battery_usable"]
    return (abs(rep["min_margin_linf_m"] - w["d_safe"]) < 0.5
            or abs(rep["max_hazard"] - scn.hazard["tau_core"]) < 0.02
            or abs(rep["min_separation_m"] - dr["d_sep"]) < 0.5
            or any(abs(d.get("energy_kj", 0) - e_max) < 0.005 * e_max for d in rep["drones"]))


def noisy_plans(scn, n, rng):
    """خطط حول الخطة المرجعية الآمنة (صعود ثم طيران أفقي ثم هبوط)، مع تحريك 6 نقاط توجيه
    داخلية بضجيج غاوسي من 1 إلى 40 م: من الآمنة تمامًا إلى غير الآمنة بوضوح."""
    base = climb_over_plan(scn)
    lo, hi = scn.bounds
    for i in range(n):
        sigma = [1.0, 3.0, 10.0, 40.0][i % 4]
        plan = []
        for P in base:
            s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
            t = np.linspace(0, s[-1], 8)
            Q = np.stack([np.interp(t, s, P[:, c]) for c in range(3)], axis=1)
            Q[1:-1] = np.clip(Q[1:-1] + rng.normal(0, sigma, (6, 3)), lo, hi)
            plan.append(Q)
        yield plan


@pytest.mark.parametrize("path, n", [(MAIN[0], 40), (MAIN[1], 24), (MAIN[2], 8)], ids=["small", "medium", "large"])
def test_validator_agrees_with_the_fitness_function(path, n):
    """فحصان مستقلان وحكم واحد: على الخطة كاملة، وعلى كل مسيّرة وحدها، وأقرب اقتراب نفسه
    بين المسيّرات (بعينات كل 0.01 ث هنا، ومحلول بدقة في geometry.py)."""
    scn = load_scenario(path)
    pb = Problem(scn, budget=10**9)
    alone = []
    for m in scn.missions:
        one = copy.deepcopy(scn)
        one.missions = [m]
        one.problem = dict(one.problem, n_drones=1)
        alone.append((one, Problem(one, budget=10**9)))
    kinds = {True: 0, False: 0}
    for plan in noisy_plans(scn, n, np.random.default_rng(7)):
        checks = [(scn, pb, plan)] + ([(one, p1, [plan[k]]) for k, (one, p1) in enumerate(alone)] if pb.K > 1 else [])
        for city, problem, paths in checks:
            rep = check_plan(city, paths)
            if near_a_limit(rep, city):
                continue
            info = problem.evaluate_paths(paths, count=False)[1]
            assert rep["valid"] == info["feasible"], rep["problems"]
            if problem.K > 1:
                assert rep["min_separation_m"] == pytest.approx(info["d_min_m"], abs=0.01)
            kinds[rep["valid"]] += 1
    assert kinds[True] >= 3 and kinds[False] >= 3                  # اختُبر الحكمان كلاهما فعلًا


# النتائج المحفوظة
@pytest.mark.skipif(not SAVED, reason="no saved runs in results/quick")
@pytest.mark.parametrize("path", SAVED, ids=lambda p: Path(p).stem)
def test_every_saved_plan_passes_the_independent_check(path):
    rep = check_result_file(path)
    assert rep["agrees_with_fitness"], rep["problems"]
    if rep["fitness_feasible"]:
        assert rep["valid"] and rep["min_margin_linf_m"] >= 5.0 and rep["max_hazard"] < 0.5


def test_command_line_exit_code(tmp_path, capsys):
    scn = load_scenario(SIMULATION / "scenarios/small.json")
    good = {"algorithm": "hand", "scenario": "small", "seed": 0, "feasible": True,
            "paths": [[list(m.S), [m.S[0], m.S[1], 140.0], [m.G[0], m.G[1], 140.0], list(m.G)] for m in scn.missions]}
    assert check_plan(scn, good["paths"])["valid"]
    (tmp_path / "good.json").write_text(json.dumps(good))
    assert V.main([str(tmp_path)]) == 0
    bad = dict(good, paths=[[list(m.S), list(m.G)] for m in scn.missions])        # مباشرة عبر المدينة
    (tmp_path / "bad.json").write_text(json.dumps(bad))
    assert V.main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "2 plans checked: 1 valid, 1 breaking a rule, 1 disagreeing" in out
