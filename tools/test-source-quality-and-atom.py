#!/usr/bin/env python3
"""Deterministic checks for source quality policy and Atom discovery."""

from __future__ import annotations

import importlib.machinery
import json
import tempfile
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ATOM = importlib.machinery.SourceFileLoader("atom", str(ROOT / ".apm/skills/kc-pipeline/scripts/atom-discovery.py")).load_module()
QUALITY = importlib.machinery.SourceFileLoader("quality", str(ROOT / ".apm/skills/kc-inventory/scripts/check-source-quality.py")).load_module()
CONTROLLER = importlib.machinery.SourceFileLoader("controller", str(ROOT / ".apm/skills/kc-pipeline/scripts/run-corpus-operations.py")).load_module()
URL = "https://raw.githubusercontent.com/anthropics/claude-code/main/feed.xml"
RELEASE = "https://github.com/anthropics/claude-code/releases/tag/v2.1.277"


def feed(entries: str, technical: str = "") -> str:
    return f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">{technical}{entries}</feed>'


def entry(identifier: str, title: str, content: str, link: str = RELEASE) -> str:
    return f"<entry><id>{identifier}</id><title>{title}</title><updated>2026-09-20T00:00:00Z</updated><link href=\"{link}\"/><content>{content}</content></entry>"


def test_atom() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        before, after, technical, state = root / "before.xml", root / "after.xml", root / "technical.xml", root / "state.json"
        before.write_text(feed(entry("v2.1.276", "Claude Code 2.1.276", "Earlier release.")), encoding="utf-8")
        after.write_text(feed(entry("v2.1.276", "Claude Code 2.1.276", "Earlier release.") + entry("v2.1.277", "Claude Code 2.1.277", "AGENTS.md is supported when CLAUDE.md is absent. Project instructions show it through /config. This support is temporarily unavailable on Bedrock, Vertex and Foundry.")), encoding="utf-8")
        technical.write_text(feed(entry("v2.1.276", "Claude Code 2.1.276", "Earlier release.") + entry("v2.1.277", "Claude Code 2.1.277", "AGENTS.md is supported when CLAUDE.md is absent. Project instructions show it through /config. This support is temporarily unavailable on Bedrock, Vertex and Foundry."), "<!-- whitespace and feed metadata only -->"), encoding="utf-8")
        first = ATOM.update(URL, state, fixture=before, timeout=1, maximum=100_000)
        second = ATOM.update(URL, state, fixture=after, timeout=1, maximum=100_000)
        third = ATOM.update(URL, state, fixture=after, timeout=1, maximum=100_000)
        fourth = ATOM.update(URL, state, fixture=technical, timeout=1, maximum=100_000)
        if first["status"] != "changed" or second["added"] != ["v2.1.277"] or third["status"] != "unchanged" or fourth["status"] != "unchanged":
            raise AssertionError("Atom change classification is not deterministic")
        release = next(item for item in second["entries"] if item["id"] == "v2.1.277")
        if release["canonical_link"] != RELEASE or "AGENTS.md" not in release["content"]:
            raise AssertionError("Claude Code 2.1.277 fixture lost canonical evidence")
        # Return to the same entries with an XML-only delta: it is a new feed
        # snapshot but no new event.  The adapter exposes that as unchanged.
        saved = json.loads(state.read_text(encoding="utf-8"))
        if not saved["snapshot_sha256"]:
            raise AssertionError("Atom snapshot lacks SHA-256")


def test_quality() -> None:
    policy = {"contract_version": 1, "areas": [{"id": "claude", "required_roles": ["discovery", "evidence"], "max_successful_check_age_days": 14, "minimum_primary_sources": 1, "event_identity": ["provider", "version"]}], "owner_exceptions": []}
    healthy_sources = [{"id": "feed", "areas": ["claude"], "roles": ["discovery", "evidence"], "primary": True, "adapter_status": "ready", "last_successful_check": "2026-09-19"}]
    events = [
        {"provider": "anthropic", "version": "2.1.277", "url": RELEASE, "primary": True, "canonical": True, "content_hash": "a"},
        {"provider": "anthropic", "version": "2.1.277", "url": "https://example.test/feed", "primary": True, "content_hash": "a"},
        {"provider": "anthropic", "version": "2.1.277", "url": "https://example.test/changelog", "primary": True, "content_hash": "a"},
        {"provider": "anthropic", "version": "2.1.277", "url": "https://example.test/docs", "primary": True, "content_hash": "a"},
        {"provider": "anthropic", "version": "2.1.278", "url": "https://example.test/next", "primary": True, "content_hash": "b"},
    ]
    healthy = QUALITY.evaluate(policy, healthy_sources, events, date(2026, 9, 20))
    if not healthy["healthy"] or len(healthy["events"]) != 2 or len(healthy["events"][0]["corroborating_evidence"]) != 3:
        raise AssertionError("healthy coverage or event deduplication failed")
    cases = [
        ([], "missing_discovery"),
        ([{**healthy_sources[0], "last_successful_check": "2026-01-01"}], "stale_source"),
        ([{**healthy_sources[0], "adapter_status": "unsupported-adapter"}], "missing_discovery"),
        ([{**healthy_sources[0], "primary": False}], "secondary_only_evidence"),
    ]
    for sources, expected in cases:
        result = QUALITY.evaluate(policy, sources, events, date(2026, 9, 20))
        if expected not in result["coverage"][0]["problems"]:
            raise AssertionError(f"quality policy did not detect {expected}")
    exception_policy = {**policy, "owner_exceptions": [{"area_id": "claude", "reason": "approved temporary provider outage"}]}
    exception = QUALITY.evaluate(exception_policy, [], events, date(2026, 9, 20))
    if exception["coverage"][0]["state"] != "degraded":
        raise AssertionError("owner-approved exception was not preserved")
    conflict = QUALITY.evaluate(policy, healthy_sources, [{**events[0]}, {**events[1], "content_hash": "conflict"}], date(2026, 9, 20))
    if not conflict["events"][0]["conflict"]:
        raise AssertionError("conflicting evidence was not flagged")


def test_pipeline_quality_summary() -> None:
    """The owner consumes exactly the checker result, including policy absence."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        policy = {"contract_version": 1, "areas": [{"id": "claude", "required_roles": ["discovery", "evidence"], "minimum_primary_sources": 1, "max_successful_check_age_days": 14}], "owner_exceptions": []}
        sources = [{"id": "release", "areas": ["claude"], "roles": ["discovery", "evidence"], "primary": True, "adapter_status": "ready", "last_successful_check": "2026-09-19"}]
        events = [{"provider": "anthropic", "version": "2.1.277", "canonical_url": RELEASE, "url": RELEASE, "primary": True, "canonical": True, "content_hash": "release"}]
        for name, value in (("policy.json", policy), ("sources.json", sources), ("events.json", events)):
            (root / name).write_text(json.dumps(value), encoding="utf-8")
        configured = CONTROLLER.source_quality_result(root, {"source_quality": {"policy": "policy.json", "sources": "sources.json", "events": "events.json", "today": "2026-09-20"}})
        if configured["status"] != "healthy" or configured["coverage"][0]["state"] != "covered":
            raise AssertionError("pipeline did not retain healthy source-quality matrix")
        missing = CONTROLLER.source_quality_result(root, {})
        if missing["status"] != "not_configured" or not missing["recommendation"]:
            raise AssertionError("missing policy is not an explicit non-blocking result")
        stale_sources = [{**sources[0], "last_successful_check": "2026-01-01"}]
        (root / "sources.json").write_text(json.dumps(stale_sources), encoding="utf-8")
        stale = CONTROLLER.source_quality_result(root, {"source_quality": {"policy": "policy.json", "sources": "sources.json", "events": "events.json", "today": "2026-09-20"}})
        if stale["status"] != "stale" or stale["coverage"][0]["problems"] != ["stale_source"]:
            raise AssertionError("stale source was not preserved structurally")


if __name__ == "__main__":
    test_atom()
    test_quality()
    test_pipeline_quality_summary()
    print("Проверки Atom и качества источников прошли.")
