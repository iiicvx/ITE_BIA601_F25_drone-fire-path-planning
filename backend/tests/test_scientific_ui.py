"""تحقق مستقل من التحويلات العددية المعروضة ومقطع الخطر."""
import json
import re
import shutil
import subprocess
from pathlib import Path
import numpy as np
import pytest
from simulation.geometry import FireField

ROOT=Path(__file__).resolve().parents[2]

def test_chart_steps_terrain_partition_and_hazard_section_match_python():
    node=shutil.which("node")
    if not node:pytest.skip("Node.js is required for rendered-model arithmetic")
    result=subprocess.run([node,"tests/verify_science.mjs"],cwd=ROOT/"frontend",capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stderr
    report=json.loads(result.stdout)
    assert report["passed"] and report["groundSamples"]==75 and report["exactStepChart"]
    section=np.asarray(report["section"])
    points=np.column_stack([section[:,0],np.zeros(len(section)),section[:,1]])
    field=FireField(np.array([[0,0,0,15,1,80]],float),k=.25)
    np.testing.assert_allclose(field.H(points),.5,rtol=0,atol=1e-12)
    assert report["coreRadius"]==pytest.approx(15*np.sqrt(np.log(2)),abs=1e-12)
    assert report["coreHeight"]==pytest.approx(80*np.log(2),abs=1e-12)

def test_csv_numbers_match_original_runs_and_independent_arithmetic():
    from simulation.numerical_audit import audit
    result=audit()
    assert result["passed"],result["failures"]
    assert result["checks"]>1000

def test_vehicle_terminology_uses_musayyarah_with_shadda():
    catalog=json.loads((ROOT/"frontend/public/content/ar.json").read_text(encoding="utf-8"))
    def strings(value):
        if isinstance(value,str):yield value
        elif isinstance(value,dict):
            for item in value.values():yield from strings(item)
        elif isinstance(value,list):
            for item in value:yield from strings(item)
    for text in strings(catalog):assert not re.search(r"درون|طائر(?:ة|ات|ت)",text),text
    assert catalog["camera"]["drone"]=="المُسيَّرة"
    assert "مُسيَّرتان" in catalog["workspace"]["small"]
