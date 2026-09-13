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
  return value === null || value === undefined || value === "" || (Array.isArray(value) && value.length === 0);
}

function optionValues(field) {
  return new Set((field.options || []).map((option) => String(option.value)));
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
      if (field.required && isEmptyRequired(value)) {
        errors.push({ path: field.path, message: "Pflichtfeld ist leer." });
      }
      if ((field.widget === "select" || field.widget === "vocabulary_select") && field.options?.length) {
        const selected = field.widget === "vocabulary_select" && value && typeof value === "object" ? value.id : value;
        if (!isEmptyRequired(selected) && !optionValues(field).has(String(selected))) {
          errors.push({ path: field.path, message: "Auswahl ist nicht im Descriptor definiert." });
        }
      }
      if (field.widget === "repeater" && value !== undefined && !Array.isArray(value)) {
        errors.push({ path: field.path, message: "Wiederholfeld muss eine Liste sein." });
      }
    });
    return errors;
  }
}
