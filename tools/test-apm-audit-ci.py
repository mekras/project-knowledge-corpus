#!/usr/bin/env python3
"""Регрессионные проверки узкого обхода ложного APM drift."""

from __future__ import annotations

import json
import importlib.machinery
import importlib.util
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / "tools" / "apm-audit-ci"


def load_audit_module():
    loader = importlib.machinery.SourceFileLoader("apm_audit_ci", str(AUDIT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def write_project(
    root: Path,
    *,
    dependency_version: str = "1.0.0",
    active_owner: str = ".",
    adapter_owner: str = ".",
    extra_failure: bool = False,
    local_hash_drift: bool = False,
    phantom_bytecode: bool = False,
    present_bytecode: bool = False,
    lock_bytecode: bool = False,
    echoed_ref_mismatch: bool = False,
    actual_ref_mismatch: bool = False,
    local_addition: bool = False,
    changed_local_addition: bool = False,
    local_removal: bool = False,
    unowned_removal: bool = False,
    rewritten_local_source: bool = False,
    local_source_presence: bool = False,
) -> Path:
    (root / "apm.yml").write_text(
        "name: local-package\nversion: 1.0.0\n",
        encoding="utf-8",
    )
    source = root / ".apm" / "skills" / "example" / "SKILL.md"
    deployed = root / ".agents" / "skills" / "example" / "SKILL.md"
    source.parent.mkdir(parents=True)
    deployed.parent.mkdir(parents=True)
    source.write_text(
        "[skill](../other/README.md)\n" if rewritten_local_source else "local source\n",
        encoding="utf-8",
    )
    deployed.write_text(
        "[skill](../../../.apm/skills/other/README.md)\n"
        if rewritten_local_source
        else "local source\n",
        encoding="utf-8",
    )
    adapter_source = root / ".apm" / "skills" / "example" / "scripts" / "adapter.py"
    adapter_deployed = root / ".agents" / "skills" / "example" / "scripts" / "adapter.py"
    adapter_source.parent.mkdir(parents=True)
    adapter_deployed.parent.mkdir(parents=True)
    adapter_source.write_text("#!/bin/sh\n", encoding="utf-8")
    adapter_deployed.write_text("#!/bin/sh\n", encoding="utf-8")
    lockfile = f"""dependencies:
- repo_url: example/local-package
  name: local-package
  version: {dependency_version}
deployments:
- value: .agents/skills/example/SKILL.md
  owners: [example/local-package, .]
  active_owner: {active_owner}
- value: .agents/skills/example/scripts/adapter.py
  owners: [example/local-package, {adapter_owner}]
  active_owner: {adapter_owner}
"""
    if local_removal or unowned_removal:
        removal_path = ".agents/skills/example/references/removed.md"
        removal_owners = (
            "[example/local-package]" if local_removal else "[example/other-package]"
        )
        lockfile += f"""- value: {removal_path}
  owners: {removal_owners}
  active_owner: example/local-package
"""
    (root / "apm.lock.yaml").write_text(lockfile, encoding="utf-8")
    if lock_bytecode:
        with (root / "apm.lock.yaml").open("a", encoding="utf-8") as stream:
            stream.write(
                "- value: .agents/skills/example/scripts/__pycache__/"
                "adapter.cpython-313.pyc\n"
                "  owners: [example/local-package]\n"
                "  active_owner: example/local-package\n"
            )
    checks = [{"name": "lockfile-exists", "passed": True}]
    if echoed_ref_mismatch or actual_ref_mismatch:
        manifest_ref = "^0.22.0"
        lockfile_ref = manifest_ref if echoed_ref_mismatch else "0.22.0"
        checks.append(
            {
                "name": "ref-consistency",
                "passed": False,
                "details": [
                    f"example/local-package: manifest ref '{manifest_ref}' != lockfile ref '{lockfile_ref}'"
                ],
            }
        )
        drift = []
    else:
        checks.append({"name": "drift", "passed": False})
        drift = [
            {
                "path": ".agents/skills/example/SKILL.md",
                "kind": "modified",
                "package": "example/local-package",
            }
        ]
    if extra_failure:
        checks.append({"name": "content-integrity", "passed": False})
    if local_hash_drift:
        checks.append(
            {
                "name": "content-integrity",
                "passed": False,
                "details": [
                    "hash-drift: .agents/skills/example/SKILL.md "
                    "(dep=<self>, expected=old, actual=new)"
                ],
            }
        )
    if phantom_bytecode:
        bytecode = root / ".agents" / "skills" / "example" / "scripts" / "__pycache__" / "adapter.cpython-313.pyc"
        if present_bytecode:
            bytecode.parent.mkdir(parents=True)
            bytecode.write_bytes(b"not phantom")
        drift.append(
            {
            "path": ".agents/skills/example/scripts/__pycache__/adapter.cpython-313.pyc",
                "kind": "unintegrated",
                "package": "",
            }
        )
    if local_source_presence:
        checks.append(
            {
                "name": "deployed-files-present",
                "passed": False,
                "details": [".agents/skills/example/SKILL.md"],
            }
        )
    if local_addition or changed_local_addition:
        added_source = root / ".apm" / "skills" / "example" / "references" / "new.md"
        added_deployed = root / ".agents" / "skills" / "example" / "references" / "new.md"
        added_source.parent.mkdir(parents=True, exist_ok=True)
        added_deployed.parent.mkdir(parents=True, exist_ok=True)
        added_source.write_text("new local source\n", encoding="utf-8")
        added_deployed.write_text(
            "changed\n" if changed_local_addition else "new local source\n",
            encoding="utf-8",
        )
        drift.append(
            {
                "path": ".agents/skills/example/references/new.md",
                "kind": "orphaned",
                "package": ".",
            }
        )
    if local_removal or unowned_removal:
        checks.append(
            {
                "name": "deployed-files-present",
                "passed": False,
                "details": [removal_path],
            }
        )
        drift.append(
            {
                "path": removal_path,
                "kind": "unintegrated",
                "package": "example/local-package",
            }
        )
    report = {
        "passed": False,
        "checks": checks,
        "drift": {
            "drift": drift
        },
    }
    fake_apm = root / "fake-apm"
    fake_apm.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import os\n"
        "assert os.environ.get('PYTHONDONTWRITEBYTECODE') == '1'\n"
        f"print({json.dumps(json.dumps(report))})\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    fake_apm.chmod(fake_apm.stat().st_mode | stat.S_IXUSR)
    return fake_apm


def run(root: Path, fake_apm: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(AUDIT), "--apm", str(fake_apm), "--project-root", str(root)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def main() -> int:
    matches = load_audit_module().matches_local_source
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / ".apm/skills/example/references/contract.md"
        deployed = root / ".agents/skills/example/references/contract.md"
        source.parent.mkdir(parents=True)
        deployed.parent.mkdir(parents=True)
        source.write_text("[contract](../../other/references/admission.md#decision)\n")
        rewritten = "[contract](../../../../.apm/skills/other/references/admission.md#decision)\n"
        deployed.write_text(rewritten)
        assert matches(source, deployed)
        deployed.write_text(rewritten + "changed\n")
        assert not matches(source, deployed)
        deployed.write_text(rewritten.replace("other/", "another/"))
        assert not matches(source, deployed)
        deployed.write_text(rewritten.replace("../../../../", "../../../"))
        assert not matches(source, deployed)

    audit_module = load_audit_module()
    assert audit_module.local_package_id(
        {"name": "local-package", "version": "2.0.0"},
        {
            "dependencies": [
                {
                    "repo_url": "example/marketplace",
                    "virtual_path": "packages/local-package",
                    "name": "local-package",
                    "version": "1.0.0",
                }
            ]
        },
    ) == "example/marketplace/packages/local-package"

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        accepted = run(root, write_project(root))
        assert accepted.returncode == 0, accepted.stdout + accepted.stderr
        assert "подтверждено файлов — 1" in accepted.stdout

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        accepted = run(root, write_project(root, dependency_version="0.9.0"))
        assert accepted.returncode == 0, accepted.stdout + accepted.stderr
        assert "подтверждено файлов — 1" in accepted.stdout

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        accepted = run(root, write_project(root, phantom_bytecode=True))
        assert accepted.returncode == 0, accepted.stdout + accepted.stderr
        assert "подтверждено файлов — 2" in accepted.stdout

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        rejected = run(
            root,
            write_project(root, phantom_bytecode=True, lock_bytecode=True),
        )
        assert rejected.returncode == 1, rejected.stdout + rejected.stderr
        assert "apm.lock.yaml" in rejected.stderr

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        accepted = run(
            root,
            write_project(
                root,
                phantom_bytecode=True,
                adapter_owner="example/other-package",
            ),
        )
        assert accepted.returncode == 0, accepted.stdout + accepted.stderr
        assert "подтверждено файлов — 2" in accepted.stdout

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        accepted = run(root, write_project(root, local_hash_drift=True))
        assert accepted.returncode == 0, accepted.stdout + accepted.stderr
        assert "подтверждено файлов — 1" in accepted.stdout

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        accepted = run(
            root,
            write_project(
                root,
                local_hash_drift=True,
                rewritten_local_source=True,
                local_source_presence=True,
            ),
        )
        assert accepted.returncode == 0, accepted.stdout + accepted.stderr
        assert "подтверждено файлов — 1" in accepted.stdout

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        accepted = run(root, write_project(root, local_addition=True))
        assert accepted.returncode == 0, accepted.stdout + accepted.stderr
        assert "подтверждено файлов — 2" in accepted.stdout

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        rejected = run(root, write_project(root, changed_local_addition=True))
        assert rejected.returncode == 1, rejected.stdout + rejected.stderr
        assert '"orphaned"' in rejected.stdout

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        accepted = run(root, write_project(root, local_removal=True))
        assert accepted.returncode == 0, accepted.stdout + accepted.stderr
        assert "подтверждено файлов — 2" in accepted.stdout

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        rejected = run(root, write_project(root, unowned_removal=True))
        assert rejected.returncode == 1, rejected.stdout + rejected.stderr
        assert '"deployed-files-present"' in rejected.stdout

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        rejected = run(
            root,
            write_project(root, phantom_bytecode=True, present_bytecode=True),
        )
        assert rejected.returncode == 1, rejected.stdout + rejected.stderr
        assert '"unintegrated"' in rejected.stdout

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        accepted = run(root, write_project(root, active_owner="example/local-package"))
        assert accepted.returncode == 0, accepted.stdout + accepted.stderr

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        rejected = run(root, write_project(root, active_owner="example/other-package"))
        assert rejected.returncode == 1, rejected.stdout + rejected.stderr
        assert '"passed": false' in rejected.stdout

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        rejected = run(root, write_project(root, extra_failure=True))
        assert rejected.returncode == 1, rejected.stdout + rejected.stderr
        assert '"content-integrity"' in rejected.stdout

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        accepted = run(root, write_project(root, echoed_ref_mismatch=True))
        assert accepted.returncode == 0, accepted.stdout + accepted.stderr
        assert "самопротиворечивым сообщением" in accepted.stdout

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        rejected = run(root, write_project(root, actual_ref_mismatch=True))
        assert rejected.returncode == 1, rejected.stdout + rejected.stderr
        assert '"ref-consistency"' in rejected.stdout

    print("Узкий обход ложного APM drift проверен.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
