"""اختبارات الموقع المستقل (backend/ + frontend/public/، دون Streamlit).

يجب أن يقدم الموقع بيانات المشروع الحقيقية فقط: ملفات المدن والتشغيلات المحفوظة
وجداول CSV، إضافة إلى التشغيل المباشر للخوارزميات الحقيقية. لا قيم مصطنعة.
ويجب أن يطابق نموذج JavaScript في المشهد ثلاثي الأبعاد نموذج Python في المشروع.
"""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import server  # noqa: E402
import server as backend_data  # noqa: E402
from simulation.geometry import FireField  # noqa: E402
from simulation.scenarios import load_scenario  # noqa: E402
from simulation.validator import _position  # noqa: E402

SCENE = ROOT / "frontend/public" / "scene"
NODE = shutil.which("node")


@pytest.fixture(scope="module")
def client():
    return TestClient(server.app, raise_server_exceptions=True)


def test_meta(client):
    m = client.get("/api/meta").json()
    assert m["algorithms"] == ["GA", "PSO", "ACO", "DP"]
    assert m["colors"]["ACO"] == "#2BD99A"  # لون الرسوم والبيانات؛ المسارات ثلاثية الأبعاد تستخدم نمطًا بنفسجيًا مشتركًا


def test_city_matches_scenario_file(client):
    disk = json.loads((ROOT / "simulation/scenarios" / "small.json").read_text())["buildings"]
    api_city = client.get("/api/city/small").json()
    assert len(api_city["buildings"]) == len(disk)
    assert api_city["buildings"][0]["h"] == disk[0]["h"]


def test_best_run_is_real_saved_result(client):
    disk = json.loads((ROOT / "simulation/results" / "experiments" / "runs" / "main" / "aco_large_s0.json").read_text())
    best = client.get("/api/best/ACO/large").json()
    assert best["best_f"] <= disk["best_f"]  # الأفضل عبر البذور <= أي بذرة منفردة
    assert best["feasible"] is True
    assert len(best["paths"]) == 5  # المدينة الكبيرة: 5 مسيّرات


def test_responses_are_json_safe(client):
    # مدن المسيّرة الواحدة تحمل inf (لا أزواج للتباعد): يجب ألا يكسر ذلك الترميز
    for url in ("/api/run/GA/small/0", "/api/scene/GA/small?seed=0", "/api/table/runs"):
        r = client.get(url)
        assert r.status_code == 200, url
        json.loads(r.text)


def test_convergence_uses_saved_histories(client):
    conv = client.get("/api/convergence/medium").json()
    assert set(conv) == {"GA", "PSO", "ACO", "DP"}
    assert conv["ACO"][0][0][2] < 10  # قيم F حقيقية، والأقل أفضل


def test_live_run_dp_small(client):
    r = client.post("/api/live", json={"alg": "DP", "city": "small", "seed": 3})
    assert r.status_code == 200
    job = r.json()["job"]
    for _ in range(60):
        j = client.get(f"/api/live/{job}").json()
        if j["done"]:
            break
        time.sleep(0.5)
    assert j["done"] and "result" in j
    assert abs(j["result"]["best_f"] - 1.64524) < 1e-3  # خط الأساس الحتمي
    sc = client.get(f"/api/live/{job}/scene")
    assert sc.status_code == 200
    assert len(sc.json()["runs"][0]["paths"]) == 1


def test_live_rejects_large_city(client):
    r = client.post("/api/live", json={"alg": "GA", "city": "large", "seed": 0})
    assert r.status_code == 400


def test_site_files_exist():
    for f in ("index.html", "styles.css", "app.js", "scene.js"):
        assert (ROOT / "frontend/public" / f).exists(), f
    html = (ROOT / "frontend/public" / "index.html").read_text(encoding="utf-8")
    assert 'dir="rtl"' in html and "/app.js" in html


def test_three_folder_layout_preserves_the_public_file_boundary(client):
    assert {path.name for path in ROOT.iterdir() if path.is_dir()} == {"frontend", "backend", "simulation"}
    assert {path.name for path in ROOT.iterdir()} <= {"frontend", "backend", "simulation", "README.md", ".gitignore"}
    for url in ("/package.json", "/node_modules/playwright/package.json",
                "/tests/check-ui.cjs", "/prepare_akhbar.py", "/requirements.txt",
                "/README.md", "/.gitignore", "/backend/README.md"):
        assert client.get(url).status_code == 404, url


def test_mobile_and_quality_gates():
    """فحوص ثابتة للواجهة: ملاءمة الجوال، وعدم الإفراط في الحركة، ووضوح الخط."""
    html = (ROOT / "frontend/public" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "frontend/public" / "styles.css").read_text(encoding="utf-8")
    assert 'viewport-fit=cover' in html
    assert 'name="theme-color"' in html
    assert html.count('class="stage-loading"') == 3  # الواجهة الرئيسية والقصة ومساحة المهمة والمختبر الموحدة
    assert "-webkit-tap-highlight-color" in css
    assert "touch-action:manipulation" in css.replace(" ", "")
    assert "(hover:hover)and(pointer:fine)" in css.replace(" ", "")  # التمرير فوق العناصر مشروط بقدرة الجهاز
    assert "transition:all" not in css.replace(" ", "")
    assert "scale(0)" not in css
    assert "user-scalable=no" not in html and "maximum-scale" not in html  # التقريب يبقى مفعّلًا
    # الخط المطلوب متاح دون اتصال بوزنيه الفعليين.
    assert '--sans:"Akhbar MT"' in css and 'font-family:"Akhbar MT"' in css
    for weight in ("regular", "bold"):
        font = ROOT / "frontend/public/assets" / f"akhbar-mt-{weight}.woff2"
        assert font.read_bytes().startswith(b"wOF2")


def test_liquid_glass_system():
    """فحوص الزجاج السائل: الانكسار الحقيقي على عناصر التحكم المحدودة فقط، وCSS في بقية العناصر."""
    html = (ROOT / "frontend/public" / "index.html").read_text(encoding="utf-8")
    glass_css = (ROOT / "frontend/public" / "glass.css").read_text(encoding="utf-8")
    glass_js = (ROOT / "frontend/public" / "glass.js").read_text(encoding="utf-8")
    app_js = (ROOT / "frontend/public" / "app.js").read_text(encoding="utf-8")
    assert "/glass.css" in html
    assert "seg-control" in html  # العدسات الكاسرة: خطوات القصة وتبويبات المدن فقط
    assert "feDisplacementMap" in glass_js and "buildLensMap" in glass_js
    assert "userSpaceOnUse" in glass_js  # وحدات آمنة على iOS دون انزياح objectBoundingBox
    assert "SegmentLens" in app_js
    # أزرار الاختيار الكبسولية: عدسة وأزرار مستديرة كليًا، والشريط مبني من JSON
    assert "border-radius:999px" in glass_css
    assert 'id="stageAlt"' in html and "data-goto" not in html  # أزرار الشريط مولدة من الفهرس
    # بصريات متعددة الطبقات: المرشحات على طبقات الخلفية، والنصوص بلا مرشحات
    assert "gbtn-bg" in glass_js and "gbtn-fg" in glass_js
    assert "StaticLens" in glass_js and "initGlassButtons" in app_js


def test_ambient_supplied_drone_remains_separate_from_simulation():
    """يجب ألا تستخدم المسيّرة الزخرفية في الواجهة اللون الخزامي المؤقت القديم."""
    html = (ROOT / "frontend/public" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "frontend/public" / "styles.css").read_text(encoding="utf-8")
    js = (ROOT / "frontend/public" / "app.js").read_text(encoding="utf-8")
    ambient = (ROOT / "frontend/public" / "ambient-drone.js").read_text(encoding="utf-8")
    assert 'id="ambientDroneCanvas"' in html
    assert '/assets/lavender-sprig.svg' not in html
    assert '.ambient-drone-canvas' in css
    assert '/ambient-drone.js' in js
    # يتشارك العارضان مصدر النموذج، وتبقى تحويلات الكائنات المنسوخة
    # مستقلة. ويقارن فحص المتصفح كذلك هويات الهندسة الفعلية.
    swarm = (ROOT / 'frontend/public' / 'scene' / 'js' / 'swarm.js').read_text(encoding='utf-8')
    assert '/scene/assets/rescue_hexacopter.glb' in swarm
    assert 'loadDrone,DRONE_MODEL_URL' in ambient and 'template.clone(true)' in ambient
    assert 'new ViewportLoop' in ambient and 'continuous:' in ambient



def test_navigation_uses_official_liquid_glass_engine():
    """يستخدم التنقل محرك Engine الأصلي الموثق بلغة JavaScript المجردة، لا نسخة منه."""
    app = (ROOT / "frontend/public" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend/public" / "glass.css").read_text(encoding="utf-8")
    implementation = (ROOT / "frontend/public" / "official-liquid-glass.js").read_text(encoding="utf-8")
    assert "startOfficialLiquidGlass" in app
    assert "new BackdropLens(" not in app
    assert "new LiquidGlassEngine(" in implementation
    assert "liquid-glass-web-react@0.1.1/+esm" in implementation
    assert "engine.setPosition(" in implementation
    assert "radius: 'auto'" in implementation
    assert "official-liquid-source" in css and "official-liquid-chrome" in css
    assert "stage-alt button.on" in css
    assert "prefers-reduced-transparency" in css


def test_official_glass_header_uses_same_moving_selection_as_stage():
    implementation = (ROOT / "frontend/public" / "official-liquid-glass.js").read_text(encoding="utf-8")
    app = (ROOT / "frontend/public" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend/public" / "glass.css").read_text(encoding="utf-8")
    styles = (ROOT / "frontend/public" / "styles.css").read_text(encoding="utf-8")
    assert "mountMovingSelection(LiquidGlassEngine, stage)" in implementation
    assert "mountMovingSelection(\n      LiquidGlassEngine, header" in implementation
    assert "'.topnav a.active', '.topnav a'" in implementation
    assert "officialTopSelection?.moveTo(link, instant)" in app
    assert "officialTopSelection?.hide()" in app
    assert "activateTopLink" in app
    assert ".topbar-inner::before" in css
    assert 'html[data-official-liquid-glass="ready"] .topnav a.active{background:transparent}' in styles


def test_official_liquid_glass_for_explanation_cards():
    """بصريات البطاقات تعيد استخدام محرك DOM الأصلي دون تعديل أي من عدستي التنقل."""
    source = (ROOT / "frontend/public" / "official-liquid-glass.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend/public" / "glass.css").read_text(encoding="utf-8")
    html = (ROOT / "frontend/public" / "index.html").read_text(encoding="utf-8")
    assert "mountExplanationCards(LiquidGlassEngine)" in source
    assert "mountGlassCard(LiquidGlassEngine, card, kind)" in source
    assert "new LiquidGlassEngine(dom" in source
    assert "#algRail .alg-card" in source
    assert ".story-steps .step-card" in source
    assert "quality: 256" in source
    assert "IntersectionObserver" in source  # تحميل مرشحات SVG المكلفة عند الحاجة فقط
    assert ".official-glass-card > :not(.official-liquid-source)" in css
    assert "#algRail .alg-card.official-glass-card::after" in css
    assert html.count('class="step-card"') == 6
    assert html.count('class="alg-card reveal"') == 4


def test_lavender_algorithm_cards_and_cta_label_layer():
    """يُبقي التنقل المعتمد كما هو؛ ويصلح الصبغة الخزامية ونص زر الشبح المخفي."""
    html = (ROOT / 'frontend/public' / 'index.html').read_text(encoding='utf-8')
    css = (ROOT / 'frontend/public' / 'glass.css').read_text(encoding='utf-8')
    js = (ROOT / 'frontend/public' / 'official-liquid-glass.js').read_text(encoding='utf-8')
    assert 'class="hero-cta-label" data-i18n="hero.ctaLab"' in html
    assert 'class="hero-cta-label" data-i18n="hero.ctaTour"' in html
    assert '.hero-cta .btn .hero-cta-label' in css and 'z-index:10' in css
    assert '.hero-cta .btn.ghost .hero-cta-label{color:#42256f' in css
    assert '#algRail .alg-card{' in css and '#eee3fb' in css
    assert 'rgba(225,202,250,.87)' in css  # طبقة بصرية ملونة، لا رمادي محايد
    assert 'border-top:0!important' in css
    assert 'mountHeroButtons(LiquidGlassEngine)' in js
    legacy_glass = (ROOT / 'frontend/public' / 'glass.js').read_text(encoding='utf-8')
    assert "!el.closest('.hero-cta')" in legacy_glass


def test_graphite_noir_reference_theme_is_permanent():
    """لوحة الألوان السوداء والجرافيتية المطلوبة تتغلب على ملفي الأنماط الفاتحين القديمين."""
    root = ROOT / "frontend/public"
    html = (root / "index.html").read_text(encoding="utf-8")
    noir = (root / "theme-noir.css").read_text(encoding="utf-8")
    glass = (root / "glass.css").read_text(encoding="utf-8")
    assert 'name="theme-color" content="#05090b"' in html
    assert '/glass.css' in html and '/theme-noir.css' in html
    assert html.index('/glass.css') < html.index('/theme-noir.css')
    assert 'color-scheme: dark' in noir
    for expected in ("--bg-primary:#05090b", "--text-primary:#f4f6f8",
                     "--surface:#10161b", "--noir-card", "--noir-inset",
                     "--noir-selection", ".official-liquid-selection",
                     "#algRail .alg-card.official-glass-card > .official-liquid-source",
                     "#challenge .formula", "#lab .sensitivity",
                     ".rail-nav button", ".btn.primary"):
        assert expected in noir, expected
    # التنفيذ البصري المخصص وبدائله يبقيان كما هما.
    for fallback in ("prefers-reduced-transparency", "forced-colors", "prefers-reduced-motion"):
        assert fallback in glass, fallback
    assert "feDisplacementMap" in (root / "glass.js").read_text(encoding="utf-8")
    assert "url(#" not in (root / "scene.js").read_text(encoding="utf-8")


# سلامة طبقة البيانات (منقول من test_web.py)
def test_data_layer_serves_saved_runs():
    names = backend_data.city_names()
    assert names["main"] == ["small", "medium", "large"] and len(names["random"]) == 30
    for alg in backend_data.ALG_ORDER:
        seeds = backend_data.saved_seeds(alg, "medium")
        assert seeds == ([0] if alg == "DP" else list(range(20)))
    r = backend_data.load_run("PSO", "large", 19)
    assert r["seed"] == 19 and r["validator"]["valid"] is False  # التشغيل غير الآمن الوحيد يُعرض كغير آمن
    best = backend_data.best_saved_run("GA", "small")
    assert best["best_f"] == min(backend_data.load_run("GA", "small", s)["best_f"] for s in range(20))


def test_scene_payload_carries_the_saved_plan_unchanged():
    r = backend_data.load_run("ACO", "medium", 3)
    p = json.loads(backend_data.build_scene_payload("medium", [r]))
    assert p["city"]["name"] == "medium" and len(p["city"]["buildings"]) == 25
    run = p["runs"][0]
    assert run["paths"] == r["paths"] and run["F"] == r["best_f"] and run["valid"] is True
    assert run["color"] == backend_data.COLORS["ACO"] and len(run["snapshots"]) == len(r["snapshots"])


def test_path_csv_matches_waypoints():
    r = backend_data.load_run("DP", "small", 0)
    lines = backend_data.path_csv(r).splitlines()
    assert lines[0] == "drone,point,x_m,y_m,z_m"
    assert len(lines) == 1 + sum(len(p) for p in r["paths"])
    x0, y0, z0 = map(float, lines[1].split(",")[2:])
    assert [x0, y0, z0] == pytest.approx(r["paths"][0][0], abs=1e-3)


def test_live_run_is_the_real_algorithm_and_is_checked():
    lr = backend_data.LiveRun("GA", "small", 7, budget=600)
    lr.thread.join(120)
    assert lr.done and lr.error is None and lr.progress == 1.0
    r = lr.to_dict()
    assert r["fe_used"] == 600 and r["live"] and r["validator"]["agrees_with_fitness"]
    from simulation.fitness import run_once
    from simulation.ga_pso import GA
    from simulation.fitness import Problem
    scn = load_scenario(ROOT / "simulation/scenarios" / "small.json")
    again = run_once(GA(), scn, 7, problem=Problem(scn, budget=600))
    assert again.best_f == r["best_f"]                                   # البذرة نفسها، الخطة نفسها


# نموذج JavaScript (منقول من test_web.py)
@pytest.fixture(scope="module")
def js(tmp_path_factory):
    if not NODE:
        pytest.skip("node is not installed")
    rng = np.random.default_rng(3)
    cities = [load_scenario(ROOT / "simulation/scenarios" / f"{c}.json") for c in ("small", "medium", "large")]
    big = cities[2]
    fires = [{"c": f.c, "R": f.R, "I": f.I, "Hf": f.Hf} for f in big.fires]
    pts = np.vstack([rng.uniform([0, 0, 0], [1000, 1000, 350], (300, 3))] +
                    [np.array(f.c) + rng.normal(0, 20, (60, 3)) for f in big.fires])
    flights = []
    for r in (backend_data.load_run("GA", "medium", 0), backend_data.load_run("ACO", "large", 0)):
        for path in r["paths"]:
            flights.append({"path": path, "speed": 10.0, "times": list(np.linspace(0, 140, 57))})
    core = [{"fire": fires[0], "dz": dz} for dz in (-5.0, 0.0, 10.0, 30.0, 45.0)]
    inp = {"points": pts.tolist(), "fires": fires, "k": big.hazard["k"], "tau": big.hazard["tau_core"],
           "buildings": [vars(b) for b in big.buildings], "flights": flights, "core": core,
           "cities": [c.to_dict() for c in cities]}
    f = tmp_path_factory.mktemp("js") / "in.json"
    f.write_text(json.dumps(inp))
    res = subprocess.run([NODE, str(ROOT / "frontend/tests" / "scene_check.mjs"), str(f)], capture_output=True, text=True,
                         timeout=120, cwd=ROOT / "frontend")
    assert res.returncode == 0, res.stderr
    return inp, json.loads(res.stdout), cities


def test_scene_hazard_is_the_fire_model_of_task_2(js):
    inp, out, cities = js
    ref = FireField.from_scenario(cities[2]).H(np.array(inp["points"]))
    assert np.allclose(out["hazard"], ref, rtol=0, atol=1e-12)


def test_scene_flight_is_the_motion_model_of_the_validator(js):
    inp, out, _ = js
    for f, o in zip(inp["flights"], out["flight"]):
        P = np.array(f["path"])
        ref = _position(P, np.array(f["times"]), f["speed"])           # سرعة ثابتة، وتحوم المسيّرة عند الهدف
        assert np.allclose(o["pos"], ref, atol=1e-9)
        L = np.sqrt((np.diff(P, axis=0) ** 2).sum(axis=1)).sum()
        assert o["duration"] == pytest.approx(L / f["speed"])


def test_scene_tower_distance_and_core_radius(js):
    inp, out, cities = js
    boxes = np.array([[b.x0, b.y0, 0, b.x1, b.y1, b.h] for b in cities[2].buildings])
    P = np.array(inp["points"])[:, None, :]
    d = np.sqrt((np.maximum(np.maximum(boxes[None, :, :3] - P, 0), P - boxes[None, :, 3:]) ** 2).sum(-1)).min(1)
    assert np.allclose(out["tower"], d, atol=1e-9)
    field = FireField(np.array([[*inp["core"][0]["fire"]["c"], inp["core"][0]["fire"]["R"],
                                 inp["core"][0]["fire"]["I"], inp["core"][0]["fire"]["Hf"]]]), k=inp["k"])
    c = np.array(inp["core"][0]["fire"]["c"])
    for cc, r in zip(inp["core"], out["core"]):
        if r > 0:                                                     # على سطح القلب H = tau بالضبط
            p = c + np.array([r, 0.0, cc["dz"]])
            assert field.H(p) == pytest.approx(inp["tau"], abs=1e-9)


def test_generated_roads_avoid_every_tower(js):
    inp, out, cities = js
    for city, roads in zip(cities, out["roads"]):
        assert len(roads) >= 2
        for r in roads:
            half = (11 + 2 * 2.6) / 2
            for b in city.buildings:
                lo, hi, a0, a1 = (b.x0, b.x1, b.y0, b.y1) if r["axis"] == "x" else (b.y0, b.y1, b.x0, b.x1)
                crosses = r["c"] + half > lo - 6 and r["c"] - half < hi + 6
                overlaps = r["a"] < a1 + 6 and r["b"] > a0 - 6
                assert not (crosses and overlaps), (city.name, r, vars(b))


def test_scene_runtime_is_complete():
    for f in ("city.js", "fire.js", "swarm.js", "util.js"):
        assert (SCENE / "js" / f).exists(), f
    vendor = SCENE / "vendor" / "three"
    assert (vendor / "three.module.js").exists() and (vendor / "LICENSE").exists()
    assert (SCENE / "assets" / "rescue_hexacopter.glb").exists()
    import re
    for js_file in list((SCENE / "js").glob("*.js")) + list((vendor / "examples").rglob("*.js")):
        for m in re.findall(r"^\s*import[^;]*?from\s+'([^']+)'", js_file.read_text(encoding="utf-8"), flags=re.M):
            assert (js_file.parent / m.split("?", 1)[0]).resolve().exists(), (js_file, m)


def test_drone_model_has_active_fire_capsule_and_rotors():
    """قد يحتوي ملف GLB المرفق على حمولة طبية معطلة؛ والحمولة النشطة هي كبسولة الإطفاء فقط."""
    import struct
    raw = (SCENE / "assets" / "rescue_hexacopter.glb").read_bytes()
    assert raw[:4] == b"glTF"
    n = struct.unpack_from("<I", raw, 12)[0]
    g = json.loads(raw[20:20 + n])
    node_ids, stack = set(), list(g["scenes"][g.get("scene", 0)]["nodes"])
    while stack:
        i = stack.pop()
        node_ids.add(i)
        stack += g["nodes"][i].get("children", [])
    active = {g["nodes"][i].get("name") for i in node_ids if all(s > 0 for s in g["nodes"][i].get("scale", [1, 1, 1]))}
    assert "Payload_FireCapsule" in active and "Payload_MedKit" not in active
    assert {f"Prop_{i}" for i in range(6)} <= active



def test_ui_cleanup_complete():
    """أُزيلت apiDot وعلامة الشعار ورابط توثيق الواجهة البرمجية العام؛ والواجهة البرمجية ما زالت تعمل."""
    html = (ROOT / "frontend/public" / "index.html").read_text(encoding="utf-8")
    assert "apiDot" not in html and "brand-mark" not in html and "live-dot" not in html
    assert "API docs" not in html and "/docs\">" not in html
    assert "FastAPI + Three.js" not in html
    assert "SIHAM" not in html  # اسم المجلد الداخلي لا يظهر في الواجهة العامة
    # القائمة مثبتة على الحافة اليسرى في الجوال (RTL: margin-inline-start)
    css = (ROOT / "frontend/public" / "styles.css").read_text(encoding="utf-8")
    assert ".top-actions{margin-inline-start:auto}" in css.replace(" ", "")
    # نسبة الحقوق القانونية تبقى بعد التنظيف
    assert "Karosio" in html and "CC BY-NC-SA 4.0" in html and "Three.js (MIT)" in html


def test_algorithm_hues_survive_neutral_noir_ui():
    """تحتفظ GA وPSO وACO وDP بألوانها المميزة؛ والرسم الخزامي يبقى دون تعديل."""
    root = ROOT / "frontend/public"
    noir = (root / "theme-noir.css").read_text(encoding="utf-8")
    app_js = (root / "app.js").read_text(encoding="utf-8")
    assert (root / "assets" / "lavender-sprig.svg").exists()
    for alg, hex_ in (("GA", "#4DA3FF"), ("PSO", "#FF8A47"),
                      ("ACO", "#2BD99A"), ("DP", "#A47CFF")):
        assert hex_ in app_js, (alg, hex_)
    for value in ("--ga-t:#87c2ff", "--pso-t:#ffb583", "--aco-t:#69e5b5", "--dp-t:#bfa5ff"):
        assert value in noir
    assert "#convChart text" in noir and "#convChart line" in noir
    # نص المعدن على خلفية مضاءة يجب أن يبقى مقروءًا فوق طبقته الفضية.
    assert ".btn.official-cta-btn.primary .hero-cta-label {color:#0a1014" in noir


def test_content_catalog_complete():
    """ملف ar.json صالح ومفهرس، وكل ربط ثابت فيه يُحل."""
    import re
    cat = json.loads((ROOT / "frontend/public" / "content" / "ar.json").read_text(encoding="utf-8"))
    for section in ("meta", "navigation", "hero", "story", "mission", "results",
                    "comparison", "validation", "laboratory", "footer", "statuses"):
        assert section in cat, section
    assert len(cat["story"]["stages"]) == 6
    html = (ROOT / "frontend/public" / "index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "frontend/public" / "app.js").read_text(encoding="utf-8")
    keys = set(re.findall(r'data-i18n(?:-html|-aria-label|-title|-placeholder)?="([^"]+)"', html))
    keys |= set(re.findall(r"""\bt\(\s*['"`]([a-zA-Z0-9_.]+)['"`]""", app_js))
    keys |= set(re.findall(r"""\braw\(\s*['"`]([a-zA-Z0-9_.]+)['"`]""", app_js))
    def get(key):
        v = cat
        for part in key.split("."):
            if isinstance(v, dict) and part in v:
                v = v[part]
            elif isinstance(v, list) and part.isdigit() and int(part) < len(v):
                v = v[int(part)]
            else:
                return None
        return v
    missing = sorted(k for k in keys if get(k) is None)
    assert missing == [], missing


def test_no_streamlit_anywhere():
    """يجب أن يعمل التطبيق النهائي دون Streamlit: لا استيراد وقت التشغيل، ولا مشغّل،
    ولا إعدادات، ولا توثيق يطلب تشغيله (باستثناء الملاحظات التاريخية)."""
    hits = []
    roots = list(ROOT.rglob("*.py")) + list(ROOT.rglob("*.js")) + list(ROOT.rglob("*.html")) \
        + list(ROOT.rglob("*.toml")) + [ROOT / "backend/requirements.txt"]
    roots = [p for p in roots if p.name != "test_site.py" and not {"node_modules", ".venv"}.intersection(p.parts)]
    for p in roots:
        try:
            t = p.read_text(encoding="utf-8")
        except Exception:
            continue
        if "streamlit" in t.lower():
            hits.append(str(p.relative_to(ROOT)))
    assert hits == [], hits
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    for banned in ("streamlit run", "share.streamlit", ".streamlit/", "import streamlit"):
        assert banned not in readme, banned
    assert "streamlit" not in sys.modules


def test_mission_and_lab_buttons_reuse_the_hero_primary_glass_without_dom_loss():
    """يغير زر المهمة نصوصه مرارًا؛ ويجب أن تبقى طبقات المحرك سليمة."""
    from html.parser import HTMLParser

    site = ROOT / "frontend/public"
    html = (site / "index.html").read_text(encoding="utf-8")
    app = (site / "app.js").read_text(encoding="utf-8") + (site / "experience.js").read_text(encoding="utf-8")
    engine = (site / "official-liquid-glass.js").read_text(encoding="utf-8")
    legacy = (site / "glass.js").read_text(encoding="utf-8")
    css = (site / "glass.css").read_text(encoding="utf-8")

    class PrimaryButtons(HTMLParser):
        def __init__(self):
            super().__init__()
            self.buttons = {}
        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if a.get("id") in ("missionPlay", "labRun"):
                self.buttons[a["id"]] = (tag, a)

    parsed = PrimaryButtons()
    parsed.feed(html)
    assert set(parsed.buttons) == {"missionPlay", "labRun"}
    for tag, attrs in parsed.buttons.values():
        assert tag == "button"
        assert set((attrs.get("class") or "").split()) >= {"btn", "primary", "official-cta-btn"}

    assert 'class="btn primary official-cta-btn" href="#story"' in html
    assert 'id="missionPlay"><span class="hero-cta-label"' in html
    assert 'id="labRun"><span class="hero-cta-label"' in html
    assert "document.querySelector('#missionPlay')" in engine
    assert "document.querySelector('#labRun')" in engine
    assert "kind: 'cta-primary'" in engine
    assert ".btn.official-cta-btn.official-liquid-host" in css
    assert ".btn.primary.official-cta-btn.official-liquid-cta-primary-host" in css
    assert "!el.classList.contains('official-cta-btn')" in legacy
    assert "$('#missionPlay').textContent" not in app
    assert "$('#missionPlay .hero-cta-label').textContent" in app


def test_3d_city_render_startup_does_not_reference_undefined_style_collection():
    """انحدار: تكرار `STYLES.forEach` أوقف كل مؤشرات تحميل المشهد ثلاثي الأبعاد."""
    scene_js = (SCENE / "js" / "city.js").read_text(encoding="utf-8")
    assert "STYLES.forEachSTYLES" not in scene_js
    assert "buildArchitecturalCity(this.group, this.data, this.seed, this.anim)" in scene_js
    if NODE:
        for name in ("city.js", "architecture.js", "fire.js", "swarm.js", "util.js"):
            subprocess.run([NODE, "--check", str(SCENE / "js" / name)], check=True, capture_output=True, text=True)
    for city in ("small", "medium", "large"):
        r = TestClient(server.app).get(f"/api/scene/ACO/{city}")
        assert r.status_code == 200, (city, r.text[:150])
        payload = r.json()
        assert payload["city"]["buildings"] and payload["runs"]


def test_scene_module_cache_prevents_reusing_the_broken_old_city_script():
    """إعادة التحميل العادية يجب ألا تستخدم ملفًا مخزنًا مؤقتًا فيه الخطأ المطبعي."""
    scene_entry = (ROOT / "frontend/public" / "scene.js").read_text(encoding="utf-8")
    assert "'/scene/js/city.js?v=viewport-20261018'" in scene_entry
    with TestClient(server.app) as client:
        for path in ("/scene.js", "/scene/js/city.js", "/scene/js/architecture.js", "/scene/js/fire.js"):
            r = client.get(path)
            assert r.status_code == 200
            assert 'no-store' in r.headers.get('cache-control', ''), path
