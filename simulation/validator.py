"""مدقق مستقل لفحص سلامة مسارات السرب (الأبراج، قلب اللهب، البطارية، التباعد، وحدود الفضاء)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
TOL = 1e-6


# دوال مساعدة خاصة
def _resample(P: np.ndarray, step: float):
    """نقاط كل <= step متر على الخط المتعدد المقاطع P (مع الرؤوس) وطولها القوسي."""
    pts, s = [P[:1]], [np.zeros(1)]
    acc = 0.0
    for a, b in zip(P[:-1], P[1:]):
        L = float(np.sqrt(((b - a) ** 2).sum()))
        n = max(int(np.ceil(L / step)), 1)
        t = np.arange(1, n + 1) / n
        pts.append(a + t[:, None] * (b - a))
        s.append(acc + t * L)
        acc += L
    return np.vstack(pts), np.concatenate(s)


def _outside_vector(pts: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    """المسافة خارج كل صندوق لكل محور: (n, B, 3)، وصفر على المحور الذي تقع النقطة ضمنه."""
    lo, hi = boxes[None, :, :3], boxes[None, :, 3:]
    p = pts[:, None, :]
    return np.maximum(np.maximum(lo - p, 0.0), p - hi)


def _hazard(pts: np.ndarray, fires, k: float) -> np.ndarray:
    """خطر العمود الحراري للحريق، مكتوب من جديد انطلاقًا من وصف النموذج."""
    H = np.zeros(len(pts))
    for f in fires:
        x, y, z = f.c
        dz = pts[:, 2] - z
        dh2 = (pts[:, 0] - x) ** 2 + (pts[:, 1] - y) ** 2
        above = dz >= 0
        sigma = f.R + k * np.where(above, dz, 0.0)
        h = np.where(above,
                     f.I * np.exp(-dh2 / sigma ** 2) * np.exp(-np.where(above, dz, 0.0) / f.Hf),
                     f.I * np.exp(-(dh2 + 4.0 * dz ** 2) / f.R ** 2))
        H += h
    return np.minimum(H, 1.0)


def _position(P: np.ndarray, t: np.ndarray, speed: float) -> np.ndarray:
    """موضع مسيّرة تطير على الخط P بسرعة ثابتة عند الأزمنة t (وتحوم عند النهاية)."""
    seg = np.sqrt((np.diff(P, axis=0) ** 2).sum(axis=1))
    keep = np.concatenate([[True], seg > 1e-12])
    P = P[keep]
    s = np.concatenate([[0.0], np.cumsum(seg[seg > 1e-12])])
    if len(P) == 1:
        return np.repeat(P, len(t), axis=0)
    d = np.clip(t * speed, 0.0, s[-1])
    return np.stack([np.interp(d, s, P[:, c]) for c in range(3)], axis=1)


# الفحص
def check_plan(scn, paths, step: float = 0.1, dt: float = 0.01) -> dict:
    """فحص كل قاعدة للخطة `paths` (خط متعدد المقاطع (n, 3) لكل مهمة) في المدينة `scn`."""
    w, dr = scn.world, scn.drone
    W, z_min, z_max, d_safe = w["W"], w["z_min"], w["z_max"], w["d_safe"]
    towers = np.array([[b.x0, b.y0, 0.0, b.x1, b.y1, b.h] for b in scn.buildings], float).reshape(-1, 6)
    tau = scn.hazard["tau_core"]
    e_max = dr["battery_kj"] * 1000.0 * dr["battery_usable"]
    problems, drones = [], []
    paths = [np.asarray(p, float) for p in paths]

    if len(paths) != len(scn.missions):
        problems.append(f"plan has {len(paths)} paths for {len(scn.missions)} drones")
    for k, (P, m) in enumerate(zip(paths, scn.missions)):
        d = {"k": k}
        if P.ndim != 2 or P.shape[1] != 3 or len(P) < 2 or not np.isfinite(P).all():
            problems.append(f"drone {k}: not a valid polyline")
            drones.append(d)
            continue
        d["endpoints_ok"] = bool(np.abs(P[0] - m.S).max() <= 1e-6 and np.abs(P[-1] - m.G).max() <= 1e-6)
        if not d["endpoints_ok"]:
            problems.append(f"drone {k}: does not start at S or end at G")
        lo, hi = np.array([0.0, 0.0, z_min]), np.array([W, W, z_max])
        d["bounds_ok"] = bool(((P >= lo - TOL) & (P <= hi + TOL)).all())
        if not d["bounds_ok"]:
            problems.append(f"drone {k}: leaves the flight space")
        pts, _ = _resample(P, step)
        if len(towers):
            o = _outside_vector(pts, towers)
            linf = o.max(axis=2).min(axis=1)                          # مسافة بمعنى L-inf
            eucl = np.sqrt((o ** 2).sum(axis=2)).min(axis=1)
            d["min_margin_linf_m"] = float(linf.min())
            d["min_clearance_m"] = float(eucl.min())
        else:
            d["min_margin_linf_m"] = d["min_clearance_m"] = float("inf")
        d["towers_ok"] = d["min_margin_linf_m"] >= d_safe - TOL
        if not d["towers_ok"]:
            problems.append(f"drone {k}: comes within {d['min_margin_linf_m']:.2f} m of a tower "
                            f"(needs {d_safe} m)")
        H = _hazard(pts, scn.fires, scn.hazard["k"]) if scn.fires else np.zeros(len(pts))
        d["max_hazard"] = float(H.max())
        d["core_ok"] = d["max_hazard"] < tau
        if not d["core_ok"]:
            problems.append(f"drone {k}: enters the fire core (hazard {d['max_hazard']:.2f} >= {tau})")
        seg = np.diff(P, axis=0)
        L = np.sqrt((seg ** 2).sum(axis=1))
        E = dr["e_c"] * L.sum() + dr["e_up"] * np.maximum(seg[:, 2], 0.0).sum()
        d["length_m"], d["energy_kj"] = float(L.sum()), float(E / 1000.0)
        d["battery_pct"] = float(100.0 * E / (dr["battery_kj"] * 1000.0))
        d["battery_ok"] = bool(E <= e_max + TOL)
        if not d["battery_ok"]:
            problems.append(f"drone {k}: needs {E / 1000:.1f} kJ, the battery allows {e_max / 1000:.1f} kJ")
        drones.append(d)

    # التباعد بين المسيّرات على شبكة زمنية دقيقة
    min_sep = float("inf")
    if len(paths) > 1 and all(np.isfinite(P).all() and P.ndim == 2 and len(P) >= 2 for P in paths):
        T = max(float(np.sqrt((np.diff(P, axis=0) ** 2).sum(axis=1)).sum()) for P in paths) / dr["speed"]
        t = np.arange(0.0, T + dt, dt)
        pos = [_position(P, t, dr["speed"]) for P in paths]
        for i in range(len(pos)):
            for j in range(i + 1, len(pos)):
                dist = np.sqrt(((pos[i] - pos[j]) ** 2).sum(axis=1))
                k = int(np.argmin(dist))
                if dist[k] < min_sep:
                    min_sep = float(dist[k])
                if dist[k] < dr["d_sep"] - TOL:
                    problems.append(f"drones {i} and {j} are {dist[k]:.2f} m apart at t = {t[k]:.1f} s "
                                    f"(needs {dr['d_sep']} m)")
    checks = {
        "endpoints": all(d.get("endpoints_ok", False) for d in drones),
        "bounds": all(d.get("bounds_ok", False) for d in drones),
        "towers": all(d.get("towers_ok", False) for d in drones),
        "fire_core": all(d.get("core_ok", False) for d in drones),
        "separation": min_sep >= dr["d_sep"] - TOL,
        "battery": all(d.get("battery_ok", False) for d in drones),
    }
    return {
        "valid": not problems and all(checks.values()),
        "checks": checks,
        "problems": problems,
        "min_clearance_m": min((d.get("min_clearance_m", 0.0) for d in drones), default=0.0),
        "min_margin_linf_m": min((d.get("min_margin_linf_m", 0.0) for d in drones), default=0.0),
        "max_hazard": max((d.get("max_hazard", 1.0) for d in drones), default=1.0),
        "min_separation_m": min_sep,
        "drones": drones,
    }


# النتائج المحفوظة
def scenario_path(name: str) -> Path:
    """'medium' -> scenarios/medium.json؛ ويبحث أيضًا في scenarios/random وscenarios/special."""
    if name in ("fleet_small", "fleet_medium", "fleet_large"):
        return ROOT / "scenarios" / "fleet" / f"{name[6:]}.json"
    for sub in ("", "random", "special"):
        p = ROOT / "scenarios" / sub / f"{name}.json"
        if p.exists():
            return p
    raise FileNotFoundError(f"no city file named {name!r}")


def check_result_file(path: Path) -> dict:
    """التحقق من نتيجة Result محفوظة واحدة (JSON كتبتها سكربتات التجارب)."""
    from .scenarios import load_scenario            # يقرأ ملف البيانات فقط
    r = json.loads(Path(path).read_text(encoding="utf-8"))
    scn = load_scenario(scenario_path(r["scenario"]))
    rep = check_plan(scn, r["paths"])
    rep.update({"file": str(path), "algorithm": r.get("algorithm"), "seed": r.get("seed"),
                "scenario": r["scenario"], "fitness_feasible": r.get("feasible")})
    rep["agrees_with_fitness"] = rep["fitness_feasible"] is None or rep["fitness_feasible"] == rep["valid"]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Independent check of saved plans.")
    ap.add_argument("paths", nargs="+", help="result JSON files or folders of them")
    a = ap.parse_args(argv)
    files = []
    for p in map(Path, a.paths):
        files += sorted(p.glob("*.json")) if p.is_dir() else [p]
    files = [f for f in files if not f.name.endswith(("_defaults.json", "index.json"))]
    bad = disagree = 0
    for f in files:
        rep = check_result_file(f)
        bad += not rep["valid"]
        disagree += not rep["agrees_with_fitness"]
        sep = "-" if not np.isfinite(rep["min_separation_m"]) else f"{rep['min_separation_m']:.2f}"
        print(f"{'OK  ' if rep['valid'] else 'FAIL'} {f.name:<34} clearance {rep['min_clearance_m']:6.2f} m  "
              f"margin {rep['min_margin_linf_m']:6.2f} m  hazard {rep['max_hazard']:.3f}  separation {sep:>6} m"
              + ("" if rep["agrees_with_fitness"] else "   <- disagrees with F"))
        for msg in rep["problems"]:
            print("       ", msg)
    print(f"\n{len(files)} plans checked: {len(files) - bad} valid, {bad} breaking a rule, "
          f"{disagree} disagreeing with the fitness function")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
