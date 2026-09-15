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

    def test_direct_record_url_parameter_is_supported(self):
        script = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        self.assertIn('new URLSearchParams(window.location.search).get("record")', script)
        self.assertIn("window.history.replaceState", script)


if __name__ == "__main__":
    unittest.main()
