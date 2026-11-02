"""اختبارات simulation/geometry.py: إجابات معروفة، ومقارنات بالعينات، وملفات المدن المجمدة."""
import glob

import numpy as np
import pytest

from simulation import geometry as G
from simulation.grid import Grid, MOVES
from simulation.scenarios import load_scenario, ROOT as SIMULATION

CUBE = np.array([[0, 0, 0, 10, 10, 10]], dtype=float)          # مكعب طوله 10 م عند المبدأ
ALL_CITIES = sorted(glob.glob(str(SIMULATION / "scenarios/*.json")) + glob.glob(str(SIMULATION / "scenarios/random/*.json")))


# طول الاصطدام (طريقة الألواح)
@pytest.mark.parametrize("p0, p1, expected", [
    ([-5, 5, 5], [15, 5, 5], 10.0),                  # يمر مباشرة على طول x
    ([-5, 20, 5], [15, 20, 5], 0.0),                 # يمر بجانب المكعب
    ([5, 5, 5], [25, 5, 5], 5.0),                    # يبدأ من الداخل
    ([2, 2, 2], [8, 8, 8], np.sqrt(108)),            # داخل المكعب كليًا (6 * sqrt(3))
    ([0, 0, 0], [10, 10, 10], np.sqrt(300)),         # من زاوية إلى زاوية
    ([-10, -10, -10], [20, 20, 20], np.sqrt(300)),   # قطر طويل عبر المكعب
    ([5, 5, 20], [5, 5, -20], 10.0),                 # رأسي، وموازٍ لـ x وy
    ([20, 5, 5], [20, 5, 50], 0.0),                  # موازٍ لـ z وخارج المكعب في x
    ([5, 5, 5], [5, 5, 5], 0.0),                     # مقطع طوله صفر
])
def test_segment_box_overlap_known(p0, p1, expected):
    got = G.segments_boxes_overlap([p0], [p1], CUBE)[0, 0]
    assert got == pytest.approx(expected, abs=1e-9)


def test_overlap_matches_dense_sampling():
    rng = np.random.default_rng(0)
    boxes = np.array([[0, 0, 0, 30, 40, 80], [60, 10, 0, 90, 50, 120]], dtype=float)
    p0 = rng.uniform(-20, 110, (300, 3))
    p1 = rng.uniform(-20, 110, (300, 3))
    exact = G.segments_boxes_overlap(p0, p1, boxes)
    t = (np.arange(20000) + 0.5) / 20000
    for i in range(0, 300, 15):
        pts = p0[i] + t[:, None] * (p1[i] - p0[i])
        L = np.linalg.norm(p1[i] - p0[i])
        for j, b in enumerate(boxes):
            inside = np.all((pts >= b[:3]) & (pts <= b[3:]), axis=1)
            assert exact[i, j] == pytest.approx(inside.mean() * L, abs=0.02)


def test_collision_length_and_report():
    path = np.array([[-5, 5, 5], [15, 5, 5], [15, 30, 5]], dtype=float)
    assert G.collision_length(path, CUBE) == pytest.approx(10.0)
    assert G.collisions(path, CUBE) == [(0, 0, pytest.approx(10.0))]
    assert G.collision_length(path, np.zeros((0, 6))) == 0.0


# المسافات
@pytest.mark.parametrize("p, expected", [
    ([17, 5, 5], 7.0),                     # أمام أحد الوجوه
    ([13, 14, 5], 5.0),                    # بجانب حافة رأسية (3، 4)
    ([12, 13, 16], np.sqrt(4 + 9 + 36)),   # بجانب زاوية
    ([5, 5, 5], 0.0),                      # في الداخل
])
def test_point_box_distance(p, expected):
    assert G.points_boxes_distance([p], CUBE)[0, 0] == pytest.approx(expected)


def test_segment_box_distance_matches_sampling():
    rng = np.random.default_rng(1)
    boxes = np.array([[0, 0, 0, 30, 40, 80], [60, 10, 0, 90, 50, 120]], dtype=float)
    p0 = rng.uniform(-60, 150, (200, 3))
    p1 = rng.uniform(-60, 150, (200, 3))
    exact = G.segments_boxes_distance(p0, p1, boxes)
    t = np.linspace(0, 1, 20001)
    for i in range(0, 200, 10):
        pts = p0[i] + t[:, None] * (p1[i] - p0[i])
        brute = G.points_boxes_distance(pts, boxes).min(axis=0)
        assert np.all(exact[i] <= brute + 1e-9)                 # لا تزيد أبدًا على أي عينة
        assert np.allclose(exact[i], brute, atol=0.02)


def test_path_clearance():
    path = np.array([[-20, 17, 5], [30, 17, 5]], dtype=float)  # يمر على بعد 7 م من وجه المكعب y = 10
    d, seg, box = G.path_clearance(path, CUBE)
    assert d == pytest.approx(7.0) and seg == 0 and box == 0


# أخذ العينات والانعطافات والحدود
def test_sample_path_weights_sum_to_length():
    path = np.array([[0, 0, 10], [100, 0, 10], [100, 0, 10], [100, 33, 50]], dtype=float)
    pts, w, s = G.sample_path(path, ds=2.0)
    assert w.sum() == pytest.approx(G.path_length(path))
    assert np.all(w <= 2.0 + 1e-12)
    assert np.all(np.diff(s) > 0)
    assert len(pts) == 50 + int(np.ceil(np.hypot(33, 40) / 2))


def test_line_integral_is_exact_for_linear_fields():
    path = np.array([[0, 0, 10], [60, 80, 10]], dtype=float)      # الطول 100
    pts, w, _ = G.sample_path(path, ds=2.0)
    assert (pts[:, 0] * w).sum() == pytest.approx(100 * 30)     # تكامل x ds = L * mean(x)


@pytest.mark.parametrize("path, expected", [
    ([[0, 0, 0], [10, 0, 0], [20, 0, 0]], [0.0]),
    ([[0, 0, 0], [10, 0, 0], [10, 10, 0]], [np.pi / 2]),
    ([[0, 0, 0], [10, 0, 0], [0, 0, 0]], [np.pi]),
    ([[0, 0, 0], [10, 0, 0], [10, 0, 0], [10, 10, 0]], [np.pi / 2]),   # تُتجاهل النقطة المكررة
])
def test_turn_angles(path, expected):
    assert np.allclose(G.turn_angles(np.array(path, float)), expected)


def test_bounds():
    b = np.array([[0, 0, 10], [300, 300, 150]], dtype=float)
    p = np.array([[-5, 10, 5], [100, 100, 100], [400, 10, 200]], dtype=float)
    assert G.outside_bounds(p, b).tolist() == [True, False, True]
    assert not G.outside_bounds(G.clip_to_bounds(p, b), b).any()


# الطاقة والبطارية
def test_energy_known_values():
    flat = np.array([[0, 0, 10], [100, 0, 10]], float)
    up = np.array([[0, 0, 10], [0, 0, 60]], float)
    down = up[::-1]
    assert G.path_energy(flat) == pytest.approx(2000)          # 20 جول/م × 100 م
    assert G.path_energy(up) == pytest.approx(50 * 20 + 50 * 100)
    assert G.path_energy(down) == pytest.approx(50 * 20)       # الهبوط لا يكلف طاقة إضافية


def test_battery_report():
    drone = {"e_c": 20, "e_up": 100, "battery_kj": 799, "battery_usable": 0.8}
    r = G.battery_report(np.array([[0, 0, 10], [1000, 0, 10]], float), drone)
    assert r["energy_kj"] == pytest.approx(20.0)
    assert r["battery_used"] == pytest.approx(20 / 799)
    assert r["e_max_kj"] == pytest.approx(639.2) and r["enough"]
    long = np.array([[0, 0, 10], [40000, 0, 10]], float)        # 800 kJ أكبر من 639.2 kJ المتاحة
    r2 = G.battery_report(long, drone)
    assert not r2["enough"] and r2["over_limit_kj"] == pytest.approx(800 - 639.2)


# التوقيت والتباعد
def test_positions_and_hover():
    path = np.array([[0, 0, 10], [100, 0, 10], [100, 50, 10]], float)
    pos = G.positions_at(path, [0, 5, 10, 12.5, 15, 99], speed=10)
    assert np.allclose(pos, [[0, 0, 10], [50, 0, 10], [100, 0, 10], [100, 25, 10],
                             [100, 50, 10], [100, 50, 10]])
    assert G.arrival_time(path, 10) == pytest.approx(15)


def test_head_on_drones_meet():
    a = np.array([[0, 0, 50], [100, 0, 50]], float)
    b = a[::-1].copy()
    d, t = G.pair_min_distance(a, b, speed=10)
    assert d == pytest.approx(0.0, abs=1e-9) and t == pytest.approx(5.0)


def test_parallel_drones_and_waiting_drone():
    a = np.array([[0, 0, 50], [100, 0, 50]], float)
    b = a + [0, 20, 0]
    assert G.pair_min_distance(a, b, 10)[0] == pytest.approx(20.0)
    short = np.array([[50, 30, 50], [50, 3, 50]], float)        # تصل عند t = 2.7 ث ثم تحوم
    d, t = G.pair_min_distance(a, short, 10)                     # تمر a بـ x = 50 عند t = 5 ث
    assert d == pytest.approx(3.0) and t == pytest.approx(5.0)


def test_exact_separation_matches_fine_sampling():
    rng = np.random.default_rng(2)
    for _ in range(30):
        paths = [np.vstack([rng.uniform(0, 300, (1, 3)), rng.uniform(0, 300, (4, 3)),
                            rng.uniform(0, 300, (1, 3))]) for _ in range(3)]
        res = G.min_separation(paths, speed=10)
        _, D, _ = G.separation_samples(paths, speed=10, dt=0.01)
        assert res["d_min"] <= D.min() + 1e-9
        assert res["d_min"] == pytest.approx(D.min(), abs=0.15)  # أسوأ حالة 0.01 ث * 20 م/ث / 2


# المدن الحقيقية
@pytest.mark.parametrize("path", ALL_CITIES)
def test_take_off_and_targets_are_clear(path):
    scn = load_scenario(path)
    for p in np.vstack([scn.starts(), scn.goals()]):
        assert G.points_boxes_distance([p], scn.boxes()).min() > 0      # خارج كل هامش 5 م


@pytest.mark.parametrize("path", [SIMULATION / "scenarios/small.json", SIMULATION / "scenarios/medium.json"])
def test_grid_moves_never_enter_a_tower_margin(path):
    """يربط الشبكة بالهندسة: كل انتقال مسموح على الشبكة لا يتداخل مع الصناديق المضخمة."""
    scn = load_scenario(path)
    g = Grid.from_scenario(scn)
    cells = np.argwhere(g.free)
    m, i, j, k = np.nonzero(g.allowed)
    a = g.centers(np.stack([i, j, k], axis=1))
    b = a + MOVES[m] * g.res
    assert len(cells) > 0
    for s in range(0, len(a), 50_000):                                # على دفعات لتوفير الذاكرة
        assert G.segments_boxes_overlap(a[s:s + 50_000], b[s:s + 50_000], scn.boxes()).max() == 0.0


# النسخ الدفعية (تستخدمها دالة اللياقة)
def test_batched_functions_match_single_ones():
    rng = np.random.default_rng(3)
    scn = load_scenario(SIMULATION / "scenarios/large.json")
    B = scn.boxes()
    for _ in range(20):
        paths = [np.vstack([m.S, rng.uniform([0, 0, 10], [1000, 1000, 350], (14, 3)), m.G]) for m in scn.missions]
        assert np.allclose(G.collision_lengths(paths, B), [G.collision_length(p, B) for p in paths])
        res = G.min_separation(paths, speed=10)
        for i in range(len(paths)):
            for j in range(i + 1, len(paths)):
                assert res["matrix"][i, j] == pytest.approx(G.pair_min_distance(paths[i], paths[j], 10)[0])


def test_distances_in_an_empty_city():
    path = np.array([[0, 0, 10], [100, 0, 10]], float)
    none = np.zeros((0, 6))
    assert G.path_clearance(path, none) == (float("inf"), -1, -1)
    assert np.all(np.isinf(G.clearance_at_points(path, none)))
    assert G.collision_length(path, none) == 0.0
