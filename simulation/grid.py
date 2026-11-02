"""بناء شبكة المكعبات الفراغية (Voxel Grid) وتشذيب المسارات لخوارزميتي ACO و DP."""
from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from itertools import product
from typing import Callable, Optional

import numpy as np

from .geometry import FireField, segments_boxes_interval, segments_boxes_overlap

# إزاحات الجيران الستة والعشرين بترتيب ثابت
MOVES = np.array([m for m in product((-1, 0, 1), repeat=3) if m != (0, 0, 0)], dtype=int)


def _shift(a: np.ndarray, o) -> np.ndarray:
    """out[i, j, k] = a[i + o0, j + o1, k + o2]، وFalse خارج المصفوفة."""
    out = np.zeros_like(a)
    src = tuple(slice(max(oi, 0), n + min(oi, 0)) for n, oi in zip(a.shape, o))
    dst = tuple(slice(max(-oi, 0), n + min(-oi, 0)) for n, oi in zip(a.shape, o))
    out[dst] = a[src]
    return out


class Grid:
    def __init__(self, W: float, z_min: float, z_max: float, res: float,
                 boxes: np.ndarray, extra_blocked: Optional[Callable[[np.ndarray], np.ndarray]] = None):
        self.W, self.z_min, self.z_max, self.res = float(W), float(z_min), float(z_max), float(res)
        self.shape = (int(round(W / res)), int(round(W / res)), int(round((z_max - z_min) / res)))
        self.origin = np.array([0.0, 0.0, self.z_min])
        nx, ny, nz = self.shape

        # مراكز الخلايا على كل محور
        self.xs = (np.arange(nx) + 0.5) * res
        self.ys = (np.arange(ny) + 0.5) * res
        self.zs = self.z_min + (np.arange(nz) + 0.5) * res

        # 1) الأبراج: تعليم الخلايا التي يقع مركزها داخل صندوق مضخم
        self.blocked_building = np.zeros(self.shape, dtype=bool)
        for x0, y0, z0, x1, y1, z1 in np.asarray(boxes, dtype=float).reshape(-1, 6):
            ix = (self.xs >= x0) & (self.xs <= x1)
            iy = (self.ys >= y0) & (self.ys <= y1)
            iz = (self.zs >= z0) & (self.zs <= z1)
            self.blocked_building |= ix[:, None, None] & iy[None, :, None] & iz[None, None, :]

        # 2) فحص إضافي اختياري (قلب الحريق المحظور من geometry.py)
        self.blocked_extra = np.zeros(self.shape, dtype=bool)
        if extra_blocked is not None:
            mask = np.asarray(extra_blocked(self.all_centers()), dtype=bool)
            self.blocked_extra = mask.reshape(self.shape) & ~self.blocked_building

        self.free = ~(self.blocked_building | self.blocked_extra)
        self.move_len = np.linalg.norm(MOVES, axis=1) * res      # 10 أو 14.14 أو 17.32 م
        self._allowed = None

    @classmethod
    def from_scenario(cls, scn, fire_core: bool = False, extra_blocked=None,
                      res: Optional[float] = None) -> "Grid":
        """شبكة مدينة. fire_core=True تحجب قلب الحريق المحظور أيضًا (تُستخدم في ACO وDP).

        العتبة grid_tau = 0.45 أقل من tau_core = 0.5، فتعطي هامشًا عند مراكز الخلايا.
        وهذا وحده لا يضمن الخطر على طول الانتقالات المستمرة أو وصلات النهايات.
        """
        if fire_core and extra_blocked is None:
            field = FireField.from_scenario(scn)
            tau = scn.hazard.get("grid_tau", 0.9 * field.tau_core)
            extra_blocked = lambda P: field.H(P) >= tau  # noqa: E731
        w = scn.world
        return cls(w["W"], w["z_min"], w["z_max"], res or w["grid_res"], scn.boxes(inflated=True), extra_blocked)

    # معلومات الحجم
    @property
    def n_cells(self) -> int:
        return int(np.prod(self.shape))

    def info(self) -> dict:
        return {
            "shape": self.shape,
            "cells": self.n_cells,
            "free": int(self.free.sum()),
            "blocked_by_towers": int(self.blocked_building.sum()),
            "blocked_by_fire_core": int(self.blocked_extra.sum()),
        }

    # الإحداثيات <-> الخلايا
    def all_centers(self) -> np.ndarray:
        """(n_cells, 3) مراكز بترتيب C (الترتيب نفسه في free.ravel())."""
        X, Y, Z = np.meshgrid(self.xs, self.ys, self.zs, indexing="ij")
        return np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)

    def center(self, idx) -> np.ndarray:
        i, j, k = idx
        return np.array([self.xs[i], self.ys[j], self.zs[k]])

    def centers(self, cells) -> np.ndarray:
        c = np.asarray(cells, dtype=int).reshape(-1, 3)
        return np.stack([self.xs[c[:, 0]], self.ys[c[:, 1]], self.zs[c[:, 2]]], axis=1)

    def cell_of(self, p) -> tuple:
        """الخلية التي تحتوي النقطة p (مقصوصة إلى الشبكة)."""
        q = np.floor((np.asarray(p, dtype=float) - self.origin) / self.res).astype(int)
        q = np.clip(q, 0, np.array(self.shape) - 1)
        return tuple(int(v) for v in q)

    def nearest_free(self, p) -> tuple:
        """الخلية الحرة الأقرب مركزها إلى p (تُستخدم لنقاط الإقلاع والأهداف)."""
        c = self.cell_of(p)
        if self.free[c]:
            return c
        idx = np.argwhere(self.free)
        d = np.linalg.norm(self.centers(idx) - np.asarray(p, dtype=float), axis=1)
        return tuple(int(v) for v in idx[np.argmin(d)])

    def flat(self, idx) -> int:
        return int(np.ravel_multi_index(idx, self.shape))

    def unflat(self, f: int) -> tuple:
        return tuple(int(v) for v in np.unravel_index(f, self.shape))

    # الانتقالات
    @property
    def allowed(self) -> np.ndarray:
        """allowed[m, i, j, k] تساوي True إذا كان الانتقال MOVES[m] من الخلية (i, j, k) مسموحًا."""
        if self._allowed is None:
            al = np.empty((len(MOVES),) + self.shape, dtype=bool)
            for m, (dx, dy, dz) in enumerate(MOVES):
                ok = self.free.copy()
                for s in product((0, dx), (0, dy), (0, dz)):
                    if s != (0, 0, 0):
                        ok &= _shift(self.free, s)
                al[m] = ok
            self._allowed = al
        return self._allowed

    def neighbors(self, idx):
        """قائمة (الخلية المجاورة، طول الانتقال بالمتر) للانتقالات المسموحة من idx."""
        i, j, k = idx
        ms = np.nonzero(self.allowed[:, i, j, k])[0]
        return [((i + MOVES[m, 0], j + MOVES[m, 1], k + MOVES[m, 2]), float(self.move_len[m])) for m in ms]

    def reachable_from(self, idx) -> np.ndarray:
        """قناع منطقي لكل خلية يمكن بلوغها من idx بانتقالات مسموحة."""
        reach = np.zeros(self.shape, dtype=bool)
        if not self.free[tuple(idx)]:
            return reach
        reach[tuple(idx)] = True
        frontier = reach.copy()
        al = self.allowed
        while frontier.any():
            new = np.zeros_like(reach)
            for m, o in enumerate(MOVES):
                new |= _shift(frontier & al[m], -o)
            frontier = new & ~reach
            reach |= frontier
        return reach


# رسم مخزن مؤقتًا لـ ACO وDP
_GRAPHS: "OrderedDict[str, dict]" = OrderedDict()      # بيانات الشبكة لكل مدينة، تُبنى مرة واحدة في كل عملية


def _city_key(scn) -> str:
    """بصمة كل ما تعتمد عليه الشبكة (مدينتان مختلفتان لا تتشاركان مدخلًا مخزنًا أبدًا)."""
    d = scn.to_dict()
    content = {k: d[k] for k in ("world", "hazard", "buildings", "fires")}
    return hashlib.sha1(json.dumps(content, sort_keys=True).encode()).hexdigest()


def city_graph(scn) -> dict:
    """الشبكة الفراغية لمدينة مع حجب قلب الحريق، وجدول الجيران، والخطر لكل خلية."""
    key = _city_key(scn)
    if key in _GRAPHS:
        _GRAPHS.move_to_end(key)
        return _GRAPHS[key]
    grid = Grid.from_scenario(scn, fire_core=True)
    nx, ny, nz = grid.shape
    n = grid.n_cells
    offset = MOVES[:, 0] * ny * nz + MOVES[:, 1] * nz + MOVES[:, 2]              # خطوة الفهرس المسطح لكل انتقال
    allowed = grid.allowed.reshape(len(MOVES), n).T                              # (n, 26)
    nbr = np.where(allowed, np.arange(n)[:, None] + offset[None, :], -1).astype(np.int32)
    centers = grid.all_centers()
    g = {"grid": grid, "nbr": nbr, "centers": centers, "H": FireField.from_scenario(scn).H(centers),
         "move_len": grid.move_len, "move_dz": MOVES[:, 2] * grid.res}
    _GRAPHS[key] = g
    while len(_GRAPHS) > 3:                                                       # إبقاء الذاكرة محدودة
        _GRAPHS.popitem(last=False)
    return g


class PathPruner:
    """تشذيب بخط النظر لمسألة واحدة (مدينة + مهام)."""

    def __init__(self, problem):
        scn = problem.scn
        self.boxes = problem.boxes
        self.field = problem.field
        self.grid_tau = scn.hazard.get("grid_tau", 0.9 * problem.field.tau_core)
        self.cores = self.core_boxes(problem.field, self.grid_tau)
        self.speed = problem.speed
        self.sep_min = problem.d_sep

    @staticmethod
    def core_boxes(field, tau):
        """صناديق موازية للمحاور تحتوي يقينًا كل نقطة خطرها >= tau. ومع F حريق،
        يحتاج H >= tau حريقًا واحدًا على الأقل بـ h_f >= tau / F، فيستخدم كل صندوق هذا المستوى.
        والمقاطع التي لا تمر بأي من هذه الصناديق لا تحتاج أخذ عينات للخطر."""
        F = field.F
        out = []
        for x, y, z, R, I, Hf in F:
            L = np.log(max(len(F) * I / tau, 1.0 + 1e-9))
            top = Hf * L                                                  # أعلى نقطة في العمود
            half = (R + field.k * top) * np.sqrt(L) + 1.0                 # أبعد امتداد أفقي
            bottom = R / 2.0 * np.sqrt(L) + 1.0                           # مدى امتداده تحت الحريق
            out.append([x - half, y - half, z - bottom, x + half, y + half, z + top + 1.0])
        return np.array(out).reshape(-1, 6)

    def visible(self, a, B):
        """فحص المقاطع المرشحة a -> B[i] مقابل الأبراج وعينات الخطر.
        يستخدم طريقة الألواح لهوامش الأبراج وعينات خطر كل <= 3 م داخل صناديق القلب.
        وقد تفوت المخالفات القصيرة الواقعة بين عينات الخطر."""
        lo = np.minimum(a, B.min(axis=0))
        hi = np.maximum(a, B.max(axis=0))
        bx = self.boxes
        near = np.all(bx[:, :3] <= hi, axis=1) & np.all(bx[:, 3:] >= lo, axis=1)   # الصناديق القريبة من حزمة المقاطع
        A = np.repeat(a[None], len(B), axis=0)
        ok = np.ones(len(B), bool)
        if near.any():
            ok = segments_boxes_overlap(A, B, bx[near]).sum(axis=1) <= 0
        idx = np.flatnonzero(ok)
        if len(idx) and len(self.cores):
            # عينات خطر كل <= 3 م، فقط على أجزاء المقاطع الواقعة داخل صندوق قلب
            t_in, t_out = segments_boxes_interval(A[idx], B[idx], self.cores)      # (s، القلوب)
            seg_i, core_i = np.nonzero(t_out > t_in)
            if len(seg_i):
                L = np.linalg.norm(B[idx] - a, axis=1)
                lo_t, hi_t = t_in[seg_i, core_i], t_out[seg_i, core_i]
                n = np.ceil((hi_t - lo_t) * L[seg_i] / 3.0).astype(int) + 1
                piece = np.repeat(np.arange(len(seg_i)), n)
                first = np.repeat(np.cumsum(n) - n, n)
                u = lo_t[piece] + (hi_t - lo_t)[piece] * (np.arange(len(piece)) - first) / np.repeat(
                    np.maximum(n - 1, 1), n)
                seg = seg_i[piece]
                pts = a + u[:, None] * (B[idx][seg] - a)
                hot = np.zeros(len(idx), bool)
                np.logical_or.at(hot, seg, self.field.H(pts) >= self.grid_tau)
                ok[idx[hot]] = False
        return ok

    def separation_ok(self, a, B, t_a, earlier):
        """لكل مقطع a -> B[i] يُطار من الزمن t_a: هل تبقى المسيّرة على بعد d_sep + 0.5 م على الأقل
        من كل مسيّرة خُططت قبلها (`earlier`: أزمنتها ونقاطها)؟

        دقيق، مثل geometry.pair_min_distance: بين لحظات مرور المسيّرة الأخرى برؤوس مسارها
        تتحرك المسيّرتان في خطين مستقيمين، فلأقرب اقتراب في كل قطعة صيغة مغلقة.
        وتحوم المسيّرة الأخرى عند هدفها بعد الوصول."""
        ok = np.ones(len(B), bool)
        if not earlier:
            return ok
        d = B - a
        L = np.linalg.norm(d, axis=1)
        vel = d / np.maximum(L, 1e-12)[:, None] * self.speed                    # (C, 3) سرعتنا
        t_end = t_a + L / self.speed                                             # (C,)
        radius = self.sep_min + 0.5
        fan_lo, fan_hi = np.minimum(a, B.min(axis=0)) - radius, np.maximum(a, B.max(axis=0)) + radius
        for T, P in earlier:
            # تجاوز سريع: أين يمكن أن تكون المسيّرة الأخرى بينما نطير أيًا من هذه المقاطع؟
            t1 = t_end.max()
            inside = (T > t_a) & (T < t1)
            W = np.vstack([np.stack([np.interp([t_a, t1], T, P[:, c]) for c in range(3)], axis=1), P[inside]])
            if np.any(W.min(axis=0) > fan_hi) or np.any(W.max(axis=0) < fan_lo):
                continue
            # أزمنة الأحداث لكل مرشح: بدايته ونهايته، وأزمنة رؤوس المسيّرة الأخرى
            # داخل نافذته (الأزمنة خارجها تُقص إلى طرفي النافذة: قطع بطول صفر)
            ev = np.sort(np.concatenate([np.clip(T[None, :], t_a, t_end[:, None]),
                                         np.full((len(B), 1), t_a), t_end[:, None]], axis=1), axis=1)
            ours = a + (ev - t_a)[..., None] * vel[:, None, :]                    # (C, E, 3)
            other = np.stack([np.interp(ev, T, P[:, c]) for c in range(3)], axis=-1)
            r = ours - other
            r0, dr = r[:, :-1], np.diff(r, axis=1)
            dd = np.einsum("cek,cek->ce", dr, dr)
            w = np.where(dd > 1e-12, -np.einsum("cek,cek->ce", r0, dr) / np.where(dd > 1e-12, dd, 1.0), 0.0)
            w = np.clip(w, 0.0, 1.0)
            dmin = np.linalg.norm(r0 + w[..., None] * dr, axis=-1).min(axis=1)
            ok &= dmin >= radius
        return ok

    def prune(self, P: np.ndarray, earlier=()) -> np.ndarray:
        """حذف نقاط الامتدادات المستقيمة، ثم اختيار أبعد اختصار يجتاز الفحوص.
        يحتوي `earlier` أزمنة ونقاط المسيّرات المخططة سابقًا، ويُفحص التباعد عنها
        طوال مدة كل اختصار. وإذا فشل كل مرشح يُحتفظ بالنقطة الأصلية التالية؛
        ويبقى هذا البديل والتحويم بعد الوصول محتاجين إلى فحص الخطة النهائية."""
        d = np.diff(P, axis=0)
        u = d / np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-12)
        bend = np.linalg.norm(u[1:] - u[:-1], axis=1) > 1e-9
        P = P[np.concatenate([[True], bend, [True]])]
        keep, i, n, s = [0], 0, len(P), 0.0
        while i < n - 1:
            cand = np.arange(i + 1, n)
            vis = self.visible(P[i], P[cand])
            if earlier and vis.any():
                vis &= self.separation_ok(P[i], P[cand], s / self.speed, earlier)
            j = int(cand[np.flatnonzero(vis)[-1]]) if vis.any() else i + 1
            s += float(np.linalg.norm(P[j] - P[i]))
            keep.append(j)
            i = j
        return P[keep]
