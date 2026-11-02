"""تنفيذ الخوارزمية الجينية (GA) وخوارزمية أسراب الجسيمات (PSO) لتخطيط المسارات في الفضاء المستمر.

يمثّل كل حل خطة طيران كاملة للسرب عبر إحداثيات نقاط التوجيه الوسطية (Waypoints):
    x = [w_11, ..., w_1N, ..., w_K1, ..., w_KN],  w = (x, y, z)
بينما تبقى نقاط الإقلاع S_k ونقاط الهدف G_k ثابتةً لكل مُسيَّرة.
"""
from __future__ import annotations

import math

import numpy as np

from .fitness import Optimizer, algorithm_params


class GA(Optimizer):
    name = "GA"
    default_params = algorithm_params("ga")
    CROSSOVERS = ("drone", "segment", "sbx")

    def __init__(self, **params):
        super().__init__(**params)
        self._check_params()
        self.extra = {}

    def _check_params(self):
        p = self.params
        ops = str(p["crossover"]).split("+")
        if any(o not in self.CROSSOVERS for o in ops) or len(set(ops)) != len(ops):
            raise ValueError(f"crossover must be one or more of {self.CROSSOVERS} joined by '+', "
                             f"got {p['crossover']!r}")
        if not 0.0 <= p["p_c"] <= 1.0:
            raise ValueError(f"p_c must be in [0, 1], got {p['p_c']}")
        if p["p_mut"] < 0:
            raise ValueError(f"p_mut must be >= 0, got {p['p_mut']}")
        if p["eta_c"] < 0:
            raise ValueError(f"eta_c must be >= 0, got {p['eta_c']}")
        if not (p["sigma_start"] >= 0 and p["sigma_end"] >= 0):
            raise ValueError("sigma_start and sigma_end must be >= 0")
        if int(p["tournament_k"]) < 1 or int(p["n_elite"]) < 0:
            raise ValueError("tournament_k must be >= 1 and n_elite >= 0")
        if p.get("pop_size") is not None and int(p["pop_size"]) < int(p["n_elite"]) + 2:
            raise ValueError(f"pop_size must be at least n_elite + 2 = {int(p['n_elite']) + 2}")

    def population_size(self, problem) -> int:
        P = self.params.get("pop_size")
        return int(P if P is not None else algorithm_params("ga", problem.scn.size)["pop_size"])

    # عمليات GA: الانتخاب والتقاطع والطفرة
    @staticmethod
    def tournament(f: np.ndarray, n: int, k: int, rng) -> np.ndarray:
        """انتخاب البطولة بحجم k لاختيار آباء الجيل التالي."""
        idx = rng.integers(0, len(f), size=(n, min(k, len(f))))
        return idx[np.arange(n), np.argmin(f[idx], axis=1)]

    @staticmethod
    def sbx(a: np.ndarray, b: np.ndarray, eta: float, rng):
        """التقاطع الثنائي المحاكى (SBX) للأعداد الحقيقية."""
        u = rng.random(a.shape)
        beta = np.where(u <= 0.5, (2.0 * u) ** (1.0 / (eta + 1.0)),
                        (1.0 / (2.0 * (1.0 - u) + 1e-300)) ** (1.0 / (eta + 1.0)))
        apply = rng.random(a.shape) < 0.5
        c1 = 0.5 * ((1.0 + beta) * a + (1.0 - beta) * b)
        c2 = 0.5 * ((1.0 - beta) * a + (1.0 + beta) * b)
        return np.where(apply, c1, a), np.where(apply, c2, b)

    @staticmethod
    def segment(a: np.ndarray, b: np.ndarray, K: int, N: int, rng):
        """تبادل مقطع متصل من نقاط التوجيه بين الأبوين لكل مُسيَّرة."""
        R = len(a)
        i = rng.integers(0, N, size=(R, K))
        j = rng.integers(i + 1, N + 1)
        n = np.arange(N)[None, None, :]
        mask = (n >= i[..., None]) & (n < j[..., None])                  # (R, K, N)
        mask = np.repeat(mask[..., None], 3, axis=-1).reshape(R, -1)     # القيمة نفسها لـ x وy وz
        return np.where(mask, b, a), np.where(mask, a, b)

    @staticmethod
    def drone(a: np.ndarray, b: np.ndarray, K: int, N: int, rng):
        """لكل مسيّرة يُتبادل مسارها كاملًا بين الأبوين باحتمال 0.5."""
        R = len(a)
        take = rng.random((R, K)) < 0.5
        mask = np.repeat(take, 3 * N, axis=1)                             # (R, K*N*3)
        return np.where(mask, b, a), np.where(mask, a, b)

    def crossover(self, A: np.ndarray, B: np.ndarray, K: int, N: int, rng) -> np.ndarray:
        """تطبيق عملية التقاطع لإنتاج الأبناء من أزواج الآباء."""
        p = self.params
        ops = str(p["crossover"]).split("+")
        C1, C2 = A.copy(), B.copy()
        cross = rng.random(len(A)) < p["p_c"]
        which = rng.integers(0, len(ops), size=len(A))
        for o, name in enumerate(ops):
            rows = cross & (which == o)
            if not rows.any():
                continue
            if name == "sbx":
                C1[rows], C2[rows] = self.sbx(A[rows], B[rows], p["eta_c"], rng)
            elif name == "segment":
                C1[rows], C2[rows] = self.segment(A[rows], B[rows], K, N, rng)
            else:
                C1[rows], C2[rows] = self.drone(A[rows], B[rows], K, N, rng)
        out = np.empty((2 * len(A), A.shape[1]))
        out[0::2], out[1::2] = C1, C2
        return out

    def mutate(self, C: np.ndarray, K: int, N: int, sigma_axis: np.ndarray, rng) -> np.ndarray:
        """الطفرة الغاوسية: تُختار كل نقطة توجيه مركزًا للطفرة باحتمال min(1, p_mut / N)،
        ثم تنتشر إزاحتها إلى النقاط المجاورة بوزن exp(-(d / mut_width)^2).
        الانتشار يقلل الانكسارات المنفردة، لكنه لا يضمن وحده مسارًا آمنًا."""
        M = len(C)
        pw = min(1.0, self.params["p_mut"] / N)
        pick = rng.random((M, K, N)) < pw
        step = rng.normal(size=(M, K, N, 3)) * sigma_axis[None, None, None, :] * pick[..., None]
        w = float(self.params.get("mut_width", 0.0))
        if w > 0:
            d = np.arange(N)[:, None] - np.arange(N)[None, :]
            spread = np.exp(-(d / w) ** 2)                                  # (N, N)
            step = np.einsum("ij,mkjc->mkic", spread, step)
        return (C.reshape(M, K, N, 3) + step).reshape(M, -1)

    def search(self, problem, rng):
        p = self.params
        K, N = problem.K, problem.N
        P = self.population_size(problem)
        n_elite = int(p["n_elite"])
        if P < n_elite + 2:
            raise ValueError(f"pop_size must be at least n_elite + 2 = {n_elite + 2}")
        axis_range = np.array([problem.scn.W, problem.scn.W, problem.bounds[1, 2] - problem.bounds[0, 2]])

        # الجيل 0
        X = problem.initial_population(min(P, problem.remaining), rng)
        f = problem.evaluate_batch(X)
        problem.end_iteration()
        best, stall, gen, stopped_by = f.min(), 0, 0, "budget"
        diversity = [float(np.mean(X.std(axis=0) / np.tile(axis_range, K * N)))]

        while not problem.done:
            gen += 1
            progress = problem.fe / problem.budget
            frac = p["sigma_start"] + (p["sigma_end"] - p["sigma_start"]) * progress
            n_child = min(P - n_elite, problem.remaining)

            parents = self.tournament(f, 2 * math.ceil(n_child / 2), int(p["tournament_k"]), rng)
            C = self.crossover(X[parents[0::2]], X[parents[1::2]], K, N, rng)[:n_child]
            C = problem.clip(self.mutate(C, K, N, frac * axis_range, rng))
            fc = problem.evaluate_batch(C)

            # الجيل التالي: النخبة، مع أفضل الخطط القديمة إذا قطعت الميزانية الأبناء
            keep = np.argsort(f, kind="stable")[: P - n_child]
            X = np.vstack([X[keep], C])
            f = np.concatenate([f[keep], fc])
            problem.end_iteration()
            diversity.append(float(np.mean(X.std(axis=0) / np.tile(axis_range, K * N))))

            if f.min() < best - 1e-12:
                best, stall = f.min(), 0
            else:
                stall += 1
            if p.get("target_f") is not None and best <= p["target_f"]:
                stopped_by = "target_f"
                break
            if p.get("max_stall") is not None and stall >= p["max_stall"]:
                stopped_by = "max_stall"
                break

        self.extra = {"generations": gen, "pop_size": P, "stopped_by": stopped_by,
                      "diversity": [round(d, 5) for d in diversity]}


class PSO(Optimizer):
    """خوارزمية أسراب الجسيمات (PSO) مع تحديث السرعة والموقع وإعادة التشتيت عند الركود."""
    name = "PSO"
    default_params = algorithm_params("pso")
    TOPOLOGIES = ("global", "ring")
    R_MODES = ("dimension", "waypoint", "particle")

    def __init__(self, **params):
        super().__init__(**params)
        self._check_params()
        self.extra = {}

    def _check_params(self):
        p = self.params
        if p["topology"] not in self.TOPOLOGIES:
            raise ValueError(f"topology must be one of {self.TOPOLOGIES}, got {p['topology']!r}")
        if p["r_mode"] not in self.R_MODES:
            raise ValueError(f"r_mode must be one of {self.R_MODES}, got {p['r_mode']!r}")
        if p.get("w_end") is not None and (not np.isfinite(p["w_end"]) or p["w_end"] < 0):
            raise ValueError(f"w_end must be a number >= 0 or null, got {p['w_end']}")
        for key in ("w", "c1", "c2"):
            if not np.isfinite(p[key]) or p[key] < 0:
                raise ValueError(f"{key} must be a number >= 0, got {p[key]}")
        if not 0 < p["v_max"] <= 1:
            raise ValueError(f"v_max is a fraction of the range and must be in (0, 1], got {p['v_max']}")
        if not 0 <= p["init_velocity"] <= 1:
            raise ValueError(f"init_velocity must be in [0, 1], got {p['init_velocity']}")
        if p["restart_mode"] not in ("init", "around_best"):
            raise ValueError(f"restart_mode must be 'init' or 'around_best', got {p['restart_mode']!r}")
        if p.get("restart_stall") is not None and int(p["restart_stall"]) < 1:
            raise ValueError(f"restart_stall must be >= 1 or null, got {p['restart_stall']}")
        if not 0 <= p["stall_tol"] < 1:
            raise ValueError(f"stall_tol must be in [0, 1), got {p['stall_tol']}")
        if not p["restart_sigma"] > 0:
            raise ValueError(f"restart_sigma must be > 0, got {p['restart_sigma']}")
        if int(p["ring_k"]) < 1:
            raise ValueError(f"ring_k must be >= 1, got {p['ring_k']}")
        if p.get("pop_size") is not None and int(p["pop_size"]) < 2:
            raise ValueError(f"pop_size must be at least 2, got {p['pop_size']}")

    def population_size(self, problem) -> int:
        P = self.params.get("pop_size")
        return int(P if P is not None else algorithm_params("pso", problem.scn.size)["pop_size"])

    @staticmethod
    def neighbourhood_best(pbest_f: np.ndarray, topology: str, k: int) -> np.ndarray:
        """تحديد أفضل موقع مرشد لكل جسيم (شامل أو حلقي)."""
        P = len(pbest_f)
        if topology == "global" or 2 * k + 1 >= P:
            return np.full(P, int(np.argmin(pbest_f)))
        idx = (np.arange(P)[:, None] + np.arange(-k, k + 1)[None, :]) % P      # (P, 2k+1)
        return idx[np.arange(P), np.argmin(pbest_f[idx], axis=1)]

    @staticmethod
    def random_factors(shape, r_mode: str, rng) -> np.ndarray:
        """توليد r1 أو r2 بحسب r_mode: قيمة لكل جسيم، أو لكل نقطة توجيه، أو لكل إحداثي."""
        M, D = shape
        if r_mode == "dimension":
            return rng.random(shape)
        if r_mode == "waypoint":
            return np.repeat(rng.random((M, D // 3)), 3, axis=1)
        return np.repeat(rng.random((M, 1)), D, axis=1)

    @classmethod
    def step(cls, X, V, pbest, guide, w, c1, c2, vmax, lower, upper, rng, r_mode="dimension"):
        """خطوة تحديث السرعة والموقع لجميع الجسيمات."""
        r1 = cls.random_factors(X.shape, r_mode, rng)
        r2 = cls.random_factors(X.shape, r_mode, rng)
        V = w * V + c1 * r1 * (pbest - X) + c2 * r2 * (guide - X)
        V = np.clip(V, -vmax, vmax)
        X = X + V
        hit = (X < lower) | (X > upper)
        X = np.clip(X, lower, upper)
        V = np.where(hit, 0.0, V)                     # الجدران الماصّة
        return X, V

    def restart(self, problem, X, V, pbest, pbest_f, rng):
        """إعادة توزيع الجسيمات مع الاحتفاظ بأفضل جسيم عند ثبات التحسن."""
        p = self.params
        b = int(np.argmin(pbest_f))
        others = np.setdiff1d(np.arange(len(X)), [b])
        n = min(len(others), problem.remaining)
        others = others[:n]
        if n == 0:
            return X, V, pbest, pbest_f
        if p["restart_mode"] == "init":
            new = problem.initial_population(n, rng)
        else:
            new = problem.clip(pbest[b] + rng.normal(0.0, 1.0, (n, X.shape[1]))
                               * p["restart_sigma"] * (problem.upper - problem.lower))
        X, V, pbest, pbest_f = X.copy(), V.copy(), pbest.copy(), pbest_f.copy()
        X[others], V[others] = new, 0.0
        f = problem.evaluate_batch(new)
        pbest[others], pbest_f[others] = new, f
        return X, V, pbest, pbest_f

    def search(self, problem, rng):
        p = self.params
        P = self.population_size(problem)
        lower, upper = problem.lower, problem.upper
        vmax = p["v_max"] * (upper - lower)
        axis_range = upper - lower

        # الدورة 0: خطط البداية نفسها المستخدمة في GA (البذرة نفسها -> المجتمع نفسه)
        n0 = min(P, problem.remaining)
        X = problem.initial_population(n0, rng)
        V = p["init_velocity"] * vmax * rng.uniform(-1.0, 1.0, X.shape) if p["init_velocity"] > 0 \
            else np.zeros_like(X)
        f = problem.evaluate_batch(X)
        pbest, pbest_f = X.copy(), f.copy()
        problem.end_iteration()
        best, stall, it, stopped_by = float(pbest_f.min()), 0, 0, "budget"
        since_restart, restarts = 0, 0
        diversity = [float(np.mean(X.std(axis=0) / axis_range))]

        while not problem.done:
            it += 1
            g = self.neighbourhood_best(pbest_f, p["topology"], int(p["ring_k"]))
            w = p["w"] if p.get("w_end") is None else \
                p["w"] + (p["w_end"] - p["w"]) * problem.fe / problem.budget      # جدول خطي اختياري
            X, V = self.step(X, V, pbest, pbest[g], w, p["c1"], p["c2"], vmax, lower, upper, rng,
                             p["r_mode"])
            n = min(len(X), problem.remaining)        # قد تنتهي الميزانية في منتصف السرب
            f = problem.evaluate_batch(X[:n])
            better = f < pbest_f[:n]
            pbest[:n][better] = X[:n][better]
            pbest_f[:n][better] = f[better]
            problem.end_iteration()
            diversity.append(float(np.mean(X.std(axis=0) / axis_range)))

            # تحسن أقل من stall_tol نسبيًا لا يُعد تقدمًا، فلا يصفّر عدادي الركود.
            if pbest_f.min() < best * (1.0 - p["stall_tol"]):
                best, stall, since_restart = float(pbest_f.min()), 0, 0
            else:
                stall += 1
                since_restart += 1
            if p.get("restart_stall") is not None and since_restart >= p["restart_stall"] and not problem.done:
                X, V, pbest, pbest_f = self.restart(problem, X, V, pbest, pbest_f, rng)
                since_restart, restarts = 0, restarts + 1
            if p.get("target_f") is not None and best <= p["target_f"]:
                stopped_by = "target_f"
                break
            if p.get("max_stall") is not None and stall >= p["max_stall"]:
                stopped_by = "max_stall"
                break

        self.extra = {"iterations": it, "pop_size": P, "stopped_by": stopped_by, "restarts": restarts,
                      "diversity": [round(d, 5) for d in diversity],
                      "mean_speed": float(np.mean(np.abs(V) / axis_range))}
