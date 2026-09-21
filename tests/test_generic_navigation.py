from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace

from integration_tests.index_github import make_indexed_test_module


ROOT = Path(__file__).resolve().parents[1]


class GenericNavigationTest(unittest.TestCase):
    def test_vocabulary_state(self):
        node = shutil.which("node") or str(
            Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
        )
        if not Path(node).exists():
            self.skipTest("Node.js required")
        subprocess.run([node, "tests/vocabulary_state.mjs"], cwd=ROOT, check=True, capture_output=True)

    def test_vocabulary_administration_state(self):
        node = shutil.which("node") or str(
            Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
        )
        if not Path(node).exists():
            self.skipTest("Node.js required")
        subprocess.run([node, "tests/vocabulary_admin.mjs"], cwd=ROOT, check=True, capture_output=True)

    def test_vocabulary_administration_page_is_generic_and_accessible(self):
        html = (ROOT / "app" / "vocabularies" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "app" / "vocabularies" / "vocabularies.js").read_text(encoding="utf-8")
        state = (ROOT / "app" / "generic" / "vocabulary-admin.js").read_text(encoding="utf-8")
        self.assertIn('role="alert"', html)
        self.assertIn('role="status"', html)
        self.assertIn("Vocabulary neu laden", html)
        self.assertIn("bleibt für bestehende Datensätze erhalten", html)
        self.assertIn("showModal()", script)
        self.assertNotIn("deleteTerm", script + state)
        for vocabulary_id in ("dokumenttypen", "rollen", "bearbeitungsstatus"):
            self.assertNotIn(vocabulary_id, script + state)

    def test_preset_state(self):
        node = shutil.which("node") or str(
            Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
        )
        if not Path(node).exists():
            self.skipTest("Node.js required")
        subprocess.run([node, "tests/preset_state.mjs"], cwd=ROOT, check=True, capture_output=True)

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

    def test_create_state(self):
        node = shutil.which("node") or str(
            Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
        )
        if not Path(node).exists():
            self.skipTest("Node.js required")
        subprocess.run([node, "tests/record_create.mjs"], cwd=ROOT, check=True, capture_output=True)
        subprocess.run([node, "tests/create_queue.mjs"], cwd=ROOT, check=True, capture_output=True)
        subprocess.run([node, "tests/recovery_queue.mjs"], cwd=ROOT, check=True, capture_output=True)
        subprocess.run([node, "tests/queue_isolation.mjs"], cwd=ROOT, check=True, capture_output=True)
        source = (ROOT / "app/generic/record-create.js").read_text()
        self.assertIn('method: "POST"', source)
        for forbidden in ("foto_papierabzuege", "beschriftung", "fotograf", "signatur.format"):
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
        self.assertIn("saveQueueProcessor.enqueueCreate", script)
        self.assertIn("currentCreateAwaitingReservation()", script)
        self.assertIn("scheduleQueueProcessing()", script)
        self.assertIn("saveQueueProcessor?.retryFirst()", script)
        self.assertIn("openQueuedSnapshot", script)
        self.assertIn("saveQueueProcessor.discard", script)
        open_recovery = script[script.index("async function openQueuedSnapshot"):script.index("function scheduleQueueProcessing")]
        self.assertIn("updateQueueStatus(queueEntries);", open_recovery)
        discard_recovery = script[script.index('$("#discard-queue-entry").addEventListener'):script.index("run(init);")]
        self.assertLess(discard_recovery.index("await saveQueueProcessor.discard"), discard_recovery.index("queueContexts.delete"))
        self.assertIn("updateSaveButton();", discard_recovery)
        self.assertIn('module-save-queue.js?v=queue-recovery-2', script)
        self.assertIn('new FormState(currentDescriptor, currentDescriptor.empty_record || {})', script)
        self.assertIn("currentFormState.reset(currentFormState.current)", script)
        self.assertIn("currentCreate || currentUpdate", script)
        self.assertIn('query.get("new") === "1"', script)
        self.assertNotIn(".sort(", component)


if __name__ == "__main__":
    unittest.main()
