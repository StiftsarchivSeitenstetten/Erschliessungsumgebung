import assert from "node:assert/strict";
import { FormState } from "../app/generic/form-state.js";
import {
  PresetStore,
  isEmptyPresetValue,
  normalizePresetValues,
  presettableFields,
} from "../app/generic/preset-store.js";

class MemoryStorage {
  constructor() { this.items = new Map(); }
  get length() { return this.items.size; }
  key(index) { return [...this.items.keys()][index] ?? null; }
  getItem(key) { return this.items.has(key) ? this.items.get(key) : null; }
  setItem(key, value) { this.items.set(key, String(value)); }
  removeItem(key) { this.items.delete(key); }
}

const fields = [
  { id: "title", path: "content.title", label: "Titel", widget: "text", visible: true, editable: true, presettable: true },
  { id: "language", path: "content.language", label: "Sprache", widget: "select", visible: true, editable: true, presettable: true },
  { id: "flag", path: "content.flag", label: "Merkmal", widget: "checkbox", visible: true, editable: true, presettable: true },
  { id: "people", path: "content.people", label: "Personen", widget: "repeater", visible: true, editable: true, presettable: true },
  { id: "date", path: "content.date", label: "Datum", widget: "date", visible: true, editable: true, presettable: true },
  { id: "range", path: "content.range", label: "Zeitraum", widget: "date_range", visible: true, editable: true, presettable: true },
  { id: "ordinary", path: "content.ordinary", label: "Normal", widget: "text", visible: true, editable: true, presettable: false },
  { id: "readonly", path: "content.readonly", label: "Nur lesen", widget: "text", visible: true, editable: false, presettable: true },
  { id: "hidden", path: "content.hidden", label: "Verborgen", widget: "text", visible: false, editable: true, presettable: true },
  { id: "created", path: "technik.erstellt_am", label: "Technik", widget: "text", visible: true, editable: true, presettable: true },
  { id: "signature", path: "signatur.nummer", label: "Nummer", widget: "text", visible: true, editable: true, presettable: true },
];
const descriptor = { module: "module_a", fields };
const storage = new MemoryStorage();
const store = new PresetStore(descriptor, "editor", storage);

assert.deepEqual(presettableFields(descriptor).map(field => field.path), [
  "content.title", "content.language", "content.flag", "content.people", "content.date", "content.range",
]);
assert.equal(isEmptyPresetValue({ year: null, month: null, day: null }), true);
assert.equal(isEmptyPresetValue(false), false);

const structured = {
  content: {
    title: "Vorbelegt",
    language: "la",
    flag: true,
    people: [{ name: "Person Eins", role: { id: "creator", label: "Urheber" } }],
    date: { year: 1900, month: 5, day: 2 },
    range: { from: { year: 1900 }, to: { year: 1902 }, display: "1900–1902" },
    ordinary: "nicht speichern",
    readonly: "nicht speichern",
    hidden: "nicht speichern",
  },
  technik: { erstellt_am: "nicht speichern" },
};
const sourceState = new FormState(descriptor, structured);
const saved = store.saveFromState(sourceState);
assert.equal(saved.module, "module_a");
assert.equal(saved.version, 1);
assert.deepEqual(Object.keys(saved.values), presettableFields(descriptor).map(field => field.path));
assert.deepEqual(new PresetStore(descriptor, "editor", storage).load(), saved);

const otherUser = new PresetStore(descriptor, "other", storage);
const otherModule = new PresetStore({ ...descriptor, module: "module_b" }, "editor", storage);
assert.deepEqual(otherUser.load().values, {});
assert.deepEqual(otherModule.load().values, {});

const targetState = new FormState(descriptor, {
  content: {
    title: "Manuell",
    language: "",
    flag: false,
    people: [],
    date: { year: null, month: null, day: null },
    range: null,
  },
});
const changed = store.apply(targetState);
assert.equal(targetState.getValue("content.title"), "Manuell");
assert.equal(targetState.getValue("content.language"), "la");
assert.equal(targetState.getValue("content.flag"), false);
assert.deepEqual(targetState.getValue("content.people"), structured.content.people);
assert.deepEqual(targetState.getValue("content.date"), structured.content.date);
assert.deepEqual(targetState.getValue("content.range"), structured.content.range);
assert.equal(changed.includes("content.title"), false);
assert.equal(targetState.isDirty(), true);

const newState = new FormState(descriptor, { content: { language: "de", flag: false } });
store.apply(newState, { includeInitialDefaults: true });
assert.equal(newState.getValue("content.language"), "la");
assert.equal(newState.getValue("content.flag"), true);
newState.discardChanges();
assert.equal(newState.getValue("content.language"), "de");
assert.equal(store.load().values["content.language"], "la");

storage.setItem(store.key, JSON.stringify({
  module: "module_a",
  values: { "content.title": "Erlaubt", "content.hidden": "Nein", "technik.erstellt_am": "Nein" },
}));
assert.deepEqual(store.load().values, { "content.title": "Erlaubt" });

const legacyStorage = new MemoryStorage();
legacyStorage.setItem("erschliessung.legacy.activePreset.v2", JSON.stringify({ values: { title: "Alt", hidden: "Nein" } }));
const legacyStore = new PresetStore(descriptor, "legacy-user", legacyStorage);
assert.deepEqual(legacyStore.load().values, { "content.title": "Alt" });
assert.notEqual(legacyStorage.getItem("erschliessung.legacy.activePreset.v2"), null);
legacyStore.clear();
assert.deepEqual(legacyStore.load().values, {});
assert.notEqual(legacyStorage.getItem("erschliessung.legacy.activePreset.v2"), null);

assert.deepEqual(normalizePresetValues(descriptor, { title: "Kurz-ID", ordinary: "Nein" }), {
  "content.title": "Kurz-ID",
});

console.log("generic preset state: ok");
