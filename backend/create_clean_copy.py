"""ينشئ نسخة نظيفة من المشروع دون البيئات المثبتة وملفات السجل."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache", ".git"}
SKIP_ROOT = {".drone-fire-server.pid", "server-output.log", "server-error.log", "launcher.log", ".coverage", "CLEAN_COPY_MANIFEST.json"}
QA_PREFIXES = ("ui-", "qa-", "viewport-", "rendering-", "beam-", "ambient-", "oblique-", "before-", "after-", "visual-")
QA_REPORTS = {"ui-lint.json", "viewport-audit.json", "rendering-audit.json", "lightweight-audit.json"}


def build(destination: Path) -> dict:
    destination = destination.resolve()
    if destination == SOURCE or SOURCE in destination.parents:
        raise ValueError("The copy must be outside the source tree")
    if not destination.parent.is_dir():
        raise ValueError("The destination parent does not exist")
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite an existing folder: {destination}")
    destination.mkdir()
    copied, excluded = [], []
    for root, dirs, files in os.walk(SOURCE):
        parent = Path(root).relative_to(SOURCE)
        for name in list(dirs):
            path = Path(root) / name
            if name in SKIP_DIRS or path.is_symlink():
                dirs.remove(name)
                excluded.append((parent / name).as_posix() + "/")
        dirs.sort()
        for name in sorted(files):
            path = Path(root) / name
            relative = parent / name
            qa_output = parent == Path("frontend/results") and (name in QA_REPORTS or (path.suffix == ".png" and name.startswith(QA_PREFIXES)))
            if path.is_symlink() or path.suffix in {".pyc", ".pyo"} or (parent == Path("backend") and name in SKIP_ROOT) or qa_output:
                excluded.append(relative.as_posix())
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            digest = hashlib.sha256()
            with target.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            copied.append({"path": relative.as_posix(), "bytes": target.stat().st_size, "sha256": digest.hexdigest()})
    manifest = {"files": copied, "excluded": sorted(excluded), "file_count": len(copied), "bytes": sum(item["bytes"] for item in copied),
                "launch": "backend/Start-Stop.bat", "dependencies": "backend/launcher.ps1 installs backend/requirements.txt into backend/.venv on first launch"}
    (destination / "backend" / "CLEAN_COPY_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"destination": str(destination), "files": manifest["file_count"], "megabytes": round(manifest["bytes"] / 1024**2, 2), "excluded_entries": len(excluded)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    print(json.dumps(build(parser.parse_args().destination), ensure_ascii=False, indent=2))
