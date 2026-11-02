"""الحسابات الهندسية للفضاء ثلاثي الأبعاد: كشف الاصطدام، حقل الخطر الحراري، الطاقة، والمسافة الفاصلة."""
from __future__ import annotations

import numpy as np

EPS = 1e-9
_GOLD = (np.sqrt(5.0) - 1.0) / 2.0


# الأساسيات
def as_path(path) -> np.ndarray:
    p = np.asarray(path, dtype=float)
    if p.ndim != 2 or p.shape[1] != 3 or len(p) < 2:
        raise ValueError(f"a path must be an (n>=2, 3) array, got shape {p.shape}")
    return p


def segment_lengths(path) -> np.ndarray:
    return np.linalg.norm(np.diff(as_path(path), axis=0), axis=1)


def path_length(path) -> float:
    return float(segment_lengths(path).sum())


def cumulative_length(path) -> np.ndarray:
    """الطول القوسي s عند كل رأس (s[0] = 0، وs[-1] = طول المسار)."""
    return np.concatenate([[0.0], np.cumsum(segment_lengths(path))])


def _dedupe(path, tol=1e-9) -> np.ndarray:
    """حذف النقاط المتتالية المكررة (مقاطع بطول صفر)."""
    p = as_path(path)
    keep = np.concatenate([[True], np.linalg.norm(np.diff(p, axis=0), axis=1) > tol])
    q = p[keep]
    return q if len(q) >= 2 else np.vstack([q, q])


def clip_to_bounds(points, bounds) -> np.ndarray:
    """قص النقاط إلى حيّز الطيران. bounds = scn.bounds = [[xmin, ymin, zmin], [xmax, ymax, zmax]]."""
    b = np.asarray(bounds, dtype=float)
    return np.clip(np.asarray(points, dtype=float), b[0], b[1])


def outside_bounds(points, bounds, tol=1e-9) -> np.ndarray:
    b = np.asarray(bounds, dtype=float)
    p = np.asarray(points, dtype=float)
    return np.any((p < b[0] - tol) | (p > b[1] + tol), axis=-1)


# الاصطدامات (طريقة الألواح)
def segments_boxes_interval(p0, p1, boxes):
    """جزء كل مقطع p0[i] -> p1[i] الواقع داخل كل صندوق، كمعاملين t_in <= t_out في [0, 1].

    p0, p1: (S, 3)   boxes: (B, 6)   ->   (t_in, t_out)، كل منهما (S, B). وحيث t_out <= t_in لا يمر
    المقطع بالصندوق. طريقة الألواح: على كل محور يكون المقطع داخل الصندوق عندما t في [t1, t2]؛
    ويكون داخل الصندوق حيث تتداخل الفترات الثلاث.
    """
    p0 = np.atleast_2d(np.asarray(p0, dtype=float))[:, None, :]          # (S, 1, 3)
    p1 = np.atleast_2d(np.asarray(p1, dtype=float))[:, None, :]
    boxes = np.asarray(boxes, dtype=float).reshape(-1, 6)
    lo, hi = boxes[None, :, :3], boxes[None, :, 3:]                      # (1, B, 3)
    d = p1 - p0
    par = np.abs(d) < EPS                                                 # موازٍ لهذا المحور
    with np.errstate(divide="ignore", invalid="ignore"):
        inv = 1.0 / np.where(par, 1.0, d)
        t1 = (lo - p0) * inv
        t2 = (hi - p0) * inv
    inside_axis = (p0 >= lo) & (p0 <= hi)
    tmin = np.where(par, np.where(inside_axis, -np.inf, np.inf), np.minimum(t1, t2))
    tmax = np.where(par, np.where(inside_axis, np.inf, -np.inf), np.maximum(t1, t2))
    return np.clip(tmin.max(axis=-1), 0.0, 1.0), np.clip(tmax.min(axis=-1), 0.0, 1.0)


def segments_boxes_overlap(p0, p1, boxes) -> np.ndarray:
    """طول كل مقطع p0[i] -> p1[i] الواقع داخل كل صندوق.

    p0, p1: (S, 3)   boxes: (B, 6)   ->   (S, B) بالمتر.
    طريقة الألواح (انظر segments_boxes_interval): التداخل = max(0, t_out - t_in) * طول المقطع.
    وهي دقيقة دون أخذ عينات.
    """
    p0 = np.atleast_2d(np.asarray(p0, dtype=float))
    L = np.linalg.norm(np.atleast_2d(np.asarray(p1, dtype=float)) - p0, axis=-1)[:, None]
    t_in, t_out = segments_boxes_interval(p0, p1, boxes)
    return np.maximum(t_out - t_in, 0.0) * L


def collision_length(path, boxes) -> float:
    """الطول الكلي داخل الصناديق، بما فيه الطيران على أسطحها.
    الطول الصفري ينفي التداخل بطول موجب، لا ملامسة نقطة منفردة.
    استخدم scn.boxes() لفحص هوامش الأبراج المضخمة."""
    p = as_path(path)
    boxes = np.asarray(boxes, dtype=float).reshape(-1, 6)
    if len(boxes) == 0:
        return 0.0
    return float(segments_boxes_overlap(p[:-1], p[1:], boxes).sum())


def collision_lengths(paths, boxes) -> np.ndarray:
    """collision_length لعدة مسارات في استدعاء متجهي واحد: (K,) بالمتر."""
    paths = [as_path(p) for p in paths]
    boxes = np.asarray(boxes, dtype=float).reshape(-1, 6)
    if len(boxes) == 0:
        return np.zeros(len(paths))
    p0 = np.concatenate([p[:-1] for p in paths])
    p1 = np.concatenate([p[1:] for p in paths])
    per_seg = segments_boxes_overlap(p0, p1, boxes).sum(axis=1)
    owner = np.repeat(np.arange(len(paths)), [len(p) - 1 for p in paths])
    return np.bincount(owner, weights=per_seg, minlength=len(paths))


def collisions(path, boxes, tol=1e-6) -> list[tuple[int, int, float]]:
    """كل (رقم المقطع، رقم الصندوق، الأمتار داخله) ذات تداخل حقيقي، للتقارير وتتبع الأخطاء."""
    p = as_path(path)
    ov = segments_boxes_overlap(p[:-1], p[1:], boxes)
    return [(int(i), int(j), float(ov[i, j])) for i, j in zip(*np.nonzero(ov > tol))]


# المسافات
def points_boxes_distance(points, boxes) -> np.ndarray:
    """(n, 3) نقاط، (B, 6) صناديق -> (n, B) مسافة إقليدية (0 داخل الصندوق)."""
    p = np.atleast_2d(np.asarray(points, dtype=float))[:, None, :]
    boxes = np.asarray(boxes, dtype=float).reshape(-1, 6)
    lo, hi = boxes[None, :, :3], boxes[None, :, 3:]
    return np.linalg.norm(np.maximum(np.maximum(lo - p, 0.0), p - hi), axis=-1)


def clearance_at_points(points, boxes) -> np.ndarray:
    """المسافة من كل نقطة إلى أقرب صندوق، مثل قيمة أقرب برج في لوحة الطيران.
    إذا لم توجد صناديق إطلاقًا (مدينة اختبار خالية) تكون كل مسافة لا نهائية."""
    d = points_boxes_distance(points, boxes)
    return d.min(axis=1) if d.shape[1] else np.full(d.shape[0], np.inf)


def segments_boxes_distance(p0, p1, boxes, iters: int = 60) -> np.ndarray:
    """تصغير عددي للمسافة بين كل مقطع وكل صندوق: (S, B).

    المسافة من نقطة متحركة p(t) = p0 + t (p1 - p0) إلى صندوق محدب دالة محدبة
    في t، فيجد بحث المقطع الذهبي على t في [0, 1] أصغرها. وتضيّق 60 خطوة الفترة
    في t إلى نحو 1e-13؛ وهذا ليس حدًا مطلقًا لخطأ المسافة بالمتر.
    """
    p0 = np.atleast_2d(np.asarray(p0, dtype=float))[:, None, :]
    d = np.atleast_2d(np.asarray(p1, dtype=float))[:, None, :] - p0
    boxes = np.asarray(boxes, dtype=float).reshape(-1, 6)
    lo, hi = boxes[None, :, :3], boxes[None, :, 3:]
    shape = (p0.shape[0], boxes.shape[0])

    def f(t):
        q = p0 + t[..., None] * d
        return np.linalg.norm(np.maximum(np.maximum(lo - q, 0.0), q - hi), axis=-1)

    a, b = np.zeros(shape), np.ones(shape)
    c, e = b - _GOLD * (b - a), a + _GOLD * (b - a)
    fc, fe = f(c), f(e)
    for _ in range(iters):
        left = fc < fe
        b = np.where(left, e, b)
        a = np.where(left, a, c)
        c, e = b - _GOLD * (b - a), a + _GOLD * (b - a)
        fc, fe = f(c), f(e)
    best = np.minimum(np.minimum(f(np.zeros(shape)), f(np.ones(shape))), np.minimum(fc, fe))
    return best


def path_clearance(path, boxes) -> tuple[float, int, int]:
    """(أصغر مسافة من المسار إلى أي صندوق، رقم المقطع، رقم الصندوق).
    استخدم الأبراج الحقيقية هنا: path_clearance(path, scn.boxes(inflated=False))."""
    p = as_path(path)
    if np.asarray(boxes).size == 0:
        return float("inf"), -1, -1                        # مدينة خالية: لا شيء يُصطدم به
    dist = segments_boxes_distance(p[:-1], p[1:], boxes)
    i, j = np.unravel_index(np.argmin(dist), dist.shape)
    return float(dist[i, j]), int(i), int(j)


# أخذ العينات والانعطافات
def sample_path(path, ds: float = 2.0):
    """تقسيم كل مقطع إلى قطع متساوية لا يزيد طولها على ds متر وإعادة منتصفاتها.

    تعيد (النقاط (m, 3)، الأوزان (m,)، s (m,)): الأوزان أطوال القطع (مجموعها
    طول المسار)، وs الطول القوسي عند كل منتصف. فيصير التكامل الخطي لحقل f على
    المسار sum(f(points) * weights) (قاعدة المنتصف).
    """
    p = as_path(path)
    seg = np.diff(p, axis=0)
    L = np.linalg.norm(seg, axis=1)
    n = np.where(L > EPS, np.ceil(L / ds), 0).astype(int)
    idx = np.repeat(np.arange(len(L)), n)
    if len(idx) == 0:
        return p[:1].copy(), np.zeros(1), np.zeros(1)
    k = np.arange(len(idx)) - np.repeat(np.cumsum(n) - n, n)           # رقم القطعة داخل مقطعها
    u = (k + 0.5) / n[idx]
    pts = p[idx] + u[:, None] * seg[idx]
    w = L[idx] / n[idx]
    s = cumulative_length(p)[idx] + u * L[idx]
    return pts, w, s


def turn_angles(path, min_len: float = 1e-6) -> np.ndarray:
    """زاوية الانعطاف (بالراديان) عند كل نقطة توجيه داخلية: 0 = استقامة، وpi = استدارة كاملة.
    تُتجاهل المقاطع الأقصر من min_len، فلا تنشئ نقطة توجيه مكررة انعطافًا زائفًا."""
    seg = np.diff(as_path(path), axis=0)
    seg = seg[np.linalg.norm(seg, axis=1) >= min_len]
    if len(seg) < 2:
        return np.zeros(0)
    a, b = seg[:-1], seg[1:]
    cos = np.einsum("ij,ij->i", a, b) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1))
    return np.arccos(np.clip(cos, -1.0, 1.0))


# الطاقة والبطارية
def segment_energy(path, e_c: float = 20.0, e_up: float = 100.0) -> np.ndarray:
    """طاقة كل مقطع (جول): E = e_c * الطول + e_up * max(الصعود, 0).

    معاملات مفترضة، لا قياسات للمسيّرة المعروضة:
    e_c = 20 جول/م تقابل حدًا أساسيًا قدره 200 واط عند 10 م/ث.
    e_up = 100 جول/م تقارب 6 كغ * 9.81 / 0.6 لكل متر صعود.
    الهبوط يدفع حد الطول فقط، دون كلفة صعود إضافية ودون استرداد طاقة.
    التحويم والتسارع والتأثيرات الهوائية خارج هذا النموذج.
    """
    d = np.diff(as_path(path), axis=0)
    return e_c * np.linalg.norm(d, axis=1) + e_up * np.maximum(d[:, 2], 0.0)


def path_energy(path, e_c: float = 20.0, e_up: float = 100.0) -> float:
    return float(segment_energy(path, e_c, e_up).sum())


def battery_report(path, drone: dict) -> dict:
    """استهلاك الطاقة مقابل البطارية. drone = scn.drone (e_c, e_up, battery_kj, battery_usable)."""
    E = path_energy(path, drone["e_c"], drone["e_up"])
    cap = drone["battery_kj"] * 1000.0
    e_max = cap * drone["battery_usable"]
    return {
        "energy_kj": E / 1000.0,
        "battery_used": E / cap,                 # نسبة من البطارية الكاملة (0.25 = 25%)
        "e_max_kj": e_max / 1000.0,
        "over_limit_kj": max(0.0, E - e_max) / 1000.0,
        "enough": E <= e_max,
    }


# التوقيت
def vertex_times(path, speed: float) -> np.ndarray:
    """الزمن الذي تمر فيه المسيّرة بكل رأس (بسرعة ثابتة)."""
    return cumulative_length(path) / speed


def arrival_time(path, speed: float) -> float:
    return path_length(path) / speed


def positions_at(path, times, speed: float) -> np.ndarray:
    """موضع المسيّرة عند كل زمن (s = speed * t على طول المسار).
    قبل t = 0 تكون عند S؛ وبعد الوصول تحوم عند G (وتبقى محسوبة في التباعد)."""
    p = _dedupe(path)
    tv = vertex_times(p, speed)
    t = np.clip(np.asarray(times, dtype=float), 0.0, tv[-1])
    return np.stack([np.interp(t, tv, p[:, k]) for k in range(3)], axis=-1)


def pair_min_distance(path_a, path_b, speed: float) -> tuple[float, float]:
    """أقرب اقتراب دقيق بين مسيّرتين تطيران على مساريهما بالسرعة نفسها: (المسافة، الزمن).

    بين حدثين متتاليين (وصول مسيّرة إلى رأس أو إلى الهدف) تتحرك المسيّرتان
    في خطين مستقيمين بسرعة ثابتة، فيكون موضعهما النسبي خطيًا في الزمن، ولأصغر
    قيمة في كل فترة صيغة مغلقة. وأخذ الأصغر عبر كل الفترات دقيق.
    """
    a, b = _dedupe(path_a), _dedupe(path_b)
    ta, tb = vertex_times(a, speed), vertex_times(b, speed)
    t = np.unique(np.concatenate([ta, tb]))
    r = positions_at(a, t, speed) - positions_at(b, t, speed)       # الموضع النسبي عند الأحداث
    if len(t) == 1:
        return float(np.linalg.norm(r[0])), 0.0
    r0, dr = r[:-1], np.diff(r, axis=0)
    dd = np.einsum("ij,ij->i", dr, dr)
    with np.errstate(divide="ignore", invalid="ignore"):
        u = np.where(dd > EPS, -np.einsum("ij,ij->i", r0, dr) / dd, 0.0)
    u = np.clip(u, 0.0, 1.0)
    dist = np.linalg.norm(r0 + u[:, None] * dr, axis=1)
    i = int(np.argmin(dist))
    return float(dist[i]), float(t[i] + u[i] * (t[i + 1] - t[i]))


def min_separation(paths, speed: float) -> dict:
    """أقرب اقتراب عبر كل أزواج المسيّرات (دقيق، لكل الأزواج دفعة واحدة).
    تعيد {'d_min', 't', 'pair': (i, j), 'matrix': (K, K) أصغر المسافات الزوجية}.

    الفكرة نفسها في pair_min_distance مع دمج أحداث كل المسيّرات: بين حدثين
    متتاليين تطير كل مسيّرة في خط مستقيم بسرعة ثابتة.
    """
    paths = [_dedupe(p) for p in paths]
    K = len(paths)
    M = np.full((K, K), np.inf)
    if K < 2:
        return {"d_min": float("inf"), "t": 0.0, "pair": (-1, -1), "matrix": M}
    t = np.unique(np.concatenate([vertex_times(p, speed) for p in paths]))
    pos = np.stack([positions_at(p, t, speed) for p in paths])           # (K, T, 3)
    I, J = np.triu_indices(K, 1)
    r = pos[I] - pos[J]                                                   # (P, T, 3)
    if len(t) == 1:
        dist, u, tmin = np.linalg.norm(r[:, 0], axis=1)[:, None], np.zeros((len(I), 1)), np.zeros((len(I), 1))
    else:
        r0, dr = r[:, :-1], np.diff(r, axis=1)
        dd = np.einsum("ptk,ptk->pt", dr, dr)
        with np.errstate(divide="ignore", invalid="ignore"):
            u = np.where(dd > EPS, -np.einsum("ptk,ptk->pt", r0, dr) / dd, 0.0)
        u = np.clip(u, 0.0, 1.0)
        dist = np.linalg.norm(r0 + u[..., None] * dr, axis=-1)            # (P, T-1)
        tmin = t[:-1][None, :] + u * np.diff(t)[None, :]
    k = np.argmin(dist, axis=1)
    dpair = dist[np.arange(len(I)), k]
    M[I, J] = M[J, I] = dpair
    b = int(np.argmin(dpair))
    return {"d_min": float(dpair[b]), "t": float(tmin[b, k[b]]), "pair": (int(I[b]), int(J[b])), "matrix": M}


def separation_samples(paths, speed: float, dt: float = 0.5):
    """المسافات بين كل زوج من المسيّرات عند الأزمنة 0 وdt و2dt ... حتى آخر وصول.
    تعيد (الأزمنة (T,)، المسافات (T, P)، قائمة الأزواج P (i, j)).
    تُستخدم في الاختبارات للمقارنة مع min_separation؛ أما العقوبة فتستخدم الناتج التحليلي."""
    T = max(arrival_time(p, speed) for p in paths)
    times = np.arange(0.0, T + dt, dt)
    pos = np.stack([positions_at(p, times, speed) for p in paths])     # (K, T, 3)
    pairs = [(i, j) for i in range(len(paths)) for j in range(i + 1, len(paths))]
    if not pairs:
        return times, np.zeros((len(times), 0)), pairs
    D = np.stack([np.linalg.norm(pos[i] - pos[j], axis=1) for i, j in pairs], axis=1)
    return times, D, pairs


# خطر النار والدخان
# فوق الحريق يتسع العمود مع الارتفاع ويتلاشى ببطء؛ وتحته يتلاشى بسرعة.
# H(p) = min(1, مجموع مساهمات الحرائق). وH >= tau_core قيد صلب.
class FireField:
    def __init__(self, fires: np.ndarray, k: float = 0.25, tau_core: float = 0.5, ds: float = 2.0):
        """fires: (F, 6) صفوف [x, y, z, R, I, Hf]."""
        self.F = np.asarray(fires, dtype=float).reshape(-1, 6)
        self.k, self.tau_core, self.ds = float(k), float(tau_core), float(ds)

    @classmethod
    def from_scenario(cls, scn) -> "FireField":
        rows = [[*f.c, f.R, f.I, f.Hf] for f in scn.fires]
        hz = scn.hazard
        return cls(np.array(rows), hz["k"], hz["tau_core"], hz.get("sample_ds", 2.0))

    # الحقل
    def per_fire(self, points) -> np.ndarray:
        """(n, 3) نقاط -> (n, F) مساهمة كل حريق (قبل القص عند 1)."""
        p = np.atleast_2d(np.asarray(points, dtype=float))
        x, y, z, R, I, Hf = (self.F[:, i][None, :] for i in range(6))
        dz = p[:, 2:3] - z
        dh2 = (p[:, 0:1] - x) ** 2 + (p[:, 1:2] - y) ** 2
        up = np.maximum(dz, 0.0)
        sigma = R + self.k * up
        # أُسّية واحدة للفرعين: exp(a) * exp(b) = exp(a + b)
        expo = np.where(dz >= 0.0, dh2 / sigma ** 2 + up / Hf, (dh2 + 4.0 * dz * dz) / R ** 2)
        return I * np.exp(-expo)

    def H(self, points) -> np.ndarray:
        """الخطر في [0, 1]. تقبل (n, 3) أو نقطة واحدة (3,)."""
        p = np.asarray(points, dtype=float)
        if len(self.F) == 0:
            return np.zeros(p.shape[:-1])
        h = np.minimum(self.per_fire(p.reshape(-1, 3)).sum(axis=1), 1.0)
        return h.reshape(p.shape[:-1])

    def is_core(self, points) -> np.ndarray:
        """True داخل القلب المحظور (H >= tau_core). تُمرر إلى الشبكة لحجب خلايا القلب."""
        return self.H(points) >= self.tau_core

    # على طول مسار
    def path_hazard(self, path, ds: float | None = None) -> dict:
        """الخطر على طول مسار، من عينات كل <= ds متر (قاعدة المنتصف).

        exposure    : تكامل H على المسار (متر × خطر). وتقسمه دالة اللياقة
                      على طول الخط المستقيم L_ref.
        core_length : أمتار المسار داخل القلب المحظور (H >= tau_core). ويجب أن تكون 0.
        max_hazard  : أعلى H على المسار
        mean_hazard : exposure / طول المسار
        """
        pts, w, _ = sample_path(as_path(path), ds or self.ds)
        h = self.H(pts)
        L = float(w.sum())
        exposure = float((h * w).sum())
        return {
            "exposure": exposure,
            "core_length": float(w[h >= self.tau_core].sum()),
            "max_hazard": float(h.max()) if len(h) else 0.0,
            "mean_hazard": exposure / L if L > 0 else 0.0,
        }

    def paths_hazard(self, paths, ds: float | None = None) -> list[dict]:
        """path_hazard لكل مسيّرة بتقييم واحد للحقل (أسرع في دالة اللياقة)."""
        samples = [sample_path(as_path(p), ds or self.ds) for p in paths]
        h_all = self.H(np.concatenate([s[0] for s in samples]))
        out, start = [], 0
        for pts, w, _ in samples:
            h = h_all[start:start + len(pts)]
            start += len(pts)
            L, exposure = float(w.sum()), float((h * w).sum())
            out.append({"exposure": exposure, "core_length": float(w[h >= self.tau_core].sum()),
                        "max_hazard": float(h.max()), "mean_hazard": exposure / L if L > 0 else 0.0})
        return out

    def profile(self, path, ds: float | None = None):
        """(s, H) على طول المسار، مثل رسم الخطر أثناء الرحلة في الموقع."""
        pts, _, s = sample_path(as_path(path), ds or self.ds)
        return s, self.H(pts)

    # شكل القلب (للفحوص والرسوم)
    def core_radius_at_fire_height(self, f: int = 0) -> float:
        """نصف القطر الأفقي للقلب عند ارتفاع الحريق نفسه (حريق منفرد): R * sqrt(ln(I / tau))."""
        R, I = self.F[f, 3], self.F[f, 4]
        return float(R * np.sqrt(max(np.log(I / self.tau_core), 0.0)))

    def core_top_above_fire(self, f: int = 0) -> float:
        """مدى ارتفاع القلب فوق الحريق (حريق منفرد): H_f * ln(I / tau)."""
        I, Hf = self.F[f, 4], self.F[f, 5]
        return float(Hf * max(np.log(I / self.tau_core), 0.0))
