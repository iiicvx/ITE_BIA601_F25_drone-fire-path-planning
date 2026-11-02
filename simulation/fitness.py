"""حساب دالة الهدف (Fitness Function) والواجهة المشتركة لتقييم الخوارزميات الأربع (GA, PSO, ACO, DP).

تُقاس جودة مسار كل مُسيَّرة k عبر أربعة معايير:
    F_k = w_T J_T + w_E J_E + w_H J_H + w_S J_S
مع إضافة عقوبة القيود الصلبة V (الاصطدام بالأبراج، قلب اللهب، سعة البطارية، المسافة الفاصلة، حدود الفضاء):
    F = mean(F_k) + M * V + P0 * [V > 0]
"""
from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np
import yaml

from . import geometry as G
from .geometry import FireField

ROOT = Path(__file__).resolve().parent


class BudgetExhausted(RuntimeError):
    """يُرفع عندما تطلب خوارزمية تقييمات لياقة أكثر مما تسمح به ميزانيتها."""


@dataclass
class Weights:
    w_T: float = 1.0
    w_E: float = 0.5
    w_H: float = 10.0
    w_S: float = 0.5


@dataclass
class Penalty:
    M: float = 1000.0
    P0: float = 100.0


def load_fitness_config(path: str | Path = ROOT / "config" / "fitness.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


# أهداف مسيّرة واحدة
def path_objectives(path, L_ref: float, E_ref: float, exposure: float, drone: dict) -> dict:
    """أهداف بلا وحدات: الخط المستقيم يعطي J_T = J_E = 1 وJ_S = 0؛ ويعتمد J_H على H."""
    L = G.path_length(path)
    E = G.path_energy(path, drone["e_c"], drone["e_up"])
    theta = G.turn_angles(path)
    return {
        "J_T": L / L_ref,
        "J_E": E / E_ref,
        "J_H": exposure / L_ref,
        "J_S": float(np.sum((theta / np.pi) ** 2)),
        "length_m": L,
        "energy_j": E,
    }


def weighted_sum(obj: dict, w: Weights) -> float:
    return w.w_T * obj["J_T"] + w.w_E * obj["J_E"] + w.w_H * obj["J_H"] + w.w_S * obj["J_S"]


# المسألة
class Problem:
    """مدينة واحدة + دالة لياقة واحدة + ميزانية تقييم واحدة، مشتركة بين كل الخوارزميات."""

    def __init__(self, scn, weights: Weights | None = None, penalty: Penalty | None = None,
                 budget: int | None = None, strict_budget: bool = True, cfg: dict | None = None):
        cfg = cfg or load_fitness_config()
        self.scn = scn
        self.weights = weights or Weights(**cfg["weights"])
        self.penalty = penalty or Penalty(**cfg["penalty"])
        self.init_cfg = cfg["init"]
        self.snapshot_fracs = list(cfg["snapshots"])

        self.K = len(scn.missions)
        self.N = int(scn.problem["n_waypoints"])
        self.dim = 3 * self.K * self.N                       # 18 / 90 / 210 متغيرًا
        self.S, self.G = scn.starts(), scn.goals()
        self.bounds = scn.bounds
        self.lower = np.tile(self.bounds[0], self.K * self.N)
        self.upper = np.tile(self.bounds[1], self.K * self.N)
        self.boxes = scn.boxes(inflated=True)
        self.boxes_real = scn.boxes(inflated=False)
        self.field = FireField.from_scenario(scn)
        self.drone = scn.drone
        self.speed, self.d_sep = float(scn.drone["speed"]), float(scn.drone["d_sep"])

        dz = np.maximum(self.G[:, 2] - self.S[:, 2], 0.0)
        self.L_ref = np.linalg.norm(self.G - self.S, axis=1)
        self.E_ref = self.drone["e_c"] * self.L_ref + self.drone["e_up"] * dz
        self.E_max = self.drone["battery_kj"] * 1000.0 * self.drone["battery_usable"]

        self.budget = int(budget if budget is not None else scn.problem["budget_fe"])
        self.strict_budget = strict_budget
        self.reset()

    # السجلات
    def reset(self):
        """نسيان كل ما يخص التشغيلات السابقة (تُستدعى قبل كل تشغيل جديد على Problem نفسه)."""
        self.fe = 0
        self.best_f = math.inf
        self.best_paths = None
        self.best_x = None
        self.best_info = None
        self.history = []            # (fe, best_f) في كل مرة تتحسن فيها أفضل قيمة
        self.iter_history = []       # (iteration, fe, best_f) من end_iteration()
        self.first_feasible_fe = None
        self.snapshots = []          # أفضل خطة عند نسب ثابتة من الميزانية
        self._snap_fe = [max(1, math.ceil(f * self.budget)) for f in self.snapshot_fracs]
        self._t0 = time.perf_counter()

    @property
    def done(self) -> bool:
        return self.fe >= self.budget

    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.fe)

    def end_iteration(self):
        """تسجيل (iteration, fe, best_f): نقطة واحدة من منحنى التكرار مقابل أفضل لياقة."""
        self.iter_history.append((len(self.iter_history) + 1, self.fe, self.best_f))

    # متجه الحل <-> المسارات
    def waypoints(self, x) -> np.ndarray:
        """x (dim,) -> (K, N, 3) نقاط توجيه، مقصوصة إلى حيّز الطيران."""
        w = np.asarray(x, dtype=float).reshape(self.K, self.N, 3)
        return np.clip(w, self.bounds[0], self.bounds[1])

    def decode(self, x) -> list[np.ndarray]:
        """x (dim,) -> K خطوط متعددة المقاطع [S_k, w_k1, ..., w_kN, G_k]، كل منها (N + 2, 3)."""
        w = self.waypoints(x)
        return [np.vstack([self.S[k], w[k], self.G[k]]) for k in range(self.K)]

    def encode(self, paths) -> np.ndarray:
        """K خطوط متعددة المقاطع بها N نقطة توجيه داخلية بالضبط -> x (dim,)."""
        return np.concatenate([np.asarray(p, dtype=float)[1:-1].ravel() for p in paths])

    def clip(self, x) -> np.ndarray:
        return np.clip(x, self.lower, self.upper)

    def straight_line_x(self) -> np.ndarray:
        """نقاط توجيه متساوية التباعد على الخط المستقيم S -> G لكل مسيّرة."""
        t = (np.arange(1, self.N + 1) / (self.N + 1))[None, :, None]
        return (self.S[:, None, :] + t * (self.G - self.S)[:, None, :]).ravel()

    def random_x(self, rng) -> np.ndarray:
        return rng.uniform(self.lower, self.upper)

    def via_point_x(self, n: int, rng) -> np.ndarray:
        """n خطة عشوائية: تطير كل مسيّرة S -> V -> G عبر نقطة عبور عشوائية خاصة بها V
        (موزعة بانتظام في حيّز الطيران)، مع توزيع N نقطة توجيه بالتساوي على ذلك المسار ذي الضلعين."""
        lo, hi = self.bounds
        V = rng.uniform(lo, hi, (n, self.K, 3))
        t = np.arange(1, self.N + 1) / (self.N + 1)                       # نسب الطول القوسي
        S, G = self.S[None], self.G[None]                                  # (1, K, 3)
        l1 = np.linalg.norm(V - S, axis=-1)
        l2 = np.linalg.norm(G - V, axis=-1)
        L = l1 + l2 + 1e-12
        s = t[None, None, :] * L[..., None]                                # (n, K, N)
        first = s <= l1[..., None]
        u1 = np.where(first, s / np.maximum(l1[..., None], 1e-12), 0.0)
        u2 = np.where(first, 0.0, (s - l1[..., None]) / np.maximum(l2[..., None], 1e-12))
        P1 = S[:, :, None, :] + u1[..., None] * (V - S)[:, :, None, :]
        P2 = V[:, :, None, :] + u2[..., None] * (G - V)[:, :, None, :]
        return np.where(first[..., None], P1, P2).reshape(n, -1)

    def initial_population(self, size: int, rng) -> np.ndarray:
        """المجتمع الابتدائي لـ GA وPSO (هو نفسه للاثنتين عند إعطاء البذرة نفسها).

        * line_fraction (20%): نقاط توجيه على الخط المستقيم S -> G مع ضجيج غاوسي (5% من W)
        * البقية: التفافات عشوائية S -> V -> G عبر نقطة عبور عشوائية V، مع ضجيج صغير
          (1% من W). تذهب يمينًا ويسارًا وفوق الأبراج وحولها، فيبدأ البحث من مسارات
          كثيرة مختلفة. (أما النمط 'uniform' فينثر نقاط التوجيه عشوائيًا.)
        """
        n_line = int(round(self.init_cfg["line_fraction"] * size))
        n_rest = size - n_line
        X = np.empty((size, self.dim))
        if n_line:
            noise = rng.normal(0.0, self.init_cfg["line_noise"] * self.scn.W, (n_line, self.dim))
            X[:n_line] = self.straight_line_x() + noise
        if n_rest:
            if self.init_cfg.get("mode", "via") == "uniform":
                X[n_line:] = rng.uniform(self.lower, self.upper, (n_rest, self.dim))
            else:
                noise = rng.normal(0.0, self.init_cfg.get("via_noise", 0.01) * self.scn.W, (n_rest, self.dim))
                X[n_line:] = self.via_point_x(n_rest, rng) + noise
        return self.clip(X)

    # التقييم
    def evaluate(self, x) -> float:
        """لياقة متجه حل واحد (يُحسب تقييمًا واحدًا)."""
        x = np.asarray(x, dtype=float)
        F, _ = self.evaluate_paths(self.decode(x), x=x)
        return F

    def evaluate_batch(self, X) -> np.ndarray:
        """لياقة كل صف من X (يُحسب تقييم لكل صف)."""
        return np.array([self.evaluate(x) for x in np.atleast_2d(X)])

    def evaluate_paths(self, paths, count: bool = True, x=None) -> tuple[float, dict]:
        """لياقة K خطوط متعددة المقاطع وتفصيل كل حد فيها. count=False للتقارير فقط."""
        if count and self.strict_budget and self.fe >= self.budget:
            raise BudgetExhausted(f"budget of {self.budget} evaluations used up")
        paths = [G.as_path(p) for p in paths]
        if len(paths) != self.K:
            raise ValueError(f"expected {self.K} paths, got {len(paths)}")
        if not all(np.isfinite(p).all() for p in paths):
            raise ValueError("a path contains NaN or infinite coordinates (bug in the algorithm?)")
        w, pen = self.weights, self.penalty

        # الأهداف
        hz = self.field.paths_hazard(paths)
        objs = [path_objectives(p, self.L_ref[k], self.E_ref[k], hz[k]["exposure"], self.drone)
                for k, p in enumerate(paths)]
        F_k = np.array([weighted_sum(o, w) for o in objs])

        # القيود
        col = G.collision_lengths(paths, self.boxes)
        core = np.array([h["core_length"] for h in hz])
        E = np.array([o["energy_j"] for o in objs])
        out = np.array([np.linalg.norm(np.maximum(np.maximum(self.bounds[0] - p, 0.0), p - self.bounds[1]),
                                       axis=1).sum() for p in paths])
        V_col, V_core = col / self.L_ref, core / self.L_ref
        V_bat = np.maximum(0.0, E - self.E_max) / self.E_max
        V_bound = out / self.L_ref
        if self.K > 1:
            sep = G.min_separation(paths, self.speed)
            iu = np.triu_indices(self.K, 1)
            V_sep = float(np.maximum(0.0, 1.0 - sep["matrix"][iu] / self.d_sep).sum())
            d_min = sep["d_min"]
        else:
            V_sep, d_min = 0.0, math.inf
        V = float(np.mean(V_col + V_core + V_bat + V_bound) + V_sep)
        feasible = V <= 1e-12
        F_obj = float(F_k.mean())
        F = F_obj + pen.M * V + (0.0 if feasible else pen.P0)

        info = {
            "F": F, "F_obj": F_obj, "V": V, "feasible": bool(feasible),
            "F_k": F_k.tolist(),
            "J_T": [o["J_T"] for o in objs], "J_E": [o["J_E"] for o in objs],
            "J_H": [o["J_H"] for o in objs], "J_S": [o["J_S"] for o in objs],
            "V_col": V_col.tolist(), "V_core": V_core.tolist(), "V_bat": V_bat.tolist(),
            "V_bound": V_bound.tolist(), "V_sep": V_sep,
            "length_m": [o["length_m"] for o in objs], "energy_kj": (E / 1000.0).tolist(),
            "collision_m": col.tolist(), "core_m": core.tolist(),
            "max_hazard": [h["max_hazard"] for h in hz], "d_min_m": d_min,
        }
        if count:
            self._record(F, paths, info, x)
        return F, info

    def _record(self, F, paths, info, x):
        self.fe += 1
        if F < self.best_f:
            self.best_f = F
            self.best_paths = [p.copy() for p in paths]
            self.best_x = None if x is None else np.array(x, dtype=float)
            self.best_info = info
            self.history.append((self.fe, F))
        if info["feasible"] and self.first_feasible_fe is None:
            self.first_feasible_fe = self.fe
        while len(self.snapshots) < len(self._snap_fe) and self.fe >= self._snap_fe[len(self.snapshots)]:
            self.snapshots.append({"fe": self.fe, "best_f": self.best_f,
                                   "paths": [p.tolist() for p in self.best_paths]})

    # تقرير كامل (لا يُحسب من الميزانية)
    def report(self, paths) -> dict:
        """كل ما يخص الخطة، لجداول النتائج والمدقق والموقع."""
        F, info = self.evaluate_paths(paths, count=False)
        paths = [G.as_path(p) for p in paths]
        drones = []
        for k, p in enumerate(paths):
            clear, _, _ = G.path_clearance(p, self.boxes_real)
            bat = G.battery_report(p, self.drone)
            drones.append({
                "k": k,
                "length_m": info["length_m"][k],
                "time_s": info["length_m"][k] / self.speed,
                "energy_kj": bat["energy_kj"],
                "battery_used_pct": 100.0 * bat["battery_used"],
                "exposure": info["J_H"][k] * self.L_ref[k],
                "max_hazard": info["max_hazard"][k],
                "clearance_m": clear,
                "collision_m": info["collision_m"][k],
                "core_m": info["core_m"][k],
                "turns_deg": np.degrees(G.turn_angles(p)).round(1).tolist(),
                "F_k": info["F_k"][k],
            })
        sep = G.min_separation(paths, self.speed) if self.K > 1 else None
        return {
            "scenario": self.scn.name, "F": F, "F_obj": info["F_obj"], "V": info["V"],
            "feasible": info["feasible"],
            "mission_time_s": max(d["time_s"] for d in drones),
            "min_separation_m": None if sep is None else sep["d_min"],
            "min_separation_at_s": None if sep is None else sep["t"],
            "min_separation_pair": None if sep is None else list(sep["pair"]),
            "min_clearance_m": min(d["clearance_m"] for d in drones),
            "drones": drones,
            "terms": {k: info[k] for k in ("J_T", "J_E", "J_H", "J_S", "V_col", "V_core", "V_bat",
                                           "V_bound", "V_sep")},
            "weights": asdict(self.weights), "penalty": asdict(self.penalty),
        }


# إعدادات المُحسِّن والنتائج
def algorithm_params(name: str, size: str | None = None,
                     path: str | Path = ROOT / "config" / "algorithms.yaml") -> dict:
    """المعاملات الفائقة لخوارزمية واحدة من config/algorithms.yaml.
    القيم المعطاة لكل حجم ({small: .., medium: .., large: ..}) تُحدَّد عند إعطاء `size`،
    وإلا تُترك None (فتحددها الخوارزمية من المدينة التي تعمل عليها)."""
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    merged = {**cfg.get("common", {}), **(cfg.get(name) or {})}
    out = {}
    for k, v in merged.items():
        if isinstance(v, dict) and set(v) <= {"small", "medium", "large"}:
            out[k] = v[size] if size else None
        else:
            out[k] = v
    return out


@dataclass
class Result:
    algorithm: str
    scenario: str
    seed: int
    params: dict
    best_f: float
    feasible: bool
    fe_used: int
    budget: int
    time_s: float
    first_feasible_fe: int | None
    paths: list                       # K خطوط متعددة المقاطع لأفضل خطة (قوائم [x, y, z])
    report: dict                      # Problem.report(أفضل خطة): كل المقاييس
    history: list                     # (fe, best_f) عند كل تحسن
    iter_history: list                # (iteration, fe, best_f) -> منحنى التكرار مقابل أفضل لياقة
    snapshots: list = field(default_factory=list)   # أفضل خطة عند نسب ثابتة من الميزانية (للموقع)
    extra: dict = field(default_factory=dict)       # تفاصيل خاصة بالخوارزمية (الأجيال، سبب التوقف...)

    def to_dict(self) -> dict:
        return asdict(self)


class Optimizer(ABC):
    name: str = "base"
    default_params: dict = {}

    def __init__(self, **params):
        unknown = set(params) - set(self.default_params)
        if self.default_params and unknown:
            raise ValueError(f"unknown parameter(s) for {self.name}: {sorted(unknown)}; "
                             f"allowed: {sorted(self.default_params)}")
        self.params = {**self.default_params, **params}

    @abstractmethod
    def search(self, problem: Problem, rng: np.random.Generator) -> None:
        """البحث حتى problem.done (أو حتى تنتهي الطريقة نفسها، مثل DP)."""


def run_once(alg: Optimizer, scn, seed: int, budget: int | None = None, problem: Problem | None = None) -> Result:
    """تشغيل `alg` على المدينة `scn` بالبذرة `seed`؛ قابل للإعادة على البيئة العددية نفسها."""
    problem = problem or Problem(scn, budget=budget)
    problem.reset()
    rng = np.random.default_rng(seed)
    t0 = time.perf_counter()
    try:
        alg.search(problem, rng)
    except BudgetExhausted:
        pass                                   # انتهت الميزانية في منتصف دورة
    elapsed = time.perf_counter() - t0
    if problem.best_paths is None:
        raise RuntimeError(f"{alg.name} did not evaluate any solution")
    if not problem.iter_history or problem.iter_history[-1][1] != problem.fe:
        problem.end_iteration()                # إغلاق المنحنى عند آخر تقييم
    rep = problem.report(problem.best_paths)
    return Result(
        algorithm=alg.name, scenario=scn.name, seed=seed, params=dict(alg.params),
        best_f=float(problem.best_f), feasible=bool(rep["feasible"]), fe_used=problem.fe,
        budget=problem.budget, time_s=elapsed, first_feasible_fe=problem.first_feasible_fe,
        # دقة كاملة: التقريب قد ينقل خطة تقع على الحد تمامًا (مثل 10.00003 م بين
        # مسيّرتين) إلى الجهة الخاطئة منه، والخطة المحفوظة يجب أن تكون الخطة التي قُيّمت
        paths=[p.tolist() for p in problem.best_paths], report=rep,
        history=[(int(a), float(b)) for a, b in problem.history],
        iter_history=[(int(i), int(a), float(b)) for i, a, b in problem.iter_history],
        snapshots=problem.snapshots,
        extra=dict(getattr(alg, "extra", {}) or {}),
    )


class RandomSearch(Optimizer):
    # مثال عملي مختصر للواجهة البرمجية، تستخدمه الاختبارات أيضًا.
    name = "RandomSearch"
    default_params = {"batch": 50}

    def search(self, problem, rng):
        while not problem.done:
            n = min(self.params["batch"], problem.remaining)
            X = problem.initial_population(n, rng)     # 20% قرب الخط المستقيم، و80% التفافات
            problem.evaluate_batch(X)                  # يحسب n تقييمات ويحتفظ بالأفضل
            problem.end_iteration()                    # نقطة واحدة من منحنى التقارب


# خطة مرجعية آمنة بسيطة
def climb_over_plan(scn, step: float = 15.0) -> list[np.ndarray]:
    """خطة مرجعية للفحوص والعروض (ليست خوارزمية): تصعد كل مسيّرة رأسيًا فوق
    الأبراج الواقعة تحت خط طيرانها، ثم تطير أفقيًا، ثم تهبط إلى هدفها. وتطير المسيّرة k
    أعلى من الارتفاع اللازم لها بـ k * step متر، فلا تلتقي المسيّرات في الجو."""
    d = scn.world["d_safe"]
    plans = []
    for k, m in enumerate(scn.missions):
        S, Gk = np.array(m.S), np.array(m.G)
        need = max(S[2], Gk[2])
        for b in scn.buildings:     # أبراج يلامس هامشها خط الطيران الأفقي
            box = np.array([b.x0 - d, b.y0 - d, -1.0, b.x1 + d, b.y1 + d, 1.0])
            p0, p1 = np.array([S[0], S[1], 0.0]), np.array([Gk[0], Gk[1], 0.0])
            if G.segments_boxes_overlap([p0], [p1], box[None])[0, 0] > 0 or \
                    G.points_boxes_distance([p0], box[None])[0, 0] == 0:
                need = max(need, b.h + d + 3.0)
        z = min(need + k * step, scn.world["z_max"] - 0.5)
        plans.append(np.array([S, [S[0], S[1], z], [Gk[0], Gk[1], z], Gk]))
    return plans


# عرض توضيحي وتبرير الأوزان
def weight_justification(city_files=None) -> dict:
    """لماذا هذه الأوزان؟ نوعان من الأدلة، محسوبان من المدن الحقيقية.

    1. التكافؤات: ما الذي يكلف مثل جعل المسار أطول بنسبة 10% (+0.1 * w_T)؟
         صعود إضافي   dh    = 0.1 * E_ref / (w_E * e_up)        (يعتمد على المهمة)
         الخطر        أمتار الطيران عند H = 0.3 = 0.1 * L_ref / (w_H * 0.3)
         انعطاف واحد  theta = pi * sqrt(0.1 / w_S)
    2. التوازن: حصة كل حد موزون من F للخطة المرجعية الآمنة في كل مدينة.
       مجموعة الأوزان الجيدة تجعل الزمن في المقدمة (سرعة الإنقاذ) دون أن يصبح أي حد مهملًا.
    """
    from .scenarios import load_scenario

    files = city_files or sorted(list((ROOT / "scenarios").glob("*.json")) +
                                 list((ROOT / "scenarios" / "random").glob("*.json")))
    climb, hazard_m, shares = [], [], []
    w = None
    for f in files:
        scn = load_scenario(f)
        pb = Problem(scn)
        w = pb.weights
        climb += list(0.1 * pb.E_ref / (w.w_E * pb.drone["e_up"]))
        hazard_m += list(0.1 * pb.L_ref / (w.w_H * 0.3))
        _, i = pb.evaluate_paths(climb_over_plan(scn), count=False)
        t = np.array([w.w_T * np.mean(i["J_T"]), w.w_E * np.mean(i["J_E"]),
                      w.w_H * np.mean(i["J_H"]), w.w_S * np.mean(i["J_S"])])
        shares.append(t / t.sum())
    sh = np.array(shares)
    return {
        "n_cities": len(files), "n_missions": len(climb), "weights": asdict(w),
        "climb_m": {"median": float(np.median(climb)), "min": float(np.min(climb)), "max": float(np.max(climb))},
        "hazard_m_at_0.3": {"median": float(np.median(hazard_m)), "min": float(np.min(hazard_m)),
                            "max": float(np.max(hazard_m))},
        "turn_deg": float(np.degrees(np.pi * np.sqrt(0.1 / w.w_S))),
        "turns_of_30deg": float(0.1 / (w.w_S * (30 / 180) ** 2)),
        "share_mean": dict(zip(("time", "energy", "hazard", "smoothness"), sh.mean(axis=0).round(3).tolist())),
        "share_min": dict(zip(("time", "energy", "hazard", "smoothness"), sh.min(axis=0).round(3).tolist())),
        "share_max": dict(zip(("time", "energy", "hazard", "smoothness"), sh.max(axis=0).round(3).tolist())),
    }


def main():
    """python -m simulation.fitness            تقييم خطتين بسيطتين في كل مدينة أساسية
    python -m simulation.fitness --weights  الأدلة على اختيار الأوزان (للتقرير)"""
    import argparse
    import json

    from .scenarios import load_scenario

    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", action="store_true")
    if ap.parse_args().weights:
        r = weight_justification()
        print(json.dumps(r, indent=1))
        print(f"\nWhat costs the same as a 10 % longer path ({r['n_missions']} missions, {r['n_cities']} cities):")
        print(f"  climbing an extra {r['climb_m']['median']:.0f} m (median; {r['climb_m']['min']:.0f}-{r['climb_m']['max']:.0f} m)")
        print(f"  flying {r['hazard_m_at_0.3']['median']:.0f} m through hazard 0.3 (median; "
              f"{r['hazard_m_at_0.3']['min']:.0f}-{r['hazard_m_at_0.3']['max']:.0f} m)")
        print(f"  one {r['turn_deg']:.0f} degree turn, or {r['turns_of_30deg']:.1f} turns of 30 degrees")
        print("Share of each term in F for the safe reference plans: "
              + ", ".join(f"{k} {100 * v:.0f} %" for k, v in r["share_mean"].items()))
        return
    print(f"{'city':<8}{'plan':<12}{'F':>9}  {'safe':<6}{'mean F_k':>9}{'V':>9}   J_T / J_E / J_H / J_S (mean over drones)")
    for size in ("small", "medium", "large"):
        scn = load_scenario(ROOT / "scenarios" / f"{size}.json")
        pb = Problem(scn)
        for name, paths in (("straight", pb.decode(pb.straight_line_x())), ("climb-over", climb_over_plan(scn))):
            F, i = pb.evaluate_paths(paths, count=False)
            terms = " / ".join(f"{np.mean(i[t]):.3f}" for t in ("J_T", "J_E", "J_H", "J_S"))
            print(f"{size:<8}{name:<12}{F:>9.3f}  {str(i['feasible']):<6}{i['F_obj']:>9.3f}{i['V']:>9.4f}   {terms}")


if __name__ == "__main__":
    main()
