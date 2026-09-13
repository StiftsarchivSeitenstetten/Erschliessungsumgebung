from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GenericFormRendererStaticTest(unittest.TestCase):
    def test_generic_shell_loads_module_descriptor_and_read_only_records(self):
        html = (ROOT / "app" / "module" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "app" / "module" / "module.js").read_text(encoding="utf-8")

        self.assertIn('src="module.js"', html)
        self.assertIn('href="/arbeitsbereiche"', html)
        self.assertIn("Read-only Preview", html)
        self.assertIn("new FormRenderer({ readOnly: true })", script)
        self.assertIn('params.get("module")', script)
        self.assertIn("/api/modules/${encodeURIComponent(moduleKey)}", script)
        self.assertIn("/records", script)
        self.assertIn("renderer.render(moduleDescriptor, data.record)", script)
        self.assertNotIn('method: "POST"', script)
        self.assertNotIn('method: "PUT"', script)
        self.assertNotIn('method: "PATCH"', script)
        self.assertNotIn('method: "DELETE"', script)

    def test_form_renderer_uses_descriptor_metadata_without_photo_fields(self):
        script = (ROOT / "app" / "generic" / "form-renderer.js").read_text(encoding="utf-8")

        self.assertIn("export class FormRenderer", script)
        self.assertIn("moduleDescriptor.sections", script)
        self.assertIn("moduleDescriptor.fields", script)
        self.assertIn("field.visible === false", script)
        self.assertIn("field.editable", script)
        self.assertIn("field.presettable", script)
        self.assertIn(".sort((a, b) => a.order - b.order)", script)
        self.assertIn("this.widgetRegistry.render(field.widget", script)
        for forbidden in (
            "foto_papierabzuege",
            "papierabzuege",
            "beschriftung",
            "beschreibung",
            "fotograf",
            "dargestellte_personen",
            "erschliessung",
        ):
            self.assertNotIn(forbidden, script)

    def test_widget_registry_declares_required_read_only_widgets(self):
        script = (ROOT / "app" / "generic" / "widget-registry.js").read_text(encoding="utf-8")

        for widget in (
            "text",
            "textarea",
            "checkbox",
            "select",
            "date",
            "date_range",
            "vocabulary_select",
            "repeater",
        ):
            self.assertIn(f'registry.register("{widget}"', script)
        self.assertIn("Unbekanntes Widget", script)
        self.assertIn("renderRepeater", script)
        self.assertIn("item_fields", script)
        self.assertIn("context.renderField", script)
        self.assertIn("getPathValue(item, itemField.path)", script)

    def test_path_utils_offer_generic_dot_path_access_and_formatting(self):
        script = (ROOT / "app" / "generic" / "path-utils.js").read_text(encoding="utf-8")

        self.assertIn("export function getPathValue", script)
        self.assertIn('path.split(".").reduce', script)
        self.assertIn("export function formatStructuredValue", script)
        self.assertIn("export function formatDateValue", script)
        self.assertIn("export function formatDateRangeValue", script)


if __name__ == "__main__":
    unittest.main()
