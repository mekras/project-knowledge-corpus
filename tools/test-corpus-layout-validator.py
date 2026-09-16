#!/usr/bin/env python3
"""Regression tests for the portable corpus layout validator."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path
from textwrap import dedent


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPO_ROOT / ".apm" / "skills" / "kc-inventory" / "scripts" / "validate-corpus-layout.py"
RECORDER = REPO_ROOT / ".apm" / "skills" / "kc-inventory" / "scripts" / "record-snapshot-verification.py"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text).lstrip(), encoding="utf-8")


def indented_yaml_fragment(text: str) -> str:
    return "\n".join(f"        {line}" if line else "" for line in dedent(text).lstrip().splitlines())


def write_minimal_corpus(root: Path, corpus_yml: str | None = None) -> None:
    write_text(
        root / "corpus.yml",
        corpus_yml
        or """
        contract_version: 1
        tracked_data:
          root: data
          source_pattern: data/<source>/source.yml
          source_unit_pattern: data/<source>/<units>/<unit>/item.yml
          statement_pattern: data/<source>/<units>/<unit>/statements.yml
        local_data:
          raw: .local/raw
          private: .local/private
          cache: .local/cache
          temporary_file_pattern: "*.tmp.*"
        source_units:
          document:
            unit: file_or_section
            path_pattern: data/<source>/documents/<slug>
        workflow_stages:
          - indexed
          - normalized
          - statements_extracted
          - source_checked
          - blocked
        """,
    )
    write_text(
        root / "catalog.yml",
        """
        sources:
          - id: TEST
            title: "Test source"
            path: data/test-source
        """,
    )
    write_text(
        root / "data" / "test-source" / "source.yml",
        """
        id: TEST
        slug: test-source
        title: "Test source"
        access:
          default: "Open test fixture."
        status: active
        carrier_type: document
        source_kind: reference
        adapter: manual
        reliability: test fixture
        refresh_policy: manual
        """,
    )
    write_text(
        root / "data" / "test-source" / "items.yml",
        """
        items:
          - id: TEST-ITEM-001
            title: "Test item"
            access: "Same as source."
            status: active
            workflow_stage: indexed
        """,
    )


def write_long_source(root: Path, *, stage: str = "normalized") -> None:
    write_text(
        root / "data" / "test-source" / "source.yml",
        """
        id: TEST
        slug: test-source
        title: "Test source"
        access:
          default: "Open test fixture."
        status: active
        carrier_type: document
        source_kind: book
        long_source: true
        adapter: manual
        storage_strategy: local_only
        copy_policy: metadata_only
        reliability: test fixture
        refresh_policy: manual
        extraction_status: normalized_fragments_ready
        """,
    )
    write_text(
        root / "data" / "test-source" / "items.yml",
        f"""
        items:
          - id: TEST-ITEM-001
            title: "Chapter 1"
            access: "Same as source."
            status: active
            workflow_stage: {stage}
        """,
    )


def write_long_source_item(root: Path, *, stage: str = "normalized") -> None:
    write_text(
        root / "data" / "test-source" / "source.yml",
        """
        id: TEST
        slug: test-source
        title: "Test source"
        access:
          default: "Open test fixture."
        status: active
        carrier_type: document
        source_kind: reference
        long_source: false
        adapter: manual
        storage_strategy: local_only
        copy_policy: metadata_only
        reliability: test fixture
        refresh_policy: manual
        """,
    )
    write_text(
        root / "data" / "test-source" / "items.yml",
        f"""
        items:
          - id: TEST-ITEM-001
            title: "Long appendix"
            access: "Same as source."
            status: active
            workflow_stage: {stage}
            long_source: true
        """,
    )


def write_source_map(root: Path, *, coverage: str | None = None, extra: str = "") -> None:
    coverage_text = indented_yaml_fragment(
        coverage if coverage is not None else "coverage_absence_reason: Not started."
    )
    extra_text = indented_yaml_fragment(extra) if extra else ""
    write_text(
        root / "data" / "test-source" / "source-map.yml",
        f"""
        source_map_version: 1
        source_id: TEST
        long_source: true
        extraction_passport:
          format: pdf
          file_size_bytes: 123
          content_hash_absence_reason: "Test fixture has no source file."
          metadata_source: manual
          extraction_tool: manual
          extraction_status: normalized_fragments_ready
        structure:
          units:
            - id: chapter-1
              title: "Chapter 1"
              order: 1
{coverage_text}
{extra_text}
        """,
    )


def write_external_corpus_source(root: Path, with_items: bool = False) -> None:
    write_text(
        root / "catalog.yml",
        """
        sources:
          - id: TEST
            title: "Test source"
            path: data/test-source
          - id: EXT
            title: "External corpus"
            path: data/external-corpus
        """,
    )
    write_text(
        root / "data" / "external-corpus" / "source.yml",
        """
        id: EXT
        slug: external-corpus
        title: "External corpus"
        access:
          default: "Access follows the connected project or local checkout."
        status: active
        carrier_type: repository
        source_kind: knowledge_corpus
        adapter: builtin.git
        reliability: working
        refresh_policy: manual
        locator: "ssh://git@example.org/team/corpus.git#knowledge"
        external_corpus:
          contract: portable_v1
          use_as: peer
          local_checkout: .local/external-corpora/external-corpus
        """,
    )
    if with_items:
        write_text(
            root / "data" / "external-corpus" / "items.yml",
            """
            items:
              - id: EXT-CATALOG
                title: "External catalog"
                access: "Same as source."
                status: active
                workflow_stage: indexed
            """,
        )


def write_statement(
    root: Path,
    status: str = "ready_for_review",
    kind: str | None = None,
    text: str = "Fact.",
    excerpt: str = "Fact.",
    artifact_text: str = "Fact.",
    scope: str = "{}",
) -> None:
    kind_line = f"kind: {kind}\n            " if kind is not None else ""
    write_text(root / "data" / "test-source" / "documents" / "item-001" / "artifact.md", artifact_text)
    write_text(
        root / "data" / "test-source" / "documents" / "item-001" / "item.yml",
        """
        id: TEST-ITEM-001
        title: "Test item"
        access: "Same as source."
        status: active
        workflow_stage: indexed
        """,
    )
    write_text(
        root / "data" / "test-source" / "documents" / "item-001" / "statements.yml",
        f"""
        source_id: TEST
        item_id: TEST-ITEM-001
        statements:
          - id: TEST-001
            source_id: TEST
            item_id: TEST-ITEM-001
            status: {status}
            {kind_line}text: "{text}"
            excerpt: "{excerpt}"
            artifact: artifact.md
            checked_at: 2026-06-30
            scope: {scope}
            open_questions: []
        """,
    )


def write_statement_v2(root: Path, *, include_legacy_status: bool = False) -> None:
    status_line = "status: candidate" if include_legacy_status else ""
    write_text(root / "data" / "test-source" / "documents" / "item-001" / "artifact.md", "Source fragment.")
    write_text(
        root / "data" / "test-source" / "documents" / "item-001" / "item.yml",
        """
        id: TEST-ITEM-001
        title: "Test item"
        access: "Same as source."
        status: active
        workflow_stage: statements_extracted
        """,
    )
    write_text(
        root / "data" / "test-source" / "documents" / "item-001" / "statements.yml",
        f"""
        statement_contract_version: 2
        source_id: TEST
        item_id: TEST-ITEM-001
        statements:
          - id: TEST-001
            source_id: TEST
            item_id: TEST-ITEM-001
            kind: fact
            {status_line}
            text: "A traceable test statement."
            excerpt: "Source fragment."
            artifact: artifact.md
            checked_at: 2026-07-26
            scope: {{}}
            open_questions: []
            processing_status:
              extraction: complete
              traceability: passed
              semantic_review: passed
              strong_review: not_required
              corroboration_check: complete
            source_role: primary
            evidence_strength: weak
            confidence: high
            temporal_status: historical
            corroboration: single_source
            limitations:
              - "The source is historical."
        """,
    )


def write_concepts(root: Path, *, relationships: str = "[]") -> None:
    write_text(
        root / "concepts.yml",
        f"""
        concept_contract_version: 1
        concepts:
          - id: persona
            primary: персонаж
            definition: "A model of a group of users with shared goals and context."
            boundaries:
              includes:
                - "A model of a user group."
              excludes:
                - "A specific user."
            authority:
              type: project_decision
              ref: ADR-0001
            defined_by:
              - TEST-001
            relationships: {relationships}
        """,
    )


def write_derived_statement(
    root: Path,
    *,
    analysis_id: str = "NIGHT",
    statement_id: str = "DRV-NIGHT-001",
    kind: str = "observation",
    status: str = "candidate",
    statement_ids: str = "[TEST-001]",
    item_ids: str = "[]",
    artifacts: str = "[]",
    external_references: str = "[]",
    derivation_type: str = "aggregation",
    derivation_artifact: str | None = "analysis/night-starts/calculate.sql",
    checked_by: str = "",
) -> None:
    write_text(
        root / "analysis" / "night-starts" / "calculate.sql",
        "SELECT COUNT(*) FROM searches;\n",
    )
    artifact_line = (
        f'artifact: "{derivation_artifact}"' if derivation_artifact is not None else ""
    )
    write_text(
        root / "analysis" / "night-starts" / "derived-statements.yml",
        f"""
        analysis_id: {analysis_id}
        title: "Night search starts"
        derived_statements:
          - id: {statement_id}
            kind: {kind}
            status: {status}
            text: "Most headquarters in the sample started at night."
            derived_from:
              statement_ids: {statement_ids}
              item_ids: {item_ids}
              artifacts: {artifacts}
              external_references: {external_references}
            derivation:
              type: {derivation_type}
              method: "Count starts between 22:00 and 06:00."
              {artifact_line}
              parameters:
                night_interval: "22:00-06:00"
            checked_at: 2026-07-10
            checked_by: "{checked_by}"
            scope:
              applies_to: ["test sample"]
              does_not_apply_to: []
            limitations:
              - "Start time does not describe search duration."
            open_questions: []
        """,
    )


def run_validator(
    root: Path,
    *,
    strict_statements: bool = False,
    strict_concepts: bool = False,
    strict_verification: bool = False,
    operational: bool = False,
    operational_policy: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(VALIDATOR)]
    if strict_statements:
        command.append("--strict-statements")
    if strict_concepts:
        command.append("--strict-concepts")
    if strict_verification:
        command.append("--strict-verification")
    if operational:
        command.append("--operational")
    if operational_policy is not None:
        command.extend(["--operational-policy", str(operational_policy)])
    command.append(str(root))
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def assert_passes(root: Path) -> None:
    result = run_validator(root)
    if result.returncode != 0:
        raise AssertionError(f"expected validator to pass, got:\n{result.stdout}")


def assert_fails_with(
    root: Path,
    expected: str,
    *,
    strict_statements: bool = False,
    strict_concepts: bool = False,
) -> None:
    result = run_validator(
        root,
        strict_statements=strict_statements,
        strict_concepts=strict_concepts,
    )
    if result.returncode == 0:
        raise AssertionError("expected validator to fail")
    if expected not in result.stdout:
        raise AssertionError(f"expected {expected!r} in output:\n{result.stdout}")


def initialize_git(root: Path) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        corpus_path = root / "corpus.yml"
        corpus_path.write_text(
            corpus_path.read_text(encoding="utf-8").replace(
                "  - source_checked\n",
                "  - source_checked\n  - verification_assessed\n",
            ),
            encoding="utf-8",
        )
        unit = root / "data" / "test-source" / "documents" / "snapshot"
        write_text(
            root / "data" / "test-source" / "items.yml",
            """
            items:
              - id: TEST-ITEM-001
                item_contract_version: 2
                title: "Test item"
                access: "Same as source."
                status: active
                workflow_stage: verification_assessed
                path: documents/snapshot
            """,
        )
        write_text(
            unit / "item.yml",
            """
            id: TEST-ITEM-001
            item_contract_version: 2
            title: "Test item"
            access: "Same as source."
            status: active
            workflow_stage: verification_assessed
            """,
        )
        artifact = unit / "message.md"
        write_text(artifact, "User-provided snapshot.\n")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        write_text(
            unit / "verification.yml",
            f"""
            verification_contract_version: 1
            artifact: message.md
            hash:
              algorithm: sha256
              value: {digest}
            acquisition:
              method: user_provided
              recorded_at: 2026-09-02
            verification:
              method: no_source_comparison
              checked_at: 2026-09-02
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
                - Not compared with the external source.
            """,
        )
        assert_passes(root)

        artifact.write_text("Changed snapshot.\n", encoding="utf-8")
        assert_fails_with(root, "artifact hash does not match verification.yml")
        artifact.write_text("User-provided snapshot.\n", encoding="utf-8")

        verification_path = unit / "verification.yml"
        original = verification_path.read_text(encoding="utf-8")
        verification_path.write_text(
            original.replace("verification_contract_version: 1", "verification_contract_version: 9"),
            encoding="utf-8",
        )
        assert_fails_with(root, "unsupported verification_contract_version: 9")
        verification_path.write_text(original, encoding="utf-8")

        verification_path.write_text(
            original.replace("metadata: []", "metadata: []\n    profile_name: local-reader"),
            encoding="utf-8",
        )
        assert_fails_with(root, "forbidden verification field: profile_name")
        verification_path.write_text(original, encoding="utf-8")

        verification_path.write_text(
            original.replace("artifact: message.md", "artifact: /tmp/message.md"),
            encoding="utf-8",
        )
        assert_fails_with(root, "artifact must be relative to the unit")
        verification_path.write_text(original, encoding="utf-8")

        verification_path.write_text(
            original.replace(
                "method: no_source_comparison",
                "method: manual_confirmation",
            ).replace("content: full_text", "content: fragment"),
            encoding="utf-8",
        )
        assert_fails_with(root, "fragment content scope requires scope.fragment")
        verification_path.write_text(original, encoding="utf-8")

        artifact.unlink()
        assert_fails_with(root, "verified artifact does not exist")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        unit = root / "data" / "test-source" / "documents" / "test-item"
        write_text(
            root / "data" / "test-source" / "items.yml",
            """
            items:
              - id: TEST-ITEM-001
                item_contract_version: 2
                title: "Test item"
                access: "Same as source."
                status: active
                workflow_stage: indexed
                path: documents/test-item
            """,
        )
        write_text(
            unit / "item.yml",
            """
            id: TEST-ITEM-001
            item_contract_version: 2
            title: "Test item"
            access: "Same as source."
            status: active
            workflow_stage: indexed
            """,
        )
        result = run_validator(root, strict_verification=True)
        if result.returncode != 0 or "item contract version 2 has no verification.yml" not in result.stdout:
            raise AssertionError(
                "strict verification must warn, but not fail, before verification_assessed:\n"
                f"{result.stdout}{result.stderr}"
            )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        unit = root / "data" / "test-source" / "documents" / "legacy-item"
        write_text(
            root / "data" / "test-source" / "items.yml",
            """
            items:
              - id: TEST-ITEM-001
                title: "Legacy item"
                access: "Same as source."
                status: active
                workflow_stage: source_checked
                path: documents/legacy-item
            """,
        )
        write_text(
            unit / "item.yml",
            """
            id: TEST-ITEM-001
            title: "Legacy item"
            access: "Same as source."
            status: active
            workflow_stage: source_checked
            """,
        )
        result = run_validator(root, strict_verification=True)
        expected = "legacy item has no verification.yml; external verification and freshness are not recorded"
        if result.returncode != 0 or expected not in result.stdout:
            raise AssertionError(
                "strict verification must report an unverified legacy item without failing:\n"
                f"{result.stdout}{result.stderr}"
            )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        unit = root / "data" / "test-source" / "documents" / "recorded"
        write_text(
            root / "data" / "test-source" / "items.yml",
            """
            items:
              - id: TEST-ITEM-001
                title: "Test item"
                access: "Same as source."
                status: active
                workflow_stage: normalized
                path: documents/recorded
            """,
        )
        write_text(
            unit / "item.yml",
            """
            id: TEST-ITEM-001
            title: "Test item"
            access: "Same as source."
            status: active
            workflow_stage: normalized
            """,
        )
        artifact = unit / "message.md"
        write_text(artifact, "Provided text.\n")
        recorded = subprocess.run(
            [
                sys.executable,
                str(RECORDER),
                str(unit),
                str(artifact),
                "--acquisition-method",
                "user_provided",
                "--verification-method",
                "no_source_comparison",
                "--content-scope",
                "full_text",
                "--content-match",
                "unverified",
                "--scope-completeness",
                "complete",
                "--overall-result",
                "unverified",
                "--checked-by-role",
                "corpus_maintainer",
            ],
            text=True,
            capture_output=True,
        )
        if recorded.returncode != 0:
            raise AssertionError(f"snapshot recorder failed:\n{recorded.stdout}{recorded.stderr}")
        assert_passes(root)
        item_text = (unit / "item.yml").read_text(encoding="utf-8")
        if "item_contract_version: 2" not in item_text or "verification_assessed" not in item_text:
            raise AssertionError("single-unit migration did not update item.yml")

        repeated = subprocess.run(
            [
                sys.executable,
                str(RECORDER),
                str(unit),
                str(artifact),
                "--acquisition-method",
                "user_provided",
                "--verification-method",
                "no_source_comparison",
                "--content-scope",
                "full_text",
                "--content-match",
                "unverified",
                "--scope-completeness",
                "complete",
                "--overall-result",
                "unverified",
                "--checked-by-role",
                "corpus_maintainer",
            ],
            text=True,
            capture_output=True,
        )
        if repeated.returncode != 0:
            raise AssertionError("safe repeat of snapshot recorder failed")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        assert_passes(root)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        assert_fails_with(
            root,
            "missing concepts.yml required by strict concept validation",
            strict_concepts=True,
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(root, kind="fact")
        write_concepts(root)
        result = run_validator(root, strict_concepts=True)
        if result.returncode != 0:
            raise AssertionError(f"expected strict concept validation to pass, got:\n{result.stdout}")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(root, kind="fact")
        write_concepts(root)
        concepts_path = root / "concepts.yml"
        concepts_path.write_text(
            concepts_path.read_text(encoding="utf-8").replace(
                'definition: "A model of a group of users with shared goals and context."',
                'definition: ""',
            ),
            encoding="utf-8",
        )
        assert_fails_with(
            root,
            "definition must be non-empty text",
            strict_concepts=True,
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(root, kind="fact")
        write_concepts(root, relationships="[{type: applies_to, target: unknown-concept}]")
        assert_fails_with(
            root,
            "target references unknown concept: unknown-concept",
            strict_concepts=True,
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        contract = root / "corpus.yml"
        contract.write_text(
            contract.read_text(encoding="utf-8")
            + """
project_profile: restricted_internal
action_policy:
  acquire: allow_with_source_constraints
  process: allow
  retain_uncertain: retain_with_quality_metadata
  retain_sensitive: retain_with_access_metadata
  tracked_storage: restricted_project_rules
  external_disclosure: owner_decision
  delete: owner_decision
  irreversible_transform: owner_decision
  secrets_in_tracked_storage: prohibit
""",
            encoding="utf-8",
        )
        assert_passes(root)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        contract = root / "corpus.yml"
        contract.write_text(
            contract.read_text(encoding="utf-8")
            + """
project_profile: restricted_internal
action_policy:
  process: allow
  secrets_in_tracked_storage: allow
""",
            encoding="utf-8",
        )
        assert_fails_with(root, "action_policy missing required keys")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(root)
        assert_passes(root)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement_v2(root)
        assert_passes(root)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement_v2(root)
        statements_path = root / "data" / "test-source" / "documents" / "item-001" / "statements.yml"
        statements_path.write_text(
            statements_path.read_text(encoding="utf-8").replace(
                "confidence: high",
                "confidence: low",
            ),
            encoding="utf-8",
        )
        assert_fails_with(root, "requires strong_review")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement_v2(root)
        statements_path = root / "data" / "test-source" / "documents" / "item-001" / "statements.yml"
        statements_path.write_text(
            statements_path.read_text(encoding="utf-8").replace(
                "semantic_review: passed",
                "semantic_review: failed",
            ),
            encoding="utf-8",
        )
        assert_fails_with(root, "failed semantic review requires strong_review")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement_v2(root, include_legacy_status=True)
        assert_fails_with(root, "status is not allowed in statement contract v2")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement_v2(root)
        statements_path = root / "data" / "test-source" / "documents" / "item-001" / "statements.yml"
        statements_path.write_text(
            statements_path.read_text(encoding="utf-8").replace(
                "statement_contract_version: 2",
                "statement_contract_version: 99",
            ),
            encoding="utf-8",
        )
        assert_fails_with(root, "unsupported statement_contract_version: 99")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        items_path = root / "data" / "test-source" / "items.yml"
        items_path.write_text(
            items_path.read_text(encoding="utf-8").replace(
                "workflow_stage: indexed",
                "workflow_stage: blocked",
            ),
            encoding="utf-8",
        )
        assert_fails_with(root, "blocker_code must be one of:")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(root, status="blocked")
        assert_fails_with(root, "blocker_code must be one of:")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(root)
        assert_fails_with(root, "missing kind in strict statement validation", strict_statements=True)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(
            root,
            kind="fact",
            text="The validator should not accept copied statement text as evidence.",
            excerpt="The validator should not accept copied statement text as evidence.",
            artifact_text="The source contains the original evidence.",
        )
        assert_fails_with(root, "excerpt duplicates statement text", strict_statements=True)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(
            root,
            kind="fact",
            text="The source says the corpus needs traceable excerpts.",
            excerpt="traceable excerpt missing from artifact",
            artifact_text="The source says another fragment.",
        )
        assert_fails_with(
            root,
            "excerpt is not found in referenced text artifact",
            strict_statements=True,
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(
            root,
            kind="fact",
            text="The corpus joins two non-contiguous verbatim spans for brevity.",
            excerpt="First verbatim fragment ... second verbatim fragment",
            artifact_text="First verbatim fragment. Unrelated middle sentence. Second verbatim fragment.",
        )
        result = run_validator(root, strict_statements=True)
        if result.returncode != 0:
            raise AssertionError(
                f"expected an ellipsis-joined multi-fragment excerpt to pass, got:\n{result.stdout}"
            )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(
            root,
            kind="fact",
            text="The corpus must reject a fragment order that does not match the source.",
            excerpt="Second verbatim fragment ... First verbatim fragment",
            artifact_text="First verbatim fragment. Unrelated middle sentence. Second verbatim fragment.",
        )
        assert_fails_with(
            root,
            "excerpt is not found in referenced text artifact",
            strict_statements=True,
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(
            root,
            kind="fact",
            text="The source says section metadata must stay useful.",
            excerpt="section metadata",
            artifact_text="The source says section metadata must stay useful.",
            scope="{section_title: ''}",
        )
        assert_fails_with(root, "scope.section_title must be non-empty", strict_statements=True)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(root, kind="invalid_kind")
        assert_fails_with(root, "kind must be one of:")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(root, status="fact")
        assert_fails_with(root, "status contains statement kind fact")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(root, kind="fact")
        write_derived_statement(root)
        assert_passes(root)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(root, kind="fact")
        write_derived_statement(root, kind="fact")
        assert_fails_with(root, "fact is direct only")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(root, kind="fact")
        write_derived_statement(root, statement_id="NIGHT-001")
        assert_fails_with(root, "id must match DRV-NIGHT-NNN")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(root, kind="fact")
        write_derived_statement(root, statement_ids="[]")
        assert_fails_with(root, "derived_from must contain at least one input")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(root, kind="fact")
        write_derived_statement(root, statement_ids="[MISSING-001]")
        assert_fails_with(root, "derived statement input is missing in corpus: MISSING-001")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(root, kind="fact")
        write_derived_statement(root, statement_ids="[DRV-NIGHT-001]")
        assert_fails_with(root, "derived statements must use direct inputs")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_external_corpus_source(root)
        write_statement(root, kind="fact")
        write_derived_statement(
            root,
            statement_ids="[]",
            external_references=(
                "[{corpus_source_id: EXT, statement_id: EXT-001, revision: v1}]"
            ),
        )
        assert_passes(root)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(root, kind="fact")
        write_derived_statement(
            root,
            statement_ids="[]",
            external_references=(
                "[{corpus_source_id: MISSING, statement_id: EXT-001, revision: v1}]"
            ),
        )
        assert_fails_with(root, "corpus source is missing: MISSING")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_external_corpus_source(root)
        write_statement(root, kind="fact")
        write_derived_statement(
            root,
            statement_ids="[]",
            external_references="[{corpus_source_id: EXT, statement_id: EXT-001}]",
        )
        assert_fails_with(root, "revision or revision_absence_reason is required")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(root, kind="fact")
        write_derived_statement(root, derivation_artifact=None)
        assert_fails_with(root, "aggregation derivation requires artifact")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(root, kind="fact")
        write_derived_statement(root, derivation_artifact="../calculate.sql")
        assert_fails_with(root, "derivation.artifact must be repository-relative")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(root, kind="fact")
        write_derived_statement(root, status="confirmed")
        assert_fails_with(root, "confirmed statement requires checked_by")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_statement(root, kind="fact")
        write_derived_statement(
            root,
            status="confirmed",
            checked_by="Reviewer",
            statement_ids="[]",
            artifacts=(
                "[{path: data/test-source/searches.local.csv, "
                "content_hash_absence_reason: 'Test fixture'}]"
            ),
        )
        assert_fails_with(root, "confirmed statement input requires content_hash")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_external_corpus_source(root)
        assert_passes(root)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_text(
            root / "catalog.yml",
            """
            sources:
              - id: EXT
                title: "External corpus"
                path: data/external-corpus
            """,
        )
        write_text(
            root / "data" / "external-corpus" / "source.yml",
            """
            id: EXT
            slug: external-corpus
            title: "External corpus"
            access:
              default: "Access follows the connected project."
            status: active
            carrier_type: repository
            source_kind: knowledge_corpus
            adapter: builtin.git
            reliability: working
            refresh_policy: manual
            locator: "ssh://git@example.org/team/corpus.git#knowledge"
            """,
        )
        assert_fails_with(root, "knowledge_corpus source requires external_corpus block")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        (root / "inventory").mkdir()
        assert_fails_with(root, "inventory/: legacy corpus layer remains outside data/")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(
            root,
            """
            contract_version: 1
            tracked_data:
              root: data
              layers:
                registry: data
                legacy_inventory: knowledge/inventory
            local_data:
              raw: .local/raw
            source_units:
              document:
                unit: file_or_section
                path_pattern: data/<source>/documents/<slug>
            """,
        )
        assert_fails_with(root, "corpus.yml: legacy layer remains active outside portable layout")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_long_source(root)
        assert_fails_with(root, "long source reached normalization or statements without source-map.yml")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_long_source_item(root)
        assert_fails_with(root, "long source reached normalization or statements without source-map.yml")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_long_source(root)
        write_source_map(root)
        assert_passes(root)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_long_source(root, stage="statements_extracted")
        write_source_map(
            root,
            coverage="""
            coverage:
              units:
                - unit_id: chapter-1
            """,
        )
        assert_fails_with(root, "status must be one of:")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_long_source(root, stage="statements_extracted")
        write_source_map(
            root,
            coverage="""
            coverage:
              units:
                - unit_id: chapter-1
                  status: deferred
                  reason: "Left for later."
            """,
        )
        assert_fails_with(root, "status must be one of:")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_long_source(root, stage="statements_extracted")
        write_source_map(
            root,
            coverage="""
            coverage:
              units:
                - unit_id: chapter-1
                  status: postponed
                  reason: "Not reviewed yet."
            """,
        )
        assert_fails_with(root, "blocker_code must be one of:")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_long_source(root, stage="statements_extracted")
        write_source_map(
            root,
            coverage="""
            coverage:
              units:
                - unit_id: chapter-1
                  status: postponed
                  reason: "Not reviewed yet."
                  blocker_code: not_a_real_code
            """,
        )
        assert_fails_with(root, "blocker_code must be one of:")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_long_source(root, stage="statements_extracted")
        write_source_map(
            root,
            coverage="""
            coverage:
              units:
                - unit_id: chapter-1
                  status: postponed
                  reason: "Owner must decide."
                  blocker_code: owner_decision_required
            """,
        )
        assert_passes(root)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_long_source(root)
        write_source_map(root, extra='full_text: "Complete tracked text is not allowed."')
        assert_fails_with(root, "source-map.yml contains full-text-like fields")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_text(
            root / "operational-policy.yml",
            """
            rules:
              - kind: arbitrary-topic
                path: data/**
                action: blocker
                reason: "Произвольная тема не должна становиться блокером."
            """,
        )
        initialize_git(root)
        result = run_validator(
            root,
            operational=True,
            operational_policy=Path("operational-policy.yml"),
        )
        if result.returncode == 0 or "operational policy rule #1" not in result.stdout:
            raise AssertionError("Произвольный вид находки принят как операционный блокер.")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_minimal_corpus(root)
        write_text(
            root / "data" / "test-source" / "gist.html",
            """
            <meta property="fb:app_id" content="1401488693436528">
            <meta name="apple-itunes-app" content="app-id=1477376905">
            <meta name="author" content="262588213843476">
            <meta name="gist-id" content="141849770">
            """,
        )
        initialize_git(root)
        result = run_validator(root, operational=True)
        if result.returncode != 0 or "personal-data" in result.stdout:
            raise AssertionError(
                "Bare technical identifiers from public HTML were classified as personal data.\n"
                f"{result.stdout}"
            )

        write_text(
            root / "data" / "test-source" / "example-addresses.md",
            """
            jane@example.com
            john@example.com
            test@example.com
            user@example.com
            info@coop.example.com
            etl@enisa.europa.eu
            press@enisa.europa.eu
            ssdf@nist.gov
            doc.writer@asciidoctor.org
            guide@writethedocs.org
            osi@social.opensource.org
            press@perplexity.ai
            project@google-groups.com
            """,
        )
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        result = run_validator(root, operational=True)
        if result.returncode != 0 or "personal-data" in result.stdout:
            raise AssertionError(
                "Addresses on reserved domains or role mailboxes were classified as personal data.\n"
                f"{result.stdout}"
            )

        write_text(
            root / "data" / "test-source" / "ordinary-address.md",
            "ssw0rd@prod-db.company.com\n",
        )
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        result = run_validator(root, operational=True)
        if result.returncode != 0 or "personal-data" not in result.stdout:
            raise AssertionError(
                "An address on an ordinary domain was not reported as a quality warning.\n"
                f"{result.stdout}"
            )

        write_text(root / "data" / "test-source" / "contact-plus.md", "Phone: +7 (999) 123-45-67\n")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        result = run_validator(root, operational=True)
        if result.returncode != 0 or "personal-data" not in result.stdout:
            raise AssertionError(
                "A formatted international phone number was not reported as a quality warning.\n"
                f"{result.stdout}"
            )

        (root / "data" / "test-source" / "contact-plus.md").unlink()
        write_text(root / "data" / "test-source" / "contact-russian.md", "Phone: 8 (999) 123-45-67\n")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        result = run_validator(root, operational=True)
        if result.returncode != 0 or "personal-data" not in result.stdout:
            raise AssertionError(
                "A formatted Russian phone number starting with 8 was not reported as a quality warning.\n"
                f"{result.stdout}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
