"""اختبارات انحدار لذاكرة المتصفح المؤقتة ولعدسات التنقل التي تُحمَّل متأخرة."""
from pathlib import Path
import sys
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
import server  # noqa: E402


def test_ui_documents_are_not_cached_as_stale_revisions():
    with TestClient(server.app) as client:
        for url in ["/", "/index.html", "/styles.css", "/glass.css",
                    "/theme-noir.css", "/app.js", "/content.js",
                    "/official-liquid-glass.js", "/content/ar.json"]:
            response = client.get(url)
            assert response.status_code == 200, url
            assert "no-store" in response.headers.get("cache-control", ""), url
        # لا تُعاد تهيئة نتائج الواجهة البرمجية المباشرة ولا الأصول الثقيلة.
        assert "no-store" not in client.get("/healthz").headers.get("cache-control", "")
        assert "no-store" not in client.get("/scene/assets/rescue_hexacopter.glb").headers.get("cache-control", "")


def test_loading_glass_works_even_after_window_load():
    source = (ROOT / "frontend/public/app.js").read_text(encoding="utf-8")
    assert "if (document.readyState === 'complete') initializeGlassEnhancements();" in source
    assert "addEventListener('load', initializeGlassEnhancements, { once: true })" in source
    assert "if (glassEnhancementsStarted) return" in source
    assert "document.fonts?.ready.then" in source
    assert "updateScrollNavigation()" in source
    assert "event.persisted" in source
    assert "import('/ambient-drone.js?" in source  # الزخرفة الاختيارية لا يجوز أن تعطل التنقل


def test_revision_stamps_coherent():
    html = (ROOT / "frontend/public/index.html").read_text(encoding="utf-8")
    app = (ROOT / "frontend/public/app.js").read_text(encoding="utf-8")
    content = (ROOT / "frontend/public/content.js").read_text(encoding="utf-8")
    version = 'viewport-20261018'
    for path in ['/styles.css', '/glass.css', '/theme-noir.css', '/app.js']:
        assert f'{path}?v={version}' in html
    for path in ['/scene.js', '/glass.js', '/official-liquid-glass.js', '/content.js', '/ambient-drone.js']:
        assert f'{path}?v={version}' in app
    assert f'/content/ar.json?v={version}' in content
