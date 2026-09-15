from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PhotoUiStaticTest(unittest.TestCase):
    def test_search_results_open_records_in_new_tab(self):
        script = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        self.assertIn('link.textContent = "Datensatz öffnen"', script)
        self.assertIn('link.target = "_blank"', script)
        self.assertIn('link.rel = "noopener"', script)
        self.assertIn("öffnet in neuem Tab", script)
        self.assertNotIn('button.addEventListener("click", () => openExistingRecord(record.id))', script)

    def test_record_navigation_and_dirty_warning_are_present(self):
        html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="record-nav-top"', html)
        self.assertIn('id="record-nav-bottom"', html)
        self.assertIn("Vorheriger Datensatz", html)
        self.assertIn("Nächster Datensatz", html)
        self.assertIn("function hasUnsavedChanges()", script)
        self.assertIn("beforeunload", script)
        self.assertIn("Ungespeicherte Änderungen verwerfen", script)
        self.assertIn('id="discard-changes"', html)
        self.assertIn("function discardChanges()", script)
        self.assertIn('id="save-status"', html)
        self.assertIn("const SAVE_STATES", script)
        self.assertIn("function setSaveState(nextState)", script)

    def test_direct_record_url_parameter_is_supported(self):
        script = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        self.assertIn('new URLSearchParams(window.location.search).get("record")', script)
        self.assertIn("window.history.replaceState", script)

    def test_persistent_save_queue_assets_and_status_are_present(self):
        html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
        store = (ROOT / "app" / "generic" / "save-queue-store.js").read_text(encoding="utf-8")
        worker = (ROOT / "app" / "generic" / "save-queue.js").read_text(encoding="utf-8")
        self.assertIn('id="queue-status"', html)
        self.assertIn('id="retry-queue"', html)
        self.assertIn('id="open-queued-snapshot"', html)
        self.assertIn('id="discard-queued-save"', html)
        self.assertLess(html.index('src="generic/save-queue-store.js"'), html.index('src="app.js"'))
        self.assertLess(html.index('src="generic/save-queue.js"'), html.index('src="app.js"'))
        self.assertIn('DEFAULT_DATABASE_NAME = "Erschliessungsumgebung"', store)
        self.assertIn('DEFAULT_STORE_NAME = "save_queue"', store)
        self.assertNotIn("localStorage", store)
        self.assertIn('next.status !== "queued"', worker)
        self.assertIn("await store.remove", worker)


if __name__ == "__main__":
    unittest.main()
