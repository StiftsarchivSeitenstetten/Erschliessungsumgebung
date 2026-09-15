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
    this.reset(recordData);
  }

  get original() {
    return this.serverSnapshot;
  }

  get current() {
    return this.workingRecord;
  }

  reset(recordData = this.serverSnapshot) {
    this.serverSnapshot = cloneValue(recordData) || {};
    this.workingRecord = cloneValue(recordData) || {};
    this.pendingSnapshot = null;
  }

  discardChanges() {
    this.workingRecord = cloneValue(this.pendingSnapshot ?? this.serverSnapshot) || {};
  }

  getValue(path) {
    return getPathValue(this.workingRecord, path);
  }

  setValue(path, value) {
    setPathValue(this.workingRecord, path, cloneValue(value));
  }

  isDirty() {
    return !valuesEqual(this.buildPayload(this.serverSnapshot), this.buildPayload(this.workingRecord));
  }

  hasUnpersistedChanges() {
    const securedSnapshot = this.pendingSnapshot ?? this.serverSnapshot;
    return !valuesEqual(this.buildPayload(securedSnapshot), this.buildPayload(this.workingRecord));
  }

  changedPaths() {
    return editableFields(this.moduleDescriptor)
      .map((field) => field.path)
      .filter((path) => !valuesEqual(getPathValue(this.serverSnapshot, path), getPathValue(this.workingRecord, path)));
  }

  buildPayload(recordData = this.workingRecord) {
    const payload = {};
    editableFields(this.moduleDescriptor).forEach((field) => {
      setPathValue(payload, field.path, cloneValue(getPathValue(recordData, field.path)));
    });
    return payload;
  }

  beginSave() {
    this.pendingSnapshot = cloneValue(this.workingRecord) || {};
    return this.buildPayload(this.pendingSnapshot);
  }

  confirmSave(confirmedRecord) {
    if (this.pendingSnapshot === null) throw new Error("Kein ausstehender Snapshot vorhanden.");
    const pending = this.pendingSnapshot;
    const latest = this.workingRecord;
    const confirmed = cloneValue(confirmedRecord) || {};
    const acknowledged = cloneValue(confirmed) || {};
    editableFields(this.moduleDescriptor).forEach((field) => {
      setPathValue(acknowledged, field.path, cloneValue(getPathValue(pending, field.path)));
    });
    const nextWorking = cloneValue(acknowledged) || {};
    editableFields(this.moduleDescriptor).forEach((field) => {
      const latestValue = getPathValue(latest, field.path);
      if (!valuesEqual(latestValue, getPathValue(pending, field.path))) {
        setPathValue(nextWorking, field.path, cloneValue(latestValue));
      }
    });
    this.serverSnapshot = acknowledged;
    this.workingRecord = nextWorking;
    this.pendingSnapshot = null;
  }

  cancelSave() {
    this.pendingSnapshot = null;
  }

  applyServerValues(values) {
    Object.entries(values || {}).forEach(([path, value]) => {
      setPathValue(this.workingRecord, path, cloneValue(value));
      if (this.pendingSnapshot !== null) setPathValue(this.pendingSnapshot, path, cloneValue(value));
    });
  }

  validate() {
    const errors = [];
    editableFields(this.moduleDescriptor).forEach((field) => {
      const value = getPathValue(this.workingRecord, field.path);
      validateField(field, value, field.path, errors);
    });
    return errors;
  }
}
