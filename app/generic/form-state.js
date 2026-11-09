import { cloneValue, getPathValue, setPathValue, valuesEqual } from "./path-utils.js";
import { decimalIssue } from "./numeric-input.js?v=thoma-review-1";

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
    const value = getPathValue(recordData, field.path);
    setPathValue(snapshot, field.path, editableFieldValue(field, value));
  });
  return snapshot;
}

function hasProtectedItems(field) {
  return (field.item_fields || []).some(child => child.visible === false || child.editable !== true || hasProtectedItems(child));
}

function editableFieldValue(field, value) {
  requireCanonicalRepeater(field, value);
  if (field.widget !== "repeater" || !Array.isArray(value) || !hasProtectedItems(field)) return cloneValue(value);
  return value.map(item => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return cloneValue(item);
    const result = {};
    editableFields({fields: field.item_fields || []}).forEach(child => {
      const childValue = getPathValue(item, child.path);
      if (childValue !== undefined) setPathValue(result, child.path, editableFieldValue(child, childValue));
    });
    return result;
  });
}

function requireCanonicalRepeater(field, value, {snapshot = false, path = field.path} = {}) {
  if (field.widget !== "repeater" || !hasProtectedItems(field)) return;
  if (field.repeater_policy !== "constants") throw new Error(`${path}: Geschützte Wiederholfelder ohne erforderliche Schema-Konstanten werden nicht unterstützt.`);
  for (const [index, item] of (Array.isArray(value) ? value : []).entries()) {
    if (!item || typeof item !== "object" || Array.isArray(item)) continue;
    const children = field.item_fields || [];
    const declared = new Set(children.map(child => child.path));
    const checkPaths = (node, prefix = "") => {
      for (const [key, entry] of Object.entries(node)) {
        const relative = prefix ? `${prefix}.${key}` : key;
        if (declared.has(relative)) continue;
        if (!children.some(child => child.path.startsWith(relative + ".")) || !entry || typeof entry !== "object" || Array.isArray(entry)) {
          throw new Error(`${path}.${index}.${relative}: Nicht deklarierte lokale Zeileninformation kann nicht sicher wiederhergestellt werden.`);
        }
        checkPaths(entry, relative);
      }
    };
    checkPaths(item);
    for (const child of children) {
      const current = getPathValue(item, child.path);
      const fullPath = `${path}.${index}.${child.path}`;
      if (child.editable === true && child.visible !== false) {
        requireCanonicalRepeater(child, current, {snapshot, path: fullPath});
      } else if (child.visible !== false) {
        if (!child.required || !Object.hasOwn(child, "const")) throw new Error(`${fullPath}: Erforderliches Schema-const fehlt.`);
        if (current !== undefined && (snapshot || !valuesEqual(current, child.const))) throw new Error(`${fullPath}: Geschützter lokaler Wert kann nicht übernommen werden.`);
      } else if (current !== undefined) {
        throw new Error(`${fullPath}: Unsichtbarer lokaler Wert kann nicht übernommen werden.`);
      }
    }
  }
}

export function validateRepeaterSnapshot(moduleDescriptor, snapshot) {
  editableFields(moduleDescriptor).forEach(field => requireCanonicalRepeater(field,
    getPathValue(snapshot, field.path), {snapshot: true}));
}

// Display-only values come exclusively from visible required schema constants.
// No row from a baseline is ever paired with an edited row.
function restoreProtectedValues(field, value) {
  requireCanonicalRepeater(field, value);
  if (field.widget !== "repeater" || !Array.isArray(value) || !hasProtectedItems(field)) return cloneValue(value);
  return value.map(item => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return cloneValue(item);
    const result = cloneValue(item);
    (field.item_fields || []).forEach(child => {
      if (child.visible === false) return;
      const current = getPathValue(result, child.path);
      if (child.editable === true) {
        if (current !== undefined) setPathValue(result, child.path, restoreProtectedValues(child, current));
      } else setPathValue(result, child.path, cloneValue(child.const));
    });
    return result;
  });
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
  if (field.visible === false || field.editable !== true) return;
  if (field.widget === "decimal") {
    const message = decimalIssue(field, value);
    if (message) errors.push({ path, message, input: true });
  }
  if (field.widget === "text_select" && field.required && (typeof value !== "string" || !value.trim())) {
    errors.push({ path, message: "Pflichtfeld ist leer.", input: true });
  }
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
    this.canonicalRecord = cloneValue(recordData) || {};
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
    const snapshot = buildEditableSnapshot(this.moduleDescriptor, recordData);
    editableFields(this.moduleDescriptor).forEach(field => {
      if (!field.required && !hasPath(this.canonicalRecord, field.path) && isEmptyOptionalCreateValue(getPathValue(snapshot, field.path))) {
        deletePathAndEmptyParents(snapshot, field.path);
      }
    });
    return snapshot;
  }

  loadWorkingSnapshot(snapshot) {
    validateRepeaterSnapshot(this.moduleDescriptor, snapshot);
    editableFields(this.moduleDescriptor).forEach((field) => {
      setPathValue(this.workingRecord, field.path, restoreProtectedValues(field,
        getPathValue(snapshot, field.path)));
    });
  }

  beginSave(options) {
    this.requireValidInputs(options);
    this.pendingSnapshot = cloneValue(this.workingRecord) || {};
    this.pendingCreatePayload = null;
    return this.buildPayload(this.pendingSnapshot);
  }

  beginCreateSave(options) {
    this.requireValidInputs(options);
    this.pendingSnapshot = cloneValue(this.workingRecord) || {};
    this.pendingCreatePayload = buildCreateSnapshot(this.moduleDescriptor, this.pendingSnapshot);
    return cloneValue(this.pendingCreatePayload);
  }

  confirmSave(confirmedRecord) {
    if (this.pendingSnapshot === null) throw new Error("Kein ausstehender Snapshot vorhanden.");
    const pending = this.pendingSnapshot;
    const latest = this.workingRecord;
    const confirmed = cloneValue(confirmedRecord) || {};
    this.buildPayload(confirmed);
    const acknowledged = cloneValue(confirmed) || {};
    editableFields(this.moduleDescriptor).forEach((field) => {
      if (this.pendingCreatePayload !== null && !hasPath(this.pendingCreatePayload, field.path) && !this.moduleDescriptor.create?.workflow) return;
      setPathValue(acknowledged, field.path, restoreProtectedValues(field,
        getPathValue(pending, field.path)));
    });
    const nextWorking = cloneValue(acknowledged) || {};
    editableFields(this.moduleDescriptor).forEach((field) => {
      const latestValue = getPathValue(latest, field.path);
      if (!valuesEqual(latestValue, getPathValue(pending, field.path))) {
        setPathValue(nextWorking, field.path, restoreProtectedValues(field, latestValue));
      }
    });
    this.canonicalRecord = cloneValue(confirmed);
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

  isFreeTextInput(path) {
    const parts = path.split(".").filter(part => !/^\d+$/.test(part));
    let fields = this.moduleDescriptor.fields;
    let field;
    while (parts.length) {
      field = fields?.find(candidate => parts.slice(0, candidate.path.split(".").length).join(".") === candidate.path);
      if (!field) return false;
      parts.splice(0, field.path.split(".").length);
      fields = field.item_fields;
    }
    return field?.widget === "text_select";
  }

  requireValidInputs({draft = false} = {}) {
    const errors = this.validate().filter(error => error.input && !(draft && error.path && this.isFreeTextInput(error.path)));
    if (errors.length) throw new Error(errors.map(error => `${error.path}: ${error.message}`).join(" "));
  }
}
