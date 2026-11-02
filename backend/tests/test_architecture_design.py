"""اختبارات انحدار: المعمار طبقة بصرية فقط فوق مدن اختبار ثابتة لا تتغير."""
from pathlib import Path
import json
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCENE = ROOT / 'frontend/public' / 'scene'
ARCH = SCENE / 'js' / 'architecture.js'


def test_all_simulators_use_the_same_architectural_city_builder():
    city = (SCENE / 'js' / 'city.js').read_text(encoding='utf-8')
    scene = (ROOT / 'frontend/public' / 'scene.js').read_text(encoding='utf-8')
    assert "import { buildArchitecturalCity } from './architecture.js';" in city
    assert 'buildArchitecturalCity(this.group, this.data, this.seed, this.anim)' in city
    assert "import { City, buildSky }" in scene


def test_silhouettes_and_facade_combinations_are_diverse_for_all_cities():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for production geometry verification')
    result = subprocess.run([node, 'tests/verify_architecture.mjs'], cwd=ROOT / 'frontend', capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.splitlines()[-1])
    assert report['total'] == 186
    assert report['maxOvershoot'] < 1e-4
    assert report['checkedPatches'] > 1000 and report['nonOverlappingShell']
