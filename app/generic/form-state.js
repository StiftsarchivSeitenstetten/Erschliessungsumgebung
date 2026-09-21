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

export function buildEditableSnapshot(moduleDescriptor, recordData = {}) {
  const snapshot = {};
  editableFields(moduleDescriptor).forEach((field) => {
    setPathValue(snapshot, field.path, cloneValue(getPathValue(recordData, field.path)));
  });
  return snapshot;
}

function isEmptyOptionalCreateValue(value) {
  return value === null || value === undefined || value === "" ||
    (Array.isArray(value) && value.length === 0) ||
    (value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === 0);
}

function deletePathAndEmptyParents(data, path) {
  const parts = path.split(".");

  function remove(current, index) {
    if (!current || typeof current !== "object" || Array.isArray(current)) return false;
    const key = parts[index];
    if (index === parts.length - 1) delete current[key];
    else if (remove(current[key], index + 1)) delete current[key];
    return Object.keys(current).length === 0;
  }

  remove(data, 0);
}

function hasPath(data, path) {
  let current = data;
  for (const part of path.split(".")) {
    if (!current || typeof current !== "object" || !Object.prototype.hasOwnProperty.call(current, part)) return false;
    current = current[part];
  }
  return true;
}

export function buildCreateSnapshot(moduleDescriptor, recordData = {}) {
  const snapshot = buildEditableSnapshot(moduleDescriptor, recordData);
  editableFields(moduleDescriptor).forEach((field) => {
    if (!field.required && isEmptyOptionalCreateValue(getPathValue(snapshot, field.path))) {
      deletePathAndEmptyParents(snapshot, field.path);
    }
  });
  return snapshot;
}

export function editableSnapshotsEqual(moduleDescriptor, left, right) {
  return valuesEqual(buildEditableSnapshot(moduleDescriptor, left), buildEditableSnapshot(moduleDescriptor, right));
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
    this.pendingCreatePayload = null;
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
    return buildEditableSnapshot(this.moduleDescriptor, recordData);
  }

  loadWorkingSnapshot(snapshot) {
    editableFields(this.moduleDescriptor).forEach((field) => {
      setPathValue(this.workingRecord, field.path, cloneValue(getPathValue(snapshot, field.path)));
    });
  }

  beginSave() {
    this.pendingSnapshot = cloneValue(this.workingRecord) || {};
    this.pendingCreatePayload = null;
    return this.buildPayload(this.pendingSnapshot);
  }

  beginCreateSave() {
    this.pendingSnapshot = cloneValue(this.workingRecord) || {};
    this.pendingCreatePayload = buildCreateSnapshot(this.moduleDescriptor, this.pendingSnapshot);
    return cloneValue(this.pendingCreatePayload);
  }

  confirmSave(confirmedRecord) {
    if (this.pendingSnapshot === null) throw new Error("Kein ausstehender Snapshot vorhanden.");
    const pending = this.pendingSnapshot;
    const latest = this.workingRecord;
    const confirmed = cloneValue(confirmedRecord) || {};
    const acknowledged = cloneValue(confirmed) || {};
    editableFields(this.moduleDescriptor).forEach((field) => {
      if (this.pendingCreatePayload !== null && !hasPath(this.pendingCreatePayload, field.path)) return;
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
    this.pendingCreatePayload = null;
  }

  cancelSave() {
    this.pendingSnapshot = null;
    this.pendingCreatePayload = null;
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
