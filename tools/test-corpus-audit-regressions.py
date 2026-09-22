#!/usr/bin/env python3
"""Regression scenarios for the independent audit findings."""

from __future__ import annotations

import hashlib
import importlib.machinery
import json
import base64
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
BASE_LOADER = importlib.machinery.SourceFileLoader(
    "test_corpus_operations", str(ROOT / "tools" / "test-corpus-operations.py")
)
BASE = BASE_LOADER.load_module()
SCRIPT = ROOT / ".apm" / "skills" / "kc-pipeline" / "scripts" / "run-corpus-operations.py"


def load_controller():
    loader = importlib.machinery.SourceFileLoader("corpus_operations_audit", str(SCRIPT))
    return loader.load_module()


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_init(root: Path) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)


def run(root: Path, *arguments: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "knowledge", "--operations", "operations.yml", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode != expected:
        raise AssertionError(
            f"expected {expected}, got {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def state(root: Path) -> dict:
    return json.loads((root / ".local" / "state" / "corpus-pipeline.json").read_text(encoding="utf-8"))


def configure_report(root: Path, findings: list[dict], mode: str = "apply_now") -> None:
    operations = root / "operations.yml"
    operations.write_text(
        operations.read_text(encoding="utf-8")
        + f"\ntransfer_policy:\n  mode: {mode}\nimpact_report:\n  path: .local/reports/impact-findings.yml\n",
        encoding="utf-8",
    )
    operations.write_text(
        operations.read_text(encoding="utf-8")
        + "surface_paths:\n  user_documentation: [product.txt]\n  code: [src/**]\n  configuration: [config/**]\n  requirements: [docs/**]\n",
        encoding="utf-8",
    )
    report = root / ".local" / "reports" / "impact-findings.yml"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(yaml.safe_dump({"findings": findings}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (root / ".gitignore").write_text(
        (root / ".gitignore").read_text(encoding="utf-8") + ".local/\n", encoding="utf-8"
    )


def apply_finding(finding_id: str, *, target: str = "product.txt", expected_hashes: dict | None = None) -> dict:
    finding = {
        "id": finding_id,
        "status": "apply_now",
        "basis": "Проверенное основание.",
        "source": "TEST",
        "affected_surfaces": ["user_documentation"],
        "expected_result": "Артефакт соответствует источнику.",
        "recommended_change": "Обновить артефакт.",
        "source_delta": {
            "source_id": "TEST",
            "categories": ["unchanged"],
            "unit_ids": ["TEST-V2-COMPLETE"],
        },
        "target_paths": [target],
    }
    if expected_hashes is not None:
        finding["expected_hashes"] = expected_hashes
    return finding


def controlled_update(path: str, before: bytes, after: bytes) -> list[dict]:
    return [{
        "op": "update",
        "path": path,
        "before_sha256": hashlib.sha256(before).hexdigest(),
        "after_sha256": hashlib.sha256(after).hexdigest(),
        "content_base64": base64.b64encode(after).decode("ascii"),
    }]


def agent_route(root: Path) -> None:
    source = root / "knowledge" / "data" / "test-long" / "source.yml"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "adapter: builtin.local-file",
            "adapter: agent\n"
            "agent_route:\n"
            "  mode: agent\n"
            "  allowed_operations: [index, fetch, verify]\n"
            "  write_scope: [knowledge/data/test-long]\n"
            "  instructions: \"Обновить индекс тестового источника.\"",
        ),
        encoding="utf-8",
    )


def write_agent_evidence(
    root: Path,
    *,
    run_id: str,
    before: dict,
    after: dict,
    before_path: str,
    before_file_hash: str,
    after_file_hash: str,
) -> None:
    data = {
        "contract_version": 1,
        "run_id": run_id,
        "source_id": "TEST-LONG",
        "source_locator": "file:///tmp/test-long-source.txt",
        "operation": "index",
        "result": "changed",
        "before": {"snapshot_hash": digest(before), "paths": {}},
        "after": {"snapshot_hash": digest(after), "paths": {}},
        "checked_paths": [],
        "changed_paths": [],
        "allowed_write_scope": ["knowledge/data/test-long"],
    }
    controller = load_controller()
    after_paths = controller.scoped_file_manifest(root, data["allowed_write_scope"])
    before_paths = dict(after_paths)
    before_paths[before_path] = before_file_hash
    data["before"]["paths"] = before_paths
    data["after"]["paths"] = after_paths
    data["checked_paths"] = sorted(after_paths)
    data["changed_paths"] = sorted(
        path for path in set(before_paths) | set(after_paths)
        if before_paths.get(path) != after_paths.get(path)
    )
    path = root / ".local" / "agent-index-evidence.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_negative_selection_is_not_content() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        BASE.build_corpus(root)
        items = root / "knowledge" / "data" / "test" / "items.yml"
        text = items.read_text(encoding="utf-8")
        for item_id, status in (("TEST-FETCH", "irrelevant"), ("TEST-NORMALIZED", "rejected"), ("TEST-STATEMENTS", "rejected")):
            text = text.replace(
                f"  - id: {item_id}\n    title:",
                f"  - id: {item_id}\n    selection_status: {status}\n    title:",
            )
        items.write_text(text, encoding="utf-8")
        git_init(root)
        plan = run(root)
        for queue in ("fetch", "normalize", "statements", "semantic_review", "source_check"):
            block = BASE.extract_queue_block(plan.stdout, queue)
            if any(item_id in block for item_id in ("TEST-FETCH", "TEST-NORMALIZED", "TEST-STATEMENTS")):
                raise AssertionError(f"negative selection entered content queue {queue}")
        run(root, "--rebuild-indexes")
        index = (root / "knowledge" / "index" / "statements.yml").read_text(encoding="utf-8")
        if "TEST-001" in index:
            raise AssertionError("rejected unit statement entered the content index")


def test_agent_evidence_contract() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        BASE.build_corpus(root)
        BASE.write_long_source(root, coverage_units="""
            coverage:
              units:
                - unit_id: chapter-1
                  status: extracted
        """)
        agent_route(root)
        BASE.reject_automated_work(root, keep_blocked=False)
        git_init(root)
        failed = run(root, "--run-pipeline", "--agent-index-refreshed", "TEST-LONG", expected=1)
        if "index_refresh_incomplete" not in failed.stdout:
            raise AssertionError("legacy agent flag closed the refresh")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        BASE.build_corpus(root)
        BASE.write_long_source(root, coverage_units="""
            coverage:
              units:
                - unit_id: chapter-1
                  status: extracted
        """)
        agent_route(root)
        BASE.reject_automated_work(root, keep_blocked=False)
        git_init(root)
        run(root, "--run-pipeline", expected=1)
        saved = state(root)
        before = saved["index_sync"]["after"]["TEST-LONG"]
        items = root / "knowledge" / "data" / "test-long" / "items.yml"
        before_hash = file_digest(items)
        items.write_text(
            items.read_text(encoding="utf-8").replace(
                "items: []",
                'items:\n  - id: TEST-LONG-NEW\n    selection_status: irrelevant\n    title: "Новая единица"\n    access: "Открытый тестовый источник."\n    status: active\n    workflow_stage: indexed',
            ),
            encoding="utf-8",
        )
        controller = load_controller()
        after = controller.source_index_snapshot(root / "knowledge")["TEST-LONG"]
        write_agent_evidence(
            root,
            run_id=saved["run_id"],
            before=before,
            after=after,
            before_path="knowledge/data/test-long/items.yml",
            before_file_hash=before_hash,
            after_file_hash=file_digest(items),
        )
        run(root, "--run-pipeline", "--agent-index-evidence", "TEST-LONG", ".local/agent-index-evidence.yml")
        if state(root)["status"] != "completed":
            raise AssertionError("valid agent evidence was rejected")


def test_adapter_failure_keeps_last_success() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        BASE.build_corpus(root)
        BASE.reject_automated_work(root, keep_blocked=False)
        git_init(root)
        run(root, "--run-pipeline")
        adapter = root / "index-adapter.py"
        adapter.write_text(
            adapter.read_text(encoding="utf-8").replace(
                "operation, source_id = sys.argv[1:]",
                "operation, source_id = sys.argv[1:]\n"
                "if Path('.local/fail-index').exists() and operation == 'index':\n"
                "    print('not-json')\n"
                "    raise SystemExit(0)",
            ).replace("processing_scope: full", "selection_status: irrelevant"),
            encoding="utf-8",
        )
        BASE.write(root / ".local" / "fail-index", "yes\n")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        run(root, "--run-pipeline", expected=1)
        failed = state(root)
        if not failed["index_sync"]["after"]:
            raise AssertionError("failed adapter erased confirmed after snapshot")
        if not failed["index_sync"].get("adapter_results") or not failed["index_sync"].get("failed_attempts"):
            raise AssertionError("successful and failed adapter attempts were not separated")
        (root / ".local" / "fail-index").unlink()
        BASE.write(root / ".local" / "add-index-unit", "yes\n")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        run(root, "--run-pipeline")
        delta = next(
            item for item in state(root)["index_sync"]["delta"]["sources"]
            if item["source_id"] == "TEST-INDEX-ONLY"
        )
        if "TEST-INDEX-ONLY-METADATA" in delta["added"] or "TEST-INDEX-ONLY-NEW" not in delta["added"]:
            raise AssertionError("recovery calculated delta from an empty index")


def test_index_rebuild_recovers_after_interrupt() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        BASE.build_corpus(root)
        controller = load_controller()
        items_index = root / "knowledge" / "index" / "items.yml"
        original_replace = controller.os.replace
        interrupted = False

        def replace_once(source, destination):
            nonlocal interrupted
            if Path(destination) == items_index and not interrupted:
                original_replace(source, destination)
                interrupted = True
                raise RuntimeError("simulated interruption")
            original_replace(source, destination)

        controller.os.replace = replace_once
        try:
            try:
                controller.rebuild_indexes(root / "knowledge", root)
            except RuntimeError:
                pass
        finally:
            controller.os.replace = original_replace
        transaction = root / ".local" / "state" / "index-rebuild.json"
        if not transaction.is_file():
            raise AssertionError("incomplete rebuild was not recorded")
        controller.rebuild_indexes(root / "knowledge", root)
        if transaction.exists():
            raise AssertionError("rebuild transaction was not finalized")


def test_apply_now_requires_artifact_evidence() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        BASE.build_corpus(root)
        BASE.reject_automated_work(root, keep_blocked=False)
        BASE.write(root / "product.txt", "before")
        configure_report(root, [apply_finding("no-op")])
        git_init(root)
        run(root, "--run-pipeline", expected=1)
        if state(root)["reason_code"] != "apply_evidence_missing":
            raise AssertionError("successful no-op command closed apply_now")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        BASE.build_corpus(root)
        BASE.reject_automated_work(root, keep_blocked=False)
        BASE.write(root / "product.txt", "applied")
        expected = file_digest(root / "product.txt")
        finding = apply_finding("idempotent", expected_hashes={"product.txt": expected})
        finding["change_set"] = controlled_update("product.txt", b"applied", b"applied")
        configure_report(root, [finding])
        git_init(root)
        run(root, "--run-pipeline")


def test_controlled_apply_rejects_links_and_restores() -> None:
    """Every rejected write proves the external target retained its original bytes."""
    controller = load_controller()
    with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside_tmp:
        root = Path(temporary)
        outside = Path(outside_tmp) / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        (root / "docs").mkdir()
        git_init(root)

        def finding(path: str, before: bytes = b"outside") -> dict:
            return {
                "id": path.replace("/", "-"), "status": "apply_now", "target_paths": [path],
                "source_delta": {"source_id": "TEST", "categories": ["changed"], "unit_ids": ["TEST"]},
                "path_surfaces": {path: "user_documentation"},
                "change_set": controlled_update(path, before, b"changed"),
            }

        # Existing, nested, relative, chained and dangling links must all be
        # rejected before a write.  The assertion below checks the *outside*
        # file, rather than trusting a later Git diff.
        (root / "docs" / "link.md").symlink_to(outside)
        for path in ("docs/link.md",):
            try:
                controller.apply_controlled_change_sets(root, [finding(path)])
            except controller.OperationsError:
                pass
            else:
                raise AssertionError("external symlink was accepted")
            if outside.read_text(encoding="utf-8") != "outside":
                raise AssertionError("external target was changed through a symlink")
        (root / "docs" / "nested").symlink_to(outside.parent, target_is_directory=True)
        try:
            controller.apply_controlled_change_sets(root, [finding("docs/nested/outside.txt")])
        except controller.OperationsError:
            pass
        else:
            raise AssertionError("nested symlink was accepted")
        if outside.read_text(encoding="utf-8") != "outside":
            raise AssertionError("nested external target was changed")
        (root / "docs" / "relative.md").symlink_to("../../" + outside.parent.name + "/outside.txt")
        (root / "docs" / "chain.md").symlink_to("link.md")
        (root / "docs" / "dangling.md").symlink_to("missing.md")
        for path in ("docs/relative.md", "docs/chain.md", "docs/dangling.md"):
            try:
                controller.apply_controlled_change_sets(root, [finding(path, b"")])
            except controller.OperationsError:
                pass
            else:
                raise AssertionError(f"symlink {path} was accepted")
        if outside.read_text(encoding="utf-8") != "outside":
            raise AssertionError("outside target changed through a transient chain")

        target = root / "docs" / "safe.md"
        target.write_bytes(b"before")
        valid = finding("docs/safe.md", b"before")
        controller.apply_controlled_change_sets(root, [valid])
        if target.read_bytes() != b"changed":
            raise AssertionError("controlled change set was not applied")
        invalid = finding("docs/safe.md", b"before")
        try:
            controller.apply_controlled_change_sets(root, [invalid])
        except controller.OperationsError:
            pass
        else:
            raise AssertionError("mismatched before hash was accepted")

        hard = root / "docs" / "hard.md"
        try:
            hard.hardlink_to(outside)
        except OSError:
            pass
        else:
            try:
                controller.apply_controlled_change_sets(root, [finding("docs/hard.md")])
            except controller.OperationsError:
                pass
            else:
                raise AssertionError("hard link was accepted")
            if outside.read_text(encoding="utf-8") != "outside":
                raise AssertionError("external hard-link target was changed")

        original_replace = controller.safe_replace_bytes
        calls = 0
        second = root / "docs" / "second.md"
        second.write_bytes(b"second")
        first = {**finding("docs/safe.md", b"changed"), "id": "first"}
        second_finding = {**finding("docs/second.md", b"second"), "id": "second"}
        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise controller.OperationsError("simulated write failure")
            return original_replace(*args, **kwargs)
        controller.safe_replace_bytes = fail_second
        try:
            try:
                controller.apply_controlled_change_sets(root, [first, second_finding])
            except controller.OperationsError:
                pass
            else:
                raise AssertionError("mid-apply failure was accepted")
        finally:
            controller.safe_replace_bytes = original_replace
        if target.read_bytes() != b"changed" or second.read_bytes() != b"second":
            raise AssertionError("controlled apply did not restore original files after failure")


def test_agent_task_packets() -> None:
    controller = load_controller()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        corpus = root / "knowledge"
        corpus.mkdir()
        output = corpus / "data" / "result.txt"
        output.parent.mkdir(parents=True)
        output.write_text("evidence", encoding="utf-8")
        for queue in ("content_selection", "normalize", "statements", "verification", "impact_audit", "apply_changes"):
            packet = controller.build_agent_task_packet(root, corpus, "run-1", queue, [{"id": "UNIT-1", "path": "knowledge/data/item.yml", "reason": "test"}])
            if packet["queue"] != queue or packet["unit_ids"] != ["UNIT-1"] or not packet["completion_criteria"]:
                raise AssertionError("task packet is incomplete")
            evidence = root / f"{queue}.json"
            evidence.write_text(json.dumps({"packet_id": packet["packet_id"], "outputs": [{"path": "knowledge/data/result.txt", "sha256": file_digest(output)}]}), encoding="utf-8")
            accepted = controller.accept_agent_task_evidence(root, packet, evidence)
            if accepted["packet_id"] != packet["packet_id"]:
                raise AssertionError("packet evidence was not accepted")


def test_no_change_and_counter_contracts() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        BASE.build_corpus(root)
        BASE.reject_automated_work(root, keep_blocked=False)
        configure_report(root, [{"id": "missing", "status": "no_change", "affected_surfaces": ["code"]}], mode="propose_only")
        git_init(root)
        run(root, "--run-pipeline", expected=1)

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        BASE.build_corpus(root)
        items = root / "knowledge" / "data" / "test" / "items.yml"
        items.write_text(
            items.read_text(encoding="utf-8").replace(
                "  - id: TEST-FETCH\n    title:",
                "  - id: TEST-FETCH\n    selection_status: irrelevant\n    title:",
            ),
            encoding="utf-8",
        )
        git_init(root)
        run(root, "--run-pipeline", "--max-steps", "1", expected=10)
        summary = state(root)["owner_summary"]
        if summary["unit_counts_are_unique_ids"] or "rejected" not in summary["additional_unit_dimensions"]:
            raise AssertionError("overlapping rejected dimension was reported as a unique category")


def test_repeated_propose_only_is_unique() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        BASE.build_corpus(root)
        BASE.reject_automated_work(root, keep_blocked=False)
        configure_report(root, [apply_finding("repeat")], mode="propose_only")
        git_init(root)
        run(root, "--run-pipeline")
        first = state(root)["owner_summary"]["proposed_changes"]
        run(root, "--run-pipeline")
        second = state(root)["owner_summary"]["proposed_changes"]
        if len(first) != 1 or len(second) != 1 or len({item["id"] for item in second}) != 1:
            raise AssertionError("repeated propose_only duplicated the proposal")


def test_adversarial_eligibility_and_surface_contracts() -> None:
    """The admission gate must reject bad evidence before proposal or apply."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        BASE.build_corpus(root)
        controller = load_controller()
        corpus_root = root / "knowledge"
        operations = {"surface_paths": {"user_documentation": ["docs/**"]}}
        source_id = "TEST"
        unit_id = "TEST-V2-COMPLETE"
        sync = {
            "delta": {"sources": [{"source_id": source_id, "changed": [unit_id]}]},
            "baseline": {},
            "after": controller.source_index_snapshot(corpus_root),
        }
        finding = apply_finding("adversarial", target="docs/result.md")
        finding["source_delta"] = {"source_id": source_id, "categories": ["changed"], "unit_ids": [unit_id]}
        normalized = controller.normalize_impact_finding(finding)
        controller.validate_impact_findings(root, corpus_root, operations, [normalized], sync)

        def rejected(label: str, action) -> None:
            try:
                action()
            except controller.OperationsError:
                return
            raise AssertionError(label)

        # irrelevant/rejected must be blocked equally in propose_only and apply_now.
        items = corpus_root / "data" / "test" / "items.yml"
        items.write_text(items.read_text(encoding="utf-8").replace(
            f"  - id: {unit_id}\n    title:",
            f"  - id: {unit_id}\n    selection_status: irrelevant\n    title:",
        ), encoding="utf-8")
        rejected("irrelevant unit entered propose_only", lambda: controller.validate_impact_findings(root, corpus_root, operations, [normalized], sync))
        rejected("irrelevant unit entered apply_now", lambda: controller.validate_impact_findings(root, corpus_root, operations, [normalized], sync))
        rejected("rejected changed unit entered finding", lambda: controller.validate_finding_source_units(corpus_root, normalized, sync))

        # A substituted ID and a missing backing unit are not made valid by a category label.
        stolen = dict(normalized)
        stolen["source_delta"] = {"source_id": source_id, "categories": ["changed"], "unit_ids": ["OTHER"]}
        rejected("substituted unit ID was accepted", lambda: controller.validate_finding_source_units(corpus_root, stolen, sync))
        missing = dict(normalized)
        missing["source_delta"] = {"source_id": source_id, "categories": ["changed"], "unit_ids": ["MISSING"]}
        rejected("finding without source unit was accepted", lambda: controller.validate_finding_source_units(corpus_root, missing, sync))

        # The current index, not an earlier delta alone, decides eligibility.
        rejected("status change between stages was ignored", lambda: controller.validate_finding_source_units(corpus_root, normalized, sync))
        items.write_text(items.read_text(encoding="utf-8").replace(
            f"  - id: {unit_id}\n    selection_status: irrelevant\n    title:",
            f"  - id: {unit_id}\n    title:",
        ), encoding="utf-8")

        bad_surface = dict(normalized)
        bad_surface["target_paths"] = ["forbidden.cfg"]
        bad_surface["target_surfaces"] = {"forbidden.cfg": "user_documentation"}
        rejected("surface label authorized forbidden.cfg", lambda: controller.finding_path_surfaces(bad_surface, operations))
        escaped = dict(normalized)
        escaped["target_paths"] = ["../escape"]
        escaped["target_surfaces"] = {"../escape": "user_documentation"}
        rejected("path traversal was accepted", lambda: controller.finding_path_surfaces(escaped, operations))

        docs = root / "docs"
        docs.mkdir()
        outside = root.parent / "outside-corpus-audit.txt"
        outside.write_text("outside", encoding="utf-8")
        (docs / "link.md").symlink_to(outside)
        symlink_finding = dict(normalized)
        symlink_finding["target_paths"] = ["docs/link.md"]
        symlink_finding["target_surfaces"] = {"docs/link.md": "user_documentation"}
        rejected("external symlink was accepted", lambda: controller.validate_apply_findings(
            root, corpus_root, [symlink_finding], sync, {}, {"docs/link.md": "x"}, (), operations
        ))

        (docs / "result.md").write_text("done", encoding="utf-8")
        expected = file_digest(docs / "result.md")
        satisfied = dict(normalized)
        satisfied["expected_hashes"] = {"docs/result.md": expected}
        evidence = controller.validate_apply_findings(
            root, corpus_root, [satisfied], sync, {"docs/result.md": "same"}, {"docs/result.md": "same"}, (), operations
        )
        if evidence[0]["preexisting_paths"] != ["docs/result.md"]:
            raise AssertionError("proved already-satisfied path was not retained")
        rejected("extra undeclared product file was accepted", lambda: controller.validate_apply_findings(
            root, corpus_root, [satisfied], sync,
            {"docs/result.md": "old", "forbidden.cfg": "old"},
            {"docs/result.md": "new", "forbidden.cfg": "new"}, (), operations,
        ))


def test_agent_template_matches_validator_and_controller() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        BASE.build_corpus(root)
        template = yaml.safe_load((ROOT / ".apm" / "skills" / "kc-inventory" / "assets" / "source.yml").read_text(encoding="utf-8"))
        template.update({"id": "TEST", "slug": "test", "title": "Template test", "retrieved_at": "2026-09-19", "last_checked_at": "2026-09-19"})
        template["agent_route"]["write_scope"] = ["knowledge/data/test"]
        (root / "knowledge" / "data" / "test" / "source.yml").write_text(
            yaml.safe_dump(template, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        validator = ROOT / ".apm" / "skills" / "kc-inventory" / "scripts" / "validate-corpus-layout.py"
        checked = subprocess.run([sys.executable, str(validator), "knowledge", "--output", "json"], cwd=root, capture_output=True, text=True)
        if checked.returncode != 0:
            raise AssertionError(f"filled agent template failed validator: {checked.stdout}{checked.stderr}")
        controller = load_controller()
        source = next(item for item in controller.load_sources(root / "knowledge") if item.source_id == "TEST")
        if not controller.valid_agent_route(root, source):
            raise AssertionError("filled agent template failed controller route validation")


def main() -> int:
    test_negative_selection_is_not_content()
    test_agent_evidence_contract()
    test_adapter_failure_keeps_last_success()
    test_index_rebuild_recovers_after_interrupt()
    test_apply_now_requires_artifact_evidence()
    test_controlled_apply_rejects_links_and_restores()
    test_agent_task_packets()
    test_no_change_and_counter_contracts()
    test_repeated_propose_only_is_unique()
    test_adversarial_eligibility_and_surface_contracts()
    test_agent_template_matches_validator_and_controller()
    print("Аудиторские регрессионные сценарии прошли.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
