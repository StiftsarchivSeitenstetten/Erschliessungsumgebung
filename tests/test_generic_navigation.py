from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace

from integration_tests.index_github import make_indexed_test_module


ROOT = Path(__file__).resolve().parents[1]


class GenericNavigationTest(unittest.TestCase):
    def test_update_state(self):
        node = shutil.which("node") or str(
            Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
        )
        if not Path(node).exists():
            self.skipTest("Node.js required")
        subprocess.run([node, "tests/record_update.mjs"], cwd=ROOT, check=True, capture_output=True)
        source = (ROOT / "app/generic/record-update.js").read_text()
        for forbidden in ('method: "POST"', "foto_papierabzuege", "beschriftung"):
            self.assertNotIn(forbidden, source)

    def test_executable_navigation_state(self):
        node = shutil.which("node")
        if not node:
            bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
            node = str(bundled) if bundled.exists() else None
        if not node:
            self.skipTest("Node.js is required for frontend state assertions")
        subprocess.run([node, "tests/navigation_state.mjs"], cwd=ROOT, check=True, capture_output=True)

    def test_descriptor_filters_list_and_search_by_role(self):
        with tempfile.TemporaryDirectory() as directory:
            module = make_indexed_test_module(Path(directory))
            module = replace(module, search_config={**module.search_config, "lookup":["daten.text", "daten.intern"]})
            volunteer = module.descriptor_for_role("ehrenamtlich")
            editor = module.descriptor_for_role("redaktion")
            for key in ("fulltext", "lookup"):
                self.assertNotIn("daten.intern", volunteer["search"][key])
                self.assertIn("daten.intern", editor["search"][key])
            self.assertNotIn("daten.intern", [c["path"] for c in volunteer["list"]["columns"]])
            self.assertIn("daten.intern", [c["path"] for c in editor["list"]["columns"]])

    def test_navigation_is_generic_and_guarded(self):
        script = (ROOT / "app/module/module.js").read_text()
        component = (ROOT / "app/generic/record-list.js").read_text()
        for forbidden in ("foto_papierabzuege", "beschriftung", "row.signatur", "fotograf"):
            self.assertNotIn(forbidden, script + component)
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            self.assertNotIn(f'method: "{method}"', script)
        self.assertIn("dialog.showModal()", script)
        self.assertIn('$("#change-module").addEventListener', script)
        self.assertIn('window.addEventListener("popstate"', script)
        self.assertIn("if (!await allowNavigation()) return", script)
        self.assertIn("request !== generation", script)
        self.assertIn("updatePayloadPreview();", script)
        self.assertIn("false, true", script)
        self.assertNotIn(".sort(", component)


if __name__ == "__main__":
    unittest.main()
