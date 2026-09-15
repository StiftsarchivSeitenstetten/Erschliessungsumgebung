import { SERVER_MANAGED_PATHS } from "./form-state.js";
import { cloneValue, getPathValue, valuesEqual } from "./path-utils.js";

const STORAGE_PREFIX = "erschliessung.genericPreset.v1";
const LEGACY_KEY_PATTERN = /^erschliessung\..+\.activePreset\.v\d+$/;
const PRESET_FORBIDDEN_PATHS = new Set([
  ...SERVER_MANAGED_PATHS,
  "signatur.nummer",
  "signatur.anzeige",
  "signatur.status",
]);

export function presettableFields(moduleDescriptor) {
  return (moduleDescriptor.fields || []).filter((field) => (
    field.visible !== false &&
    field.editable === true &&
    field.presettable === true &&
    !PRESET_FORBIDDEN_PATHS.has(field.path) &&
    !field.path.startsWith("technik.")
  ));
}

export function isEmptyPresetValue(value) {
  if (value === null || value === undefined || value === "") return true;
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === "object") return Object.values(value).every(isEmptyPresetValue);
  return false;
}

export function normalizePresetValues(moduleDescriptor, rawValues) {
  if (!rawValues || typeof rawValues !== "object" || Array.isArray(rawValues)) return {};
  const fields = presettableFields(moduleDescriptor);
  const byPath = new Map(fields.map((field) => [field.path, field]));
  const byId = new Map();
  fields.forEach((field) => {
    if (!field.id) return;
    if (byId.has(field.id)) byId.set(field.id, null);
    else byId.set(field.id, field);
  });
  const normalized = {};
  Object.entries(rawValues).forEach(([storedPath, value]) => {
    const field = byPath.get(storedPath) || byId.get(storedPath);
    if (field) normalized[field.path] = cloneValue(value);
  });
  return normalized;
}

function parsePreset(serialized) {
  try {
    const parsed = JSON.parse(serialized);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

export class PresetStore {
  constructor(moduleDescriptor, username, storage = globalThis.localStorage) {
    this.moduleDescriptor = moduleDescriptor;
    this.username = username || "anonymous";
    this.storage = storage;
    this.key = `${STORAGE_PREFIX}:${encodeURIComponent(this.username)}:${encodeURIComponent(moduleDescriptor.module)}`;
  }

  envelope(values) {
    return { version: 1, module: this.moduleDescriptor.module, values };
  }

  readCurrent() {
    const serialized = this.storage?.getItem(this.key);
    if (serialized === null || serialized === undefined) return null;
    const parsed = parsePreset(serialized);
    if (!parsed || parsed.module !== this.moduleDescriptor.module) return this.envelope({});
    return this.envelope(normalizePresetValues(this.moduleDescriptor, parsed.values));
  }

  readLegacy() {
    if (!this.storage) return null;
    for (let index = 0; index < this.storage.length; index += 1) {
      const key = this.storage.key(index);
      if (!LEGACY_KEY_PATTERN.test(key || "")) continue;
      const parsed = parsePreset(this.storage.getItem(key));
      const values = normalizePresetValues(this.moduleDescriptor, parsed?.values);
      if (Object.keys(values).length) return this.saveValues(values);
    }
    return null;
  }

  load() {
    try {
      return this.readCurrent() || this.readLegacy() || this.envelope({});
    } catch {
      return this.envelope({});
    }
  }

  saveValues(values) {
    const preset = this.envelope(normalizePresetValues(this.moduleDescriptor, values));
    this.storage?.setItem(this.key, JSON.stringify(preset));
    return preset;
  }

  saveFromState(formState) {
    const values = {};
    presettableFields(this.moduleDescriptor).forEach((field) => {
      const value = formState.getValue(field.path);
      if (!isEmptyPresetValue(value)) values[field.path] = cloneValue(value);
    });
    return this.saveValues(values);
  }

  apply(formState, { includeInitialDefaults = false } = {}) {
    const preset = this.load();
    const changed = [];
    Object.entries(preset.values).forEach(([path, value]) => {
      const current = formState.getValue(path);
      const initial = getPathValue(formState.original, path);
      if (!isEmptyPresetValue(current) && !(includeInitialDefaults && valuesEqual(current, initial))) return;
      if (valuesEqual(current, value)) return;
      formState.setValue(path, value);
      changed.push(path);
    });
    return changed;
  }

  clear() {
    // Der leere Eintrag verhindert, dass ein erhaltenes Legacy-Preset erneut importiert wird.
    return this.saveValues({});
  }
}
