"""اختبارات مولد المدن وملفات المدن المجمدة والشبكة الفراغية.

تُفحص كل قاعدة من قواعد المولد هنا مرة أخرى بشيفرة مستقلة، فيُكشف أي ملف مدينة
يخالف قاعدة حتى لو كان في فحوص المولد نفسه خطأ.
"""
import copy
import glob
import itertools
import json

import numpy as np
import pytest

from simulation.scenarios import SIZES, generate_city, load_config, validate, Building, Scenario, load_scenario
from simulation.scenarios import ROOT as SIMULATION
from simulation.grid import Grid, MOVES

CFG = load_config()
C = CFG["common"]
ALL_CITIES = sorted(glob.glob(str(SIMULATION / "scenarios/*.json")) + glob.glob(str(SIMULATION / "scenarios/random/*.json")))
MAIN = {s: str(SIMULATION / f"scenarios/{s}.json") for s in SIZES}


def footprint_gap(a, b):
    return max(b.x0 - a.x1, a.x0 - b.x1, b.y0 - a.y1, a.y0 - b.y1)


def dist_to_box(p, box):
    lo, hi = np.asarray(box[:3]), np.asarray(box[3:])
    return float(np.linalg.norm(np.maximum(np.maximum(lo - p, 0), p - hi)))


# الملفات موجودة، ويعيد المولد إنتاجها حرفيًا
def test_33_city_files():
    assert len(ALL_CITIES) == 33
    for s in SIZES:
        assert len(glob.glob(str(SIMULATION / f"scenarios/random/{s}_r*.json"))) == 10


@pytest.mark.parametrize("size", SIZES)
def test_main_city_is_reproducible(size):
    """التوليد من البذرة نفسها يعطي الملف المجمد حرفيًا."""
    frozen = load_scenario(MAIN[size])
    again = generate_city(size, CFG["seeds"]["main"], CFG, name=size)
    assert json.dumps(again.to_dict()) == json.dumps(frozen.to_dict())


def test_json_round_trip():
    scn = load_scenario(MAIN["large"])
    assert Scenario.from_dict(json.loads(json.dumps(scn.to_dict()))).to_dict() == scn.to_dict()


# كل قاعدة، على كل ملف
@pytest.mark.parametrize("path", ALL_CITIES)
def test_generator_checks_pass(path):
    assert validate(load_scenario(path), CFG) == []


@pytest.mark.parametrize("path", ALL_CITIES)
def test_city_rules_independently(path):
    scn = load_scenario(path)
    s = CFG["sizes"][scn.size]
    W, B, F, Ms = s["W"], scn.buildings, scn.fires, scn.missions

    # العالم والأحجام
    assert scn.world == {"W": W, "z_min": C["z_min"], "z_max": s["z_max"], "d_safe": C["d_safe"],
                         "grid_res": C["grid_res"]}
    assert (len(B), len(F), len(Ms)) == (s["n_buildings"], s["n_fires"], s["n_drones"])
    assert scn.problem["n_variables"] == 3 * s["n_drones"] * s["n_waypoints"]

    # الأبراج
    hs = [b.h for b in B]
    assert min(hs) == s["height"][0] and max(hs) == s["height"][1]
    for b in B:
        assert C["base_size"][0] <= b.x1 - b.x0 <= C["base_size"][1]
        assert C["base_size"][0] <= b.y1 - b.y0 <= C["base_size"][1]
        assert min(b.x0, b.y0) >= C["edge_margin"] and max(b.x1, b.y1) <= W - C["edge_margin"]
    for a, b in itertools.combinations(B, 2):
        assert footprint_gap(a, b) >= C["min_gap"]

    # منطقة الإقلاع
    S = np.array(scn.staging["points"])
    assert np.all(S[:, 2] == C["z_min"])
    if len(S) > 1:
        assert np.allclose(np.linalg.norm(np.diff(S, axis=0), axis=1), C["staging"]["spacing"])
    for p in S:
        assert min(dist_to_box(p, b.inflated(C["d_safe"])) for b in B) > 0

    # الحرائق
    fc = C["fire"]
    for f in F:
        b = B[f.building]
        x, y, z = f.c
        on_face = {"E": abs(x - b.x1) < 1e-6, "W": abs(x - b.x0) < 1e-6,
                   "N": abs(y - b.y1) < 1e-6, "S": abs(y - b.y0) < 1e-6}[f.face]
        assert on_face
        if f.handled_by == "drone":
            assert max(0.4 * b.h, fc["drone_fire_z_min"]) - 1e-6 <= z <= 0.8 * b.h + 1e-6
        else:
            assert fc["ground_fire_z"][0] - 1e-6 <= z <= fc["ground_fire_z"][1] + 1e-6
        assert s["fire_R"][0] <= f.R <= s["fire_R"][1] and fc["I"][0] <= f.I <= fc["I"][1]
    for a, b in itertools.combinations(F, 2):
        assert np.hypot(a.c[0] - b.c[0], a.c[1] - b.c[1]) >= fc["min_separation"] - 1e-6
    assert len({f.building for f in F}) == len(F)
    assert sum(f.handled_by == "drone" for f in F) == len(Ms)

    # المهام: مهمة لكل مسيّرة، ونقطة الإطلاق على بعد 1.6R من الواجهة وأخفض من الحريق بـ 5 م
    assert sorted(m.fire for m in Ms) == sorted(f.id for f in F if f.handled_by == "drone")
    for m in Ms:
        f = F[m.fire]
        expected = np.array(f.c) + fc["target_offset_R"] * f.R * np.array(f.normal) - [0, 0, fc["target_drop"]]
        assert np.allclose(m.G, expected, atol=0.01)
        assert min(dist_to_box(np.array(m.G), b.inflated(C["d_safe"])) for b in B) >= fc["target_clearance"] - 1e-6


# validate() ترفض المدن المعيبة
def test_validate_catches_broken_cities():
    good = load_scenario(MAIN["medium"])
    assert validate(good, CFG) == []

    close = copy.deepcopy(good)                              # برجان بينهما 10 م
    a, b = close.buildings[0], close.buildings[1]
    w, d = b.x1 - b.x0, b.y1 - b.y0
    b.x0, b.y0 = a.x1 + 10, a.y0
    b.x1, b.y1 = b.x0 + w, b.y0 + d
    assert any("closer than" in e for e in validate(close, CFG))

    inside = copy.deepcopy(good)                             # نُقل الهدف إلى داخل برج
    t = inside.buildings[5]
    inside.missions[0].G = [(t.x0 + t.x1) / 2, (t.y0 + t.y1) / 2, 20.0]
    assert any("too close to a tower" in e for e in validate(inside, CFG))

    trapped = copy.deepcopy(good)                            # أربعة جدران عالية حول الهدف
    gx, gy, _ = trapped.missions[0].G
    n = len(trapped.buildings)
    walls = [(gx - 60, gy - 60, gx + 60, gy - 30), (gx - 60, gy + 30, gx + 60, gy + 60),
             (gx - 60, gy - 30, gx - 30, gy + 30), (gx + 30, gy - 30, gx + 60, gy + 30)]
    for i, (x0, y0, x1, y1) in enumerate(walls):            # 240 م + هامش 5 م يبلغ سقف 250 م
        trapped.buildings.append(Building(n + i, x0, y0, x1, y1, 240.0))
    assert any("target of drone 0 not reachable" in e for e in validate(trapped, CFG))


# الشبكة الفراغية
@pytest.mark.parametrize("size, shape, cells", [("small", (30, 30, 14), 12_600),
                                                 ("medium", (60, 60, 24), 86_400),
                                                 ("large", (100, 100, 34), 340_000)])
def test_grid_sizes_match_the_proposal(size, shape, cells):
    g = Grid.from_scenario(load_scenario(MAIN[size]))
    assert g.shape == shape and g.n_cells == cells
    assert g.xs[0] == 5 and g.zs[0] == C["z_min"] + 5 and g.zs[-1] == CFG["sizes"][size]["z_max"] - 5


def test_grid_blocks_tower_margins_exactly():
    scn = load_scenario(MAIN["small"])
    g = Grid.from_scenario(scn)
    P = g.all_centers()
    inside = np.zeros(len(P), bool)
    for b in scn.buildings:
        x0, y0, z0, x1, y1, z1 = b.inflated(C["d_safe"])
        inside |= (P[:, 0] >= x0) & (P[:, 0] <= x1) & (P[:, 1] >= y0) & (P[:, 1] <= y1) & (P[:, 2] <= z1)
    assert np.array_equal(~g.free.ravel(), inside)


def test_grid_coordinates_and_nearest_free():
    scn = load_scenario(MAIN["medium"])
    g = Grid.from_scenario(scn)
    c = g.cell_of([123.0, 456.0, 77.0])
    assert c == (12, 45, 6) and np.allclose(g.center(c), [125, 455, 75])
    assert g.unflat(g.flat(c)) == c
    b = scn.buildings[0]
    blocked_point = [(b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2, 15.0]
    nf = g.nearest_free(blocked_point)
    assert g.free[nf] and not g.free[g.cell_of(blocked_point)]


def test_no_corner_cutting_and_symmetric_moves():
    g = Grid(30, 10, 40, 10, np.zeros((0, 6)))
    g.free[1, 0, :] = False
    g._allowed = None
    m = next(i for i, mv in enumerate(MOVES) if tuple(mv) == (1, 1, 0))
    assert not g.allowed[m, 0, 0, 0]                          # سيقطع الزاوية المحجوبة
    g2 = Grid.from_scenario(load_scenario(MAIN["small"]))
    for mi, mv in enumerate(MOVES):                            # الانتقال مسموح في الاتجاهين
        back = next(i for i, v in enumerate(MOVES) if tuple(v) == tuple(-mv))
        a = g2.allowed[mi]
        src = tuple(slice(max(0, -o), n - max(0, o)) for o, n in zip(mv, g2.shape))
        dst = tuple(slice(max(0, o), n - max(0, -o)) for o, n in zip(mv, g2.shape))
        assert np.array_equal(a[src], g2.allowed[back][dst])


def test_reachability_detects_an_enclosed_cell():
    g = Grid(200, 10, 110, 10, np.zeros((0, 6)))
    g.free[5:10, 5:10, 2:7] = False
    g.free[7, 7, 4] = True                                     # خلية حرة داخل غلاف مغلق
    g._allowed = None
    reach = g.reachable_from((0, 0, 0))
    assert not reach[7, 7, 4] and reach[15, 15, 5]
    assert reach.sum() == g.free.sum() - 1
