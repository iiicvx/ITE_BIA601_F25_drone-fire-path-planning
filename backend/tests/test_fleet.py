"""فحوص تكامل علمية لتجربة السرب الحقيقية 2 / 4 / 6 مسيّرات وواجهتها البرمجية."""
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from simulation.scenarios import validate, load_scenario
from simulation.fleet import fleet_config
from simulation.fitness import Problem
from simulation.validator import check_plan

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
import server as data
import server


@pytest.mark.parametrize("size,count", [("small", 2), ("medium", 4), ("large", 6)])
def test_fleet_scenario_and_every_saved_plan(size, count):
    path = data.scenario_path(f"fleet_{size}")
    scn = load_scenario(path)
    _, cfg = fleet_config()
    assert validate(scn, cfg) == []
    assert scn.problem["n_drones"] == len(scn.missions) == len(scn.fires) == count
    assert scn.problem["n_variables"] == 3 * count * scn.problem["n_waypoints"]
    assert len({tuple(m.S) for m in scn.missions}) == count
    assert len({tuple(m.G) for m in scn.missions}) == count
    runs = data.fleet_runs(size)
    assert {r["algorithm"] for r in runs} == set(data.ALG_ORDER)
    for run in runs:
        assert run["scenario_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert len(run["paths"]) == count
        assert run["budget"] == scn.problem["budget_fe"]
        assert run["fe_used"] == (1 if run["algorithm"] == "DP" else run["budget"])
        for mission, points in zip(scn.missions, run["paths"]):
            np.testing.assert_array_equal(points[0], mission.S)
            np.testing.assert_array_equal(points[-1], mission.G)
        F, info = Problem(scn).evaluate_paths(run["paths"], count=False)
        assert F == pytest.approx(run["best_f"], rel=0, abs=1e-10)
        independent = check_plan(scn, run["paths"])
        assert independent["valid"] == info["feasible"] == run["validator"]["valid"]
        assert independent["checks"] == run["validator"]["checks"]
    summary = data.load_fleet_summary(size)
    safe = [r for r in summary["rows"] if r["valid"]]
    assert summary["winner"] == min(safe, key=lambda r: r["F"])["algorithm"]


def test_fleet_payload_and_export_never_round_scored_paths():
    client = TestClient(server.app)
    for size, count in [("small", 2), ("medium", 4), ("large", 6)]:
        result = client.get(f"/api/fleet/{size}/GA").json()
        payload = client.get(f"/api/fleet/{size}/GA/scene").json()
        assert len(payload["runs"][0]["paths"]) == count
        assert payload["runs"][0]["paths"] == result["paths"]
        assert payload["city"]["name"] == f"fleet_{size}"
        csv = client.get(f"/api/fleet/{size}/GA/csv").text
        actual = [list(map(float, row.split(',')[2:])) for row in csv.splitlines()[1:]]
        assert actual == [p for path in result["paths"] for p in path]
    assert client.get('/api/fleet/unknown/GA').status_code == 404


def test_live_fleet_run_has_two_real_paths_and_one_cached_validation():
    client = TestClient(server.app)
    start = client.post('/api/live', json={"alg": "DP", "city": "small", "fleet": True})
    assert start.status_code == 200
    assert start.json()["budget"] == 10000
    job = start.json()["job"]
    for _ in range(120):
        status = client.get(f'/api/live/{job}').json()
        if status["done"]:
            break
        time.sleep(.05)
    assert status["done"] and "error" not in status
    assert status["progress"] == 1
    assert len(status["result"]["paths"]) == 2
    assert status["result"]["validator"]["agrees_with_fitness"]
    runner = server._JOBS[job]["runner"]
    assert runner.to_dict() is runner.to_dict()  # المدقق لا يعمل عند كل استعلام
    assert client.get(f'/api/live/{job}/scene').json()["city"]["problem"]["n_drones"] == 2
    assert client.post('/api/live', json={"seed": -1}).status_code == 422
    assert client.post('/api/live', json={"budget": 0}).status_code == 422


def test_new_ui_copy_resolves_and_uses_versioned_results():
    import re
    cat = json.loads((ROOT / 'frontend/public/content/ar.json').read_text(encoding='utf-8'))
    script = (ROOT / 'frontend/public/experience.js').read_text(encoding='utf-8')
    for key in re.findall(r"\b(?:t|raw)\(['\"]([a-zA-Z0-9_.]+)['\"]", script):
        value = cat
        for part in key.split('.'):
            value = value[part]
        assert value is not None, key
