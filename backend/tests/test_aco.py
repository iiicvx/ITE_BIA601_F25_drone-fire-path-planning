"""اختبارات خوارزمية مستعمرة النمل (ACO في simulation/aco_dp.py)."""
import copy
import json

import numpy as np
import pytest

from simulation.aco_dp import ACO, city_graph
from simulation.fitness import algorithm_params, run_once, RandomSearch
from simulation import geometry as G
from simulation.grid import MOVES
from simulation.scenarios import Mission, load_scenario, ROOT as SIMULATION
from simulation.fitness import Problem, climb_over_plan

SMALL = load_scenario(SIMULATION / "scenarios/small.json")
MEDIUM = load_scenario(SIMULATION / "scenarios/medium.json")


def ready(scn, **params):
    """كائن ACO مهيأ للمدينة scn كما يهيئه search() (لاختبار أجزائه)."""
    aco = ACO(**params)
    pb = Problem(scn)
    aco.prepare(pb)
    return aco, pb


# المعاملات
def test_defaults_come_from_the_config_file():
    aco = ACO()
    assert aco.params == algorithm_params("aco")
    assert [algorithm_params("aco", s)["pop_size"] for s in ("small", "medium", "large")] == [40, 60, 80]
    assert aco.population_size(Problem(MEDIUM)) == 60


@pytest.mark.parametrize("bad", [{"alpha": -1}, {"beta": float("inf")}, {"rho": 0}, {"rho": 1},
                                 {"tau_ratio": 1}, {"gb_every": 0}, {"step_factor": 0.5}, {"prune": "yes"},
                                 {"pop_size": 0}, {"lambda_h": -3}, {"conflict_margin": -1}, {"ants": 10}])
def test_bad_parameters_are_rejected(bad):
    with pytest.raises(ValueError):
        ACO(**bad)


# الشبكة
def test_neighbour_table_matches_the_grid():
    g = city_graph(SMALL)
    grid, nbr = g["grid"], g["nbr"]
    assert nbr.shape == (grid.n_cells, 26) and g["H"].shape == (grid.n_cells,)
    rng = np.random.default_rng(0)
    for c in rng.choice(np.flatnonzero(grid.free.ravel()), 300, replace=False):
        cell = grid.unflat(int(c))
        allowed = {grid.flat(nb) for nb, _ in grid.neighbors(cell)}
        assert set(int(x) for x in nbr[c] if x >= 0) == allowed
    assert np.all(nbr[~grid.free.ravel()] < 0)                            # لا يخرج أي انتقال من خلية محجوبة
    assert city_graph(SMALL) is g                                          # تُبنى مرة واحدة ثم تُخزَّن


def test_cache_tells_different_cities_apart():
    other = copy.deepcopy(SMALL)
    other.buildings[0].h += 20                                            # الاسم نفسه بمحتوى مختلف
    assert city_graph(other) is not city_graph(SMALL)


# النمل
def test_ant_paths_are_valid_walks_on_the_grid():
    aco, pb = ready(MEDIUM)
    g = city_graph(MEDIUM)
    grid = g["grid"]
    tau = np.ones(grid.n_cells)
    path, length, failed = aco.construct(0, 40, tau, [], np.random.default_rng(1))
    assert (~failed).sum() >= 35
    free = grid.free.ravel()
    for a in np.flatnonzero(~failed):
        c = path[a, :length[a]]
        assert c[0] == aco._start[0] and c[-1] == aco._goal[0]
        assert len(np.unique(c)) == len(c)                                  # قائمة المحظورات: لا تُزار خلية مرتين
        assert free[c].all()
        steps = np.array([np.subtract(grid.unflat(int(b)), grid.unflat(int(a_))) for a_, b in zip(c[:-1], c[1:])])
        for s_, a_ in zip(steps, c[:-1]):
            m = next(i for i, mv in enumerate(MOVES) if tuple(mv) == tuple(s_))
            assert grid.allowed[m].ravel()[a_]                              # كل خطوة انتقال مسموح
    assert not aco._visited.any()                                           # تُفرَّغ قوائم المحظورات بعد ذلك


@pytest.mark.parametrize("scn", [SMALL, MEDIUM], ids=["small", "medium"])
def test_pruned_paths_are_safe_shorter_and_keep_the_ends(scn):
    aco, pb = ready(scn)
    grid = city_graph(scn)["grid"]
    for k in range(pb.K):
        path, length, failed = aco.construct(k, 30, np.ones(grid.n_cells), [], np.random.default_rng(k))
        for a in np.flatnonzero(~failed):
            raw = np.vstack([pb.S[k], city_graph(scn)["centers"][path[a, :length[a]]], pb.G[k]])
            P = aco.prune(raw)
            assert np.allclose(P[0], pb.S[k]) and np.allclose(P[-1], pb.G[k])
            assert G.collision_length(P, pb.boxes) == 0.0
            assert pb.field.path_hazard(P, ds=0.5)["max_hazard"] < pb.field.tau_core
            assert G.path_length(P) <= G.path_length(raw) + 1e-9
            assert len(P) <= len(raw)


def test_core_boxes_contain_the_whole_core():
    aco, pb = ready(MEDIUM)
    rng = np.random.default_rng(3)
    for f in MEDIUM.fires:
        P = np.array(f.c) + rng.uniform([-150, -150, -60], [150, 150, 300], (200_000, 3))
        P = P[pb.field.H(P) >= MEDIUM.hazard["grid_tau"]]
        inside = np.all((P[:, None, :] >= aco._cores[None, :, :3]) & (P[:, None, :] <= aco._cores[None, :, 3:]),
                        axis=2).any(axis=1)
        assert len(P) > 0 and inside.all()


def test_positions_on_padded_paths_and_hover():
    T = np.array([[0.0, 10.0, np.inf], [0.0, 5.0, 15.0]])
    P = np.array([[[0, 0, 0], [100, 0, 0], [100, 0, 0]], [[0, 0, 0], [0, 50, 0], [0, 50, 100]]], float)
    q = np.array([[5.0, 30.0], [10.0, 20.0]])
    pos = ACO._positions(T, P, q)
    assert np.allclose(pos, [[[50, 0, 0], [100, 0, 0]], [[0, 50, 50], [0, 50, 100]]])


def test_later_drones_avoid_earlier_ones():
    """مسيّرتان يتقاطع خطاهما المستقيمان في اللحظة نفسها: الخطة الناتجة تبقيهما متباعدتين."""
    scn = copy.deepcopy(SMALL)
    scn.buildings, scn.fires = scn.buildings[:0], scn.fires[:0]
    scn.missions = [Mission(0, 0, [20.0, 150.0, 60.0], [220.0, 150.0, 60.0]),
                    Mission(1, 0, [120.0, 50.0, 60.0], [120.0, 250.0, 60.0])]
    scn.problem = dict(scn.problem, n_drones=2)
    r = run_once(ACO(), scn, seed=0, budget=200)
    assert r.feasible and r.report["min_separation_m"] >= scn.drone["d_sep"]


# البحث
def test_same_seed_same_run_and_budget_is_exact():
    r1 = run_once(ACO(), SMALL, seed=11, budget=400)
    r2 = run_once(ACO(), SMALL, seed=11, budget=400)
    assert r1.best_f == r2.best_f and r1.paths == r2.paths and r1.iter_history == r2.iter_history
    assert r1.fe_used == 400
    assert all(b - a == 40 for (_, a, _), (_, b, _) in zip(r1.iter_history[:-1], r1.iter_history[1:]))


def test_the_best_never_gets_worse():
    r = run_once(ACO(), MEDIUM, seed=0, budget=600)
    curve = [b for _, _, b in r.iter_history]
    assert all(y <= x for x, y in zip(curve, curve[1:])) and curve[-1] == r.best_f


@pytest.mark.parametrize("budget", [1, 39, 40, 41])
def test_any_budget_works(budget):
    r = run_once(ACO(), SMALL, seed=0, budget=budget)
    assert r.fe_used == budget and np.isfinite(r.best_f)


def test_failed_ants_are_handled():
    r = run_once(ACO(step_factor=1.0), MEDIUM, seed=0, budget=180)    # خطوات قليلة جدًا: تفشل نمال كثيرة
    assert r.fe_used == 180 and max(r.extra["failed_ants"]) > 0 and np.isfinite(r.best_f)


def test_optional_stopping_criteria():
    r = run_once(ACO(max_stall=3), SMALL, seed=0, budget=10_000)
    assert r.extra["stopped_by"] == "max_stall" and r.fe_used < 10_000
    r = run_once(ACO(target_f=50.0), SMALL, seed=0, budget=10_000)
    assert r.extra["stopped_by"] == "target_f" and r.best_f <= 50.0


def test_every_variant_runs_on_every_size():
    large = load_scenario(SIMULATION / "scenarios/large.json")
    variants = [{"prune": False}, {"gb_every": 1}, {"climb_weight": 2.0}, {"lambda_h": 0.0},
                {"conflict_margin": 0}, {"alpha": 2.0, "beta": 1.0}]
    for scn in (SMALL, MEDIUM, large):
        for v in variants:
            budget = 2 * ACO(**v).population_size(Problem(scn))
            r = run_once(ACO(**v), scn, seed=0, budget=budget)
            assert r.fe_used == budget and np.isfinite(r.best_f)


def test_aco_solves_the_small_city():
    ref = Problem(SMALL).evaluate_paths(climb_over_plan(SMALL), count=False)[0]
    r = run_once(ACO(), SMALL, seed=1, budget=2000)
    assert r.feasible and 1.5 <= r.best_f < 0.6 * ref
    assert r.report["min_clearance_m"] >= 5.0
    json.dumps(r.to_dict())


def test_aco_beats_random_search_with_the_same_budget():
    aco = [run_once(ACO(), MEDIUM, seed=s, budget=600).best_f for s in range(2)]
    rs = [run_once(RandomSearch(), MEDIUM, seed=s, budget=600).best_f for s in range(2)]
    assert max(aco) < min(rs)
