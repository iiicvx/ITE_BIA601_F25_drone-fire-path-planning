"""اختبارات FireField في simulation/geometry.py: شكل العمود الحراري، والقلب المحظور، والتعرض، والمدن المجمدة."""
import glob

import numpy as np
import pytest

from simulation.grid import Grid, MOVES
from simulation.geometry import FireField
from simulation.scenarios import load_scenario, ROOT as SIMULATION

ALL_CITIES = sorted(glob.glob(str(SIMULATION / "scenarios/*.json")) + glob.glob(str(SIMULATION / "scenarios/random/*.json")))
R, I, HF = 15.0, 1.0, 80.0
ONE = FireField(np.array([[100.0, 100.0, 80.0, R, I, HF]]))            # حريق واحد عند (100، 100، 80)


def at(dx=0.0, dy=0.0, dz=0.0):
    return np.array([[100 + dx, 100 + dy, 80 + dz]])


# شكل الحقل
def test_value_at_fire_centre_is_intensity():
    assert ONE.H(at())[0] == pytest.approx(I)
    f = FireField(np.array([[0, 0, 50, 15, 0.8, 80]]))
    assert f.H(np.array([0, 0, 50.0])) == pytest.approx(0.8)          # نقطة واحدة -> قيمة مفردة


def test_continuous_at_fire_height():
    for dh in (0.0, 5.0, 12.0, 30.0):
        above, below = ONE.H(at(dx=dh, dz=1e-9))[0], ONE.H(at(dx=dh, dz=-1e-9))[0]
        assert above == pytest.approx(below, abs=1e-9)


def test_decreases_with_horizontal_distance():
    h = ONE.H(np.vstack([at(dx=d) for d in range(0, 80, 5)]))
    assert np.all(np.diff(h) < 0)


def test_heat_rises():
    for d in (10.0, 20.0, 40.0):
        assert ONE.H(at(dz=d))[0] > ONE.H(at(dz=-d))[0]                # فوق الحريق أخطر من تحته


def test_column_gets_wider_with_height():
    def half_width(dz):                                                 # حيث ينخفض H إلى نصف قيمته على المحور
        axis = ONE.H(at(dz=dz))[0]
        d = np.linspace(0, 200, 200001)
        h = ONE.H(np.stack([100 + d, np.full_like(d, 100), np.full_like(d, 80 + dz)], axis=1))
        return d[np.argmax(h < axis / 2)]
    w0, w60, w150 = half_width(0), half_width(60), half_width(150)
    assert w0 < w60 < w150
    assert w60 == pytest.approx((R + 0.25 * 60) * np.sqrt(np.log(2)), abs=0.01)


def test_two_fires_add_up_and_clip_at_one():
    two = FireField(np.array([[0, 0, 50, 15, 0.9, 80], [5, 0, 50, 15, 0.9, 80]]))
    assert two.H(np.array([2.5, 0, 50.0])) == pytest.approx(1.0)
    far = two.per_fire(np.array([[0, 300, 50.0]]))
    assert np.all(far < 1e-12)


def test_no_fires_gives_zero():
    assert np.all(FireField(np.zeros((0, 6))).H(np.ones((4, 3))) == 0)


# قلب الحريق المحظور
def test_core_size_matches_closed_form():
    r, top = ONE.core_radius_at_fire_height(), ONE.core_top_above_fire()
    assert r == pytest.approx(R * np.sqrt(np.log(2)))                  # 12.49 م
    assert top == pytest.approx(HF * np.log(2))                        # 55.45 م
    assert ONE.is_core(at(dx=r - 0.01))[0] and not ONE.is_core(at(dx=r + 0.01))[0]
    assert ONE.is_core(at(dz=top - 0.01))[0] and not ONE.is_core(at(dz=top + 0.01))[0]
    bottom = R / 2 * np.sqrt(np.log(2))                                # يكاد القلب لا يمتد تحت الحريق
    assert ONE.is_core(at(dz=-bottom + 0.01))[0] and not ONE.is_core(at(dz=-bottom - 0.01))[0]


# على طول مسار
def test_exposure_of_straight_line_through_fire():
    """خط أفقي عبر مركز الحريق: تكامل I exp(-(x/R)^2) dx = I R sqrt(pi)."""
    path = np.array([[-200.0, 100, 80], [400.0, 100, 80]])
    r = ONE.path_hazard(path, ds=0.5)
    assert r["exposure"] == pytest.approx(I * R * np.sqrt(np.pi), rel=1e-4)
    assert r["core_length"] == pytest.approx(2 * R * np.sqrt(np.log(2)), abs=0.5)
    assert r["max_hazard"] == pytest.approx(1.0, abs=1e-3)


def test_far_path_has_no_exposure():
    path = np.array([[0.0, 400, 20], [400.0, 400, 20]])
    r = ONE.path_hazard(path)
    assert r["exposure"] < 1e-9 and r["core_length"] == 0.0


def test_profile_lengths_match():
    path = np.array([[0.0, 100, 80], [200.0, 100, 80]])
    s, h = ONE.profile(path)
    assert len(s) == len(h) == 100 and s[-1] < 200


# المدن الحقيقية
@pytest.mark.parametrize("path", ALL_CITIES)
def test_targets_and_take_off_are_safe(path):
    scn = load_scenario(path)
    field = FireField.from_scenario(scn)
    hS, hG = field.H(scn.starts()), field.H(scn.goals())
    assert hS.max() < 1e-3                       # منطقة الإقلاع بعيدة عن كل حريق
    assert hG.max() < 0.1                        # نقطة الإطلاق: نحو 0.05 * I، أقل بكثير من القلب
    if len(scn.fires) == 1:                      # حريق واحد: بالضبط I * exp(-((1.6R)^2 + 10^2) / R^2)
        f = scn.fires[0]
        assert hG[0] == pytest.approx(f.I * np.exp(-((1.6 * f.R) ** 2 + 10 ** 2) / f.R ** 2), rel=1e-6)


@pytest.mark.parametrize("path", ALL_CITIES)
def test_grid_with_fire_core_keeps_every_mission_reachable(path):
    scn = load_scenario(path)
    g = Grid.from_scenario(scn, fire_core=True)
    field = FireField.from_scenario(scn)
    # كل خلية حرة خارج القلب (قد تكون بعض خلايا القلب محجوبة أصلًا بهامش برج)
    assert field.H(g.all_centers()[g.free.ravel()]).max() < scn.hazard["grid_tau"]
    reach = g.reachable_from(g.nearest_free(scn.missions[0].S))
    for m in scn.missions:
        assert reach[g.nearest_free(m.S)] and reach[g.nearest_free(m.G)]


@pytest.mark.parametrize("path", ALL_CITIES)
def test_grid_moves_never_touch_the_core(path):
    """مع حجب الخلايا عند خطر >= 0.45، لا يبلغ أي انتقال مسموح قرب الحريق خطرًا قدره 0.5."""
    scn = load_scenario(path)
    field = FireField.from_scenario(scn)
    g = Grid.from_scenario(scn, fire_core=True)
    C = g.all_centers().reshape(g.shape + (3,))
    near = np.zeros(g.shape, bool)
    for f in scn.fires:
        near |= np.linalg.norm(C - np.array(f.c), axis=-1) < 70
    m, i, j, k = np.nonzero(g.allowed & near[None])
    a = C[i, j, k]
    b = a + MOVES[m] * g.res
    t = np.linspace(0, 1, 25)
    for s in range(0, len(a), 20_000):
        pts = a[s:s + 20_000, None, :] + (b - a)[s:s + 20_000, None, :] * t[None, :, None]
        assert field.H(pts.reshape(-1, 3)).max() < field.tau_core


def test_paths_hazard_matches_path_hazard():
    scn = load_scenario(SIMULATION / "scenarios/large.json")
    field = FireField.from_scenario(scn)
    rng = np.random.default_rng(4)
    paths = [np.vstack([m.S, rng.uniform([0, 0, 10], [1000, 1000, 350], (14, 3)), m.G]) for m in scn.missions]
    for a, b in zip(field.paths_hazard(paths), [field.path_hazard(p) for p in paths]):
        for key in a:
            assert a[key] == pytest.approx(b[key])
