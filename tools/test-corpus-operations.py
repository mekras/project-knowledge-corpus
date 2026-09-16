#!/usr/bin/env python3
"""Regression tests for the portable corpus operations controller."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from textwrap import dedent


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / ".apm" / "skills" / "kc-pipeline" / "scripts" / "run-corpus-operations.py"
VALIDATOR = REPO_ROOT / ".apm" / "skills" / "kc-inventory" / "scripts" / "validate-corpus-layout.py"
QUEUE_NAMES = (
    "content_selection",
    "fetch",
    "transcribe",
    "normalize",
    "statements",
    "traceability",
    "semantic_review",
    "strong_review",
    "corroboration",
    "source_check",
    "verification",
    "concepts",
    "impact_audit",
    "apply_changes",
    "corpus_validation",
    "human_decision",
)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text).lstrip(), encoding="utf-8")


def build_corpus(root: Path) -> None:
    write(
        root / "knowledge" / "corpus.yml",
        """
        contract_version: 1
        tracked_data:
          root: data
        local_data:
          local_file_pattern: "*.local.*"
        source_units:
          document:
            unit: document
            path_pattern: data/<source>/documents/<slug>
        indexes:
          items: index/items.yml
          statements: index/statements.yml
        workflow_stages:
          - indexed
          - needs_fetch
          - fetched
          - needs_transcript
          - raw_transcribed
          - normalized
          - statements_extracted
          - source_checked
          - verification_assessed
          - blocked
          - rejected
        """,
    )
    write(
        root / "knowledge" / "catalog.yml",
        """
        sources:
          - id: TEST
            title: "Тестовый источник"
            path: data/test
          - id: TEST-INDEX-ONLY
            title: "Индексируемый источник"
            path: data/test-index-only
        """,
    )
    write(
        root / "knowledge" / "data" / "test" / "source.yml",
        """
        id: TEST
        slug: test
        title: "Тестовый источник"
        access:
          default: "Открытый тестовый источник."
        status: active
        carrier_type: document
        source_kind: reference
        storage_strategy: full_copy
        adapter: builtin.local-file
        locator: "file:///tmp/test-source.txt"
        reliability: test
        refresh_policy: manual
        """,
    )
    write(
        root / "knowledge" / "data" / "test" / "items.yml",
        """
        items:
          - id: TEST-FETCH
            title: "Нужно получить"
            access: "Открытый тестовый источник."
            status: active
            workflow_stage: needs_fetch
          - id: TEST-NORMALIZED
            title: "Нормализован"
            access: "Открытый тестовый источник."
            status: active
            workflow_stage: normalized
            path: documents/normalized
          - id: TEST-BLOCKED
            title: "Нужен владелец"
            access: "Открытый тестовый источник."
            status: blocked
            workflow_stage: blocked
            blocker_code: owner_decision_required
          - id: TEST-STATEMENTS
            title: "С утверждениями"
            access: "Открытый тестовый источник."
            status: active
            workflow_stage: statements_extracted
            path: documents/statements
          - id: TEST-CONTENT-SELECTION
            title: "Нужен содержательный отбор"
            access: "Открытый тестовый источник."
            status: active
            workflow_stage: indexed
            processing_scope: metadata_only
          - id: TEST-SELECTED
            title: "Выбраны фрагменты"
            access: "Открытый тестовый источник."
            status: active
            workflow_stage: indexed
            processing_scope: selected_fragments
          - id: TEST-V2-COMPLETE
            title: "Историческое утверждение без записанной внешней сверки"
            access: "Открытый тестовый источник."
            status: active
            workflow_stage: source_checked
            path: documents/v2-complete
        """,
    )
    write(
        root / "knowledge" / "data" / "test-index-only" / "source.yml",
        """
        id: TEST-INDEX-ONLY
        slug: test-index-only
        title: "Индексируемый источник"
        access:
          default: "Открытый тестовый источник."
        status: active
        carrier_type: document
        source_kind: reference
        storage_strategy: index_only
        adapter: builtin.index
        reliability: test
        refresh_policy: manual
        """,
    )
    write(
        root / "knowledge" / "data" / "test-index-only" / "items.yml",
        """
        items:
          - id: TEST-INDEX-ONLY-METADATA
            title: "Только в индексе"
            access: "Открытый тестовый источник."
            status: active
            workflow_stage: indexed
            processing_scope: metadata_only
          - id: TEST-INDEX-ONLY-SELECTED
            title: "Выбранная единица индексируемого источника"
            access: "Открытый тестовый источник."
            status: active
            workflow_stage: indexed
            processing_scope: full
        """,
    )
    write(
        root / "knowledge" / "data" / "test" / "documents" / "normalized" / "item.yml",
        """
        id: TEST-NORMALIZED
        title: "Нормализован"
        access: "Открытый тестовый источник."
        status: active
        workflow_stage: normalized
        """,
    )
    write(root / "knowledge" / "data" / "test" / "documents" / "normalized" / "normalized.md", "Тестовый текст.\n")
    write(
        root / "knowledge" / "data" / "test" / "documents" / "statements" / "item.yml",
        """
        id: TEST-STATEMENTS
        title: "С утверждениями"
        access: "Открытый тестовый источник."
        status: active
        workflow_stage: statements_extracted
        """,
    )
    write(
        root / "knowledge" / "data" / "test" / "documents" / "statements" / "statements.yml",
        """
        source_id: TEST
        item_id: TEST-STATEMENTS
        statements:
          - id: TEST-001
            source_id: TEST
            item_id: TEST-STATEMENTS
            status: candidate
            kind: fact
            text: "Тестовое утверждение."
            excerpt: "Тестовое утверждение."
            artifact: normalized.md
            checked_at: 2026-07-10
            scope: {}
            open_questions: []
        """,
    )
    write(
        root / "knowledge" / "data" / "test" / "documents" / "statements" / "normalized.md",
        "Тестовое утверждение.\n",
    )
    write(
        root / "knowledge" / "data" / "test" / "documents" / "v2-complete" / "item.yml",
        """
        id: TEST-V2-COMPLETE
        title: "Историческое утверждение без записанной внешней сверки"
        access: "Открытый тестовый источник."
        status: active
        workflow_stage: source_checked
        """,
    )
    write(
        root / "knowledge" / "data" / "test" / "documents" / "v2-complete" / "statements.yml",
        """
        statement_contract_version: 2
        source_id: TEST
        item_id: TEST-V2-COMPLETE
        statements:
          - id: TEST-002
            source_id: TEST
            item_id: TEST-V2-COMPLETE
            kind: fact
            text: "Историческое утверждение со слабым основанием."
            excerpt: "Историческое утверждение со слабым основанием."
            artifact: normalized.md
            checked_at: 2026-07-10
            scope: {}
            open_questions: []
            processing_status:
              extraction: complete
              traceability: passed
              semantic_review: passed
              strong_review: not_required
              corroboration_check: complete
            source_role: secondary
            evidence_strength: weak
            confidence: high
            temporal_status: historical
            corroboration: single_source
            limitations:
              - "Сведения относятся к прошлому состоянию."
        """,
    )
    write(
        root / "knowledge" / "data" / "test" / "documents" / "v2-complete" / "normalized.md",
        "Историческое утверждение со слабым основанием.\n",
    )
    write(
        root / "adapter.py",
        """
        import json
        import sys
        from pathlib import Path

        source_id, locator = sys.argv[1:]
        Path("knowledge/data/test/adapter-marker.yml").write_text("locator: " + locator + "\\n", encoding="utf-8")
        print(json.dumps({
            "contract_version": 1,
            "source_id": source_id,
            "adapter": "builtin.local-file",
            "status": "changed",
            "message": "Паспорт локального файла обновлён.",
            "artifacts": ["knowledge/data/test/adapter-marker.yml"],
        }))
        """,
    )
    write(
        root / "advance-content-selection.py",
        """
        import json
        from pathlib import Path

        state = json.loads(Path(".local/state/corpus-pipeline.json").read_text(encoding="utf-8"))
        if state.get("status") != "running":
            raise SystemExit("pipeline state was not persisted as running")
        path = Path("knowledge/data/test/items.yml")
        text = path.read_text(encoding="utf-8")
        old = '''  - id: TEST-CONTENT-SELECTION
            title: "Нужен содержательный отбор"
            access: "Открытый тестовый источник."
            status: active
            workflow_stage: indexed
            processing_scope: metadata_only'''
        new = old.replace("workflow_stage: indexed", "workflow_stage: rejected")
        if old not in text:
            raise SystemExit("test item was not found")
        path.write_text(text.replace(old, new), encoding="utf-8")
        """,
    )
    write(
        root / "operations.yml",
        f"""
        operations_version: 1
        report:
          path: .local/reports/operations.md
        stages:
          source_sync:
            commands:
              - id: create-marker
                argv:
                  - {sys.executable}
                  - -c
                  - "from pathlib import Path; Path('knowledge/data/test/marker.txt').write_text('ok', encoding='utf-8')"
                working_directory: .
                write_paths:
                  - knowledge/data/test
                required: true
          content_selection:
            commands:
              - id: reject-unselected-test-item
                argv:
                  - {sys.executable}
                  - advance-content-selection.py
                working_directory: .
                write_paths:
                  - knowledge/data/test
                required: true
          bad_write:
            commands:
              - id: overwrite-staged-file-outside-scope
                argv:
                  - {sys.executable}
                  - -c
                  - "from pathlib import Path; Path('outside.txt').write_text('changed', encoding='utf-8')"
                working_directory: .
                write_paths:
                  - knowledge/data/test
                required: true
          ignored_bad_write:
            commands:
              - id: overwrite-ignored-file-outside-scope
                argv:
                  - {sys.executable}
                  - -c
                  - "from pathlib import Path; Path('.private/source.txt').write_text('changed ignored material', encoding='utf-8')"
                working_directory: .
                write_paths:
                  - knowledge/data/test
                required: true
          concepts:
            commands:
              - id: check-concepts
                argv: [{sys.executable}, -c, "pass"]
                working_directory: .
                write_paths: [knowledge]
                required: true
          impact_audit:
            commands:
              - id: audit-impact
                argv: [{sys.executable}, -c, "pass"]
                working_directory: .
                write_paths: [knowledge]
                required: true
          apply_changes:
            commands:
              - id: apply-safe-changes
                argv: [{sys.executable}, -c, "pass"]
                working_directory: .
                write_paths: [knowledge]
                required: true
          corpus_validation:
            commands:
              - id: validate-complete-corpus
                argv: [{sys.executable}, -c, "pass"]
                working_directory: .
                write_paths: [knowledge]
                required: true
        adapters:
          builtin.local-file:
            argv:
              - {sys.executable}
              - adapter.py
              - "{{source_id}}"
              - "{{locator}}"
            working_directory: .
            write_paths:
              - knowledge/data/test
        """,
    )
    write(root / "outside.txt", "original\n")
    write(root / ".gitignore", ".private/\n")
    write(root / ".private" / "source.txt", "original ignored material\n")


def configure_v2_adapter(root: Path) -> None:
    source_path = root / "knowledge" / "data" / "test" / "source.yml"
    source_path.write_text(
        source_path.read_text(encoding="utf-8").replace(
            "adapter: builtin.local-file",
            "adapter: project.v2\n"
            "access_requirements:\n"
            "  authorization_kind: account_session\n"
            "  required_capabilities: [read_item]\n"
            "  profile_name: test-reader\n"
            "  interactive_setup: allowed",
        ),
        encoding="utf-8",
    )
    write(
        root / "adapter-v2.py",
        """
        import json
        import sys
        from pathlib import Path

        operation, source_id, profile_name = sys.argv[1:]
        if Path(".local/leak-secret").exists():
            print("token=TOP-SECRET", file=sys.stderr)
            raise SystemExit(1)
        if operation == "probe":
            status = "ready" if Path(".local/profile-ready").exists() else "profile-missing"
            message = "Профиль готов." if status == "ready" else "Локальный профиль отсутствует."
            artifacts = []
        elif operation == "fetch":
            Path("knowledge/data/test/v2-fetch.yml").write_text("profile: " + profile_name + "\\n", encoding="utf-8")
            status = "changed"
            message = "Снимок получен."
            artifacts = ["knowledge/data/test/v2-fetch.yml"]
        elif operation == "verify":
            status = "unverified" if Path(".local/verify-success").exists() else "access-limited"
            message = "Проверка завершена." if status == "unverified" else "Новая сверка недоступна."
            artifacts = []
        elif operation == "authorize":
            Path(".local/authorize-called").parent.mkdir(parents=True, exist_ok=True)
            Path(".local/authorize-called").write_text("called", encoding="utf-8")
            status = "ready"
            message = "Интерактивная авторизация завершена."
            artifacts = []
        else:
            raise SystemExit(3)
        print(json.dumps({
            "contract_version": 2,
            "operation": operation,
            "source_id": source_id,
            "adapter": "project.v2",
            "status": status,
            "message": message,
            "artifacts": artifacts,
        }))
        """,
    )
    operations_path = root / "operations.yml"
    operations_path.write_text(
        operations_path.read_text(encoding="utf-8")
        + f"""
  project.v2:
    contract_version: 2
    operations:
      probe:
        argv: [{sys.executable}, adapter-v2.py, probe, "{{source_id}}", "{{profile_name}}"]
        working_directory: .
        write_paths: []
      fetch:
        argv: [{sys.executable}, adapter-v2.py, fetch, "{{source_id}}", "{{profile_name}}"]
        working_directory: .
        write_paths: [knowledge/data/test]
      verify:
        argv: [{sys.executable}, adapter-v2.py, verify, "{{source_id}}", "{{profile_name}}"]
        working_directory: .
        write_paths: [knowledge/data/test]
      authorize:
        argv: [{sys.executable}, adapter-v2.py, authorize, "{{source_id}}", "{{profile_name}}"]
        working_directory: .
        write_paths: []
""",
        encoding="utf-8",
    )
    gitignore = root / ".gitignore"
    gitignore.write_text(gitignore.read_text(encoding="utf-8") + ".local/\n", encoding="utf-8")


def reject_automated_work(root: Path, *, keep_blocked: bool) -> None:
    stage_names = (
        "needs_fetch",
        "fetched",
        "needs_transcript",
        "raw_transcribed",
        "normalized",
        "statements_extracted",
        "source_checked",
        "indexed",
    )
    for path in (root / "knowledge" / "data").rglob("*.yml"):
        text = path.read_text(encoding="utf-8")
        for stage in stage_names:
            text = text.replace(f"workflow_stage: {stage}", "workflow_stage: rejected")
        text = text.replace("status: candidate", "status: confirmed")
        if not keep_blocked:
            text = text.replace("workflow_stage: blocked", "workflow_stage: rejected")
        path.write_text(text, encoding="utf-8")


def add_no_progress_fetch_executor(root: Path) -> None:
    path = root / "operations.yml"
    text = path.read_text(encoding="utf-8")
    addition = (
        "  fetch:\n"
        "    commands:\n"
        "      - id: touch-unrelated-marker\n"
        "        argv:\n"
        f"          - {sys.executable}\n"
        "          - -c\n"
        "          - \"from pathlib import Path; "
        "Path('knowledge/data/test/unrelated.txt').write_text('changed', encoding='utf-8')\"\n"
        "        working_directory: .\n"
        "        write_paths:\n"
        "          - knowledge/data/test\n"
        "        required: true\n"
    )
    path.write_text(
        text.replace("\nadapters:\n", f"\n{addition}adapters:\n"),
        encoding="utf-8",
    )


def add_resource_deferred_fetch_and_statements_executor(root: Path) -> None:
    write(
        root / "advance-statements.py",
        """
        from pathlib import Path

        path = Path("knowledge/data/test/items.yml")
        text = path.read_text(encoding="utf-8")
        old = '''  - id: TEST-NORMALIZED
            title: "Нормализован"
            access: "Открытый тестовый источник."
            status: active
            workflow_stage: normalized'''
        new = old.replace("workflow_stage: normalized", "workflow_stage: rejected")
        if old not in text:
            raise SystemExit("test statements item was not found")
        path.write_text(text.replace(old, new), encoding="utf-8")
        card = Path("knowledge/data/test/documents/normalized/item.yml")
        card.write_text(
            card.read_text(encoding="utf-8").replace(
                "workflow_stage: normalized",
                "workflow_stage: rejected",
            ),
            encoding="utf-8",
        )
        """,
    )
    path = root / "operations.yml"
    text = path.read_text(encoding="utf-8")
    addition = (
        "  fetch:\n"
        "    resources:\n"
        "      min_free_disk_bytes: 1000000000000000000000000000000\n"
        "      estimated_peak_disk_bytes: 0\n"
        "    commands:\n"
        "      - id: unavailable-heavy-fetch\n"
        f"        argv: [{sys.executable}, -c, \"raise SystemExit('must not run')\"]\n"
        "        working_directory: .\n"
        "        write_paths: [knowledge/data]\n"
        "        required: true\n"
        "  statements:\n"
        "    commands:\n"
        "      - id: process-ready-statements\n"
        f"        argv: [{sys.executable}, advance-statements.py]\n"
        "        working_directory: .\n"
        "        write_paths: [knowledge/data/test]\n"
        "        required: true\n"
    )
    path.write_text(
        text.replace("\nadapters:\n", f"\n{addition}adapters:\n"),
        encoding="utf-8",
    )


def add_grouped_human_decisions(root: Path) -> None:
    path = root / "knowledge" / "data" / "test" / "items.yml"
    text = path.read_text(encoding="utf-8")
    addition = (
        "  - id: TEST-BLOCKED-ACCESS\n"
        "    title: \"Нужен доступ\"\n"
        "    access: \"Доступ отсутствует.\"\n"
        "    status: blocked\n"
        "    workflow_stage: blocked\n"
        "    blocker_code: access_unavailable\n"
        "    automatic_attempts:\n"
        "      - \"Проверен основной URL.\"\n"
        "      - \"Проверен разрешённый альтернативный маршрут.\"\n"
        "  - id: TEST-BLOCKED-STORAGE\n"
        "    title: \"Нужно выбрать хранение\"\n"
        "    access: \"Внутренний материал.\"\n"
        "    status: blocked\n"
        "    workflow_stage: blocked\n"
        "    blocker_code: storage_not_permitted\n"
    )
    path.write_text(text + addition, encoding="utf-8")
    operations = root / "operations.yml"
    operations.write_text(
        operations.read_text(encoding="utf-8").replace(
            "stages:\n",
            "human_attention:\n  max_active_groups: 2\nstages:\n",
            1,
        ),
        encoding="utf-8",
    )


def make_pipeline_executor_violate_write_scope(root: Path) -> None:
    path = root / "operations.yml"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        f"          - {sys.executable}\n          - advance-content-selection.py",
        (
            f"          - {sys.executable}\n"
            "          - -c\n"
            "          - \"from pathlib import Path; "
            "Path('outside.txt').write_text('pipeline changed', encoding='utf-8')\""
        ),
    )
    path.write_text(text, encoding="utf-8")


def make_final_stage_leave_operational_blocker(root: Path) -> None:
    path = root / "operations.yml"
    text = path.read_text(encoding="utf-8")
    old = (
        "      - id: validate-complete-corpus\n"
        f"        argv: [{sys.executable}, -c, \"pass\"]"
    )
    new = (
        "      - id: validate-complete-corpus\n"
        f"        argv: [{sys.executable}, -c, "
        "\"from pathlib import Path; "
        "Path('knowledge/data/test/runtime-leak.yml').write_text('api_key=runtime-secret', "
        "encoding='utf-8')\"]"
    )
    if old not in text:
        raise AssertionError("Не найдена команда финальной проверки в тестовых настройках.")
    path.write_text(text.replace(old, new), encoding="utf-8")


def run(root: Path, *arguments: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "knowledge", "--operations", "operations.yml", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode != expected:
        raise AssertionError(
            f"Ожидался код {expected}, получен {result.returncode}.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def remove_stage_commands(root: Path, stage: str) -> None:
    """Strip a stage's registered commands from operations.yml so it has no executor."""
    path = root / "operations.yml"
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(rf"(?m)^  {re.escape(stage)}:\n(?:    .*\n)*")
    new_text, count = pattern.subn("", text, count=1)
    if count != 1:
        raise AssertionError(f"Не найден блок команд стадии {stage} в operations.yml.")
    path.write_text(new_text, encoding="utf-8")


def write_run_state(root: Path, **overrides: object) -> Path:
    """Write a self-consistent corpus-pipeline.json for --complete-global-stage tests."""
    state = {
        "contract_version": 1,
        "run_id": "test-run",
        "status": "paused_limit",
        "reason_code": "step_limit_reached",
        "started_at": "2026-09-01T00:00:00+00:00",
        "updated_at": "2026-09-01T00:00:00+00:00",
        "completed_at": None,
        "attempts": 1,
        "steps": 1,
        "available_task_count": 0,
        "blocked_task_count": 0,
        "blocker_codes": [],
        "human_decision_groups": [],
        "human_decision_group_count": 0,
        "human_decision_group_overflow": 0,
        "completed_global_stages": [],
        "resource_waiting": [],
        "active_executor": None,
        "queues": {name: [] for name in QUEUE_NAMES},
        "message": "Тестовое состояние.",
    }
    state.update(overrides)
    path = root / ".local" / "state" / "corpus-pipeline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        add_resource_deferred_fetch_and_statements_executor(root)
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        continued = run(root, "--run-pipeline", "--max-steps", "2", expected=10)
        state = json.loads(
            (root / ".local" / "state" / "corpus-pipeline.json").read_text(encoding="utf-8")
        )
        if "process-ready-statements" not in continued.stdout:
            raise AssertionError("Ресурсно недоступная ранняя очередь остановила готовую позднюю очередь.")
        if not any(
            item["queue"] == "fetch" and "disk_bytes_required=" in item["reason"]
            for item in state["resource_waiting"]
        ):
            raise AssertionError("Состояние не сохранило причину отложенной тяжёлой очереди.")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        add_grouped_human_decisions(root)
        reject_automated_work(root, keep_blocked=True)
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        run(root, "--run-pipeline", expected=20)
        state = json.loads(
            (root / ".local" / "state" / "corpus-pipeline.json").read_text(encoding="utf-8")
        )
        if state["blocked_task_count"] != 3:
            raise AssertionError("Группировка потеряла исходные элементы внешнего хвоста.")
        if (
            state["human_decision_group_count"] != 3
            or len(state["human_decision_groups"]) != 2
            or state["human_decision_group_overflow"] != 1
        ):
            raise AssertionError("Бюджет активных групп решений применён неверно.")
        if not all("action_required" in group for group in state["human_decision_groups"]):
            raise AssertionError("Группа внешнего решения не называет требуемое действие.")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        make_pipeline_executor_violate_write_scope(root)
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        failed = run(root, "--run-pipeline", expected=1)
        state = json.loads(
            (root / ".local" / "state" / "corpus-pipeline.json").read_text(encoding="utf-8")
        )
        if state["status"] != "failed" or state["reason_code"] != "execution_contract_error":
            raise AssertionError("Нарушение write_paths оставило проход в нетерминальном состоянии.")
        if "вне write_paths: outside.txt" not in state["message"] or "status: running" in failed.stdout:
            raise AssertionError("Отчёт не сохранил причину нарушения write_paths.")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)

        plan = run(root)
        for expected_line in (
            "- content_selection: 1",
            "- fetch: 3",
            "- statements: 1",
            "- semantic_review: 1",
            "- verification: 1",
            "- human_decision: 1",
            "- concepts: 1",
            "- impact_audit: 1",
            "- apply_changes: 1",
            "- corpus_validation: 1",
        ):
            if expected_line not in plan.stdout:
                raise AssertionError(f"В плане нет строки: {expected_line}")
        if "TEST-INDEX-ONLY-METADATA" in plan.stdout:
            raise AssertionError("Не выбранная единица index_only не должна образовывать массовую очередь.")
        if "TEST-V2-COMPLETE" not in plan.stdout or "внешняя сверка и актуальность снимка не записаны" not in plan.stdout:
            raise AssertionError("Legacy-единица без verification.yml не попала в очередь внешней сверки.")
        strict_legacy = subprocess.run(
            [sys.executable, str(VALIDATOR), "knowledge", "--strict-verification"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if (
            strict_legacy.returncode != 0
            or "legacy item has no verification.yml; external verification and freshness are not recorded"
            not in strict_legacy.stdout
        ):
            raise AssertionError("Строгий валидатор не сообщил о legacy-единице без внешней сверки.")
        legacy_item = root / "knowledge" / "data" / "test" / "documents" / "v2-complete" / "item.yml"
        legacy_item.write_text(
            legacy_item.read_text(encoding="utf-8")
            .replace("workflow_stage: source_checked", "item_contract_version: 2\nworkflow_stage: verification_assessed"),
            encoding="utf-8",
        )
        items_path = root / "knowledge" / "data" / "test" / "items.yml"
        items_path.write_text(
            items_path.read_text(encoding="utf-8")
            .replace("workflow_stage: source_checked\n            path: documents/v2-complete", "item_contract_version: 2\n            workflow_stage: verification_assessed\n            path: documents/v2-complete"),
            encoding="utf-8",
        )
        artifact = legacy_item.parent / "normalized.md"
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        write(
            legacy_item.parent / "verification.yml",
            f"""
            verification_contract_version: 1
            artifact: normalized.md
            hash:
              algorithm: sha256
              value: {digest}
            acquisition:
              method: user_provided
              recorded_at: 2026-09-06
            verification:
              method: no_source_comparison
              checked_at: 2026-09-06
              checked_by:
                role: corpus_maintainer
              scope:
                content: full_text
                metadata: []
              result:
                overall: unverified
                content_match: unverified
                scope_completeness: complete
                metadata:
                  locator: unverified
                  author: unverified
                  publication_date: unverified
              limitations:
                - Внешняя сверка не выполнена.
            """,
        )
        strict = subprocess.run(
            [sys.executable, str(VALIDATOR), "knowledge", "--strict-verification"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if strict.returncode != 0:
            raise AssertionError(f"Строгий валидатор не принял записанную проверку:\n{strict.stdout}{strict.stderr}")
        verified_plan = run(root)
        if "TEST-V2-COMPLETE" in verified_plan.stdout:
            raise AssertionError("Единица с verification.yml и verification_assessed осталась в очереди.")
        if (root / ".local").exists() or (root / "knowledge" / "index").exists():
            raise AssertionError("Планирование без параметров не должно записывать файлы.")

        paused = run(root, "--run-pipeline", "--max-steps", "1", expected=10)
        state_path = root / ".local" / "state" / "corpus-pipeline.json"
        state = state_path.read_text(encoding="utf-8")
        if '"status": "paused_limit"' not in state or '"available_task_count": 0' in state:
            raise AssertionError("Лимит попытки не сохранил незавершённый проход и полный хвост.")
        run_id_line = next(line for line in state.splitlines() if '"run_id"' in line)
        unavailable = run(root, "--run-pipeline", expected=11)
        resumed_state = state_path.read_text(encoding="utf-8")
        if '"status": "paused_resources"' not in resumed_state or run_id_line not in resumed_state:
            raise AssertionError("Следующая попытка не продолжила тот же проход.")
        if "status: completed" in paused.stdout or "status: completed" in unavailable.stdout:
            raise AssertionError("Управляемая пауза не должна называться завершением прохода.")

        run(root, "--rebuild-indexes", "--write-report")
        items_index = (root / "knowledge" / "index" / "items.yml").read_text(encoding="utf-8")
        statements_index = (root / "knowledge" / "index" / "statements.yml").read_text(encoding="utf-8")
        report = (root / ".local" / "reports" / "operations.md").read_text(encoding="utf-8")
        if "TEST-NORMALIZED" not in items_index or "TEST-001" not in statements_index:
            raise AssertionError("Пересобранные индексы не содержат исходные записи.")
        if "# Операционный отчёт корпуса" not in report:
            raise AssertionError("Локальный отчёт не записан.")
        validation = subprocess.run(
            [sys.executable, str(VALIDATOR), "knowledge"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if validation.returncode != 0:
            raise AssertionError(
                "Пересобранные индексы не проходят проверку структуры корпуса:\n"
                f"{validation.stdout}{validation.stderr}"
            )

        marker = root / "knowledge" / "data" / "test" / "marker.txt"
        if marker.exists():
            raise AssertionError("Команды нельзя выполнять без --run-commands.")
        run(root, "--run-commands")
        if marker.read_text(encoding="utf-8") != "ok":
            raise AssertionError("Явно разрешённая команда не выполнилась.")
        forbidden_write = run(root, "--run-commands", "--stage", "bad_write", expected=2)
        if "вне write_paths: outside.txt" not in forbidden_write.stderr:
            raise AssertionError("Изменение уже отслеживаемого файла вне write_paths не обнаружено.")
        ignored_write = run(root, "--run-commands", "--stage", "ignored_bad_write", expected=2)
        if "вне write_paths: .private/source.txt" not in ignored_write.stderr:
            raise AssertionError("Изменение игнорируемого файла вне write_paths не обнаружено.")

        adapter_marker = root / "knowledge" / "data" / "test" / "adapter-marker.yml"
        adapters = run(root, "--run-adapters", "--source", "TEST")
        if "TEST (builtin.local-file): changed" not in adapters.stdout or not adapter_marker.is_file():
            raise AssertionError("Исполняемый адаптер не вернул структурированный результат.")

        source_path = root / "knowledge" / "data" / "test" / "source.yml"
        source_path.write_text(
            source_path.read_text(encoding="utf-8").replace("adapter: builtin.local-file", "adapter: project.unknown"),
            encoding="utf-8",
        )
        unsupported = run(root, "--run-adapters")
        if "TEST (project.unknown): unsupported-adapter" not in unsupported.stdout:
            raise AssertionError("Неизвестный адаптер не получил явный статус.")
        source_path.write_text(
            source_path.read_text(encoding="utf-8").replace("adapter: project.unknown", "adapter: builtin.local-file"),
            encoding="utf-8",
        )
        operations_path = root / "operations.yml"
        operations_path.write_text(
            operations_path.read_text(encoding="utf-8") + "\ntoken: secret-value\n",
            encoding="utf-8",
        )
        secret = run(root, "--run-adapters", expected=2)
        if "поле с секретом" not in secret.stderr:
            raise AssertionError("Настройки с явным секретом не были отклонены.")
        operations_path.write_text(
            operations_path.read_text(encoding="utf-8").replace("\ntoken: secret-value\n", "\n"),
            encoding="utf-8",
        )
        operations_path.write_text(
            operations_path.read_text(encoding="utf-8").replace(
                "operations_version: 1",
                "operations_version: 1\nhuman_attention:\n  max_active_groups: 0",
            ),
            encoding="utf-8",
        )
        invalid_attention = run(root, expected=2)
        if "max_active_groups" not in invalid_attention.stderr:
            raise AssertionError("Недопустимый бюджет внимания не был отклонён.")
        operations_path.write_text(
            operations_path.read_text(encoding="utf-8").replace(
                "\nhuman_attention:\n  max_active_groups: 0",
                "",
            ),
            encoding="utf-8",
        )

        write(root / "knowledge" / "data" / "test" / "source-contact.md", "Контакт источника: +7 (999) 123-45-67\n")
        write(root / "knowledge" / "data" / "test" / "leak.md", "api_key=super-secret-value\n")
        write(root / "knowledge" / "data" / "test" / "leak.local.md", "api_key=local-secret-value\n")
        source_path.write_text(
            source_path.read_text(encoding="utf-8") + "contact: source@example.test\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        marker.unlink()
        checked = run(root, "--operational-check", "--run-commands", expected=1)
        if "блокеры доступа: 1" not in checked.stdout or "super-secret-value" in checked.stdout:
            raise AssertionError("Операционная проверка не обезличила блокер доступа.")
        if marker.exists():
            raise AssertionError("Блокер доступа не остановил команду до записи.")
        if "предупреждения качества: 1" not in checked.stdout:
            raise AssertionError("Содержательные контактные данные не стали предупреждением качества.")

        write(
            root / "knowledge" / "operational-check.yml",
            """
            rules:
              - kind: access-secret
                path: data/test/leak.md
                action: suppress
                reason: "Тестовый маркер ложного срабатывания."
            """,
        )
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        suppressed = run(
            root,
            "--operational-check",
            "--operational-policy",
            "knowledge/operational-check.yml",
        )
        if "блокеры доступа: 0" not in suppressed.stdout or "подавлено правилом или метаданными: 2" not in suppressed.stdout:
            raise AssertionError("Документированное подавление не применилось.")

        items_path = root / "knowledge" / "data" / "test" / "items.yml"
        items_path.write_text(
            items_path.read_text(encoding="utf-8").replace(
                "path: documents/normalized",
                "path: ../outside",
                1,
            ),
            encoding="utf-8",
        )
        rejected = run(root, expected=2)
        if "относительным путём внутри корпуса" not in rejected.stderr:
            raise AssertionError("Выход за пределы источника не был отклонён.")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        statements = (
            root
            / "knowledge"
            / "data"
            / "test"
            / "documents"
            / "v2-complete"
            / "statements.yml"
        )
        statements.write_text(
            statements.read_text(encoding="utf-8")
            .replace("semantic_review: passed", "semantic_review: failed")
            .replace("strong_review: not_required", "strong_review: pending"),
            encoding="utf-8",
        )
        plan = run(root)
        if "- strong_review: 1" not in plan.stdout or "- semantic_review: 2" in plan.stdout:
            raise AssertionError("Спорный случай обычной модели не направлен на усиленную проверку.")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        state_path = root / ".local" / "state" / "corpus-pipeline.json"
        lock_path = state_path.with_name(f"{state_path.name}.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = run(root, "--run-pipeline", expected=2)
        if "уже выполняется другим процессом" not in locked.stderr:
            raise AssertionError("Одновременный исполнитель не был остановлен блокировкой состояния.")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        executor_path = root / "advance-content-selection.py"
        executor_path.write_text(
            (
                "import sys\nsys.stdout.write('x' * 131072)\nsys.stdout.flush()\n"
                "import time\ntime.sleep(1)\n"
                + executor_path.read_text(encoding="utf-8")
            ),
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        process = subprocess.Popen(
            [sys.executable, str(SCRIPT), "knowledge", "--operations", "operations.yml", "--run-pipeline", "--max-steps", "1"],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        state_path = root / ".local" / "state" / "corpus-pipeline.json"
        for _ in range(20):
            if state_path.is_file():
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if isinstance(state.get("active_executor"), dict):
                    break
            time.sleep(0.1)
        else:
            process.kill()
            raise AssertionError("Долгая команда не сохранила активного исполнителя.")
        active = state["active_executor"]
        if active.get("queue") != "content_selection" or not active.get("heartbeat_at"):
            process.kill()
            raise AssertionError("Состояние не сохранило очередь и heartbeat активной команды.")
        stdout, stderr = process.communicate(timeout=10)
        if process.returncode != 10:
            raise AssertionError(f"Долгая команда не завершила ожидаемую попытку.\n{stdout}\n{stderr}")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        state_path = root / ".local" / "state" / "corpus-pipeline.json"
        write(
            state_path,
            """
            {
              "contract_version": 1,
              "run_id": "interrupted-run",
              "status": "running",
              "reason_code": "attempt_started",
              "started_at": "2026-07-31T10:00:00+00:00",
              "updated_at": "2026-07-31T10:00:00+00:00",
              "completed_at": null,
              "attempts": 1,
              "steps": 0,
              "available_task_count": 1,
              "blocked_task_count": 0,
              "blocker_codes": [],
              "human_decision_groups": [],
              "human_decision_group_count": 0,
              "human_decision_group_overflow": 0,
              "completed_global_stages": [],
              "resource_waiting": [],
              "active_executor": {"pid": 999999, "queue": "content_selection", "command_id": "lost", "started_at": "2026-07-31T10:00:00+00:00", "heartbeat_at": "2026-07-31T10:00:00+00:00"},
              "queues": {"content_selection": [], "fetch": [], "transcribe": [], "normalize": [], "statements": [], "traceability": [], "semantic_review": [], "strong_review": [], "corroboration": [], "source_check": [], "concepts": [], "impact_audit": [], "apply_changes": [], "corpus_validation": [], "human_decision": []},
              "message": "Устаревшее состояние."
            }
            """,
        )
        reconciled = run(root, "--reconcile-state", expected=10)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state["status"] != "paused_limit" or state["reason_code"] != "executor_interrupted":
            raise AssertionError("Брошенное running-состояние не переведено в возобновляемую паузу.")
        if "активный исполнитель: нет" not in reconciled.stdout:
            raise AssertionError("Сверка не показала отсутствие живого исполнителя.")
        state["status"] = "running"
        state["reason_code"] = "attempt_started"
        state["active_executor"] = {
            "pid": os.getpid(),
            "queue": "content_selection",
            "command_id": "unknown-identity",
            "started_at": "2026-07-31T10:00:00+00:00",
            "heartbeat_at": "2026-07-31T10:00:00+00:00",
        }
        state_path.write_text(json.dumps(state), encoding="utf-8")
        unknown_identity = run(root, "--reconcile-state", expected=1)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state["reason_code"] != "executor_identity_unknown" or "Автоматическое продолжение запрещено" not in state["message"]:
            raise AssertionError("Живой PID без надёжной идентичности не остановил автоматическое продолжение.")
        if "status: failed" not in unknown_identity.stdout:
            raise AssertionError("Сверка не показала терминальное состояние неизвестного исполнителя.")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        items_path = root / "knowledge" / "data" / "test" / "items.yml"
        items_path.write_text(
            items_path.read_text(encoding="utf-8").replace(
                "blocker_code: owner_decision_required",
                "blocker_code: source_unavailable\n    automatic_attempts:\n      - \"Одна попытка DNS.\"",
            ),
            encoding="utf-8",
        )
        invalid = run(root, expected=2)
        if "двух разных автоматических попыток доступа" not in invalid.stderr:
            raise AssertionError("Одиночная неудача доступа была принята как внешний блокер.")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        reject_automated_work(root, keep_blocked=True)
        waiting = run(root, "--run-pipeline", expected=20)
        state = json.loads(
            (root / ".local" / "state" / "corpus-pipeline.json").read_text(encoding="utf-8")
        )
        if state["status"] != "waiting_external" or state["blocker_codes"] != [
            "owner_decision_required"
        ]:
            raise AssertionError("Внешний блокер не сохранился в состоянии прохода.")
        if "blocker_code=owner_decision_required" not in waiting.stdout:
            raise AssertionError("Отчёт не показывает машиночитаемый код внешнего блокера.")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        reject_automated_work(root, keep_blocked=False)
        run(root, "--run-pipeline", "--max-steps", "2", expected=10)
        state_path = root / ".local" / "state" / "corpus-pipeline.json"
        paused = json.loads(state_path.read_text(encoding="utf-8"))
        if paused["completed_global_stages"] != ["concepts", "impact_audit"]:
            raise AssertionError("Пауза не сохранила завершённые глобальные стадии.")
        resumed = run(root, "--run-pipeline")
        first = json.loads(state_path.read_text(encoding="utf-8"))
        if first["run_id"] != paused["run_id"]:
            raise AssertionError("Продолжение глобальных стадий создало новый проход.")
        if "check-concepts" in resumed.stdout or "audit-impact" in resumed.stdout:
            raise AssertionError("Продолжение повторно запустило завершённые глобальные стадии.")
        if first["status"] != "completed" or first["available_task_count"] != 0:
            raise AssertionError("Пустой хвост не завершил проход.")
        if first["completed_global_stages"] != [
            "concepts",
            "impact_audit",
            "apply_changes",
            "corpus_validation",
        ]:
            raise AssertionError("Проход завершился без обязательных глобальных стадий.")
        run(root, "--run-pipeline")
        second = json.loads(state_path.read_text(encoding="utf-8"))
        if second["status"] != "completed" or second["run_id"] == first["run_id"]:
            raise AssertionError("После завершения не был создан новый проход.")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        add_no_progress_fetch_executor(root)
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        stalled = run(root, "--run-pipeline", expected=1)
        state = json.loads(
            (root / ".local" / "state" / "corpus-pipeline.json").read_text(encoding="utf-8")
        )
        if state["reason_code"] != "no_progress" or "не изменил машиночитаемую очередь" not in state["message"]:
            raise AssertionError(
                "Исполнитель без прогресса текущей стадии не остановил проход.\n"
                f"state={state}\nstdout={stalled.stdout}\nstderr={stalled.stderr}"
            )

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        reject_automated_work(root, keep_blocked=False)
        make_final_stage_leave_operational_blocker(root)
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        failed = run(root, "--run-pipeline", expected=1)
        state = json.loads(
            (root / ".local" / "state" / "corpus-pipeline.json").read_text(encoding="utf-8")
        )
        if state["status"] != "failed" or state["reason_code"] != "postflight_failed":
            raise AssertionError("Итоговый операционный блокер не отменил completed.")
        if "блокеры доступа: 1" not in failed.stdout or "runtime-secret" in failed.stdout:
            raise AssertionError("Итоговая проверка не обезличила операционный блокер.")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        statements = (
            root
            / "knowledge"
            / "data"
            / "test"
            / "documents"
            / "v2-complete"
            / "statements.yml"
        )
        statements.write_text(
            statements.read_text(encoding="utf-8").replace(
                "statement_contract_version: 2",
                "statement_contract_version: 99",
            ),
            encoding="utf-8",
        )
        failed = run(root, "--run-pipeline", expected=1)
        state = json.loads(
            (root / ".local" / "state" / "corpus-pipeline.json").read_text(encoding="utf-8")
        )
        if state["reason_code"] != "preflight_failed" or "ошибка договора" not in failed.stdout:
            raise AssertionError("Обязательная предзапусковая проверка не сохранила отказ прохода.")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        state_path = root / ".local" / "state" / "corpus-pipeline.json"
        write(state_path, "{not-json")
        corrupt = run(root, "--run-pipeline", expected=2)
        if "Не удалось прочитать состояние прохода" not in corrupt.stderr:
            raise AssertionError("Повреждённое состояние прохода не было отклонено.")

    print("Проверки операционного контура корпуса прошли.")
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        configure_v2_adapter(root)
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)

        missing_profile = run(root, "--run-adapters", "--source", "TEST")
        if "project.v2, probe): profile-missing" not in missing_profile.stdout:
            raise AssertionError("probe did not report the missing local profile precisely")
        if (root / "knowledge" / "data" / "test" / "v2-fetch.yml").exists():
            raise AssertionError("fetch ran despite a failed probe")
        if (root / ".local" / "authorize-called").exists():
            raise AssertionError("interactive authorization started automatically")

        (root / ".local").mkdir(parents=True, exist_ok=True)
        (root / ".local" / "profile-ready").write_text("ready", encoding="utf-8")
        fetched = run(root, "--run-adapters", "--source", "TEST")
        if "project.v2, probe): ready" not in fetched.stdout or "project.v2): changed" not in fetched.stdout:
            raise AssertionError("ready probe did not permit the version 2 fetch")
        if not (root / "knowledge" / "data" / "test" / "v2-fetch.yml").is_file():
            raise AssertionError("version 2 fetch did not create its declared artifact")

        verification_path = root / "knowledge" / "data" / "test" / "documents" / "statements" / "verification.yml"
        write(verification_path, "preserved: true\n")
        before = verification_path.read_text(encoding="utf-8")
        unavailable = run(
            root,
            "--run-adapters",
            "--adapter-operation",
            "verify",
            "--source",
            "TEST",
        )
        if "project.v2, verify): access-limited" not in unavailable.stdout:
            raise AssertionError("verify did not preserve the precise access-limited result")
        if verification_path.read_text(encoding="utf-8") != before:
            raise AssertionError("failed verification changed the saved snapshot verification")

        explicit_authorize = run(
            root,
            "--run-adapters",
            "--adapter-operation",
            "authorize",
            "--source",
            "TEST",
        )
        if "project.v2, authorize): ready" not in explicit_authorize.stdout:
            raise AssertionError("explicit interactive authorization did not run")
        if not (root / ".local" / "authorize-called").is_file():
            raise AssertionError("authorize operation did not leave its local marker")

        (root / ".local" / "leak-secret").write_text("on", encoding="utf-8")
        sanitized = run(
            root,
            "--run-adapters",
            "--adapter-operation",
            "probe",
            "--source",
            "TEST",
        )
        if "TOP-SECRET" in sanitized.stdout or "TOP-SECRET" in sanitized.stderr:
            raise AssertionError("adapter secret leaked into the report")
        if "token=[скрыто]" not in sanitized.stdout:
            raise AssertionError("adapter secret was not replaced with a safe marker")

        operations_path = root / "operations.yml"
        operations_path.write_text(
            operations_path.read_text(encoding="utf-8").replace(
                "project.v2:\n    contract_version: 2",
                "project.v2:\n    contract_version: 9",
            ),
            encoding="utf-8",
        )
        unsupported_version = run(
            root,
            "--run-adapters",
            "--source",
            "TEST",
            expected=2,
        )
        if "Неподдерживаемая версия договора адаптера" not in unsupported_version.stderr:
            raise AssertionError("unknown adapter contract version was not rejected")

    # --complete-global-stage: successful manual close of a stage without a configured
    # executor advances the queue, and a resumed --run-pipeline finishes the remaining
    # (still project-executed) global stages without rerunning the manually closed one.
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        reject_automated_work(root, keep_blocked=False)
        remove_stage_commands(root, "concepts")
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        write(root / "concepts-evidence.md", "Концепции обновлены вручную.\n")

        stalled = run(root, "--run-pipeline", expected=11)
        state_path = root / ".local" / "state" / "corpus-pipeline.json"
        before = json.loads(state_path.read_text(encoding="utf-8"))
        if before["status"] != "paused_resources" or "concepts" not in [
            entry["queue"] for entry in before["resource_waiting"]
        ]:
            raise AssertionError("Стадия без исполнителя не осталась в ожидании ресурсов.")

        closed = run(
            root,
            "--complete-global-stage",
            "concepts",
            "--evidence",
            "concepts-evidence.md",
            "--note",
            "Закрыто вручную для проверки.",
        )
        if "закрыта вручную" not in closed.stdout:
            raise AssertionError("Успешное закрытие стадии не подтверждено в выводе.")
        after = json.loads(state_path.read_text(encoding="utf-8"))
        if "concepts" not in after["completed_global_stages"]:
            raise AssertionError("Ручное закрытие не добавило стадию в completed_global_stages.")
        completion = after.get("global_stage_completions", {}).get("concepts")
        if (
            not completion
            or completion["completed_by"] != "manual"
            or completion["evidence"] != ["concepts-evidence.md"]
            or completion["note"] != "Закрыто вручную для проверки."
        ):
            raise AssertionError("Запись global_stage_completions не сохранила ожидаемые поля.")
        if (
            after["run_id"] != before["run_id"]
            or after["status"] != before["status"]
            or after["reason_code"] != before["reason_code"]
            or after["attempts"] != before["attempts"]
            or after["steps"] != before["steps"]
        ):
            raise AssertionError("Ручное закрытие изменило поля, которые должны оставаться неизменными.")

        finished = run(root, "--run-pipeline")
        final_state = json.loads(state_path.read_text(encoding="utf-8"))
        if final_state["status"] != "completed":
            raise AssertionError("Проход не завершился после ручного закрытия единственной незакрытой стадии.")
        if "check-concepts" in finished.stdout:
            raise AssertionError("Ручное закрытие не должно запускать команду закрытой стадии.")
        if final_state["completed_global_stages"] != [
            "concepts",
            "impact_audit",
            "apply_changes",
            "corpus_validation",
        ]:
            raise AssertionError("Продолжение не закрыло оставшиеся глобальные стадии проектными командами.")
        if "concepts" not in final_state.get("global_stage_completions", {}):
            raise AssertionError("Итоговое состояние потеряло след ручного закрытия стадии.")

    # --complete-global-stage: a stage with a registered command must never be closed manually.
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        write(root / "evidence.md", "x\n")
        rejected = run(
            root,
            "--complete-global-stage",
            "concepts",
            "--evidence",
            "evidence.md",
            expected=2,
        )
        if "зарегистрирован исполнитель" not in rejected.stderr:
            raise AssertionError("Стадия с настроенной командой была закрыта вручную.")

    # --complete-global-stage: refuse to close a stage while the primary queue circuit is not empty.
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        remove_stage_commands(root, "concepts")
        write_run_state(root)
        write(root / "evidence.md", "x\n")
        nonempty = run(
            root,
            "--complete-global-stage",
            "concepts",
            "--evidence",
            "evidence.md",
            expected=2,
        )
        if "Первичный контур" not in nonempty.stderr:
            raise AssertionError("Непустой первичный контур не остановил ручное закрытие.")

    # --complete-global-stage: refuse to close a global stage out of order.
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        reject_automated_work(root, keep_blocked=False)
        remove_stage_commands(root, "impact_audit")
        write_run_state(root)
        write(root / "evidence.md", "x\n")
        out_of_order = run(
            root,
            "--complete-global-stage",
            "impact_audit",
            "--evidence",
            "evidence.md",
            expected=2,
        )
        if "Нарушен порядок" not in out_of_order.stderr or "concepts" not in out_of_order.stderr:
            raise AssertionError("Закрытие стадии не по порядку не было отклонено.")

    # --complete-global-stage: refuse to close a stage when --evidence does not exist on disk.
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        reject_automated_work(root, keep_blocked=False)
        remove_stage_commands(root, "concepts")
        write_run_state(root)
        missing_evidence = run(
            root,
            "--complete-global-stage",
            "concepts",
            "--evidence",
            "no-such-artifact.md",
            expected=2,
        )
        if "не существует" not in missing_evidence.stderr:
            raise AssertionError("Отсутствующий на диске --evidence не был отклонён.")

    # --complete-global-stage: a repeated call for an already closed stage is a safe no-op.
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        reject_automated_work(root, keep_blocked=False)
        remove_stage_commands(root, "concepts")
        write_run_state(root)
        write(root / "concepts-evidence.md", "Готово.\n")
        run(root, "--complete-global-stage", "concepts", "--evidence", "concepts-evidence.md")
        state_path = root / ".local" / "state" / "corpus-pipeline.json"
        before_repeat = state_path.read_text(encoding="utf-8")
        repeated = run(root, "--complete-global-stage", "concepts", "--evidence", "concepts-evidence.md")
        after_repeat = state_path.read_text(encoding="utf-8")
        if "уже закрыта" not in repeated.stdout:
            raise AssertionError("Повторное закрытие уже закрытой стадии не сообщило об идемпотентности.")
        if before_repeat != after_repeat:
            raise AssertionError("Повторное закрытие уже закрытой стадии изменило состояние прохода.")

    # --complete-global-stage: refuse to touch a run that already finished (status=completed).
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        remove_stage_commands(root, "concepts")
        write_run_state(
            root,
            status="completed",
            reason_code="all_queues_empty",
            completed_at="2026-09-01T00:00:00+00:00",
        )
        write(root / "evidence.md", "x\n")
        completed_rejected = run(
            root,
            "--complete-global-stage",
            "concepts",
            "--evidence",
            "evidence.md",
            expected=2,
        )
        if "completed" not in completed_rejected.stderr:
            raise AssertionError("Закрытие стадии для завершённого прохода не было отклонено.")

    # read_run_state: reject global_stage_completions naming a stage outside completed_global_stages.
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_corpus(root)
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        write_run_state(
            root,
            completed_global_stages=[],
            global_stage_completions={
                "concepts": {
                    "completed_by": "manual",
                    "completed_at": "2026-09-01T00:00:00+00:00",
                    "evidence": ["concepts-evidence.md"],
                    "note": None,
                }
            },
        )
        invalid_completion = run(root, "--reconcile-state", expected=2)
        if "global_stage_completions" not in invalid_completion.stderr:
            raise AssertionError("Некорректная запись global_stage_completions не была отклонена.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
