from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GenericFormRendererStaticTest(unittest.TestCase):
    def test_generic_shell_loads_module_descriptor_and_existing_records(self):
        html = (ROOT / "app" / "module" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "app" / "module" / "module.js").read_text(encoding="utf-8")

        self.assertIn('src="module.js?v=snapshot-1"', html)
        self.assertIn('href="/arbeitsbereiche?view=generic"', html)
        self.assertIn('id="save-record"', html)
        self.assertIn('id="new-record"', html)
        self.assertIn('id="save-preset"', html)
        self.assertIn('id="apply-preset"', html)
        self.assertIn('id="delete-preset"', html)
        self.assertIn('let mode = "read"', script)
        self.assertIn("new FormState(moduleDescriptor, data.record)", script)
        self.assertIn("new FormRenderer({ mode })", script)
        self.assertIn('params.get("module")', script)
        self.assertIn("/api/modules/${encodeURIComponent(moduleKey)}", script)
        self.assertIn("/records", script)
        self.assertIn("renderer.render(currentDescriptor, currentFormState)", script)
        self.assertNotIn('method: "POST"', script)
        self.assertNotIn('method: "PUT"', script)
        self.assertNotIn('method: "PATCH"', script)
        self.assertNotIn('method: "DELETE"', script)
        self.assertIn("Payload anzeigen", html)
        self.assertIn("Änderungen verwerfen", html)
        self.assertIn('disabled>Speichern</button>', html)
        self.assertNotIn("nur lokal erzeugt und nicht versendet", html)

    def test_form_renderer_uses_descriptor_metadata_without_photo_fields(self):
        script = (ROOT / "app" / "generic" / "form-renderer.js").read_text(encoding="utf-8")

        self.assertIn("export class FormRenderer", script)
        self.assertIn("moduleDescriptor.sections", script)
        self.assertIn("moduleDescriptor.fields", script)
        self.assertIn("field.visible === false", script)
        self.assertIn("field.editable", script)
        self.assertIn("field.presettable", script)
        self.assertIn("readIntoState", script)
        self.assertIn("widgetRegistry.readValue", script)
        self.assertIn("if (value !== undefined) formState.setValue", script)
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
        self.assertIn("renderRepeaterItem", script)
        self.assertIn("item_fields", script)
        self.assertIn("context.renderField", script)
        self.assertIn("getPathValue(item, itemField.path)", script)
        self.assertIn("readValue(context, root)", script)
        self.assertIn("setValue(context, root, value)", script)
        self.assertIn("Eintrag hinzufügen", script)
        self.assertIn("Eintrag entfernen", script)
        self.assertIn("JSON.parse(text)", script)
        self.assertIn("parseNullableInteger", script)
        self.assertIn("vocabularyFieldOptions", script)
        self.assertIn("canonicalTermReference", script)
        self.assertIn("unbekannter Begriff", (ROOT / "app" / "generic" / "vocabulary-client.js").read_text(encoding="utf-8"))

    def test_path_utils_offer_generic_dot_path_access_and_formatting(self):
        script = (ROOT / "app" / "generic" / "path-utils.js").read_text(encoding="utf-8")

        self.assertIn("export function getPathValue", script)
        self.assertIn('path.split(".").reduce', script)
        self.assertIn("export function formatStructuredValue", script)
        self.assertIn("export function formatDateValue", script)
        self.assertIn("export function formatDateRangeValue", script)

    def test_form_state_builds_payload_from_editable_visible_fields_only(self):
        script = (ROOT / "app" / "generic" / "form-state.js").read_text(encoding="utf-8")

        self.assertIn("export class FormState", script)
        self.assertIn("this.serverSnapshot = cloneValue(recordData)", script)
        self.assertIn("this.workingRecord = cloneValue(recordData)", script)
        self.assertIn("this.pendingSnapshot = null", script)
        self.assertIn("beginSave()", script)
        self.assertIn("confirmSave(confirmedRecord)", script)
        self.assertIn("cancelSave()", script)
        self.assertIn("discardChanges()", script)
        self.assertIn("isDirty()", script)
        self.assertIn("changedPaths()", script)
        self.assertIn("buildPayload(recordData = this.workingRecord)", script)
        self.assertIn("field.visible !== false", script)
        self.assertIn("field.editable === true", script)
        self.assertIn("!SERVER_MANAGED_PATHS.has(field.path)", script)
        self.assertIn('"technik.erstellt_am"', script)
        self.assertIn('"technik.geaendert_von"', script)
        self.assertIn("validate()", script)
        self.assertIn("Pflichtfeld ist leer", script)

    def test_generic_frontend_keeps_writes_in_dedicated_generic_components(self):
        for path in (
            ROOT / "app" / "generic" / "form-state.js",
            ROOT / "app" / "generic" / "form-renderer.js",
            ROOT / "app" / "generic" / "widget-registry.js",
            ROOT / "app" / "generic" / "vocabulary-client.js",
            ROOT / "app" / "module" / "module.js",
        ):
            script = path.read_text(encoding="utf-8")
            for forbidden in ('method: "POST"', 'method: "PATCH"', 'method: "DELETE"'):
                self.assertNotIn(forbidden, script)
            for forbidden in ("foto_papierabzuege", "dargestellte_personen", "beschriftung", "fotograf"):
                self.assertNotIn(forbidden, script)
        update = (ROOT / "app" / "generic" / "record-update.js").read_text(encoding="utf-8")
        self.assertIn('method: "PUT"', update)
        self.assertNotIn('method: "POST"', update)
        create = (ROOT / "app" / "generic" / "record-create.js").read_text(encoding="utf-8")
        self.assertIn('method: "POST"', create)
        self.assertNotIn('method: "PUT"', create)
        for forbidden in ("foto_papierabzuege", "dargestellte_personen", "beschriftung", "fotograf"):
            self.assertNotIn(forbidden, create)

    def test_vocabulary_client_loads_generic_read_only_endpoint(self):
        script = (ROOT / "app" / "generic" / "vocabulary-client.js").read_text(encoding="utf-8")
        self.assertIn("/api/vocabularies/", script)
        self.assertIn("field.vocabulary", script)
        self.assertIn("term.active", script)
        self.assertIn("vocabulary_id", script)
        for forbidden in ("dokumenttyp", "brief", "absender", "foto_papierabzuege"):
            self.assertNotIn(forbidden, script)

    def test_preset_component_is_descriptor_driven_without_photo_fields(self):
        script = (ROOT / "app" / "generic" / "preset-store.js").read_text(encoding="utf-8")

        self.assertIn("field.presettable === true", script)
        self.assertIn("field.visible !== false", script)
        self.assertIn("field.editable === true", script)
        self.assertIn("SERVER_MANAGED_PATHS", script)
        self.assertIn("includeInitialDefaults", script)
        self.assertIn("readLegacy", script)
        for forbidden in ("foto_papierabzuege", "beschriftung", "fotograf", "sammler"):
            self.assertNotIn(forbidden, script)


if __name__ == "__main__":
    unittest.main()
