#!/usr/bin/env python3
"""Offline regression checks for E5 setup, artifact handling and adapter limits."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".apm/skills/kc-search/scripts"
sys.path.insert(0, str(SCRIPTS))
import e5_runtime
from e5_runtime import storage


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


setup = load("configure_e5", SCRIPTS / "configure-e5.py")
adapter = load("e5_adapter", SCRIPTS / "e5_runtime/adapter.py")


class E5Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="e5 русский.local.", dir=ROOT / "tools")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.scope = self.folder / "scope.json"
        self.scope.write_text('{"scope_version":1,"sources":[]}', encoding="utf-8")
        self.checksum = hashlib.sha256(self.scope.read_bytes()).hexdigest()
        self.output = self.folder / "embedding.local.json"

    def cli(self, *extra):
        return subprocess.run([sys.executable, "-S", str(SCRIPTS / "configure-e5.py"),
            "--scope", str(self.scope), "--approved-scope-sha256", self.checksum,
            "--runtime-python", sys.executable, "--model-dir", str(self.folder / "model.local.data"),
            "--output", str(self.output), *extra], capture_output=True, text=True,
            encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "ascii"}, timeout=10)

    def test_cli_creates_usable_configuration_without_optional_libraries(self):
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(config["approved_scope_sha256"], self.checksum)
        self.assertEqual(config["command"][0], sys.executable)
        self.assertEqual(config["command"][1], "-B")
        self.assertTrue(Path(config["command"][2]).is_file())
        self.assertFalse(json.loads(result.stdout)["runtime_validated"])
        self.assertFalse((self.folder / "model.local.data").exists())

    def test_refuses_overwrite_before_download(self):
        self.output.write_text("existing", encoding="utf-8")
        result = self.cli("--download-model")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no overwrite", result.stderr)
        self.assertEqual(self.output.read_text(), "existing")
        self.assertFalse((self.folder / "model.local.data").exists())

    def test_scope_change_stops_before_any_write(self):
        result = self.cli("--approved-scope-sha256", "0" * 64, "--download-model")
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.output.exists())
        self.assertFalse((self.folder / "model.local.data").exists())

    def test_malformed_scope_is_rejected(self):
        self.scope.write_text("[]")
        self.checksum = hashlib.sha256(self.scope.read_bytes()).hexdigest()
        self.assertEqual(self.cli().returncode, 1)

    def artifact(self, content=b"fixture model"):
        return {"model.onnx": ("onnx/model.onnx", hashlib.sha256(content).hexdigest())}

    def test_download_is_pinned_verified_and_idempotent(self):
        files = self.artifact()
        with patch.object(setup, "FILES", files), patch.object(setup.urllib.request, "urlopen",
                return_value=io.BytesIO(b"fixture model")) as transport:
            setup.download_model(self.folder)
            self.assertIn(e5_runtime.REVISION, transport.call_args.args[0])
        with patch.object(setup, "FILES", files), patch.object(setup.urllib.request, "urlopen") as transport:
            setup.download_model(self.folder)
            transport.assert_not_called()
        self.assertEqual((self.folder / "model.onnx").read_bytes(), b"fixture model")

    def test_corrupt_download_leaves_no_artifact_or_temporary_file(self):
        before = set(self.folder.iterdir())
        with patch.object(setup, "FILES", self.artifact()), patch.object(setup.urllib.request, "urlopen",
                return_value=io.BytesIO(b"corrupt")), self.assertRaisesRegex(ValueError, "hash mismatch"):
            setup.download_model(self.folder)
        self.assertEqual(set(self.folder.iterdir()), before)

    def test_existing_corrupt_model_is_preserved_and_rejected(self):
        path = self.folder / "model.onnx"
        path.write_bytes(b"corrupt")
        with patch.object(setup, "FILES", self.artifact()), self.assertRaisesRegex(ValueError, "no overwrite"):
            setup.download_model(self.folder)
        self.assertEqual(path.read_bytes(), b"corrupt")

    def test_verification_rejects_changed_and_symlinked_model(self):
        path = self.folder / "model.onnx"
        with patch.object(e5_runtime, "FILES", self.artifact()):
            with self.assertRaises(ValueError):
                e5_runtime.verify(self.folder)
            path.write_bytes(b"fixture model")
            e5_runtime.verify(self.folder)
            path.unlink()
            path.symlink_to(self.scope)
            with self.assertRaises(ValueError):
                e5_runtime.verify(self.folder)

    def request(self):
        return {"embedding_protocol_version": 1, "model": e5_runtime.MODEL,
                "revision": e5_runtime.REVISION, "inputs": [{"id": "0", "text": "query: помощь"}]}

    def test_input_validation_rejects_incompatible_requests(self):
        adapter.validate_request(self.request())
        for change in ({"revision": "wrong"}, {"inputs": []}, {"inputs": [None]},
                       {"inputs": [{"id": "0", "text": "без префикса"}]},
                       {"inputs": self.request()["inputs"] * 2}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                adapter.validate_request(self.request() | change)

    def test_runtime_versions_checked_before_import(self):
        with patch.object(adapter.importlib.metadata, "version", return_value="wrong"), self.assertRaises(ValueError):
            adapter.encode(self.request()["inputs"], self.folder)

    def test_token_overflow_is_rejected_without_truncation(self):
        tokenizer = Mock()
        tokenizer.encode_batch.return_value = [Mock(ids=list(range(513)))]
        modules = {"numpy": Mock(), "onnxruntime": Mock(), "tokenizers": Mock()}
        modules["tokenizers"].Tokenizer.from_file.return_value = tokenizer
        with patch.dict(sys.modules, modules), patch.object(adapter.importlib.metadata, "version",
                side_effect=lambda name: adapter.VERSIONS[name]), self.assertRaisesRegex(ValueError, "512"):
            adapter.encode(self.request()["inputs"], self.folder)
        tokenizer.no_truncation.assert_called_once()
        modules["onnxruntime"].InferenceSession.assert_not_called()

    def test_default_storage_is_per_user_and_independent_of_project(self):
        common = self.folder / "common"
        with patch.dict(os.environ, {"XDG_CACHE_HOME": str(common)}):
            a = storage.shared_locations()
            other = self.folder / "project-b"
            other.mkdir()
            old = Path.cwd()
            try:
                os.chdir(other)
                b = storage.shared_locations()
            finally:
                os.chdir(old)
        self.assertEqual(a, b)
        self.assertTrue(a["model_dir"].is_relative_to(common))
        self.assertIn(e5_runtime.REVISION, a["model_dir"].parts)

    def test_invalid_xdg_location_falls_back_to_home(self):
        with patch.dict(os.environ, {"XDG_CACHE_HOME": "relative"}), patch.object(Path, "home", return_value=self.folder):
            paths = storage.shared_locations()
        self.assertTrue(paths["model_dir"].is_relative_to(self.folder / ".cache"))

    def test_new_requirements_select_a_different_runtime_but_the_same_model(self):
        a = storage.shared_locations(self.folder)
        with patch.object(storage, "digest", return_value="0" * 64):
            b = storage.shared_locations(self.folder)
        self.assertNotEqual(a["runtime_dir"], b["runtime_dir"])
        self.assertEqual(a["model_dir"], b["model_dir"])
        with patch.object(storage, "REVISION", "another-version"):
            c = storage.shared_locations(self.folder)
        self.assertNotEqual(a["model_dir"], c["model_dir"])
        self.assertEqual(a["runtime_dir"], c["runtime_dir"])

    def test_default_configuration_does_not_implicitly_install_runtime(self):
        common = self.folder / "common"
        result = subprocess.run([sys.executable, "-S", str(SCRIPTS / "configure-e5.py"),
            "--scope", str(self.scope), "--approved-scope-sha256", self.checksum,
            "--output", str(self.output)], env={**os.environ, "XDG_CACHE_HOME": str(common)},
            capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 1)
        self.assertIn("--prepare-runtime", result.stderr)
        self.assertFalse(common.exists())
        self.assertFalse(self.output.exists())

    def test_two_project_configs_use_one_default_model_directory(self):
        common = self.folder / "common"
        configurations = []
        for name in ("project-a", "project-b"):
            folder = self.folder / name
            folder.mkdir()
            scope = folder / "scope.json"
            scope.write_text(json.dumps({"scope_version": 1, "sources": [], "description": name}))
            checksum = hashlib.sha256(scope.read_bytes()).hexdigest()
            result = subprocess.run([sys.executable, "-S", str(SCRIPTS / "configure-e5.py"),
                "--scope", str(scope), "--approved-scope-sha256", checksum,
                "--runtime-python", sys.executable, "--output", str(folder / "config.json")],
                env={**os.environ, "XDG_CACHE_HOME": str(common)},
                capture_output=True, text=True, encoding="utf-8", check=True)
            configurations.append(json.loads((folder / "config.json").read_text()))
        self.assertEqual(configurations[0]["command"], configurations[1]["command"])
        self.assertNotEqual(configurations[0]["approved_scope_sha256"],
                            configurations[1]["approved_scope_sha256"])
        self.assertIn(str(common), configurations[0]["command"][-1])
        self.assertFalse(common.exists(), "Configuration without setup flags must not install anything")

    def fake_runtime_command(self, locations):
        def run(command, cache):
            if "venv" in command:
                locations["runtime_python"].parent.mkdir(parents=True)
                locations["runtime_python"].touch()
        return run

    @patch.object(storage.sys, "version_info", (3, 13))
    def test_prepared_runtime_is_reused_without_installation(self):
        locations = storage.shared_locations(self.folder)
        with patch.object(storage, "run", side_effect=self.fake_runtime_command(locations)) as runner:
            self.assertEqual(storage.prepare_runtime(locations), "created")
            self.assertEqual(sum("install" in c.args[0] for c in runner.call_args_list), 1)
        with patch.object(storage, "run") as runner:
            self.assertEqual(storage.prepare_runtime(locations), "reused")
            self.assertEqual(runner.call_count, 1)
            self.assertNotIn("install", runner.call_args.args[0])

    @patch.object(storage.sys, "version_info", (3, 13))
    def test_incomplete_existing_runtime_is_preserved(self):
        locations = storage.shared_locations(self.folder)
        locations["runtime_dir"].mkdir(parents=True)
        sentinel = locations["runtime_dir"] / "keep"
        sentinel.write_text("existing installation")
        with patch.object(storage, "run") as runner, self.assertRaises(ValueError):
            storage.prepare_runtime(locations)
        self.assertEqual(sentinel.read_text(), "existing installation")
        runner.assert_not_called()

    @patch.object(storage.sys, "version_info", (3, 13))
    def test_busy_shared_runtime_stops_duplicate_setup(self):
        locations = storage.shared_locations(self.folder)
        lock = locations["runtime_dir"].with_name(locations["runtime_dir"].name + ".lock")
        lock.mkdir(parents=True)
        with patch.object(storage, "run") as runner, self.assertRaisesRegex(ValueError, "retry"):
            storage.prepare_runtime(locations)
        runner.assert_not_called()
        self.assertTrue(lock.exists())

    @patch.object(storage.sys, "version_info", (3, 13))
    def test_failed_new_runtime_leaves_no_partial_installation(self):
        locations = storage.shared_locations(self.folder)
        with patch.object(storage, "run", side_effect=ValueError("installation failed")), self.assertRaises(ValueError):
            storage.prepare_runtime(locations)
        self.assertFalse(locations["runtime_dir"].exists())
        self.assertFalse(locations["runtime_dir"].with_name(locations["runtime_dir"].name + ".lock").exists())

    @patch.object(storage.sys, "version_info", (3, 13))
    def test_runtime_version_change_is_not_silently_reinstalled(self):
        locations = storage.shared_locations(self.folder)
        with patch.object(storage, "run", side_effect=self.fake_runtime_command(locations)):
            storage.prepare_runtime(locations)
        marker = locations["runtime_dir"] / "e5-runtime.json"
        old = marker.read_bytes()
        with patch.object(storage, "check_runtime", side_effect=ValueError("changed packages")), self.assertRaises(ValueError):
            storage.prepare_runtime(locations)
        self.assertEqual(marker.read_bytes(), old)

    def test_unsupported_python_is_rejected_before_writing(self):
        locations = storage.shared_locations(self.folder / "shared")
        with patch.object(storage.sys, "version_info", (3, 12)), self.assertRaisesRegex(ValueError, "3.13"):
            storage.prepare_runtime(locations)
        self.assertFalse((self.folder / "shared").exists())

    def test_concurrent_verified_model_file_is_reused(self):
        def concurrent_creation(source, destination):
            destination.write_bytes(b"fixture model")
            raise FileExistsError()
        with patch.object(setup, "FILES", self.artifact()), patch.object(setup.urllib.request, "urlopen",
                return_value=io.BytesIO(b"fixture model")), patch.object(setup.os, "link", side_effect=concurrent_creation):
            setup.download_model(self.folder)
        self.assertEqual((self.folder / "model.onnx").read_bytes(), b"fixture model")
        self.assertEqual({p.name for p in self.folder.iterdir()}, {"model.onnx", "scope.json"})


if __name__ == "__main__":
    unittest.main()
