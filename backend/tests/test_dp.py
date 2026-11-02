"""اختبارات خط الأساس بالبرمجة الديناميكية (DP في simulation/aco_dp.py، بعلاقة Bellman-Ford)."""
import copy
import glob
import heapq
import json

import numpy as np
import pytest

from simulation.aco_dp import ACO, DP
from simulation.fitness import algorithm_params, run_once
from simulation.grid import PathPruner, city_graph, MOVES
from simulation import geometry as G
from simulation.scenarios import Building, load_scenario, ROOT as SIMULATION
from simulation.fitness import Problem

SMALL = load_scenario(SIMULATION / "scenarios/small.json")
MEDIUM = load_scenario(SIMULATION / "scenarios/medium.json")
ALL_CITIES = sorted(glob.glob(str(SIMULATION / "scenarios/*.json")) + glob.glob(str(SIMULATION / "scenarios/random/*.json")))


def dijkstra(g, start, const, haz):
    """مرجع مستقل: خوارزمية Dijkstra التقليدية بكومة، مكتوبة دون حيل numpy."""
    nbr, H = g["nbr"], g["H"]
    d = np.full(len(nbr), np.inf)
    d[start] = 0.0
    heap = [(0.0, start)]
    while heap:
        du, u = heapq.heappop(heap)
        if du > d[u]:
            continue
        for m in range(nbr.shape[1]):
            v = int(nbr[u, m])
            if v < 0:
                continue
            c = const[m] + haz[m] * 0.5 * (H[u] + H[v])
            if du + c < d[v]:
                d[v] = du + c
                heapq.heappush(heap, (du + c, v))
    return d


def setup(scn, k=0):
    pb = Problem(scn)
    g = city_graph(scn)
    grid = g["grid"]
    start = grid.flat(grid.nearest_free(pb.S[k]))
    goal = grid.flat(grid.nearest_free(pb.G[k]))
    const, haz = DP.step_costs(pb, k)
    return pb, g, start, goal, const, haz


def path_cost(cells, g, const, haz):
    total = 0.0
    for a, b in zip(cells[:-1], cells[1:]):
        m = int(np.flatnonzero(g["nbr"][a] == b)[0])
        total += const[m] + haz[m] * 0.5 * (g["H"][a] + g["H"][b])
    return total


# المعاملات
def test_defaults_and_bad_parameters():
    assert DP().params == algorithm_params("dp")
    for bad in ({"prune": "yes"}, {"max_sweeps": 0}, {"depth": 3}):
        with pytest.raises(ValueError):
            DP(**bad)


# الأمثلية
@pytest.mark.parametrize("scn, k", [(SMALL, 0), (MEDIUM, 0), (MEDIUM, 2)], ids=["small", "medium-0", "medium-2"])
def test_bellman_ford_table_equals_dijkstra_everywhere(scn, k):
    """جدول الكلفة كاملًا (لكل خلية، لا للهدف فقط) يطابق Dijkstra المستقلة."""
    pb, g, start, goal, const, haz = setup(scn, k)
    d_bf, pred, info = DP().bellman_ford(g, start, goal, const, haz)
    d_ref = dijkstra(g, start, const, haz)
    reach = np.isfinite(d_ref)
    assert np.array_equal(np.isfinite(d_bf), reach)
    assert np.allclose(d_bf[reach], d_ref[reach], rtol=0, atol=1e-9)
    assert info["converged"] and info["changed_per_sweep"][-1] == 0      # توقف لأن الجدول استقر


def test_extracted_path_has_the_table_cost_and_valid_steps():
    pb, g, start, goal, const, haz = setup(MEDIUM, 1)
    d, pred, _ = DP().bellman_ford(g, start, goal, const, haz)
    cells = DP.extract(pred, start, goal)
    assert cells[0] == start and cells[-1] == goal and len(np.unique(cells)) == len(cells)
    assert path_cost(cells, g, const, haz) == pytest.approx(d[goal], abs=1e-9)
    grid = g["grid"]
    for a, b in zip(cells[:-1], cells[1:]):
        m = next(i for i, mv in enumerate(MOVES) if tuple(mv) == tuple(np.subtract(grid.unflat(int(b)), grid.unflat(int(a)))))
        assert grid.allowed[m].ravel()[a]


def test_no_ant_path_is_cheaper_than_the_dp_optimum():
    pb, g, start, goal, const, haz = setup(MEDIUM, 0)
    d, _, _ = DP().bellman_ford(g, start, goal, const, haz)
    aco = ACO()
    aco.prepare(Problem(MEDIUM))
    path, length, failed = aco.construct(0, 40, np.ones(g["grid"].n_cells), [], np.random.default_rng(0))
    costs = [path_cost(path[a, :length[a]], g, const, haz) for a in np.flatnonzero(~failed)]
    assert len(costs) > 30 and min(costs) >= d[goal] - 1e-9


# الخطة
def test_dp_plan_is_safe_and_counts_one_evaluation():
    r = run_once(DP(), MEDIUM, seed=0)
    assert r.fe_used == 1 and len(r.iter_history) == 1 and r.feasible
    pb = Problem(MEDIUM)
    for P in r.paths:
        P = np.array(P)
        assert G.collision_length(P, pb.boxes) == 0.0
        assert pb.field.path_hazard(P, ds=0.5)["max_hazard"] < pb.field.tau_core
    assert r.extra["no_path"] == [] and all(r.extra["converged"])
    json.dumps(r.to_dict())


def test_pruning_shortens_the_optimal_cell_path():
    raw = run_once(DP(prune=False), MEDIUM, seed=0)
    pruned = run_once(DP(), MEDIUM, seed=0)
    assert pruned.best_f < raw.best_f
    assert raw.extra["grid_cost"] == pruned.extra["grid_cost"]          # الجدول الأمثل نفسه في الحالتين
    pb = Problem(MEDIUM)
    PathPruner(pb)                                                       # المُشذِّب المشترك يُبنى وحده


def test_dp_is_deterministic():
    a = run_once(DP(), SMALL, seed=0)
    b = run_once(DP(), SMALL, seed=123)
    assert a.best_f == b.best_f and a.paths == b.paths


def test_no_path_is_detected():
    """هدف محاط بالجدران من كل جانب: يجب أن تصرّح DP بذلك بدل إعادة مسار خاطئ."""
    scn = copy.deepcopy(MEDIUM)
    gx, gy, _ = scn.missions[0].G
    n = len(scn.buildings)
    for i, (x0, y0, x1, y1) in enumerate([(gx - 60, gy - 60, gx + 60, gy - 30), (gx - 60, gy + 30, gx + 60, gy + 60),
                                          (gx - 60, gy - 30, gx - 30, gy + 30), (gx + 30, gy - 30, gx + 60, gy + 30)]):
        scn.buildings.append(Building(n + i, x0, y0, x1, y1, 240.0))
    r = run_once(DP(), scn, seed=0)
    assert r.extra["no_path"] == [0] and r.extra["grid_cost"][0] is None
    assert not r.feasible and r.best_f > 100                                # يُبلَّغ عنها كخطة غير آمنة، ولا تُعرض كحل
    assert r.extra["grid_cost"][1] is not None                              # بقية المسيّرات تحصل على مساراتها


def test_sweep_limit_is_reported():
    r = run_once(DP(max_sweeps=3), SMALL, seed=0)
    assert r.extra["converged"] == [False] and r.extra["no_path"] == [0]
    assert np.isfinite(r.best_f)


@pytest.mark.parametrize("path", ALL_CITIES)
def test_dp_solves_every_city(path):
    scn = load_scenario(path)
    r = run_once(DP(), scn, seed=0)
    assert r.feasible and r.extra["no_path"] == [] and all(r.extra["converged"])
    assert r.report["min_clearance_m"] >= scn.world["d_safe"]
    assert max(r.extra["sweeps"]) < city_graph(scn)["grid"].n_cells        # أقل بكثير من الحد |V| - 1
