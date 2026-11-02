"""اختبارات خوارزمية أسراب الجسيمات (PSO في simulation/ga_pso.py)."""
import json

import numpy as np
import pytest

from simulation.fitness import algorithm_params, run_once, RandomSearch
from simulation.ga_pso import GA, PSO
from simulation.scenarios import load_scenario, ROOT as SIMULATION
from simulation.fitness import Problem, climb_over_plan

SMALL = load_scenario(SIMULATION / "scenarios/small.json")
MEDIUM = load_scenario(SIMULATION / "scenarios/medium.json")


# المعاملات
def test_defaults_come_from_the_config_file():
    pso = PSO()
    assert pso.params == algorithm_params("pso")
    assert [algorithm_params("pso", s)["pop_size"] for s in ("small", "medium", "large")] == [40, 60, 80]
    assert pso.population_size(Problem(MEDIUM)) == 60


@pytest.mark.parametrize("bad", [{"topology": "star"}, {"r_mode": "random"}, {"w": -0.1}, {"c1": float("nan")},
                                 {"v_max": 0}, {"v_max": 1.5}, {"init_velocity": 2}, {"ring_k": 0},
                                 {"pop_size": 1}, {"restart_mode": "again"}, {"restart_stall": 0},
                                 {"stall_tol": 1.0}, {"restart_sigma": 0}, {"w_end": -1}, {"speed": 3}])
def test_bad_parameters_are_rejected(bad):
    with pytest.raises(ValueError):
        PSO(**bad)


# اللبنات الأساسية
def test_neighbourhood_best():
    f = np.array([5.0, 1.0, 7.0, 3.0, 9.0, 0.5, 8.0, 6.0])
    assert np.all(PSO.neighbourhood_best(f, "global", 1) == 5)
    ring = PSO.neighbourhood_best(f, "ring", 1)            # أفضل (i-1, i, i+1) على الحلقة
    assert ring.tolist() == [1, 1, 1, 3, 5, 5, 5, 0]
    assert np.all(PSO.neighbourhood_best(f[:3], "ring", 1) == 1)   # حلقة بحجم السرب = الطوبولوجيا العامة


def test_step_respects_speed_limit_bounds_and_walls():
    rng = np.random.default_rng(0)
    lo, hi = np.zeros(6), np.full(6, 100.0)
    vmax = 0.2 * (hi - lo)
    X = rng.uniform(0, 100, (500, 6))
    V = rng.uniform(-50, 50, (500, 6))
    pbest = rng.uniform(-200, 300, (500, 6))                # بعيد جدًا: يفرض قفزات كبيرة واصطدامًا بالجدران
    guide = rng.uniform(-200, 300, (500, 6))
    X2, V2 = PSO.step(X, V, pbest, guide, 0.7298, 1.49618, 1.49618, vmax, lo, hi, rng)
    assert np.all(np.abs(V2) <= vmax + 1e-12)
    assert np.all((X2 >= lo) & (X2 <= hi))
    walls = (X2 == lo) | (X2 == hi)
    assert walls.any() and np.all(V2[walls] == 0)                       # الجدران الماصّة توقف الجسيم


def test_step_with_no_attraction_only_keeps_inertia():
    rng = np.random.default_rng(1)
    lo, hi = np.full(6, -1e9), np.full(6, 1e9)
    X, V = rng.normal(size=(10, 6)), rng.normal(size=(10, 6))
    X2, V2 = PSO.step(X, V, X, X, 0.5, 1.5, 1.5, np.full(6, 1e9), lo, hi, rng)
    assert np.allclose(V2, 0.5 * V) and np.allclose(X2, X + 0.5 * V)


def test_random_factor_modes():
    rng = np.random.default_rng(2)
    d = PSO.random_factors((4, 12), "dimension", rng)
    w = PSO.random_factors((4, 12), "waypoint", rng)
    p = PSO.random_factors((4, 12), "particle", rng)
    assert d.shape == w.shape == p.shape == (4, 12)
    assert len(np.unique(d)) == 48
    assert np.all(w.reshape(4, 4, 3) == w.reshape(4, 4, 3)[..., :1])      # إحداثيات x وy وz لنقطة التوجيه تتشارك r
    assert np.all(p == p[:, :1])                                          # قيمة r واحدة للخطة كلها


# البحث
def test_same_seed_same_run_and_budget_is_exact():
    r1 = run_once(PSO(), SMALL, seed=11, budget=1500)
    r2 = run_once(PSO(), SMALL, seed=11, budget=1500)
    assert r1.best_f == r2.best_f and r1.paths == r2.paths and r1.iter_history == r2.iter_history
    assert r1.fe_used == 1500 and r1.iter_history[0][1] == 40
    assert run_once(PSO(), SMALL, seed=12, budget=1500).paths != r1.paths


def test_pso_starts_from_the_same_plans_as_the_ga():
    """مقارنة عادلة: بالبذرة نفسها تقيّم الخوارزميتان المجتمع الابتدائي نفسه."""
    g = run_once(GA(), MEDIUM, seed=3, budget=60)
    p = run_once(PSO(), MEDIUM, seed=3, budget=60)
    assert g.best_f == p.best_f and g.paths == p.paths


def test_the_best_never_gets_worse():
    r = run_once(PSO(), MEDIUM, seed=0, budget=1500)
    curve = [b for _, _, b in r.iter_history]
    assert all(y <= x for x, y in zip(curve, curve[1:])) and curve[-1] == r.best_f


def test_restarts_happen_and_keep_the_budget():
    r = run_once(PSO(restart_stall=1, stall_tol=0.5), SMALL, seed=0, budget=800)
    assert r.extra["restarts"] > 0 and r.fe_used == 800
    r = run_once(PSO(restart_stall=None), SMALL, seed=0, budget=800)
    assert r.extra["restarts"] == 0


@pytest.mark.parametrize("budget", [1, 39, 40, 41, 79])
def test_any_budget_works(budget):
    r = run_once(PSO(), SMALL, seed=0, budget=budget)
    assert r.fe_used == budget and np.isfinite(r.best_f)


def test_optional_stopping_criteria():
    r = run_once(PSO(max_stall=3, restart_stall=None), SMALL, seed=0, budget=10_000)
    assert r.extra["stopped_by"] == "max_stall" and r.fe_used < 10_000
    r = run_once(PSO(target_f=50.0), SMALL, seed=0, budget=10_000)
    assert r.extra["stopped_by"] == "target_f" and r.best_f <= 50.0
    assert run_once(PSO(), SMALL, seed=0, budget=500).extra["stopped_by"] == "budget"


def test_every_variant_runs_on_every_size():
    large = load_scenario(SIMULATION / "scenarios/large.json")
    variants = [{"topology": "ring"}, {"r_mode": "dimension"}, {"r_mode": "waypoint"}, {"init_velocity": 0.5},
                {"w": 0.9, "w_end": 0.4}, {"restart_mode": "around_best", "restart_stall": 1, "stall_tol": 0.5}]
    for scn in (SMALL, MEDIUM, large):
        for v in variants:
            r = run_once(PSO(**v), scn, seed=0, budget=300)
            assert r.fe_used == 300 and np.isfinite(r.best_f)


def test_solutions_stay_inside_the_flight_space():
    pb = Problem(MEDIUM, budget=1200)
    run_once(PSO(), MEDIUM, seed=4, problem=pb)
    w = pb.waypoints(pb.best_x)
    assert np.all(w >= pb.bounds[0]) and np.all(w <= pb.bounds[1])


def test_pso_solves_the_small_city():
    ref = Problem(SMALL).evaluate_paths(climb_over_plan(SMALL), count=False)[0]
    r = run_once(PSO(), SMALL, seed=1)
    assert r.feasible and r.fe_used == 10_000
    assert 1.5 <= r.best_f < 0.6 * ref
    assert r.report["min_clearance_m"] >= 5.0
    json.dumps(r.to_dict())


def test_pso_beats_random_search_with_the_same_budget():
    pso = [run_once(PSO(), MEDIUM, seed=s, budget=3000).best_f for s in range(3)]
    rs = [run_once(RandomSearch(), MEDIUM, seed=s, budget=3000).best_f for s in range(3)]
    assert max(pso) < min(rs)
