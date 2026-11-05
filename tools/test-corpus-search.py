#!/usr/bin/env python3
"""Exercise the published search command at its CLI boundary."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".apm/skills/kc-search"
SCRIPT = SKILL / "scripts/search-corpus.py"

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="поиск с пробелами.local.", dir=ROOT / "tools")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        shutil.copytree(SKILL / "evals/script-fixtures/ready", self.folder, dirs_exist_ok=True)
        self.corpus = self.folder / "corpus"
        self.source = self.corpus / "data/example"
        self.scope = self.folder / "scope.json"

    def run_command(self, operation="search", query="наставника", extra=(), scope=None):
        command = [sys.executable, "-S", str(SCRIPT), operation, "--corpus-root", str(self.corpus),
                   "--scope", str(scope or self.scope)]
        command += ["--query", query] if operation == "search" else ["--suite", str(self.folder / "suite.json")]
        result = subprocess.run(command + list(extra), cwd=self.folder,
                                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "ascii"},
                                text=True, encoding="utf-8", capture_output=True, check=False, timeout=15)
        return result

    def result(self, **kwargs):
        result = self.run_command(**kwargs)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def modify_scope(self, transform):
        data = json.loads(self.scope.read_text(encoding="utf-8"))
        transform(data)
        self.scope.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def embedding_args(self, mode="semantic", fault=None):
        config_path = self.folder / "embedding.json"
        if fault:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["command"].append(fault)
            if fault == "timeout":
                config["timeout_seconds"] = 1
            config_path.write_text(json.dumps(config), encoding="utf-8")
        return ("--mode", mode, "--embedding-config", str(config_path))

    def test_search_finds_statements_quotes_and_unusual_transcript_names(self):
        result = self.result()
        paths = {row["path"] for row in result["results"]}
        self.assertIn("data/example/statements.yml", paths)
        self.assertIn("data/example/занятие.расшифровано", paths)
        for row in result["results"]:
            if row["kind"] != "text":
                continue
            path = self.corpus / row["path"]
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(row["text"], "\n".join(lines[row["line_start"] - 1:row["line_end"]]))
            self.assertEqual(row["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(row["usage"]["status"], "unassessed")
            self.assertEqual(row["usage"]["limitations"], ["Учебный пример"])

    def test_ranked_evaluation_and_negative_control(self):
        result = self.result(operation="evaluate")
        self.assertEqual(result["positive_cases"], 2)
        self.assertEqual(result["recall_at_k"], 1)
        self.assertGreater(result["mrr_at_k"], 0)
        self.assertFalse(result["answer_quality_measured"])
        self.assertEqual(result["cases"][2]["results"], [])
        self.assertEqual(result["cases"][1]["question"], "Будет ли у стажёра помощник?")

    def test_baseline_omission_and_explicit_query_expansion(self):
        baseline = self.folder / "baseline.json"
        data = json.loads(self.scope.read_text(encoding="utf-8"))
        data["sources"][0]["exclude"] = ["statements.yml", "занятие.расшифровано"]
        baseline.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(self.result(scope=baseline)["results"], [])
        self.assertTrue(self.result()["results"])
        self.assertEqual(self.result(query="помощник")["results"], [])
        self.assertTrue(self.result(query="помощник наставника")["results"])

    def test_edited_and_deleted_files_leave_no_cached_hits(self):
        self.assertTrue(self.result(query="разовыймаркер")["results"])
        path = self.source / "message.md"
        path.write_text("Текст изменён.\n", encoding="utf-8")
        self.assertEqual(self.result(query="разовыймаркер")["results"], [])
        path.unlink()
        self.assertNotIn("data/example/message.md", self.result()["coverage"]["files"])

    def test_scope_and_coverage_are_visible_even_for_empty_results(self):
        (self.source / "binary.bin").write_bytes(b"\x00\xff")
        (self.source / "large.txt").write_text("x" * 1500, encoding="utf-8")
        (self.source / "secret.local.txt").write_text("секретное", encoding="utf-8")
        (self.source / "record.tmp.txt").write_text("временное", encoding="utf-8")
        result = self.result(query="несуществующееслово", extra=("--max-file-bytes", "1000"))
        reasons = {row["reason"] for row in result["coverage"]["skipped"]}
        self.assertTrue({"size_limit", "not_utf8_text", "local_not_enabled", "temporary_or_vcs"} <= reasons)
        self.assertTrue(result["coverage"]["absence_is_not_proven"])
        self.assertEqual(result["coverage"]["scope"], "configured_sources_only")

    def test_symlinks_do_not_expose_external_or_omitted_material(self):
        external = self.folder / "outside.txt"
        external.write_text("внешнийсекрет", encoding="utf-8")
        (self.source / "linked.txt").symlink_to(external)
        (self.source / "linked-dir").symlink_to(self.folder, target_is_directory=True)
        result = self.result(query="внешнийсекрет")
        self.assertEqual(result["results"], [])
        self.assertEqual(sum(row["reason"] == "symlink" for row in result["coverage"]["skipped"]), 2)

    def test_local_files_require_explicit_opt_in(self):
        (self.source / "добавление.local.txt").write_text("локальнаянаходка", encoding="utf-8")
        self.assertEqual(self.result(query="локальнаянаходка")["results"], [])
        self.modify_scope(lambda data: data["sources"][0].update(allow_local=True))
        self.assertTrue(self.result(query="локальнаянаходка")["results"])

    def test_missing_sources_and_excluded_directories_are_reported(self):
        (self.source / "draft").mkdir()
        (self.source / "draft" / "note.txt").write_text("скрытаянаходка", encoding="utf-8")
        self.modify_scope(lambda data: data["sources"][0].update(exclude=["draft"]))
        result = self.result(query="скрытаянаходка")
        self.assertEqual(result["results"], [])
        self.assertIn("excluded_by_scope", {s["reason"] for s in result["coverage"]["skipped"]})
        self.modify_scope(lambda data: data["sources"][0].update(root="missing"))
        self.assertIn("unavailable_source", {s["reason"] for s in self.result()["coverage"]["skipped"]})

    def test_invalid_scope_query_and_limit_fail_without_changing_files(self):
        before = {p: p.read_bytes() for p in self.corpus.rglob("*") if p.is_file()}
        self.assertNotEqual(self.run_command(query=" *** ").returncode, 0)
        self.assertNotEqual(self.run_command(extra=("--top-k", "0")).returncode, 0)
        self.modify_scope(lambda data: data["sources"][0].update(root="../outside"))
        self.assertNotEqual(self.run_command().returncode, 0)
        self.assertEqual(before, {p: p.read_bytes() for p in self.corpus.rglob("*") if p.is_file()})

    def test_invalid_or_missing_expected_evidence_is_not_a_search_failure(self):
        suite = self.folder / "suite.json"
        data = json.loads(suite.read_text(encoding="utf-8"))
        data["cases"][0]["expected"][0]["contains"] = "неверныйэталон"
        suite.write_text(json.dumps(data), encoding="utf-8")
        result = self.run_command(operation="evaluate")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Expected evidence is missing", result.stderr)

    def test_metadata_is_a_candidate_not_an_evidence_quote(self):
        result = self.result(query="Справочник")
        self.assertTrue(any(r["kind"] == "metadata" and r["line_start"] is None
                            and r["sha256"] is None for r in result["results"]))

    def test_special_files_are_not_opened(self):
        if not hasattr(os, "mkfifo"):
            self.skipTest("FIFO is not available on this platform")
        os.mkfifo(self.source / "pipe")
        result = self.result()
        self.assertIn("not_regular_file", {r["reason"] for r in result["coverage"]["skipped"]})

    def test_local_source_root_requires_opt_in_too(self):
        destination = self.source.with_name("example.local")
        self.source.rename(destination)
        self.modify_scope(lambda data: data["sources"][0].update(root="data/example.local"))
        self.assertEqual(self.result()["results"], [])

    def test_search_is_read_only_for_the_whole_fixture(self):
        def snapshot():
            return {p.relative_to(self.folder).as_posix(): p.read_bytes()
                    for p in self.folder.rglob("*") if p.is_file()}
        before = snapshot()
        self.result()
        self.result(operation="evaluate")
        self.result(extra=self.embedding_args())
        self.result(operation="evaluate", extra=self.embedding_args("compare"))
        self.assertEqual(snapshot(), before)

    def test_overlapping_roots_and_unapproved_scope_fail(self):
        self.modify_scope(lambda data: data["sources"].append(
            {**data["sources"][0], "id": "OTHER", "root": "data"}))
        self.assertNotEqual(self.run_command().returncode, 0)
        self.modify_scope(lambda data: data.update(sources=[
            {**data["sources"][0], "authorized_for_local_search": False}]))
        self.assertNotEqual(self.run_command().returncode, 0)

    def test_semantic_protocol_finds_a_nonmatching_word_with_supplied_vectors(self):
        self.assertEqual(self.result(query="помощник")["results"], [])
        result = self.result(query="помощник", extra=self.embedding_args())
        self.assertTrue(any("назначают наставника" in row["text"] for row in result["results"][:2]))
        self.assertEqual(result["engine"], "cosine")
        self.assertEqual(result["embedding"]["dimension"], 3)
        self.assertEqual(result["embedding"]["identity_check"], "adapter_self_report")
        self.assertTrue(all(row["usage"]["status"] == "unassessed" for row in result["results"]))

    def test_hybrid_preserves_channel_ranks_and_evidence(self):
        result = self.result(extra=self.embedding_args("hybrid"))
        self.assertEqual(result["engine"], "reciprocal_rank_fusion")
        self.assertTrue(any(set(row["channels"]) == {"lexical", "semantic"} for row in result["results"]))
        self.assertEqual(len({row["passage_id"] for row in result["results"]}), len(result["results"]))
        for row in result["results"]:
            score = sum(1 / (60 + channel["rank"]) for channel in row["channels"].values())
            self.assertAlmostEqual(score, row["score"])

    def test_compare_uses_same_queries_and_prepares_embeddings_in_batches(self):
        result = self.result(operation="evaluate", extra=self.embedding_args("compare"))
        self.assertEqual(set(result["variants"]), {"lexical", "semantic", "hybrid"})
        queries = [[case["query"] for case in variant["cases"]] for variant in result["variants"].values()]
        self.assertTrue(all(query == queries[0] for query in queries))
        self.assertEqual(result["embedding"]["requests"], 2)
        self.assertEqual(result["variants"]["semantic"]["recall_at_k"], 1)
        self.assertFalse(result["variants"]["semantic"]["answer_quality_measured"])
        # Dense search still returns nearest candidates for an unknown topic.
        self.assertTrue(result["variants"]["semantic"]["cases"][2]["negative_control"])

    def test_embedding_scope_must_be_reviewed_again_after_expansion(self):
        self.modify_scope(lambda data: data["sources"][0].update(allow_local=True))
        result = self.run_command(extra=self.embedding_args())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("access review does not match", result.stderr)

    def test_invalid_embedding_responses_fail_without_silent_fallback(self):
        config_path = self.folder / "embedding.json"
        original = config_path.read_bytes()
        for fault in ("zero", "nan", "dimension", "duplicate", "missing", "revision", "failure", "badjson", "timeout"):
            with self.subTest(fault=fault):
                config_path.write_bytes(original)
                result = self.run_command(extra=self.embedding_args(fault=fault))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertNotIn("private-adapter-error-content", result.stderr)

    def test_long_passages_are_split_without_changing_returned_text(self):
        text = "Вводное занятие: назначают наставника. " * 120
        (self.source / "long.md").write_text(text, encoding="utf-8")
        result = self.result(extra=self.embedding_args())
        self.assertGreater(result["embedding"]["inputs"], result["coverage"]["indexed_files"] + 2)
        self.assertTrue(any(row["text"] == text for row in result["results"]))

    def test_semantic_search_does_not_require_fts_query_overlap(self):
        query = 'помощник " OR * -- без подстановок'
        result = self.result(query=query, extra=self.embedding_args())
        self.assertEqual(result["query"], query)
        self.assertTrue(result["results"])


if __name__ == "__main__":
    unittest.main()
