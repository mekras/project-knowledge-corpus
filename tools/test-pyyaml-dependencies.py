#!/usr/bin/env python3
"""Проверить целостность разрешений PyYAML и отказ без зависимости."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".apm" / "skills"
ENV = {**os.environ, "PYTHONPATH": "", "PYTHONDONTWRITEBYTECODE": "1"}


def snapshot(root: Path) -> dict[str, str | None]:
    return {
        path.relative_to(root).as_posix(): (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        )
        for path in root.rglob("*")
    }


def run_without_yaml(script: Path, arguments: list[str], fixture: Path) -> None:
    before = snapshot(fixture)
    result = subprocess.run(
        [sys.executable, "-S", str(script), *arguments],
        cwd=fixture, env=ENV, capture_output=True, text=True, encoding="utf-8",
        timeout=30, check=False,
    )
    assert result.returncode != 0, (script, result.stdout, result.stderr)
    assert "PyYAML" in result.stdout + result.stderr, (script, result.stderr)
    assert snapshot(fixture) == before, f"{script}: отказ изменил данные"


def main() -> int:
    for name in ("kc-inventory", "kc-pipeline", "kc-retrieval-evaluation"):
        root = SKILLS / name
        declaration = json.loads((root / "references/dependency-exceptions.json").read_text(encoding="utf-8"))
        record = declaration["dependencies"][0]
        lock = (root / "references/pyyaml-requirements.txt").read_bytes()
        assert record["installation"]["integrity"] == "sha256:" + hashlib.sha256(lock).hexdigest()
        assert record["version"] == "6.0.3" and b"PyYAML==6.0.3" in lock
        assert b"--only-binary=:all:" in lock

    with tempfile.TemporaryDirectory(prefix="pyyaml.local.", dir=ROOT / "tools") as temporary:
        fixture = Path(temporary)
        inventory = SKILLS / "kc-inventory"
        shutil.copytree(inventory / "evals/script-fixtures/record-verification", fixture, dirs_exist_ok=True)
        corpus = fixture / "knowledge"
        (corpus / "catalog.yml").write_text("sources: []\n", encoding="utf-8")
        unit = corpus / "data/fixture/documents/item"
        run_without_yaml(inventory / "scripts/validate-corpus-layout.py", [str(corpus)], fixture)
        run_without_yaml(inventory / "scripts/record-snapshot-verification.py", [
            str(unit), str(unit / "snapshot.txt"),
            "--acquisition-method", "local_file", "--verification-method", "direct_reopen",
            "--content-scope", "full_text", "--content-match", "verified",
            "--scope-completeness", "complete", "--overall-result", "verified",
            "--checked-by-role", "fixture", "--checked-at", "2026-10-19",
        ], fixture)
        run_without_yaml(SKILLS / "kc-pipeline/scripts/run-corpus-operations.py", [str(corpus)], fixture)
        run_without_yaml(SKILLS / "kc-retrieval-evaluation/scripts/validate-evaluation-suite.py", [
            str(fixture / "suite.yml"),
        ], fixture)

    print("Четыре операции без PyYAML отказали без изменения данных. Хэши файлов требований совпадают.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
