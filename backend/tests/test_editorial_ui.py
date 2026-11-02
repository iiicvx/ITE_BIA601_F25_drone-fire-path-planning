"""اختبارات انحدار لاتساق النصوص وأبعاد الواجهة في نسخة الواجهة المعدلة."""
import html
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_initial_arabic_matches_the_catalog_without_stale_numbers_or_claims():
    catalog = json.loads((ROOT / "frontend/public/content/ar.json").read_text(encoding="utf-8"))

    def text(value):
        return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", value))).strip()

    class Bindings(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.bindings = []

        def handle_starttag(self, tag, attrs):
            if tag in {"meta", "link", "input", "br", "img", "path", "rect", "circle"}:
                return
            a = dict(attrs)
            self.stack.append([tag, a.get("data-i18n") or a.get("data-i18n-html"), []])

        def handle_data(self, data):
            for entry in self.stack:
                if entry[1]:
                    entry[2].append(data)

        def handle_endtag(self, tag):
            if self.stack and self.stack[-1][0] == tag:
                _, key, parts = self.stack.pop()
                if key:
                    self.bindings.append((key, text("".join(parts))))

    parser = Bindings()
    parser.feed((ROOT / "frontend/public/index.html").read_text(encoding="utf-8"))
    assert len(parser.bindings) > 100
    for key, actual in parser.bindings:
        expected = catalog
        for part in key.split("."):
            expected = expected[int(part)] if isinstance(expected, list) else expected[part]
        assert actual == text(expected), key


def test_burning_facades_decals_and_street_assets_have_physical_support():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for Three.js geometry checks")
    result = subprocess.run([node, "tests/verify_assets.mjs"], cwd=ROOT / "frontend", capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["passed"] and report["buildings"] == 186
    assert report["groundedFireWings"] == 22
    assert report["backedFireDecals"] == 44
    assert report["roofPads"] > 0
