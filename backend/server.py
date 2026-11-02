"""خادم FastAPI: يقدّم الواجهة وبيانات التجارب، ويشغّل الخوارزميات عند الطلب."""
from __future__ import annotations

import json
import hashlib
import sys
import threading
import time
import uuid
from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from simulation.scenarios import load_scenario  # noqa: E402
from simulation.experiments import ALGORITHMS, city_path  # noqa: E402
from simulation.fitness import Problem, run_once  # noqa: E402
from simulation.validator import check_plan  # noqa: E402

SIMULATION = ROOT / "simulation"
RUNS = SIMULATION / "results" / "experiments" / "runs"
EXP = SIMULATION / "results" / "experiments"
ALG_ORDER = ["GA", "PSO", "ACO", "DP"]
ALG_KEY = {"GA": "ga", "PSO": "pso", "ACO": "aco", "DP": "dp"}
COLORS = {"GA": "#4DA3FF", "PSO": "#FF8A47", "ACO": "#2BD99A", "DP": "#A47CFF"}
SIZES = ["small", "medium", "large"]
SIZE_AR = {"small": "صغيرة", "medium": "متوسطة", "large": "كبيرة"}
ALG_AR = {"GA": "الخوارزمية الجينية", "PSO": "خوارزمية الأسراب", "ACO": "مستعمرة النمل", "DP": "البرمجة الديناميكية"}
LIVE_SIZES = ("small", "medium")           # مدن الدراسة المرجعية المسموحة للتشغيل المباشر؛ ومع fleet=true تُقبل الكبيرة أيضًا
# حالات الحافة العشر المعروضة في الموقع، بترتيب فهرس السيناريوهات المجمدة.
SITE_SPECIAL_CASES = ("empty_city", "behind_tall_tower", "narrow_street", "fire_on_line", "target_near_fire",
                      "crossing_drones", "maze", "enclosed_target", "small_battery", "tiny_battery")
# نطاق التشغيل المباشر مستقل عن العرض: يبقى على الحالتين اللتين كان يقبلهما.
LIVE_SPECIAL_CASES = ("target_near_fire", "crossing_drones")

SITE = ROOT / "frontend" / "public"
SCENE = SITE / "scene"

app = FastAPI(title="Drone firefighting — cinematic site API")

_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()

LIVE_BUDGET_CAP = 12000

# لا يخزّن المتصفح مؤقتًا ملفات الواجهة التي نعدّلها، أما ملفات المدن والنتائج
# ونماذج GLB والأصول الثقيلة فتبقى مخزنة كالمعتاد،
# حتى لا تختلط إصدارات قديمة وجديدة من HTML وCSS وJS بعد التحديث.
_UI_RESOURCES = frozenset({
    '/', '/index.html', '/styles.css', '/glass.css', '/theme-noir.css',
    '/app.js', '/scene.js', '/glass.js', '/official-liquid-glass.js',
    '/content.js', '/ambient-drone.js', '/content/ar.json',
    '/experience.css', '/experience.js', '/easyui.js', '/spring-select.js', '/refinements.css',
    '/chart-data.js', '/hazard-diagram.js', '/hazard-math.js', '/scene/js/visual-assets.js',
    '/viewport-loop.js', '/fleet-camera.js', '/ambient-placement.js', '/static-data.js',
    '/scene/js/city.js', '/scene/js/architecture.js', '/scene/js/fire.js', '/scene/js/swarm.js', '/scene/js/util.js',
})


@app.middleware('http')
async def _fresh_ui(request, call_next):
    response = await call_next(request)
    if request.url.path in _UI_RESOURCES:
        response.headers['Cache-Control'] = 'no-store, max-age=0'
    return response


# بيانات المدن والنتائج المحفوظة
def city_names() -> dict:
    """{'main': ['small', 'medium', 'large'], 'random': ['small_r01', ...]}"""
    rnd = sorted(p.stem for p in (SIMULATION / "scenarios" / "random").glob("*.json"))
    return {"main": SIZES, "random": rnd}


def city_dict(name: str) -> dict:
    scn = load_scenario(scenario_path(name))
    d = scn.to_dict()
    d["name"] = name
    return d


def scenario_path(name: str) -> Path:
    if name.startswith("fleet_") and name[6:] in SIZES:
        return SIMULATION / "scenarios" / "fleet" / f"{name[6:]}.json"
    if name.startswith("special_"):
        if name not in special_case_index():
            raise ValueError("unknown special case")
        return SIMULATION / "scenarios" / "special" / f"{name}.json"
    return city_path(name)


def fleet_runs(size: str, alg: str | None = None) -> list[dict]:
    if size not in SIZES:
        raise ValueError("unknown fleet size")
    fingerprint = hashlib.sha256(scenario_path(f"fleet_{size}").read_bytes()).hexdigest()
    runs = [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((SIMULATION / "results" / "fleet").glob(f"*_{size}_s*.json"))]
    return [r for r in runs if (alg is None or r["algorithm"] == alg)
            and r.get("scenario_sha256") == fingerprint]


def fleet_run(size: str, alg: str, seed: int | None = None) -> dict | None:
    runs = fleet_runs(size, alg)
    if seed is not None:
        return next((r for r in runs if r["seed"] == seed), None)
    # السلامة شرط للفوز، حتى لو كانت كلفة خطة غير آمنة أصغر عدديًا.
    return min(runs, key=lambda r: (not (r["validator"]["valid"] and r["feasible"]), r["best_f"]), default=None)


def load_fleet_summary(size: str) -> dict:
    rows = []
    for alg in ALG_ORDER:
        runs = fleet_runs(size, alg)
        best = fleet_run(size, alg)
        if best:
            rows.append({"algorithm": alg, "runs": len(runs),
                         "safe": sum(bool(r["validator"]["valid"] and r["feasible"]) for r in runs),
                         "F": best["best_f"], "valid": best["validator"]["valid"] and best["feasible"],
                         "seed": best["seed"], "time_s": best["time_s"],
                         "budget": best["budget"], "fe_used": best["fe_used"],
                         "first_safe_fe": best["first_feasible_fe"],
                         "mission_time_s": best["report"]["mission_time_s"],
                         "min_clearance_m": best["report"]["min_clearance_m"],
                         "min_separation_m": best["report"]["min_separation_m"],
                         "agreement": all(r["validator"]["valid"] == r["feasible"] for r in runs)})
    rows.sort(key=lambda r: (not r["valid"], r["F"]))
    scn=load_scenario(scenario_path(f"fleet_{size}"))
    return {"size": size, "drones": len(scn.missions),
            "winner": next((r["algorithm"] for r in rows if r["valid"]), None), "rows": rows,
            "histories": {a: [r["iter_history"] for r in fleet_runs(size, a)] for a in ALG_ORDER},
            "improvements": {a: [r["history"] for r in fleet_runs(size, a)] for a in ALG_ORDER}}


def special_case_index() -> dict:
    """قائمة مدن العرض، مأخوذة من فهرس مدن التجربة المجمدة."""
    index = json.loads((SIMULATION / "scenarios" / "special" / "index.json").read_text())
    return {name: meta for name, meta in index.items() if meta["case"] in SITE_SPECIAL_CASES}


def load_special_cases() -> list[dict]:
    """بطاقات الحالات: ملخص التشغيلات المحفوظة، وحكم أفضل محاولة لكل خوارزمية، وأفضل خطة آمنة."""
    table = special_summary()
    out = []
    for name, meta in special_case_index().items():
        rows = table[table["case"] == meta["case"]]
        algs = {}
        for alg in ALG_ORDER:
            rr = rows[rows["algorithm"] == alg].sort_values("seed")
            # أفضل محاولة بالترتيب نفسه الذي يختار به special_run الخطة المعروضة.
            best = rr.assign(_unsafe=~rr["fitness_feasible"].astype(bool)).sort_values(["_unsafe", "F"], kind="stable")
            safe_rows = rr[rr["validator_valid"].astype(bool)]
            top = best.iloc[0] if len(best) else None
            algs[alg] = {"safe": int(rr["validator_valid"].sum()), "runs": len(rr),
                         "correct": int((rr["outcome"] == "correct").sum()),
                         "best_F": float(rr["F"].min()) if len(rr) else None,
                         "best_valid": bool(top["validator_valid"]) if top is not None else None,
                         "best_safe_F": float(safe_rows["F"].min()) if len(safe_rows) else None}
        safe_algs = [a for a in ALG_ORDER if algs[a]["best_valid"]]
        default = min(safe_algs, key=lambda a: (algs[a]["best_safe_F"], ALG_ORDER.index(a)), default=None)
        out.append({"name": name, **meta, "algorithms": algs, "default_alg": default})
    return out


@lru_cache(maxsize=64)
def special_run(name: str, alg: str) -> dict:
    scn = load_scenario(scenario_path(name))
    saved = json.loads((SIMULATION / "results" / "special" / "runs.json").read_text())
    choices = [r for r in saved if r["scenario"] == name and r["algorithm"] == alg]
    if not choices:
        raise ValueError("no saved special run")
    r = dict(min(choices, key=lambda r: (not r["feasible"], r["best_f"])))
    # تحفظ تشغيلات الحالات الخاصة المسارات دون بعض حقول Result، فنعيد قياس
    # تلك المسارات نفسها بدل اختلاق مقاييس أو أزمنة تشغيل للخوارزميات.
    r["report"] = Problem(scn).report(r["paths"])
    r["validator"] = check_plan(scn, r["paths"])
    r["validator"]["agrees_with_fitness"] = r["validator"]["valid"] == r["feasible"]
    for key, value in {"fe_used": None, "budget": scn.problem["budget_fe"], "time_s": None,
                       "first_feasible_fe": None, "snapshots": [], "iter_history": []}.items():
        r.setdefault(key, value)
    return r


def saved_seeds(alg: str, city: str) -> list[int]:
    part = "main" if city in SIZES else "random"
    key = ALG_KEY.get(alg, alg)
    return sorted(int(p.stem.rsplit("_s", 1)[1]) for p in (RUNS / part).glob(f"{key}_{city}_s*.json"))


def load_run(alg: str, city: str, seed: int) -> dict | None:
    part = "main" if city in SIZES else "random"
    p = RUNS / part / f"{ALG_KEY.get(alg, alg)}_{city}_s{seed}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def best_saved_run(alg: str, city: str) -> dict | None:
    """التشغيل المحفوظ ذو أقل قيمة F (البذرة 0 لـ DP)."""
    best = None
    for s in saved_seeds(alg, city):
        r = load_run(alg, city, s)
        if r and (best is None or r["best_f"] < best["best_f"]):
            best = r
    return best


def run_summary(r: dict) -> dict:
    """ما يحتاجه المشهد من نتيجة واحدة (مع حكم المدقق)."""
    v = r.get("validator") or {}
    return {
        "algorithm": r["algorithm"], "seed": r["seed"], "color": COLORS.get(r["algorithm"], "#ffffff"),
        "F": r["best_f"], "feasible": r["feasible"], "valid": v.get("valid", r["feasible"]),
        "problems": v.get("problems", []), "fe_used": r["fe_used"], "budget": r["budget"],
        "time_s": r["time_s"], "first_feasible_fe": r["first_feasible_fe"],
        "paths": r["paths"], "snapshots": r.get("snapshots", []),
        "drones": r["report"]["drones"], "mission_time_s": r["report"]["mission_time_s"],
        "min_separation_m": r["report"]["min_separation_m"], "min_clearance_m": r["report"]["min_clearance_m"],
        "iter_history": r.get("iter_history", []),
        "live": r.get("live", False),
    }


# عامل التشغيل المباشر للخوارزميات
class LiveRun:
    """يشغل خوارزمية واحدة في خيط خلفي لتعرض الصفحة نسبة التقدم (problem.fe / budget)."""

    def __init__(self, alg: str, city: str, seed: int, params: dict | None = None, budget: int | None = None):
        self.scn = load_scenario(scenario_path(city))
        self.problem = Problem(self.scn, budget=budget)
        self.alg = ALGORITHMS[ALG_KEY.get(alg, alg)](**(params or {}))
        self.seed = seed
        self.result = None
        self.error = None
        self.checked_result = None
        self.t0 = time.perf_counter()
        self.thread = threading.Thread(target=self._go, daemon=True)
        self.thread.start()

    def _go(self):
        try:
            self.result = run_once(self.alg, self.scn, self.seed, problem=self.problem)
            self.checked_result = self._checked_dict()
        except Exception as e:                     # نعرض الخطأ في الصفحة بدل إيقاف الخادم
            self.error = e

    @property
    def progress(self) -> float:
        return 1.0 if self.done and self.error is None else min(0.99, self.problem.fe / max(1, self.problem.budget))

    @property
    def done(self) -> bool:
        return not self.thread.is_alive()

    def to_dict(self) -> dict:
        if self.checked_result is None:
            raise ValueError("run has not completed validation")
        return self.checked_result

    def _checked_dict(self) -> dict:
        r = self.result.to_dict()
        v = check_plan(self.scn, r["paths"])
        r["validator"] = {k: v[k] for k in ("valid", "checks", "problems", "min_clearance_m",
                                             "min_margin_linf_m", "max_hazard", "min_separation_m", "drones")}
        r["validator"]["agrees_with_fitness"] = v["valid"] == r["feasible"]
        r["live"] = True
        return r


def algorithm_defaults(alg: str, size: str) -> dict:
    from simulation.fitness import algorithm_params
    return algorithm_params(ALG_KEY.get(alg, alg), size)


# جداول CSV وبيانات المشهد والتصدير
def _csv(name: str) -> pd.DataFrame:
    p = EXP / name
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


def main_summary() -> pd.DataFrame:
    return _csv("main_summary.csv")


def main_wilcoxon() -> pd.DataFrame:
    return _csv("main_wilcoxon.csv")


def random_summary() -> pd.DataFrame:
    return _csv("random_summary.csv")


def random_wilcoxon() -> pd.DataFrame:
    return _csv("random_wilcoxon.csv")


def random_friedman() -> pd.DataFrame:
    return _csv("random_friedman.csv")


def timing_summary() -> pd.DataFrame:
    return _csv("timing_summary.csv")


def sensitivity() -> pd.DataFrame:
    return _csv("sensitivity.csv")


def all_runs() -> pd.DataFrame:
    return _csv("runs.csv")


def special_summary() -> pd.DataFrame:
    p = SIMULATION / "results" / "special" / "summary.csv"
    if not p.exists():
        return pd.DataFrame()
    table = pd.read_csv(p)
    return table[table["case"].isin(SITE_SPECIAL_CASES)]


def convergence_curves(city: str) -> dict:
    """{alg: [[iter, fe, best_f] لكل بذرة]} من التشغيلات الأساسية المحفوظة لرسوم التقارب."""
    out = {}
    for alg in ALG_ORDER:
        for s in saved_seeds(alg, city):
            r = load_run(alg, city, s)
            if r:
                out.setdefault(alg, []).append(r["iter_history"])
    return out


def build_scene_payload(city: str, runs: list[dict], **options) -> str:
    payload = {"city": city_dict(city), "runs": [run_summary(r) for r in runs], "options": options}
    return json.dumps(payload, separators=(",", ":"))


def path_csv(run: dict) -> str:
    """نقاط التوجيه لكل مسيّرة في تشغيل ما كنص CSV (زر التنزيل)."""
    lines = ["drone,point,x_m,y_m,z_m"]
    for k, p in enumerate(run["paths"]):
        for i, (x, y, z) in enumerate(p):
            lines.append(f"{k + 1},{i},{x!r},{y!r},{z!r}")
    return "\n".join(lines)


# دوال مساعدة لاستجابات HTTP
def _data_error_text(error):
    """يُبقي مسارات البيانات المنطقية الأصلية في رسائل أخطاء الواجهة البرمجية العامة."""
    actual = str(SIMULATION)
    logical = str(ROOT)
    message = str(error).replace(actual.replace("\\", "\\\\"), logical.replace("\\", "\\\\"))
    return message.replace(actual, logical)


def _run_or_404(alg: str, city: str, seed: int) -> dict:
    r = load_run(alg.upper(), city, seed)
    if r is None:
        raise HTTPException(404, f"no saved run {alg}/{city}/s{seed}")
    return _clean(r)


def _clean(o):
    """يجعل قواميس النتائج صالحة لـ JSON: inf/NaN -> None، وقيم numpy -> قيم Python."""
    import math

    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, float) and (math.isinf(o) or math.isnan(o)):
        return None
    if type(o).__module__ == "numpy":
        try:
            return _clean(o.item())
        except Exception:
            return None
    return o


# معلومات عامة
@app.get("/api/meta")
def meta():
    return {
        "algorithms": ALG_ORDER,
        "colors": COLORS,
        "sizes": SIZES,
        "live_sizes": list(LIVE_SIZES),
    }


@app.get("/api/cities")
def cities():
    return city_names()


@app.get("/api/city/{name}")
def city(name: str):
    try:
        return city_dict(name)
    except Exception as e:
        raise HTTPException(404, f"unknown city {name}: {_data_error_text(e)}")


# التشغيلات
@app.get("/api/run/{alg}/{city}/{seed}")
def run(alg: str, city: str, seed: int):
    return _run_or_404(alg, city, seed)


@app.get("/api/best/{alg}/{city}")
def best(alg: str, city: str):
    r = best_saved_run(alg.upper(), city)
    if r is None:
        raise HTTPException(404, f"no saved runs {alg}/{city}")
    return _clean(r)


@app.get("/api/run/{alg}/{city}/{seed}/csv", response_class=PlainTextResponse)
def run_csv(alg: str, city: str, seed: int):
    r = _run_or_404(alg, city, seed)
    return path_csv(r)


@app.get("/api/scene/{alg}/{city}")
def scene_payload(alg: str, city: str, seed: int | None = None):
    """بيانات JSON واحدة يحتاجها العارض ثلاثي الأبعاد: المدينة وملخص تشغيل واحد والخيارات."""
    r = load_run(alg.upper(), city, seed) if seed is not None else best_saved_run(alg.upper(), city)
    if r is None:
        raise HTTPException(404, f"no saved run {alg}/{city}")
    return _clean(json.loads(build_scene_payload(city, [r])))


@app.get("/api/fleet/{size}")
def fleet_summary(size: str):
    if size not in SIZES:
        raise HTTPException(404, "unknown fleet size")
    return _clean(load_fleet_summary(size))


@app.get("/api/fleet/{size}/{alg}")
def fleet_result(size: str, alg: str, seed: int | None = None):
    if size not in SIZES or alg.upper() not in ALG_ORDER:
        raise HTTPException(404, "unknown fleet/algorithm")
    r = fleet_run(size, alg.upper(), seed)
    if r is None:
        raise HTTPException(404, "fleet run not available")
    return _clean(r)


@app.get("/api/fleet/{size}/{alg}/scene")
def fleet_scene(size: str, alg: str, seed: int | None = None):
    r = fleet_result(size, alg, seed)
    return _clean(json.loads(build_scene_payload(f"fleet_{size}", [r])))


@app.get("/api/fleet/{size}/{alg}/csv", response_class=PlainTextResponse)
def fleet_csv(size: str, alg: str, seed: int | None = None):
    return path_csv(fleet_result(size, alg, seed))


@app.get("/api/special-cases")
def special_cases():
    return _clean(load_special_cases())


@app.get("/api/special/{name}/{alg}")
def special_result(name: str, alg: str):
    try:
        return _clean(special_run(name, alg.upper()))
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "unknown special case/algorithm")


@app.get("/api/special/{name}/{alg}/scene")
def special_scene(name: str, alg: str):
    return _clean(json.loads(build_scene_payload(name, [special_result(name, alg)])))


# الجداول
_TABLES = {
    "main": main_summary,
    "wilcoxon": main_wilcoxon,
    "random": random_summary,
    "random_wilcoxon": random_wilcoxon,
    "random_friedman": random_friedman,
    "timing": timing_summary,
    "sensitivity": sensitivity,
    "runs": all_runs,
}


@app.get("/api/table/{name}")
def table(name: str):
    if name == "special":
        df = special_summary()
    elif name == "checks":
        p = EXP / "checks.json"
        return json.loads(p.read_text()) if p.exists() else {}
    else:
        fn = _TABLES.get(name)
        if fn is None:
            raise HTTPException(404, f"unknown table {name}")
        df = fn()
    return _clean(json.loads(df.to_json(orient="records")))


@app.get("/api/convergence/{city}")
def convergence(city: str):
    try:
        return _clean(convergence_curves(city))
    except Exception as e:
        raise HTTPException(404, f"unknown city {city}: {_data_error_text(e)}")


# التشغيل المباشر (خوارزميات حقيقية في خيط خلفي)
class LiveRequest(BaseModel):
    alg: str = "GA"
    city: str = "small"
    seed: int = Field(default=0, ge=0, le=999999)
    budget: int | None = Field(default=None, ge=1, le=LIVE_BUDGET_CAP)
    params: dict | None = None
    fleet: bool = False


@app.post("/api/live")
def live_start(req: LiveRequest):
    alg = req.alg.upper()
    if alg not in ALG_ORDER:
        raise HTTPException(400, f"unknown algorithm {req.alg}")
    special_names = {f"special_{case}" for case in LIVE_SPECIAL_CASES}
    special = req.city in special_names
    if req.city not in (SIZES if req.fleet else LIVE_SIZES) and not special:
        raise HTTPException(400, "live runs support small/medium cities only (large takes minutes: use saved runs)")
    city = f"fleet_{req.city}" if req.fleet and not special else req.city
    scn = load_scenario(scenario_path(city))
    budget = req.budget if req.budget is not None else min(LIVE_BUDGET_CAP, scn.problem["budget_fe"])
    job = uuid.uuid4().hex[:12]
    try:
        runner = LiveRun(alg, city, req.seed, params=req.params, budget=budget)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    with _JOBS_LOCK:
        # تُحذف المهام المنتهية بعد ساعة؛ أما المهام الجارية فتبقى دائمًا.
        stale = [key for key, value in _JOBS.items()
                 if value["runner"].done and time.perf_counter() - value["t0"] > 3600]
        for key in stale:
            del _JOBS[key]
        _JOBS[job] = {"runner": runner, "t0": time.perf_counter(), "req": req.model_dump(), "city": city}
    return {"job": job, "budget": budget}


@app.get("/api/live/{job}")
def live_poll(job: str):
    with _JOBS_LOCK:
        j = _JOBS.get(job)
    if j is None:
        raise HTTPException(404, "unknown job")
    r: LiveRun = j["runner"]
    out: dict = {"done": r.done, "progress": r.progress, "fe": r.problem.fe, "budget": r.problem.budget}
    if r.done:
        if r.error is not None:
            out["error"] = f"{type(r.error).__name__}: {r.error}"
        else:
            try:
                out["result"] = _clean(r.to_dict())
            except Exception as e:  # إذا فشل المدقق تبقى نتيجة التشغيل ظاهرة
                out["error"] = f"ResultError: {e}"
    return out


@app.get("/api/live/{job}/scene")
def live_scene(job: str):
    """بيانات المشهد لمهمة تشغيل مباشر منتهية (المدينة وتشغيلها المباشر)."""
    with _JOBS_LOCK:
        j = _JOBS.get(job)
    if j is None:
        raise HTTPException(404, "unknown job")
    r: LiveRun = j["runner"]
    if not r.done or r.error is not None or r.result is None:
        raise HTTPException(409, "job not finished successfully")
    full = r.to_dict()
    city = j["city"]
    return _clean(json.loads(build_scene_payload(city, [full])))


@app.get("/healthz")
def health():
    return {"ok": True}


# نربط الملفات الثابتة في النهاية، لأن ربطها يحجب أي مسار يأتي بعده
if SCENE.exists():
    app.mount("/scene", StaticFiles(directory=str(SCENE), html=False), name="scene")
if SITE.exists():
    app.mount("/", StaticFiles(directory=str(SITE), html=True), name="site")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
