"""اختبارات الخوارزمية الجينية (GA في simulation/ga_pso.py)."""
import json

import numpy as np
import pytest

from simulation.fitness import algorithm_params, run_once, RandomSearch
from simulation.ga_pso import GA
from simulation.scenarios import load_scenario, ROOT as SIMULATION
from simulation.fitness import Problem, climb_over_plan

SMALL = load_scenario(SIMULATION / "scenarios/small.json")
MEDIUM = load_scenario(SIMULATION / "scenarios/medium.json")


# المعاملات
def test_defaults_come_from_the_config_file():
    ga = GA()
    cfg = algorithm_params("ga")
    assert ga.params == cfg
    assert [algorithm_params("ga", s)["pop_size"] for s in ("small", "medium", "large")] == [40, 60, 80]
    assert ga.population_size(Problem(MEDIUM)) == 60


@pytest.mark.parametrize("bad", [{"crossover": "magic"}, {"crossover": "sbx+sbx"}, {"p_c": 1.5},
                                 {"p_mut": -1}, {"eta_c": -2}, {"sigma_start": -0.1},
                                 {"tournament_k": 0}, {"pop_size": 3}, {"popsize": 40}])
def test_bad_parameters_are_rejected(bad):
    with pytest.raises(ValueError):
        GA(**bad)


# العمليات
def test_tournament_picks_the_best_of_k():
    rng = np.random.default_rng(0)
    f = np.arange(100, dtype=float)
    win = GA.tournament(f, 5000, 3, rng)
    assert np.mean(win) < 30                         # أفضل 3 سحبات متوقعة من 0..99 نحو 25
    assert GA.tournament(f, 200, 100, rng).max() < 20 and np.all(GA.tournament(f, 50, 1, rng) < 100)


def test_sbx_keeps_the_parents_mean_and_stays_near_them():
    rng = np.random.default_rng(1)
    a, b = rng.uniform(0, 100, (500, 30)), rng.uniform(0, 100, (500, 30))
    c1, c2 = GA.sbx(a, b, eta=15, rng=rng)
    assert np.allclose(c1 + c2, a + b)                # SBX متماثل حول متوسط الأبوين
    assert np.mean(np.abs(c1 - a) <= np.abs(b - a) + 1e-9) > 0.95


def test_segment_and_drone_crossover_only_swap_genes():
    rng = np.random.default_rng(2)
    K, N = 3, 10
    a, b = rng.uniform(0, 1, (200, 3 * K * N)), rng.uniform(2, 3, (200, 3 * K * N))
    for op in (GA.segment, GA.drone):
        c1, c2 = op(a, b, K, N, rng)
        assert np.all((c1 == a) | (c1 == b)) and np.all((c2 == a) | (c2 == b))
        assert np.allclose(c1 + c2, a + b)
        w = (c1 == b).reshape(200, K, N, 3)
        assert np.all(w == w[..., :1])                 # إحداثيات x وy وz لنقطة التوجيه تنتقل معًا دائمًا
    c1, _ = GA.drone(a, b, K, N, rng)
    from_b = (c1 == b).reshape(200, K, N * 3)
    assert np.all(from_b.all(axis=2) | (~from_b).all(axis=2))      # مسار المسيّرة لا يُقسم أبدًا


def test_mutation_rate_and_smooth_shape():
    rng = np.random.default_rng(3)
    K, N = 2, 10
    ga = GA(p_mut=1.0, mut_width=0)
    C = np.zeros((4000, 3 * K * N))
    moved = (ga.mutate(C, K, N, np.array([10.0, 10.0, 10.0]), rng) != 0).reshape(4000, K, N, 3).any(-1)
    assert moved.sum(axis=2).mean() == pytest.approx(1.0, abs=0.05)      # p_mut من مراكز الطفرة لكل مسيّرة
    def moved_per_mutated_drone(width):
        out = GA(p_mut=0.1, mut_width=width).mutate(np.zeros((3000, 3 * K * N)), K, N, np.ones(3),
                                                       np.random.default_rng(9))
        m = (np.abs(out.reshape(3000, K, N, 3)).sum(-1) > 1e-12).sum(-1)      # نقاط التوجيه المتحركة لكل مسيّرة
        return m[m > 0].mean()
    one = 0.1 / (1 - (1 - 0.1 / N) ** N)                                     # نحو 1.05 نقطة مختارة
    assert moved_per_mutated_drone(0) == pytest.approx(one, abs=0.05)        # النقاط المختارة فقط: انكسار حاد
    assert moved_per_mutated_drone(2.5) > 5                                  # الجيران يتبعونها: انحناء ناعم


# البحث
def test_same_seed_same_run_and_budget_is_exact():
    r1 = run_once(GA(), SMALL, seed=11, budget=1500)
    r2 = run_once(GA(), SMALL, seed=11, budget=1500)
    assert r1.best_f == r2.best_f and r1.paths == r2.paths and r1.iter_history == r2.iter_history
    assert r1.fe_used == 1500
    assert r1.iter_history[0][1] == 40                         # الجيل 0 = الخطط الابتدائية الأربعون
    assert all(b - a == 38 for (_, a, _), (_, b, _) in zip(r1.iter_history[:-2], r1.iter_history[1:-1]))
    r3 = run_once(GA(), SMALL, seed=12, budget=1500)
    assert r3.paths != r1.paths


def test_elitism_never_loses_the_best():
    r = run_once(GA(), MEDIUM, seed=0, budget=1500)
    curve = [b for _, _, b in r.iter_history]
    assert all(y <= x for x, y in zip(curve, curve[1:]))
    assert curve[-1] == r.best_f


def test_tiny_budgets_and_population_edge_cases():
    r = run_once(GA(), SMALL, seed=0, budget=10)               # أصغر من مجتمع واحد
    assert r.fe_used == 10 and r.extra["generations"] == 0
    r = run_once(GA(pop_size=4, n_elite=2), SMALL, seed=0, budget=101)
    assert r.fe_used == 101


def test_optional_stopping_criteria():
    r = run_once(GA(max_stall=5), SMALL, seed=0, budget=10_000)
    assert r.extra["stopped_by"] == "max_stall" and r.fe_used < 10_000
    r = run_once(GA(target_f=50.0), SMALL, seed=0, budget=10_000)
    assert r.extra["stopped_by"] == "target_f" and r.best_f <= 50.0
    assert run_once(GA(), SMALL, seed=0, budget=500).extra["stopped_by"] == "budget"


def test_solutions_stay_inside_the_flight_space():
    pb = Problem(MEDIUM, budget=1200)
    run_once(GA(), MEDIUM, seed=4, problem=pb)
    w = pb.waypoints(pb.best_x)
    assert np.all(w >= pb.bounds[0]) and np.all(w <= pb.bounds[1])


def test_ga_solves_the_small_city():
    """الميزانية الكاملة على المدينة الصغيرة: خطة آمنة، أفضل بكثير من خطة الصعود، وقريبة من
    الحد الأدنى 1.5 (خط مستقيم في مدينة خالية)."""
    ref = Problem(SMALL).evaluate_paths(climb_over_plan(SMALL), count=False)[0]
    r = run_once(GA(), SMALL, seed=1)
    assert r.feasible and r.fe_used == 10_000
    assert 1.5 <= r.best_f < 0.5 * ref
    assert r.report["min_clearance_m"] >= 5.0
    json.dumps(r.to_dict())


def test_ga_beats_random_search_with_the_same_budget():
    ga = [run_once(GA(), MEDIUM, seed=s, budget=3000).best_f for s in range(3)]
    rs = [run_once(RandomSearch(), MEDIUM, seed=s, budget=3000).best_f for s in range(3)]
    assert max(ga) < min(rs)


# المتانة (لا انهيار في الحالات الحدية)
@pytest.mark.parametrize("budget", [1, 39, 40, 41, 79])
def test_any_budget_works(budget):
    r = run_once(GA(), SMALL, seed=0, budget=budget)
    assert r.fe_used == budget and np.isfinite(r.best_f)


def test_degenerate_plans_score_finite_and_bad_input_is_rejected():
    pb = Problem(MEDIUM)
    S = pb.S
    stuck = [np.vstack([S[k]] * (pb.N + 2)) for k in range(pb.K)]           # كل نقاط التوجيه على S
    corners = pb.decode(np.where(np.arange(pb.dim) % 2, pb.upper, pb.lower))  # نقاط توجيه على زوايا الصندوق
    for paths in (stuck, corners):
        F, info = pb.evaluate_paths(paths, count=False)
        assert np.isfinite(F) and np.isfinite(info["V"])
    bad = pb.decode(pb.straight_line_x())
    bad[0][2, 1] = np.nan
    with pytest.raises(ValueError):
        pb.evaluate_paths(bad, count=False)
    with pytest.raises(ValueError):
        pb.evaluate_paths(bad[:-1], count=False)                           # عدد مسيّرات خاطئ


def test_ga_runs_on_every_size_and_all_crossover_settings():
    for scn in (SMALL, MEDIUM, load_scenario(SIMULATION / "scenarios/large.json")):
        for cx in ("sbx", "segment", "drone", "drone+segment+sbx"):
            r = run_once(GA(crossover=cx), scn, seed=0, budget=300)
            assert r.fe_used == 300 and np.isfinite(r.best_f)
