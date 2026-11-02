"""اختبارات تعريفات المسألة والمُحسِّن والنتيجة المشتركة في simulation/fitness.py."""
import copy
import glob
import json
import math

import numpy as np
import pytest

from simulation.fitness import Optimizer, run_once, RandomSearch
from simulation.scenarios import Building, Fire, Mission, load_scenario, ROOT as SIMULATION
from simulation.fitness import BudgetExhausted, Problem, climb_over_plan, load_fitness_config

ALL_CITIES = sorted(glob.glob(str(SIMULATION / "scenarios/*.json")) + glob.glob(str(SIMULATION / "scenarios/random/*.json")))
CFG = load_fitness_config()
W = CFG["weights"]
M, P0 = CFG["penalty"]["M"], CFG["penalty"]["P0"]


def world(buildings=(), fires=(), missions=(([20, 150, 10], [220, 150, 10]),), battery_kj=799, N=3):
    """مدينة صغيرة يدوية فوق المدينة الصغيرة الحقيقية (الإعدادات نفسها بمحتوى من عندنا)."""
    scn = copy.deepcopy(load_scenario(SIMULATION / "scenarios/small.json"))
    scn.buildings = [Building(i, *b) for i, b in enumerate(buildings)]
    scn.fires = [Fire(i, 0, "E", list(c), [1.0, 0.0, 0.0], R, I, 80.0) for i, (c, R, I) in enumerate(fires)]
    scn.missions = [Mission(k, 0, list(map(float, s)), list(map(float, g))) for k, (s, g) in enumerate(missions)]
    scn.drone = dict(scn.drone, battery_kj=battery_kj)
    scn.problem = dict(scn.problem, n_waypoints=N, n_drones=len(missions))
    return scn


def line(*pts):
    return np.array(pts, dtype=float)


# الأهداف الأربعة
def test_straight_line_in_empty_city_scores_wT_plus_wE():
    pb = Problem(world())
    F, info = pb.evaluate_paths([line([20, 150, 10], [220, 150, 10])])
    assert info["feasible"] and info["J_T"] == [1.0] and info["J_E"] == [1.0]
    assert info["J_H"] == [0.0] and info["J_S"] == [0.0]
    assert F == pytest.approx(W["w_T"] + W["w_E"])


def test_detour_length_and_turns():
    pb = Problem(world())
    detour = line([20, 150, 10], [120, 250, 10], [220, 150, 10])       # ضلعان بزاوية 45 درجة
    F, info = pb.evaluate_paths([detour])
    L = 2 * math.hypot(100, 100)
    assert info["J_T"][0] == pytest.approx(L / 200)
    assert info["J_E"][0] == pytest.approx(L / 200)                     # طيران أفقي: تزيد E مع L
    assert info["J_S"][0] == pytest.approx(0.5 ** 2)                    # انعطاف واحد بزاوية 90 درجة
    assert F == pytest.approx(W["w_T"] * L / 200 + W["w_E"] * L / 200 + W["w_S"] * 0.25)


def test_climbing_costs_energy():
    pb = Problem(world(missions=(([20, 150, 10], [220, 150, 60]),)))
    F, info = pb.evaluate_paths([line([20, 150, 10], [220, 150, 60])])
    assert info["J_E"][0] == pytest.approx(1.0)                         # الخط المستقيم = المرجع
    hop = line([20, 150, 10], [120, 150, 110], [220, 150, 60])          # تصعد 100 م بدل 50 م
    E = 20 * (math.hypot(100, 100) + math.hypot(100, 50)) + 100 * 100
    E_ref = 20 * math.hypot(200, 50) + 100 * 50
    assert pb.evaluate_paths([hop])[1]["J_E"][0] == pytest.approx(E / E_ref)


def test_hazard_exposure_term():
    pb = Problem(world(fires=(([120, 200, 10], 15.0, 1.0),)))
    _, far = pb.evaluate_paths([line([20, 150, 10], [220, 150, 10])])    # على بعد 50 م من الحريق
    _, near = pb.evaluate_paths([line([20, 150, 10], [120, 180, 10], [220, 150, 10])])
    assert 0 < far["J_H"][0] < near["J_H"][0]


# القيود
def test_collision_with_a_tower():
    pb = Problem(world(buildings=((100, 130, 140, 170, 60),)))
    F, info = pb.evaluate_paths([line([20, 150, 10], [220, 150, 10])])
    inside = 40 + 2 * 5                                                 # برج عرضه 40 م مع هامشين 5 م
    assert info["collision_m"][0] == pytest.approx(inside)
    assert info["V_col"][0] == pytest.approx(inside / 200) and not info["feasible"]
    assert F == pytest.approx(info["F_obj"] + M * inside / 200 + P0)
    over = line([20, 150, 10], [90, 150, 70], [150, 150, 70], [220, 150, 10])   # أعلى من هامش السطح بـ 5 م
    assert pb.evaluate_paths([over])[1]["feasible"]


def test_fire_core_is_forbidden():
    pb = Problem(world(fires=(([120, 150, 10], 15.0, 1.0),)))
    F, info = pb.evaluate_paths([line([20, 150, 10], [220, 150, 10])])  # مباشرة عبر الحريق
    core = 2 * 15 * math.sqrt(math.log(2))
    assert info["core_m"][0] == pytest.approx(core, abs=2.0) and not info["feasible"]
    assert F > P0


def test_battery_limit():
    pb = Problem(world(battery_kj=4.0))                                  # E_max = 3.2 kJ
    F, info = pb.evaluate_paths([line([20, 150, 10], [220, 150, 10])])  # تحتاج 4.0 kJ
    assert info["V_bat"][0] == pytest.approx((4000 - 3200) / 3200) and not info["feasible"]


def test_separation_between_drones():
    two = (([20, 150, 50], [220, 150, 50]), ([220, 150, 50], [20, 150, 50]))
    pb = Problem(world(missions=two))
    head_on = [line(*two[0]), line(*two[1])]
    F, info = pb.evaluate_paths(head_on)
    assert info["d_min_m"] == pytest.approx(0.0, abs=1e-9) and info["V_sep"] == pytest.approx(1.0)
    assert not info["feasible"]
    lifted = [line([20, 150, 50], [70, 150, 50], [120, 150, 65], [170, 150, 50], [220, 150, 50]), head_on[1]]
    _, info2 = pb.evaluate_paths(lifted)        # تقفز 15 م للأعلى حيث تلتقيان (المسار الأطول يزيح
    assert 10.0 < info2["d_min_m"] <= 15.0      # نقطة الالتقاء قليلًا، فيكون d_min أقل بقليل من 15 م)
    assert info2["V_sep"] == 0.0 and info2["feasible"]


def test_bounds_and_decode_clipping():
    pb = Problem(world())
    _, info = pb.evaluate_paths([line([20, 150, 10], [120, 150, 400], [220, 150, 10])])
    assert info["V_bound"][0] > 0 and not info["feasible"]
    x = np.full(pb.dim, 1e6)
    assert np.all(pb.decode(x)[0][1:-1] == pb.bounds[1])                # decode يقص القيم إلى داخل الحيّز
    assert pb.evaluate_paths(pb.decode(x), count=False)[1]["V_bound"][0] == 0.0


# الترتيب في الخطط المسحوبة: الخطط الآمنة قبل غير الآمنة
@pytest.mark.parametrize("path", [SIMULATION / "scenarios/small.json", SIMULATION / "scenarios/medium.json", SIMULATION / "scenarios/large.json"])
def test_sampled_safe_plans_outrank_sampled_unsafe_plans(path):
    """يفحص هذه العينة والخطة المرجعية؛ فالعقوبات المحدودة لا تضمن ترتيبًا عامًا."""
    scn = load_scenario(path)
    pb = Problem(scn, budget=10**9)
    rng = np.random.default_rng(0)
    X = pb.initial_population(150, rng)
    F, feas = [], []
    for x in X:
        f, info = pb.evaluate_paths(pb.decode(x), count=False)
        F.append(f)
        feas.append(info["feasible"])
    f_ref, info_ref = pb.evaluate_paths(climb_over_plan(scn), count=False)
    F, feas = np.array(F + [f_ref]), np.array(feas + [info_ref["feasible"]])
    assert feas.any() and (~feas).any()
    assert F[feas].max() < F[~feas].min()


@pytest.mark.parametrize("path", ALL_CITIES)
def test_every_city_has_a_safe_reference_plan(path):
    """خطة الصعود فوق الأبراج آمنة في المدن الثلاث والثلاثين كلها، فكل مهمة قابلة للحل،
    وقيمة F لها أقل بكثير من P0 (حد أعلى يُنتظر أن تتفوق عليه الخوارزميات)."""
    scn = load_scenario(path)
    pb = Problem(scn)
    rep = pb.report(climb_over_plan(scn))
    assert rep["feasible"] and rep["F"] < 10 < P0
    assert rep["min_clearance_m"] >= scn.world["d_safe"]
    if pb.K > 1:
        assert rep["min_separation_m"] >= scn.drone["d_sep"]


# الواجهة البرمجية
def test_evaluate_matches_evaluate_paths_and_is_deterministic():
    scn = load_scenario(SIMULATION / "scenarios/medium.json")
    pb = Problem(scn)
    x = pb.initial_population(5, np.random.default_rng(1))[3]
    f1 = pb.evaluate(x)
    f2, _ = pb.evaluate_paths(pb.decode(x))
    assert f1 == f2 == pb.evaluate(x)
    assert pb.fe == 3


def test_encode_decode_round_trip():
    pb = Problem(load_scenario(SIMULATION / "scenarios/large.json"))
    x = pb.random_x(np.random.default_rng(2))
    paths = pb.decode(x)
    assert len(paths) == pb.K and all(p.shape == (pb.N + 2, 3) for p in paths)
    assert np.allclose(paths[0][0], pb.S[0]) and np.allclose(paths[-1][-1], pb.G[-1])
    assert np.allclose(pb.encode(paths), x)
    assert pb.dim == {"small": 18, "medium": 90, "large": 210}[pb.scn.size]


def test_initial_population():
    pb = Problem(load_scenario(SIMULATION / "scenarios/medium.json"))
    X1 = pb.initial_population(50, np.random.default_rng(7))
    X2 = pb.initial_population(50, np.random.default_rng(7))
    assert X1.shape == (50, pb.dim) and np.array_equal(X1, X2)          # البذرة نفسها، البداية نفسها
    assert np.all(X1 >= pb.lower) and np.all(X1 <= pb.upper)
    d_line = np.abs(X1 - pb.straight_line_x()).mean(axis=1)
    assert d_line[:10].max() < d_line[10:].min()                        # أول 20% تلازم الخط المستقيم


def test_budget_counting_history_and_snapshots():
    pb = Problem(load_scenario(SIMULATION / "scenarios/small.json"), budget=100)
    rng = np.random.default_rng(3)
    for _ in range(4):
        pb.evaluate_batch(pb.initial_population(25, rng))
        pb.end_iteration()
    assert pb.done and pb.remaining == 0 and pb.fe == 100
    with pytest.raises(BudgetExhausted):
        pb.evaluate(pb.straight_line_x())
    bests = [b for _, b in pb.history]
    assert bests == sorted(bests, reverse=True) and bests[-1] == pb.best_f
    assert [i for i, _, _ in pb.iter_history] == [1, 2, 3, 4]
    assert len(pb.snapshots) == len(CFG["snapshots"]) and pb.snapshots[-1]["fe"] == 100
    pb.reset()
    assert pb.fe == 0 and pb.best_f == math.inf and pb.history == []


class Greedy(Optimizer):          # تطلب تقييمات أكثر من المسموح عمدًا
    name = "Greedy"

    def search(self, problem, rng):
        while True:
            problem.evaluate(problem.random_x(rng))


def test_run_once_stops_cleanly_at_the_budget():
    scn = load_scenario(SIMULATION / "scenarios/small.json")
    r = run_once(Greedy(), scn, seed=0, budget=37)
    assert r.fe_used == 37 and r.iter_history[-1][1] == 37


def test_run_once_with_the_example_algorithm():
    scn = load_scenario(SIMULATION / "scenarios/small.json")
    r1 = run_once(RandomSearch(batch=40), scn, seed=5, budget=400)
    r2 = run_once(RandomSearch(batch=40), scn, seed=5, budget=400)
    assert r1.best_f == r2.best_f and r1.paths == r2.paths              # البذرة نفسها، التشغيل نفسه
    assert r1.fe_used == 400 and r1.feasible and r1.first_feasible_fe is not None
    assert r1.report["drones"][0]["clearance_m"] >= 5.0
    json.dumps(r1.to_dict())                                            # يمكن حفظ النتائج بصيغة JSON


@pytest.mark.parametrize("path", ALL_CITIES)
def test_flying_straight_never_solves_a_city(path):
    """خط مستقيم واحد على الأقل S -> G يخترق هامش برج، فكل مدينة تحتاج تخطيط مسار حقيقيًا."""
    scn = load_scenario(path)
    pb = Problem(scn)
    F, info = pb.evaluate_paths([np.array([m.S, m.G]) for m in scn.missions], count=False)
    assert not info["feasible"] and sum(info["collision_m"]) > 0


def test_weights_are_balanced_on_the_real_cities():
    """الزمن في المقدمة (سرعة الإنقاذ أولًا)، لكن لا حد مهمل ولا حد يطغى على البقية."""
    from simulation.fitness import weight_justification
    r = weight_justification()
    share = r["share_mean"]
    assert max(share, key=share.get) == "time"
    assert all(v > 0.03 for v in r["share_min"].values()) and all(v < 0.7 for v in r["share_max"].values())
    assert 70 < r["turn_deg"] < 90                      # انعطاف حاد واحد ~ مسار أطول بنحو 10%


def test_saved_plan_is_exactly_the_scored_plan():
    """تحتفظ Result بالدقة الكاملة، فإعادة تقييم المسارات المحفوظة تعطي F والحكم نفسيهما."""
    r = run_once(RandomSearch(batch=40), load_scenario(SIMULATION / "scenarios/medium.json"), seed=2, budget=200)
    pb = Problem(load_scenario(SIMULATION / "scenarios/medium.json"))
    F, info = pb.evaluate_paths([np.array(p) for p in r.paths], count=False)
    assert F == r.best_f and info["feasible"] == r.feasible
    assert r.snapshots[-1]["paths"] == r.paths
