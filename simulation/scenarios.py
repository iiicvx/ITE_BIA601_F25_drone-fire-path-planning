"""توليد سيناريوهات المدن ثلاثية الأبعاد (الأبراج، بؤر الحرائق، ومهام المُسيَّرات)."""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent
SIZES = ("small", "medium", "large")
FACES = {"E": (1.0, 0.0), "W": (-1.0, 0.0), "N": (0.0, 1.0), "S": (0.0, -1.0)}


# بيانات السيناريو وJSON
@dataclass
class Building:
    """برج موازٍ للمحاور: [x0, x1] x [y0, y1] x [0, h]."""
    id: int
    x0: float
    y0: float
    x1: float
    y1: float
    h: float

    def box(self) -> np.ndarray:
        """[x0, y0, z0, x1, y1, z1] للبرج الحقيقي."""
        return np.array([self.x0, self.y0, 0.0, self.x1, self.y1, self.h])

    def inflated(self, d: float) -> np.ndarray:
        """صندوق مكبَّر بهامش الأمان d على الجوانب الأربعة وفي الأعلى."""
        return np.array([self.x0 - d, self.y0 - d, 0.0, self.x1 + d, self.y1 + d, self.h + d])

    @property
    def center_xy(self) -> np.ndarray:
        return np.array([(self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2])


@dataclass
class Fire:
    """حريق على واجهة برج.

    c       : مركز الحريق [x, y, z] (على سطح الواجهة)
    face    : الواجهة المشتعلة: 'E' أو 'W' أو 'N' أو 'S'
    normal  : متجه الوحدة العمودي الخارجي لتلك الواجهة [nx, ny, 0]
    R, I, Hf: المقياس الغاوسي الأفقي، والشدة، والتضاؤل الرأسي (يستخدمها geometry.py)
    handled_by: 'drone' (تحمل إليه مسيّرة كبسولة) أو 'ground' (حريق منخفض تصله السلالم؛
                وعلى المسيّرات تجنبه فقط)
    """
    id: int
    building: int
    face: str
    c: list
    normal: list
    R: float
    I: float
    Hf: float
    handled_by: str = "drone"


@dataclass
class Mission:
    """تطير المسيّرة k من S (نقطة الإقلاع) إلى G (نقطة إطلاق الكبسولة قرب الحريق `fire`)."""
    k: int
    fire: int
    S: list
    G: list


@dataclass
class Scenario:
    name: str                 # مثلًا "small" و"medium_r03"
    size: str                 # "small" | "medium" | "large"
    seed: int                 # البذرة المطلوبة
    seed_used: int            # البذرة التي أنتجت هذه المدينة (تختلف إذا فشل الوضع وأعيدت المحاولة)
    world: dict               # W وz_min وz_max وd_safe وgrid_res
    drone: dict               # speed وd_sep
    hazard: dict              # k وtau_core
    problem: dict             # n_waypoints وbudget_fe وn_drones
    staging: dict             # edge وpoints
    buildings: list = field(default_factory=list)
    fires: list = field(default_factory=list)
    missions: list = field(default_factory=list)

    # اختصارات مساعدة
    @property
    def W(self) -> float:
        return self.world["W"]

    @property
    def bounds(self) -> np.ndarray:
        """حيّز الطيران بصيغة [[xmin, ymin, zmin], [xmax, ymax, zmax]]."""
        w = self.world
        return np.array([[0.0, 0.0, w["z_min"]], [w["W"], w["W"], w["z_max"]]])

    def boxes(self, inflated: bool = True) -> np.ndarray:
        """مصفوفة (n, 6) لصناديق الأبراج [x0, y0, z0, x1, y1, z1]، مضخمة بـ d_safe افتراضيًا."""
        d = self.world["d_safe"]
        if not self.buildings:
            return np.zeros((0, 6))
        return np.array([b.inflated(d) if inflated else b.box() for b in self.buildings])

    def starts(self) -> np.ndarray:
        return np.array([m.S for m in self.missions], dtype=float)

    def goals(self) -> np.ndarray:
        return np.array([m.G for m in self.missions], dtype=float)

    # JSON
    def to_dict(self) -> dict:
        d = asdict(self)
        d["schema"] = "drone-fire-scenario/1"
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Scenario":
        d = dict(d)
        d.pop("schema", None)
        d["buildings"] = [Building(**b) for b in d.get("buildings", [])]
        d["fires"] = [Fire(**f) for f in d.get("fires", [])]
        d["missions"] = [Mission(**m) for m in d.get("missions", [])]
        return cls(**d)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")


def load_scenario(path: str | Path) -> Scenario:
    """تحميل مدينة مجمدة، مثل load_scenario('simulation/scenarios/medium.json')."""
    return Scenario.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


class PlacementError(RuntimeError):
    """يُرفع عندما يتعذر بناء مدينة بالبذرة الحالية."""


def load_config(path: str | Path = ROOT / "config" / "sizes.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


# دوال مساعدة
def _rect_gap(a, b) -> float:
    """أكبر فجوة محورية بين مسقطين (x0, y0, x1, y1). والقيمة >= g تعني شارعًا عرضه g."""
    gx = max(b[0] - a[2], a[0] - b[2])
    gy = max(b[1] - a[3], a[1] - b[3])
    return max(gx, gy)


def _point_rect_dist(p, r) -> float:
    """المسافة الأفقية من النقطة p (x, y) إلى المسقط r (x0, y0, x1, y1)."""
    dx = max(r[0] - p[0], 0.0, p[0] - r[2])
    dy = max(r[1] - p[1], 0.0, p[1] - r[3])
    return float(np.hypot(dx, dy))


def _point_box_dist(p, box) -> float:
    """المسافة ثلاثية الأبعاد من النقطة p إلى الصندوق [x0, y0, z0, x1, y1, z1] (0 في الداخل)."""
    lo, hi = np.asarray(box[:3]), np.asarray(box[3:])
    return float(np.linalg.norm(np.maximum(np.maximum(lo - p, 0.0), p - hi)))


# الخطوات
def _staging(rng, W, K, z_min, st):
    edge = str(rng.choice(["S", "N", "W", "E"]))
    span = (K - 1) * st["spacing"]
    mid = rng.uniform(max(0.3 * W, st["inset"] + span / 2), min(0.7 * W, W - st["inset"] - span / 2))
    along = mid + (np.arange(K) - (K - 1) / 2) * st["spacing"]
    inset = st["inset"]
    if edge == "S":
        pts = [[a, inset, z_min] for a in along]
    elif edge == "N":
        pts = [[a, W - inset, z_min] for a in along]
    elif edge == "W":
        pts = [[inset, a, z_min] for a in along]
    else:
        pts = [[W - inset, a, z_min] for a in along]
    return edge, [[round(float(v), 2) for v in p] for p in pts]


def _towers(rng, size_cfg, c, staging_pts):
    W = size_cfg["W"]
    lo_b, hi_b = c["base_size"]
    m = c["edge_margin"]
    rects = []
    for _ in range(size_cfg["n_buildings"]):
        for _try in range(c["max_place_tries"]):
            w, d = (int(v) for v in rng.integers(lo_b, hi_b + 1, size=2))
            x0 = int(rng.integers(m, W - m - w + 1))
            y0 = int(rng.integers(m, W - m - d + 1))
            r = (x0, y0, x0 + w, y0 + d)
            if any(_rect_gap(r, q) < c["min_gap"] for q in rects):
                continue
            if any(_point_rect_dist(p[:2], r) < c["staging"]["clear_radius"] for p in staging_pts):
                continue
            rects.append(r)
            break
        else:
            raise PlacementError("could not place all towers")

    # الارتفاعات: أعلى قرب المركز (وسط المدينة)، ثم تُحجَّم إلى [h_lo, h_hi] بالضبط
    h_lo, h_hi = size_cfg["height"]
    ctr = np.array([W / 2, W / 2])
    raw = []
    for r in rects:
        dn = np.linalg.norm(np.array([(r[0] + r[2]) / 2, (r[1] + r[3]) / 2]) - ctr) / (W / np.sqrt(2))
        raw.append(rng.uniform(0.15, 1.0) * (0.45 + 0.55 * (1.0 - dn)))
    raw = np.array(raw)
    hs = h_lo + (raw - raw.min()) / (raw.max() - raw.min()) * (h_hi - h_lo)
    return [Building(i, float(r[0]), float(r[1]), float(r[2]), float(r[3]), float(round(h)))
            for i, (r, h) in enumerate(zip(rects, hs))]


def _fires(rng, size_cfg, c, buildings, staging_pts, boxes_inf):
    W, K, F = size_cfg["W"], size_cfg["n_drones"], size_cfg["n_fires"]
    fc = c["fire"]
    z_min = c["z_min"]
    st_ctr = np.mean(np.array(staging_pts)[:, :2], axis=0)
    fires, used, targets = [], set(), []

    def far_enough(xy):
        return all(np.hypot(xy[0] - f.c[0], xy[1] - f.c[1]) >= fc["min_separation"] for f in fires)

    for n in range(F):
        drone_fire = n < K
        if drone_fire:   # حريق مرتفع: يجب أن يبلغ البرج 35 م عند 80% من ارتفاعه
            cand = [b for b in buildings if 0.8 * b.h >= fc["drone_fire_z_min"]]
        else:            # حريق منخفض لفرق الأرض
            cand = [b for b in buildings if 0.8 * b.h >= fc["ground_fire_z"][0]]
        cand = [b for b in cand if b.id not in used
                and np.linalg.norm(b.center_xy - st_ctr) >= fc["min_dist_staging"] * W]
        if not cand:
            raise PlacementError("no tower available for a fire")
        wts = np.array([b.h for b in cand]) ** 2 if drone_fire else np.ones(len(cand))
        order = rng.choice(len(cand), size=len(cand), replace=False, p=wts / wts.sum())

        placed = False
        for bi in order:
            b = cand[bi]
            for face in rng.permutation(list(FACES)):
                nx, ny = FACES[face]
                for _try in range(6):
                    if drone_fire:
                        zf = rng.uniform(max(0.4 * b.h, fc["drone_fire_z_min"]), 0.8 * b.h)
                    else:
                        zf = rng.uniform(fc["ground_fire_z"][0], min(fc["ground_fire_z"][1], 0.8 * b.h))
                    if face in ("E", "W"):
                        x = b.x1 if face == "E" else b.x0
                        y = rng.uniform(b.y0 + 5, b.y1 - 5)
                    else:
                        y = b.y1 if face == "N" else b.y0
                        x = rng.uniform(b.x0 + 5, b.x1 - 5)
                    cxy = (x, y)
                    if not far_enough(cxy):
                        continue
                    R = float(round(rng.uniform(*size_cfg["fire_R"]) * 2) / 2)
                    I = float(round(rng.uniform(*fc["I"]), 2))
                    cc = [round(float(x), 2), round(float(y), 2), round(float(zf), 2)]
                    G = None
                    if drone_fire:
                        G = np.array([cc[0] + nx * fc["target_offset_R"] * R,
                                      cc[1] + ny * fc["target_offset_R"] * R,
                                      cc[2] - fc["target_drop"]])
                        if not (10 <= G[0] <= W - 10 and 10 <= G[1] <= W - 10 and G[2] >= z_min + 5):
                            continue
                        if min(_point_box_dist(G, bx) for bx in boxes_inf) < fc["target_clearance"]:
                            continue
                        if any(np.linalg.norm(G - t) < 20 for t in targets):
                            continue
                    fires.append(Fire(id=n, building=b.id, face=str(face), c=cc, normal=[nx, ny, 0.0],
                                      R=R, I=I, Hf=float(fc["Hf"]),
                                      handled_by="drone" if drone_fire else "ground"))
                    used.add(b.id)
                    if G is not None:
                        targets.append(G)
                    placed = True
                    break
                if placed:
                    break
            if placed:
                break
        if not placed:
            raise PlacementError(f"could not place fire {n}")
    return fires, targets


INWARD = {"S": (0.0, 1.0), "N": (0.0, -1.0), "W": (1.0, 0.0), "E": (-1.0, 0.0)}


def _missions(staging_edge, staging_pts, fires, targets):
    """إقران المسيّرات بالحرائق. توزيع المهام خارج نطاق المشروع، فنستخدم قاعدة ثابتة:
    ترتيب نقاط الإقلاع على الحافة، وترتيب الحرائق بحسب اتجاهها من منطقة الإقلاع،
    لتقليل التقاطعات غير الضرورية بين الخطوط المستقيمة."""
    axis = 0 if staging_edge in ("S", "N") else 1
    inward = np.array(INWARD[staging_edge])
    along = np.zeros(2)
    along[axis] = 1.0
    ctr = np.mean(np.array(staging_pts)[:, :2], axis=0)
    drone_fires = [f for f in fires if f.handled_by == "drone"]

    def direction(i):
        v = np.array(targets[i][:2]) - ctr
        return np.arctan2(v @ along, v @ inward)

    order_f = sorted(range(len(drone_fires)), key=direction)
    order_s = sorted(range(len(staging_pts)), key=lambda i: staging_pts[i][axis])
    missions = []
    for k, (si, fi) in enumerate(zip(order_s, order_f)):
        G = [round(float(v), 2) for v in targets[fi]]
        missions.append(Mission(k=k, fire=drone_fires[fi].id, S=staging_pts[si], G=G))
    return missions


# الفحوص
def validate(scn: Scenario, cfg: dict) -> list[str]:
    """إعادة قائمة بالمشكلات (القائمة الفارغة = المدينة صالحة)."""
    from .geometry import FireField, segments_boxes_overlap
    from .grid import Grid

    c = cfg["common"]
    s = cfg["sizes"][scn.size]
    W, z_min, z_max = scn.world["W"], scn.world["z_min"], scn.world["z_max"]
    err = []
    B = scn.buildings
    if len(B) != s["n_buildings"]:
        err.append(f"expected {s['n_buildings']} towers, got {len(B)}")
    for b in B:
        if not (b.x0 >= c["edge_margin"] and b.y0 >= c["edge_margin"]
                and b.x1 <= W - c["edge_margin"] and b.y1 <= W - c["edge_margin"]):
            err.append(f"tower {b.id} outside the map margin")
        if not (s["height"][0] <= b.h <= s["height"][1]):
            err.append(f"tower {b.id} height {b.h} outside {s['height']}")
        if not (c["base_size"][0] <= b.x1 - b.x0 <= c["base_size"][1]
                and c["base_size"][0] <= b.y1 - b.y0 <= c["base_size"][1]):
            err.append(f"tower {b.id} footprint size out of range")
    for i in range(len(B)):
        for j in range(i + 1, len(B)):
            a, b = B[i], B[j]
            if _rect_gap((a.x0, a.y0, a.x1, a.y1), (b.x0, b.y0, b.x1, b.y1)) < c["min_gap"]:
                err.append(f"towers {a.id} and {b.id} closer than {c['min_gap']} m")
    boxes = scn.boxes(inflated=True)
    pts = scn.staging["points"]
    for p in pts:
        if min((_point_box_dist(np.array(p), bx) for bx in boxes), default=1e9) <= 0:
            err.append(f"take-off point {p} inside a tower margin")
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            if np.linalg.norm(np.subtract(pts[i], pts[j])) < c["drone"]["d_sep"]:
                err.append("take-off points closer than d_sep")
    F = scn.fires
    if len(F) != s["n_fires"]:
        err.append(f"expected {s['n_fires']} fires, got {len(F)}")
    for i in range(len(F)):
        for j in range(i + 1, len(F)):
            if np.hypot(F[i].c[0] - F[j].c[0], F[i].c[1] - F[j].c[1]) < c["fire"]["min_separation"] - 1e-6:
                err.append(f"fires {F[i].id} and {F[j].id} too close")
    if len(scn.missions) != s["n_drones"]:
        err.append(f"expected {s['n_drones']} missions, got {len(scn.missions)}")
    for m in scn.missions:
        G = np.array(m.G)
        if not (0 <= G[0] <= W and 0 <= G[1] <= W and z_min <= G[2] <= z_max):
            err.append(f"target of drone {m.k} outside the flight space")
        if min(_point_box_dist(G, bx) for bx in boxes) < c["fire"]["target_clearance"] - 1e-6:
            err.append(f"target of drone {m.k} too close to a tower")
    # يجب ألا تُحل المدينة بالطيران المستقيم: خط مستقيم واحد على الأقل S -> G يخترق هامش برج
    straight = segments_boxes_overlap(scn.starts(), scn.goals(), boxes)
    if straight.sum() <= 0:
        err.append("every straight line S -> G is already safe (no obstacle to avoid)")
    # نقاط الإقلاع والأهداف يجب أن تكون خارج قلب الحريق
    field = FireField.from_scenario(scn)
    if field.is_core(scn.starts()).any() or field.is_core(scn.goals()).any():
        err.append("a take-off point or a target is inside a fire core")
    # إمكان الوصول على الشبكة الفراغية بعد حجب الأبراج وقلب الحريق
    g = Grid.from_scenario(scn, fire_core=True)
    s0 = g.nearest_free(scn.missions[0].S)
    reach = g.reachable_from(s0)
    for m in scn.missions:
        if not reach[g.nearest_free(m.S)]:
            err.append(f"take-off of drone {m.k} not connected")
        if not reach[g.nearest_free(m.G)]:
            err.append(f"target of drone {m.k} not reachable")
    return err


# الواجهة البرمجية الرئيسية
def generate_city(size: str, seed: int, cfg: dict | None = None, name: str | None = None,
                  max_attempts: int = 50) -> Scenario:
    cfg = cfg or load_config()
    c, s = cfg["common"], cfg["sizes"][size]
    size_idx = SIZES.index(size)
    for attempt in range(max_attempts):
        seed_used = seed + 1000 * attempt
        rng = np.random.default_rng([seed_used, size_idx])
        try:
            edge, pts = _staging(rng, s["W"], s["n_drones"], c["z_min"], c["staging"])
            buildings = _towers(rng, s, c, pts)
            boxes_inf = [b.inflated(c["d_safe"]) for b in buildings]
            fires, targets = _fires(rng, s, c, buildings, pts, boxes_inf)
            missions = _missions(edge, pts, fires, targets)
        except PlacementError:
            continue
        scn = Scenario(
            name=name or size, size=size, seed=seed, seed_used=seed_used,
            world={"W": s["W"], "z_min": c["z_min"], "z_max": s["z_max"],
                   "d_safe": c["d_safe"], "grid_res": c["grid_res"]},
            drone=dict(c["drone"]),
            hazard={"k": c["fire"]["k"], "tau_core": c["fire"]["tau_core"],
                    "grid_tau": c["fire"]["grid_tau"], "sample_ds": c["fire"]["sample_ds"]},
            problem={"n_drones": s["n_drones"], "n_waypoints": s["n_waypoints"],
                     "n_variables": 3 * s["n_drones"] * s["n_waypoints"], "budget_fe": s["budget_fe"]},
            staging={"edge": edge, "points": pts},
            buildings=buildings, fires=fires, missions=missions,
        )
        if not validate(scn, cfg):
            return scn
    raise RuntimeError(f"could not build a valid {size} city from seed {seed}")


def generate_all(out_dir: str | Path = ROOT / "scenarios", cfg: dict | None = None, verbose=True):
    from .grid import Grid

    cfg = cfg or load_config()
    out_dir = Path(out_dir)
    jobs = [(size, cfg["seeds"]["main"], size, out_dir / f"{size}.json") for size in SIZES]
    for size in SIZES:
        for i, sd in enumerate(cfg["seeds"]["random"], start=1):
            nm = f"{size}_r{i:02d}"
            jobs.append((size, sd, nm, out_dir / "random" / f"{nm}.json"))
    rows = []
    for size, sd, nm, path in jobs:
        t0 = time.perf_counter()
        scn = generate_city(size, sd, cfg, name=nm)
        scn.save(path)
        g = Grid.from_scenario(scn)
        rows.append((nm, scn.seed_used, len(scn.buildings), max(b.h for b in scn.buildings),
                     len(scn.fires), len(scn.missions), g.n_cells, g.info()["free"], time.perf_counter() - t0))
        if verbose:
            r = rows[-1]
            print(f"{r[0]:<12} seed={r[1]:<5} towers={r[2]:<3} max_h={r[3]:<5.0f} fires={r[4]} "
                  f"drones={r[5]} cells={r[6]:>7,} free={r[7]:>7,}  ({r[8]:.1f} s)  -> {path.relative_to(ROOT)}")
    return rows


def main():
    ap = argparse.ArgumentParser(description="Generate the frozen city files.")
    ap.add_argument("--all", action="store_true", help="3 main cities + 10 random cities per size")
    ap.add_argument("--size", choices=SIZES)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", type=str, default=None)
    a = ap.parse_args()
    cfg = load_config()
    if a.all or not a.size:
        generate_all(cfg=cfg)
        return
    seed = cfg["seeds"]["main"] if a.seed is None else a.seed
    scn = generate_city(a.size, seed, cfg)
    out = Path(a.out) if a.out else ROOT / "scenarios" / f"{a.size}_seed{seed}.json"
    scn.save(out)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
