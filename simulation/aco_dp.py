"""خوارزميتا ACO وDP على الشبكة الفراغية.

تبني نمال MMAS المسار خلية بخلية، ثم يُشذَّب المسار بخط النظر.
أما DP فتحسب أقل كلفة انتقال جمعية على الشبكة بعلاقة Bellman-Ford، وتُستخدم خط أساس للمقارنة.
"""
from __future__ import annotations

import numpy as np

from .fitness import Optimizer, algorithm_params
from .grid import PathPruner, city_graph

class ACO(Optimizer):
    name = "ACO"
    default_params = algorithm_params("aco")

    def __init__(self, **params):
        super().__init__(**params)
        self._check_params()
        self.extra = {}

    def _check_params(self):
        p = self.params
        for key in ("alpha", "beta", "lambda_h", "climb_weight", "conflict_margin"):
            if not np.isfinite(p[key]) or p[key] < 0:
                raise ValueError(f"{key} must be a number >= 0, got {p[key]}")
        if not 0 < p["rho"] < 1:
            raise ValueError(f"rho must be in (0, 1), got {p['rho']}")
        if not p["tau_ratio"] > 1:
            raise ValueError(f"tau_ratio must be > 1, got {p['tau_ratio']}")
        if int(p["gb_every"]) < 1:
            raise ValueError(f"gb_every must be >= 1, got {p['gb_every']}")
        if not p["step_factor"] >= 1:
            raise ValueError(f"step_factor must be >= 1, got {p['step_factor']}")
        if not isinstance(p["prune"], bool):
            raise ValueError(f"prune must be true or false, got {p['prune']!r}")
        if p.get("pop_size") is not None and int(p["pop_size"]) < 1:
            raise ValueError(f"pop_size must be at least 1, got {p['pop_size']}")

    def population_size(self, problem) -> int:
        P = self.params.get("pop_size")
        return int(P if P is not None else algorithm_params("aco", problem.scn.size)["pop_size"])

    def prune(self, P: np.ndarray, earlier=()) -> np.ndarray:
        """تشذيب المسار بخط النظر الآمن."""
        return self._pruner.prune(P, earlier)

    @staticmethod
    def _positions(T, P, q):
        """المواضع على خطوط متعددة المقاطع مبطنة عند الأزمنة q. T (a, L) أزمنة (inf = بطانة)، وP (a, L, 3)،
        وq (a, c) أزمنة الاستعلام -> (a, c, 3). بعد النقطة الأخيرة تحوم المسيّرة عندها."""
        L = T.shape[1]
        rows = np.arange(len(T))[:, None]
        i0 = np.clip((T[:, None, :] <= q[..., None]).sum(-1) - 1, 0, max(L - 2, 0))
        i1 = np.minimum(i0 + 1, L - 1)
        t0, t1 = np.take_along_axis(T, i0, 1), np.take_along_axis(T, i1, 1)
        span = np.where(np.isfinite(t1), t1 - t0, 0.0)
        frac = np.clip(np.where(span > 0, (q - t0) / np.where(span > 0, span, 1.0), 0.0), 0.0, 1.0)
        p0, p1 = P[rows, i0], P[rows, i1]
        return p0 + frac[..., None] * (p1 - p0)

    def _conflicts(self, prev, act, s_act, cur_act, nb0):
        """تعليم الجيران المرشحين القريبين جدًا من مسيّرة سابقة عند زمن الوصول المقدَّر.
        يفحص هذا نهاية الانتقال، لا الانتقال المستمر كله.
        تُتجاوز النمال البعيدة عن كل مسيّرة سابقة: ففي خطوة واحدة لا تتحرك النملة ولا المسيّرة السابقة
        أكثر من خلية قطرية واحدة (17.3 م)، فلا تعارض ممكنًا لها."""
        g = self._g
        bad = np.zeros(nb0.shape, bool)
        reach = self._sep_radius + 2.0 * g["move_len"].max()
        here = g["centers"][cur_act]                                                   # (a, 3)
        for T, P in prev:                                    # T (النمل، L) أزمنة، وP (النمل، L، 3) نقاط
            Ta, Pa = T[act], P[act]
            now = self._positions(Ta, Pa, (s_act / self._speed)[:, None])[:, 0]       # (a, 3)
            close = np.flatnonzero(np.linalg.norm(here - now, axis=1) < reach)
            if len(close) == 0:
                continue
            q = (s_act[close, None] + g["move_len"][None, :]) / self._speed            # (c, 26)
            pos = self._positions(Ta[close], Pa[close], q)
            bad[close] |= np.linalg.norm(g["centers"][nb0[close]] - pos, axis=-1) < self._sep_radius
        return bad

    def construct(self, k, n_ants, tau_k, prev, rng):
        """كل النمال تسير للمسيّرة k في الوقت نفسه (حساب متجهي). تعيد (الخلايا، الأطوال، الفشل)."""
        p, g = self.params, self._g
        start, goal = self._start[k], self._goal[k]
        steps = self._max_steps[k]
        dgoal = self._dgoal[k]
        cur = np.full(n_ants, start, np.int64)
        s = np.zeros(n_ants)
        active = np.ones(n_ants, bool)
        failed = np.zeros(n_ants, bool)
        path = np.full((n_ants, steps + 1), -1, np.int64)
        path[:, 0] = start
        length = np.ones(n_ants, np.int64)
        visited = self._visited
        visited[np.arange(n_ants), start] = True
        hz = np.exp(-p["lambda_h"] * g["H"])
        climb = p["climb_weight"] * np.maximum(g["move_dz"], 0.0)
        res = self._res
        for _ in range(steps):
            act = np.flatnonzero(active)
            if len(act) == 0:
                break
            nb = g["nbr"][cur[act]]
            ok = nb >= 0
            nb0 = np.where(ok, nb, 0)
            ok &= ~visited[act[:, None], nb0]
            if prev:
                ok &= ~self._conflicts(prev, act, s[act], cur[act], nb0)
            reduced = g["move_len"][None, :] + dgoal[nb0] - dgoal[cur[act]][:, None] + climb[None, :]
            eta = np.exp(-reduced / res) * hz[nb0]
            w = np.where(ok, tau_k[nb0] ** p["alpha"] * eta ** p["beta"], 0.0)
            tot = w.sum(axis=1)
            dead = ~(tot > 0)
            if dead.any():
                failed[act[dead]] = True
                active[act[dead]] = False
                live = ~dead
                act, w, nb0, tot = act[live], w[live], nb0[live], tot[live]
                if len(act) == 0:
                    break
            u = rng.random(len(act)) * tot
            choice = np.minimum((np.cumsum(w, axis=1) < u[:, None]).sum(axis=1), w.shape[1] - 1)
            nxt = nb0[np.arange(len(act)), choice]
            s[act] += g["move_len"][choice]
            path[act, length[act]] = nxt
            length[act] += 1
            visited[act, nxt] = True
            cur[act] = nxt
            active[act[nxt == goal]] = False
        failed |= active                                     # بلغ حد الخطوات
        rows = np.repeat(np.arange(n_ants), length)
        visited[rows, path[path >= 0]] = False               # تفريغ قوائم المحظورات للمسيّرة التالية
        return path, length, failed

    def to_polyline(self, k, cells, failed, earlier=()):
        """مسار خلايا -> [S، مراكز الخلايا...، G] بعد التشذيب. يُخزَّن مؤقتًا لأن النمل يكرر المسارات كثيرًا؛
        ويشمل المفتاح مسارات المسيّرات السابقة، لأن التشذيب يعتمد عليها."""
        key = (k, cells.tobytes()) + tuple(P.tobytes() for _, P in earlier)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        P = np.vstack([self._S[k], self._g["centers"][cells], self._G[k]])
        if self.params["prune"] and not failed:
            P = self.prune(P, earlier)
        if len(self._cache) > 50_000:
            self._cache.clear()
        self._cache[key] = P
        return P

    def _times(self, P):
        """الزمن الذي تصل فيه المسيّرة إلى كل رأس من رؤوس مسارها."""
        return np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]) / self._speed

    def prepare(self, problem):
        """تهيئة شبكة المدينة والمسافات الابتدائية للنمل."""
        p = self.params
        g = self._g = city_graph(problem.scn)
        grid = g["grid"]
        self._res = grid.res
        self._pruner = PathPruner(problem)
        self._cores = self._pruner.cores
        self._speed = problem.speed
        self._sep_radius = problem.d_sep + p["conflict_margin"]
        self._sep_min = problem.d_sep
        self._S, self._G = problem.S, problem.G
        self._cache = {}
        K = problem.K
        self._start = [grid.flat(grid.nearest_free(problem.S[k])) for k in range(K)]
        self._goal = [grid.flat(grid.nearest_free(problem.G[k])) for k in range(K)]
        self._dgoal = [np.linalg.norm(g["centers"] - problem.G[k], axis=1) for k in range(K)]
        cheb = [int(np.max(np.abs(np.array(grid.unflat(a)) - np.array(grid.unflat(b)))))
                for a, b in zip(self._start, self._goal)]
        self._max_steps = [max(10, int(p["step_factor"] * c)) for c in cheb]
        self._visited = np.zeros((self.population_size(problem), grid.n_cells), bool)

    def search(self, problem, rng):
        p = self.params
        self.prepare(problem)
        K, A, n_cells = problem.K, self.population_size(problem), self._g["grid"].n_cells
        tau = np.ones((K, n_cells))
        gb = None                                             # (F، [خلايا كل مسيّرة]) الأفضل حتى الآن
        it, stall, best, stopped_by = 0, 0, np.inf, "budget"
        unique_frac, fail_frac = [], []
        while not problem.done:
            it += 1
            m = min(A, problem.remaining)
            plans = [[None] * K for _ in range(m)]
            cells = [[None] * K for _ in range(m)]
            bad = np.zeros(m, bool)
            prev = []
            for k in range(K):
                path, length, failed = self.construct(k, m, tau[k], prev, rng)
                bad |= failed
                polys = []
                for a in range(m):
                    c = path[a, :length[a]]
                    cells[a][k] = c
                    earlier = [(self._times(q), q) for q in plans[a][:k]]
                    polys.append(self.to_polyline(k, c, failed[a], earlier))
                    plans[a][k] = polys[-1]
                if k < K - 1:                                 # المسيّرات اللاحقة تتجنب هذه المسارات
                    L = max(len(q) for q in polys)
                    T = np.full((m, L), np.inf)
                    Pp = np.empty((m, L, 3))
                    for a, q in enumerate(polys):
                        T[a, :len(q)] = self._times(q)
                        Pp[a, :len(q)], Pp[a, len(q):] = q, q[-1]
                    prev.append((T, Pp))
            F = np.array([problem.evaluate_paths(plans[a])[0] for a in range(m)])

            # الفيرومون: تبخر، ثم إيداع بأفضل خطة في الدورة أو الأفضل حتى الآن، ثم قص
            ok = np.flatnonzero(~bad)
            if len(ok):
                ib = int(ok[np.argmin(F[ok])])
                if gb is None or F[ib] < gb[0]:
                    gb = (float(F[ib]), [c.copy() for c in cells[ib]])
            if gb is not None:
                tau_max = 1.0 / (p["rho"] * gb[0])
                tau_min = tau_max / p["tau_ratio"]
                if it == 1:
                    tau.fill(tau_max)
                tau *= 1.0 - p["rho"]
                dep_f, dep_cells = (gb if (it % int(p["gb_every"]) == 0 or not len(ok))
                                    else (float(F[ib]), cells[ib]))
                for k in range(K):
                    tau[k, np.unique(dep_cells[k])] += 1.0 / dep_f
                np.clip(tau, tau_min, tau_max, out=tau)

            problem.end_iteration()
            unique_frac.append(round(len({b"".join(c.tobytes() for c in cs) for cs in cells}) / m, 4))
            fail_frac.append(round(float(bad.mean()), 4))
            if problem.best_f < best - 1e-12:
                best, stall = problem.best_f, 0
            else:
                stall += 1
            if p.get("target_f") is not None and best <= p["target_f"]:
                stopped_by = "target_f"
                break
            if p.get("max_stall") is not None and stall >= p["max_stall"]:
                stopped_by = "max_stall"
                break

        self.extra = {"iterations": it, "ants": A, "stopped_by": stopped_by,
                      "unique_plans": unique_frac, "failed_ants": fail_frac,
                      "max_steps": self._max_steps}
        self._visited = None


class DP(Optimizer):
    """البرمجة الديناميكية بعلاقة Bellman-Ford على الشبكة الفراغية، خط أساس حتمي للمقارنة."""
    name = "DP"
    default_params = algorithm_params("dp")

    def __init__(self, **params):
        super().__init__(**params)
        p = self.params
        if not isinstance(p["prune"], bool):
            raise ValueError(f"prune must be true or false, got {p['prune']!r}")
        if p.get("max_sweeps") is not None and int(p["max_sweeps"]) < 1:
            raise ValueError(f"max_sweeps must be >= 1 or null, got {p['max_sweeps']}")
        self.extra = {}

    @staticmethod
    def step_costs(problem, k):
        """كلفة انتقالات المسيّرة k: جزء ثابت (الزمن والطاقة)، ومعامل يُضرب في متوسط خطر الخليتين."""
        g = city_graph(problem.scn)
        w, dr = problem.weights, problem.drone
        L, dz = g["move_len"], g["move_dz"]
        const = (w.w_T * L / problem.L_ref[k]
                 + w.w_E * (dr["e_c"] * L + dr["e_up"] * np.maximum(dz, 0.0)) / problem.E_ref[k])
        haz = w.w_H * L / problem.L_ref[k]
        return const, haz

    def bellman_ford(self, g, start, goal, const, haz):
        """إرخاء Bellman-Ford على الخلايا التي تغيرت كلفتها فقط، حتى تستقر الكلفة. يعيد (d, pred, info)."""
        nbr, H = g["nbr"], g["H"]
        n, M = nbr.shape
        d = np.full(n, np.inf)
        pred = np.full(n, -1, np.int64)
        d[start] = 0.0
        active = np.array([start], np.int64)
        sweeps, relaxed, changed_log, goal_log = 0, 0, [], []
        limit = self.params.get("max_sweeps")
        converged = True
        while len(active):
            if limit is not None and sweeps >= int(limit):
                converged = False
                break
            sweeps += 1
            nb = nbr[active]                                            # (a, 26)
            ok = nb >= 0
            src = np.repeat(active, M)[ok.ravel()]
            mv = np.tile(np.arange(M), len(active))[ok.ravel()]
            dst = nb[ok].astype(np.int64)
            cand = d[src] + const[mv] + haz[mv] * 0.5 * (H[src] + H[dst])
            relaxed += len(cand)
            better = cand < d[dst]
            src, dst, cand = src[better], dst[better], cand[better]
            if len(dst):                                                # الإبقاء على أفضل عرض لكل خلية
                order = np.lexsort((cand, dst))
                dst, src, cand = dst[order], src[order], cand[order]
                first = np.concatenate([[True], dst[1:] != dst[:-1]])
                dst, src, cand = dst[first], src[first], cand[first]
                d[dst] = cand
                pred[dst] = src
            active = dst
            changed_log.append(int(len(dst)))
            goal_log.append(None if not np.isfinite(d[goal]) else round(float(d[goal]), 6))
        info = {"sweeps": sweeps, "relaxed_edges": int(relaxed), "converged": converged,
                "changed_per_sweep": changed_log, "goal_cost_per_sweep": goal_log}
        return d, pred, info

    @staticmethod
    def extract(pred, start, goal):
        """استرجاع مسار الخلايا من جدول السوابق (فارغ إذا لم يُبلغ الهدف)."""
        if pred[goal] < 0 and goal != start:
            return np.zeros(0, np.int64)
        path = [goal]
        while path[-1] != start:
            path.append(int(pred[path[-1]]))
            if len(path) > len(pred):                                   # لا يحدث مع كلف موجبة
                raise RuntimeError("predecessor loop in the DP table")
        return np.array(path[::-1], np.int64)

    def search(self, problem, rng):
        g = city_graph(problem.scn)
        grid = g["grid"]
        pruner = PathPruner(problem)
        plans, info = [], {"sweeps": [], "relaxed_edges": [], "converged": [], "grid_cost": [],
                           "path_cells": [], "no_path": [], "changed_per_sweep": [], "goal_cost_per_sweep": []}
        for k in range(problem.K):
            start = grid.flat(grid.nearest_free(problem.S[k]))
            goal = grid.flat(grid.nearest_free(problem.G[k]))
            const, haz = self.step_costs(problem, k)
            d, pred, bf = self.bellman_ford(g, start, goal, const, haz)
            cells = self.extract(pred, start, goal)
            if len(cells) == 0:                                         # لا يمكن الوصول إلى الهدف
                info["no_path"].append(k)
                P = np.vstack([problem.S[k], problem.G[k]])
            else:
                P = np.vstack([problem.S[k], g["centers"][cells], problem.G[k]])
                if self.params["prune"]:
                    P = pruner.prune(P)
            plans.append(P)
            info["sweeps"].append(bf["sweeps"])
            info["relaxed_edges"].append(bf["relaxed_edges"])
            info["converged"].append(bf["converged"])
            info["grid_cost"].append(None if not np.isfinite(d[goal]) else float(d[goal]))
            info["path_cells"].append(int(len(cells)))
            info["changed_per_sweep"].append(bf["changed_per_sweep"])
            info["goal_cost_per_sweep"].append(bf["goal_cost_per_sweep"])
        problem.evaluate_paths(plans)                                   # تقييم واحد للخطة كاملة
        problem.end_iteration()
        self.extra = info
