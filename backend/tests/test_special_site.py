"""عرض حالات الحافة العشر في الموقع: القائمة، وتطابق أحكام السلامة مع النتائج المحفوظة،
وعدم عرض نجاح وهمي لخطة مرفوضة، وبقاء نطاق التشغيل المباشر كما كان."""
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
import server  # noqa: E402

INDEX = json.loads((ROOT / "simulation/scenarios/special/index.json").read_text())
SUMMARY = pd.read_csv(ROOT / "simulation/results/special/summary.csv")
RUNS = json.loads((ROOT / "simulation/results/special/runs.json").read_text())
PUBLIC = ROOT / "frontend/public"


@pytest.fixture(scope="module")
def client():
    return TestClient(server.app)


@pytest.fixture(scope="module")
def cases(client):
    return client.get("/api/special-cases").json()


def test_all_ten_cases_are_listed_in_index_order(client, cases):
    assert [c["name"] for c in cases] == list(INDEX)
    assert len(cases) == 10
    for c in cases:
        assert c["expect"] == INDEX[c["name"]]["expect"]
        assert client.get(f"/api/city/{c['name']}").status_code == 200
    assert len(client.get("/api/table/special").json()) == len(SUMMARY) == 100
    copy = json.loads((PUBLIC / "content/ar.json").read_text(encoding="utf-8"))
    for c in cases:
        assert copy["caseCopy"][c["case"]]["title"] and copy["caseCopy"][c["case"]]["body"]
    assert client.get("/api/special/special_unknown/GA").status_code == 404
    assert client.get("/api/special/../../config/GA").status_code == 404


def test_card_counts_and_default_choice_follow_saved_results(cases):
    for c in cases:
        rows = SUMMARY[SUMMARY["case"] == c["case"]]
        for alg, info in c["algorithms"].items():
            rr = rows[rows["algorithm"] == alg]
            assert info["runs"] == len(rr)
            assert info["safe"] == int(rr["validator_valid"].sum())
            safe = rr[rr["validator_valid"]]
            assert info["best_safe_F"] == (float(safe["F"].min()) if len(safe) else None)
        safe_algs = {a: v["best_safe_F"] for a, v in c["algorithms"].items() if v["best_valid"]}
        if c["expect"] == "infeasible":
            # الحالة المستحيلة بالتصميم لا خطة آمنة فيها، فلا يُختار لها عرض افتراضي.
            assert not safe_algs and c["default_alg"] is None
        else:
            assert c["default_alg"] == min(safe_algs, key=lambda a: (safe_algs[a], server.ALG_ORDER.index(a)))
    by_case = {c["case"]: c for c in cases}
    assert by_case["maze"]["default_alg"] == "ACO"
    assert by_case["crossing_drones"]["algorithms"]["DP"]["best_valid"] is False
    assert by_case["empty_city"]["algorithms"]["PSO"]["best_safe_F"] == 1.5


@pytest.mark.parametrize("name", list(INDEX))
def test_replay_shows_the_real_saved_result_and_verdict(client, name):
    for alg in server.ALG_ORDER:
        saved = [r for r in RUNS if r["scenario"] == name and r["algorithm"] == alg]
        chosen = min(saved, key=lambda r: (not r["feasible"], r["best_f"]))
        result = client.get(f"/api/special/{name}/{alg}").json()
        scene = client.get(f"/api/special/{name}/{alg}/scene").json()
        # المسار المعروض هو المسار المحفوظ نفسه، دون استبداله بنتيجة خوارزمية أخرى.
        assert result["algorithm"] == alg and result["paths"] == chosen["paths"]
        assert scene["runs"][0]["paths"] == chosen["paths"]
        assert result["validator"]["valid"] == chosen["feasible"] == scene["runs"][0]["valid"]
        assert result["validator"]["agrees_with_fitness"]
        rows = SUMMARY[(SUMMARY["case"] == INDEX[name]["case"]) & (SUMMARY["algorithm"] == alg)]
        assert bool(rows["validator_valid"].any()) == result["validator"]["valid"]


def test_live_scope_is_unchanged_by_the_display_list(client):
    assert server.LIVE_SPECIAL_CASES == ("target_near_fire", "crossing_drones")
    assert set(server.SITE_SPECIAL_CASES) > set(server.LIVE_SPECIAL_CASES)
    for case in server.SITE_SPECIAL_CASES:
        if case in server.LIVE_SPECIAL_CASES:
            continue
        r = client.post("/api/live", json={"alg": "DP", "city": f"special_{case}", "budget": 1})
        assert r.status_code == 400, case
    assert client.post("/api/live", json={"alg": "GA", "city": "large"}).status_code == 400
    for case in server.LIVE_SPECIAL_CASES:
        r = client.post("/api/live", json={"alg": "DP", "city": f"special_{case}", "budget": 1})
        assert r.status_code == 200, case
        job = r.json()["job"]
        for _ in range(600):
            status = client.get(f"/api/live/{job}").json()
            if status["done"]:
                break
            time.sleep(0.05)
        assert status["done"] and "error" not in status


def test_rejected_plans_do_not_trigger_mission_success():
    swarm = (PUBLIC / "scene/js/swarm.js").read_text(encoding="utf-8")
    # قذف الكبسولة وإطفاء الحريق مشروطان بسلامة الخطة.
    assert "this.safe = missionSuccessAllowed(run);" in swarm
    assert "if (fire && capsule && this.safe) {" in swarm
    status = swarm[swarm.index("  status(d, t, fires) {"):swarm.index("  telemetry(d, t, fires) {")]
    assert status.index("if (!this.safe) return copy('statuses.rejected');") < status.index("statuses.arrived")
    ui = (PUBLIC / "experience.js").read_text(encoding="utf-8")
    # الخطة المرفوضة تبدأ مخفية خلف بوابة تشخيص، ولا تُشغّل تلقائيًا.
    assert "viewer.S.playing = safe &&" in ui and "setGate(!safe);" in ui
    assert "swarm.setVisible(!on)" in ui
    html = (PUBLIC / "index.html").read_text(encoding="utf-8")
    assert 'id="labGate"' in html and 'id="labPreview"' in html
    copy = json.loads((PUBLIC / "content/ar.json").read_text(encoding="utf-8"))
    assert copy["statuses"]["rejected"]
    text = json.dumps(copy, ensure_ascii=False) + html
    assert re.search("عشر", copy["cases"]["title"])
    assert "نتائج الحالتين" not in text and "حالتان صُمّمتا" not in text


def test_success_effects_need_an_explicit_safe_verdict():
    """غياب حكم السلامة أو أي قيمة غير true تمنع الإطلاق؛ والخطة الآمنة الصريحة تبقى مسموحة."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to evaluate the scene rule")
    swarm = (PUBLIC / "scene/js/swarm.js").read_text(encoding="utf-8")
    rule = re.search(r"export const missionSuccessAllowed = (run => [^;]+);", swarm)
    assert rule and rule.group(1) == "run => run?.valid === true && run?.feasible === true"
    cases = [({"valid": True, "feasible": True}, True), ({"valid": True}, False), ({"feasible": True}, False),
             ({}, False), (None, False), ({"valid": None, "feasible": True}, False),
             ({"valid": True, "feasible": None}, False), ({"valid": "true", "feasible": True}, False),
             ({"valid": 1, "feasible": 1}, False), ({"valid": False, "feasible": True}, False),
             ({"valid": True, "feasible": False}, False)]
    script = (f"const allowed = {rule.group(1)}; const runs = {json.dumps([c for c, _ in cases])};"
              "process.stdout.write(JSON.stringify([...runs.map(allowed), allowed(undefined)]));")
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30, check=True).stdout
    assert json.loads(out) == [expected for _, expected in cases] + [False]
