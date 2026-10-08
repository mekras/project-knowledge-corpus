#!/usr/bin/env python3
"""Проверить допуск материалов и основания решений через публичные команды."""

from __future__ import annotations

import hashlib
import json
import runpy
import subprocess
import sys
import tempfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
VALIDATOR = REPO / ".apm/skills/kc-inventory/scripts/validate-corpus-layout.py"
CONTROLLER = REPO / ".apm/skills/kc-pipeline/scripts/run-corpus-operations.py"


def put(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def policy(action: str = "prohibit") -> dict:
    return {"version": 1, "default": "require_approval", "rules": [
        {"id": "external", "origins": ["external_material"], "action": "allow"},
        {"id": "dialogue", "origins": ["working_dialogue"], "action": action},
    ]}


def corpus(project: Path, admission: dict | None = None) -> tuple[Path, dict, dict]:
    root = project / "knowledge"
    contract = {"contract_version": 1, "tracked_data": {"root": "data"},
                "local_data": {}, "source_units": {}}
    if admission is not None:
        contract["source_admission"] = admission
    source = {"id": "EXAMPLE", "slug": "example", "title": "Example source",
              "access": {"default": "Open fixture."}, "status": "approved",
              "carrier_type": "document", "source_kind": "reference",
              "adapter": "fixture.adapter", "reliability": "fixture", "refresh_policy": "manual",
              "provenance": {"origin": "external_material", "locator": "https://example.org/doc"},
              "admission": {"rule": "external"}}
    put(root / "corpus.yml", contract)
    put(root / "catalog.yml", {"sources": [{"id": "EXAMPLE", "title": source["title"], "path": "data/example"}]})
    put(root / "data/example/source.yml", source)
    put(root / "data/example/items.yml", {"items": []})
    return root, contract, source


def decision(project: Path, *, scope: dict | None = None, **changes: object) -> tuple[dict, dict]:
    record = {"status": "accepted", "decided_by": "Project owner", "decided_at": "2026-10-08",
              "scope": scope or {"sources": ["EXAMPLE"], "origins": ["working_dialogue"], "concepts": ["operating-mode"]},
              "decision": "Approve the stated source or concept in this scope."}
    record.update(changes)
    path = project / "docs/decisions/example.yml"
    put(path, record)
    return {"ref": "docs/decisions/example.yml", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}, record


def concept(root: Path, evidence: object, *, version: int = 2) -> dict:
    value = {"id": "operating-mode", "primary": "Режим работы", "definition": "Набор настроек приложения.",
             "boundaries": {"includes": ["Настройки поведения."], "excludes": ["Профиль пользователя."]},
             "authority": {"type": "project_decision", "ref": "docs/decisions/example.yml"},
             "defined_by": [], "decision": evidence}
    put(root / "concepts.yml", {"concept_contract_version": version, "concepts": [value]})
    return value


def check(root: Path, expected: str | None = None, *flags: str) -> dict:
    result = subprocess.run([sys.executable, str(VALIDATOR), str(root), "--project-root", str(root.parent),
                             "--output", "json", *flags], capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise AssertionError(f"Validator crashed: {result.stderr}")
    report = json.loads(result.stdout)
    errors = "\n".join(report["contract_errors"])
    if expected is None and result.returncode:
        raise AssertionError(errors)
    if expected is not None and (not result.returncode or expected not in errors):
        raise AssertionError(f"Expected {expected!r}, got {errors!r}")
    return report


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        root, _, _ = corpus(base / "legacy")
        report = check(root)
        assert any("admission is unverified" in warning for warning in report["contract_warnings"])
        check(root, "source_admission is not configured", "--strict-admission")
        check(root, "source_admission is not configured", "--admission-only")

        root, contract, source = corpus(base / "allow", policy())
        check(root, None, "--strict-admission")
        check(root, None, "--admission-only")
        bounded = policy()
        bounded["rules"][0]["locator_prefixes"] = ["https://example.org/"]
        contract["source_admission"] = bounded
        put(root / "corpus.yml", contract)
        check(root)
        source["provenance"]["locator"] = "https://example.org.evil.test/doc"
        put(root / "data/example/source.yml", source)
        check(root, "does not authorize")
        source["provenance"]["locator"] = "https://example.org/doc"
        put(root / "data/example/source.yml", source)
        source["admission"] = {"rule": "dialogue"}
        put(root / "data/example/source.yml", source)
        check(root, "does not authorize")
        source["admission"] = {"rule": ["external"]}
        put(root / "data/example/source.yml", source)
        check(root, "does not authorize")

        # Переименование разговора и метка одобрения не отменяют запрет.
        source.update(source_kind="decision_record", copy_policy="full_copy_allowed",
                      provenance={"origin": "working_dialogue", "locator": "session:example"},
                      admission={"rule": "external"})
        put(root / "data/example/source.yml", source)
        check(root, "source admission prohibited")
        evidence, _ = decision(root.parent)
        source["admission"] = {"decision": evidence}
        put(root / "data/example/source.yml", source)
        check(root, "source admission prohibited")

        root, contract, source = corpus(base / "approval", policy("require_approval"))
        source["provenance"] = {"origin": "working_dialogue", "locator": "session:example"}
        put(root / "data/example/source.yml", source)
        check(root, "does not authorize")
        evidence, record = decision(root.parent)
        source["admission"] = {"decision": evidence}
        put(root / "data/example/source.yml", source)
        check(root)
        path = root.parent / evidence["ref"]
        path.write_text("---\n" + json.dumps(record) + "\n---\n# Approved decision\n", encoding="utf-8")
        evidence["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        put(root / "data/example/source.yml", source)
        check(root)
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        evidence["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        put(root / "data/example/source.yml", source)
        check(root)
        path.write_text(path.read_text() + "Changed decision.\n", encoding="utf-8")
        check(root, "hash mismatch")

        for name, changes, expected in [
            ("draft", {"status": "proposed"}, "must be accepted"),
            ("no-owner", {"decided_by": ""}, "name decided_by"),
            ("no-decision", {"decision": ""}, "describe the accepted decision"),
            ("no-date", {"decided_at": "not-a-date"}, "ISO decided_at"),
            ("wrong-source", {"scope": {"sources": ["OTHER"], "origins": ["working_dialogue"]}}, "sources subject"),
            ("wrong-origin", {"scope": {"sources": ["EXAMPLE"], "origins": ["external_material"]}}, "provenance origin"),
        ]:
            root, _, source = corpus(base / name, policy("require_approval"))
            evidence, _ = decision(root.parent, **changes)
            source.update(provenance={"origin": "working_dialogue", "locator": "session:example"}, admission={"decision": evidence})
            put(root / "data/example/source.yml", source)
            check(root, expected)

        root, _, source = corpus(base / "paths", policy("require_approval"))
        evidence, _ = decision(root.parent)
        source.update(provenance={"origin": "working_dialogue", "locator": "session:example"}, admission={"decision": evidence})
        for ref, expected in [("../other.yml", "without traversal"), ("knowledge/corpus.yml", "outside the corpus"),
                              ("docs/missing.yml", "does not exist")]:
            evidence["ref"] = ref
            put(root / "data/example/source.yml", source)
            check(root, expected)

        for name, bad_policy, expected in [
            ("null", None, "mapping with version 1"),
            ("bad-default", {"version": 1, "default": [], "rules": []}, "default must be"),
            ("overlap", {"version": 1, "default": "prohibit", "rules": [
                {"id": "a", "origins": ["working_dialogue"], "action": "allow"},
                {"id": "b", "origins": ["working_dialogue"], "action": "prohibit"}]}, "overlapping origins"),
            ("unknown", {"version": 1, "default": "prohibit", "rules": [
                {"id": "a", "origins": ["unknown"], "action": "allow"}]}, "unknown provenance cannot"),
        ]:
            root, contract, _ = corpus(base / name)
            contract["source_admission"] = bad_policy
            put(root / "corpus.yml", contract)
            check(root, expected)

        # Запрещённая единица не скрывается в разрешённом источнике или индексе.
        root, _, source = corpus(base / "unit", policy())
        item = {"id": "EXAMPLE-ITEM", "title": "Unit", "access": "Open.", "status": "active", "workflow_stage": "indexed"}
        unit = root / "data/example/documents/unit/item.yml"
        put(root / "data/example/items.yml", {"items": [item]})
        put(unit, item)
        check(root)
        item.update(provenance={"origin": "working_dialogue", "locator": "session:example"}, admission={"rule": "external"})
        put(unit, item)
        check(root, "source admission prohibited")
        check(root, "source admission prohibited", "--admission-only")
        put(root / "data/example/items.yml", {"items": [item]})
        put(unit, {**item, "provenance": source["provenance"], "admission": source["admission"]})
        check(root, "provenance origin differs")

        # Понятие получает принятое решение без создания источника из разговора.
        root, _, _ = corpus(base / "concept", policy())
        evidence, _ = decision(root.parent)
        value = concept(root, evidence)
        check(root, None, "--strict-concepts")
        assert not (root / "data/working-dialogue").exists()
        concept(root, evidence, version=1)
        check(root, "requires concept contract version 2")
        concept(root, None)
        check(root, "empty defined_by requires")
        concept(root, "made-up-decision")
        check(root, "decision must contain")
        evidence, _ = decision(root.parent, scope={"concepts": ["another-concept"]})
        concept(root, evidence)
        check(root, "concepts subject")
        evidence, _ = decision(root.parent)
        value = concept(root, evidence)
        value["authority"]["ref"] = "another-record"
        put(root / "concepts.yml", {"concept_contract_version": 2, "concepts": [value]})
        check(root, "same project_decision")

        project = base / "проект с пробелами"
        root, _, source = corpus(project, policy())
        evidence, _ = decision(project)
        concept(root, evidence)
        (project / "nested").mkdir()
        nested = project / "nested/knowledge"
        root.rename(nested)
        check(nested, None, "--project-root", str(project))
        # Символическая ссылка не расширяет границу проекта для записи решения.
        other_evidence, _ = decision(base / "other-project")
        link = project / "docs/decisions/link.yml"
        link.symlink_to(base / "other-project" / other_evidence["ref"])
        concept(nested, {"ref": "docs/decisions/link.yml", "sha256": other_evidence["sha256"]})
        check(nested, "inside the project", "--project-root", str(project))

        result = subprocess.run([sys.executable, str(VALIDATOR), str(nested), "--admission-only", "--operational"],
                                capture_output=True, text=True)
        assert result.returncode == 2 and "cannot be combined" in result.stderr

        # Контроллер отказывает до записи состояния, индексов и вызова исполнителей.
        helpers = runpy.run_path(str(REPO / "tools/test-corpus-operations.py"))
        project = base / "controller"
        helpers["build_corpus"](project)
        root = project / "knowledge"
        with (root / "corpus.yml").open("a", encoding="utf-8") as stream:
            stream.write("\nsource_admission: " + json.dumps(policy()) + "\n")
        with (root / "data/test/source.yml").open("a", encoding="utf-8") as stream:
            stream.write("\nprovenance: {origin: working_dialogue, locator: 'session:example'}\nadmission: {rule: external}\n")
        with (root / "data/test-index-only/source.yml").open("a", encoding="utf-8") as stream:
            stream.write("\nprovenance: {origin: external_material, locator: 'https://example.org/index'}\nadmission: {rule: external}\n")
        before = {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}
        result = subprocess.run([sys.executable, str(CONTROLLER), "knowledge", "--operations", "operations.yml", "--run-pipeline"],
                                cwd=project, capture_output=True, text=True)
        assert result.returncode == 2 and "Допуск источников" in result.stderr, result.stderr
        after = {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}
        assert before == after, "Rejected controller run changed the project"
        source_path = root / "data/test/source.yml"
        source_path.write_text(source_path.read_text().replace("working_dialogue", "external_material"), encoding="utf-8")
        helpers["run"](project, "--rebuild-indexes")

    print("Проверки допуска материалов и проектных решений прошли.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
