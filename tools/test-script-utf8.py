#!/usr/bin/env python3
"""Проверить вывод скриптов и обмен с адаптером при ASCII-кодировке среды."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = [
    "kc-inventory/scripts/record-snapshot-verification.py",
    "kc-inventory/scripts/validate-corpus-layout.py",
    "kc-pipeline/scripts/run-corpus-operations.py",
    "kc-retrieval-evaluation/scripts/evaluation_suite.py",
    "kc-retrieval-evaluation/scripts/run-evaluation-suite.py",
    "kc-retrieval-evaluation/scripts/sample-source-sections.py",
    "kc-retrieval-evaluation/scripts/validate-evaluation-suite.py",
    "kc-transcription/scripts/validate-transcription-result.py",
]
ENV = {
    **os.environ,
    "LC_ALL": "C",
    "PYTHONUTF8": "0",
    "PYTHONCOERCECLOCALE": "0",
    "PYTHONIOENCODING": "ascii",
    "PYTHONDONTWRITEBYTECODE": "1",
}
MARKER = "Русский вывод"


def run(*arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, *arguments], cwd=ROOT, env=ENV,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )


def main() -> int:
    for relative in SCRIPTS:
        path = ROOT / ".apm/skills" / relative
        result = run(str(path), "--help")
        if result.returncode:
            raise AssertionError(f"{relative}: --help завершился с ошибкой: {result.stderr!r}")
        code = (
            "import runpy,sys; "
            f"sys.path.insert(0,{str(path.parent)!r}); "
            f"runpy.run_path({str(path)!r}); "
            f"print({ascii(MARKER)}); print({ascii(MARKER)},file=sys.stderr)"
        )
        result = run("-c", code)
        expected = (MARKER + "\n").encode("utf-8")
        if result.returncode or result.stdout != expected or result.stderr != expected:
            raise AssertionError(f"{relative}: потоки не сохраняют русский текст: {result.stderr!r}")

    runner = ROOT / ".apm/skills/kc-retrieval-evaluation/scripts/run-evaluation-suite.py"
    adapter = r"import json,sys; sys.stdin.buffer.read().decode('utf-8'); sys.stdout.buffer.write(json.dumps({'answer':'\u041e\u0442\u0432\u0435\u0442'},ensure_ascii=False).encode('utf-8'))"
    code = (
        "import runpy,sys; from pathlib import Path; from types import SimpleNamespace; "
        f"sys.path.insert(0,{str(runner.parent)!r}); module=runpy.run_path({str(runner)!r}); "
        f"config=SimpleNamespace(adapters={{'local':[sys.executable,'-c',{adapter!r}]}},timeout=5); "
        "result=module['call_model'](config,SimpleNamespace(adapter='local',model='test'),"
        r"'\u0417\u0430\u043f\u0440\u043e\u0441',cwd=Path.cwd(),access_mode='closed_book'); "
        r"assert result['answer']=='\u041e\u0442\u0432\u0435\u0442'"
    )
    result = run("-c", code)
    if result.returncode:
        raise AssertionError(f"Обмен с UTF-8-адаптером не прошёл: {result.stderr!r}")
    print("Вывод восьми скриптов и обмен с адаптером проверены при ASCII-кодировке среды.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
