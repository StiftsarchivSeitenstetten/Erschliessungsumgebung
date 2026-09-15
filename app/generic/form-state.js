import { cloneValue, getPathValue, setPathValue, valuesEqual } from "./path-utils.js";

export const SERVER_MANAGED_PATHS = new Set([
  "id",
  "base_revision",
  "revision",
  "technik.erstellt_am",
  "technik.erstellt_von",
  "technik.geaendert_am",
  "technik.geaendert_von"
]);

function editableFields(moduleDescriptor) {
  return (moduleDescriptor.fields || []).filter((field) => (
    field.visible !== false &&
    field.editable === true &&
    !SERVER_MANAGED_PATHS.has(field.path)
  ));
}

function visibleFields(moduleDescriptor) {
  return (moduleDescriptor.fields || []).filter((field) => field.visible !== false);
}

function isEmptyRequired(value) {
  return value === undefined;
}

function optionValues(field) {
  return new Set((field.options || []).map((option) => String(option.value)));
}

function validateField(field, value, path, errors) {
  if (field.required && isEmptyRequired(value)) {
    errors.push({ path, message: "Pflichtfeld ist leer." });
  }
  if (field.widget === "select" && field.options?.length) {
    const selected = value && typeof value === "object" && "code" in value ? value.code : value;
    if (selected !== null && selected !== undefined && selected !== "" && !optionValues(field).has(String(selected))) {
      errors.push({ path, message: "Auswahl ist nicht im Descriptor definiert." });
    }
  }
  if (field.widget === "vocabulary_select" && value !== null && value !== undefined) {
    if (typeof value !== "object" || !value.id) {
      errors.push({ path, message: "Vocabulary-Wert benötigt eine stabile Term-ID." });
    } else if (value.vocabulary_id && value.vocabulary_id !== field.vocabulary) {
      errors.push({ path, message: "Vocabulary-ID passt nicht zum Feld." });
    } else if (!(field.vocabulary_terms || []).some(term => term.id === value.id)) {
      errors.push({ path, message: `Unbekannte Term-ID: ${value.id}` });
    }
  }
  if (field.widget === "repeater") {
    if (value !== undefined && !Array.isArray(value)) {
      errors.push({ path, message: "Wiederholfeld muss eine Liste sein." });
    } else {
      (value || []).forEach((item, index) => (field.item_fields || []).forEach(itemField => {
        validateField(itemField, getPathValue(item, itemField.path), `${path}.${index}.${itemField.path}`, errors);
      }));
    }
  }
}

export class FormState {
  constructor(moduleDescriptor, recordData = {}) {
    this.moduleDescriptor = moduleDescriptor;
    this.original = cloneValue(recordData) || {};
    this.current = cloneValue(recordData) || {};
  }

  reset(recordData = this.original) {
    this.original = cloneValue(recordData) || {};
    this.current = cloneValue(recordData) || {};
  }

  discardChanges() {
    this.current = cloneValue(this.original) || {};
  }

  getValue(path) {
    return getPathValue(this.current, path);
  }

  setValue(path, value) {
    setPathValue(this.current, path, cloneValue(value));
  }

  isDirty() {
    return !valuesEqual(this.original, this.current);
  }

  changedPaths() {
    return visibleFields(this.moduleDescriptor)
      .map((field) => field.path)
      .filter((path) => !valuesEqual(getPathValue(this.original, path), getPathValue(this.current, path)));
  }

  buildPayload() {
    const payload = {};
    editableFields(this.moduleDescriptor).forEach((field) => {
      setPathValue(payload, field.path, cloneValue(getPathValue(this.current, field.path)));
    });
    return payload;
  }

  validate() {
    const errors = [];
    editableFields(this.moduleDescriptor).forEach((field) => {
      const value = getPathValue(this.current, field.path);
      validateField(field, value, field.path, errors);
    });
    return errors;
  }
}
