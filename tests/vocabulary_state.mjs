import assert from "node:assert/strict";
import { FormState } from "../app/generic/form-state.js";
import { PresetStore } from "../app/generic/preset-store.js";
import {
  VocabularyClient,
  canonicalTermReference,
  vocabularyFieldOptions,
} from "../app/generic/vocabulary-client.js";

class MemoryStorage {
  constructor() { this.items = new Map(); }
  get length() { return this.items.size; }
  key(index) { return [...this.items.keys()][index] ?? null; }
  getItem(key) { return this.items.has(key) ? this.items.get(key) : null; }
  setItem(key, value) { this.items.set(key, String(value)); }
}

const terms = [
  { id: "letter", label: "Brief", active: true, sort_order: 10 },
  { id: "fax", label: "Telefax", active: false, sort_order: 20 },
];
const field = {
  id: "kind", path: "data.kind", widget: "vocabulary_select", vocabulary: "document_types",
  visible: true, editable: true, presettable: true, vocabulary_terms: terms,
};

assert.deepEqual(canonicalTermReference(field, "letter"), { id: "letter", vocabulary_id: "document_types" });
assert.deepEqual(vocabularyFieldOptions(field, { id: "letter", vocabulary_id: "document_types" }).options, [
  { value: "letter", label: "Brief" },
]);
assert.deepEqual(vocabularyFieldOptions(field, { id: "fax", vocabulary_id: "document_types" }).options, [
  { value: "letter", label: "Brief" }, { value: "fax", label: "Telefax (inaktiv)" },
]);
const unknown = vocabularyFieldOptions(field, { id: "missing", vocabulary_id: "document_types" });
assert.equal(unknown.options[1].label, "missing (unbekannter Begriff)");
assert.match(unknown.issue, /Unbekannte Term-ID/);

let requests = 0;
const responses = {
  document_types: { id: "document_types", label: "Dokumenttypen", terms },
  roles: { id: "roles", label: "Rollen", terms: [{ id: "sender", label: "Absender", active: true }] },
};
const client = new VocabularyClient(async url => {
  requests += 1;
  const id = decodeURIComponent(url.split("/").pop());
  return { ok: true, json: async () => responses[id] };
});
const descriptor = { fields: [
  { ...field, vocabulary_terms: undefined },
  { id: "people", widget: "repeater", item_fields: [
    { id: "role", path: "role", widget: "vocabulary_select", vocabulary: "roles" },
  ] },
] };
await client.hydrateDescriptor(descriptor);
await client.hydrateDescriptor(descriptor);
assert.equal(requests, 2);
assert.equal(descriptor.fields[0].vocabulary_terms[0].id, "letter");
assert.equal(descriptor.fields[1].item_fields[0].vocabulary_terms[0].id, "sender");

const writes = [];
const writeClient = new VocabularyClient(async (url, options) => {
  writes.push({ url, options });
  const body = JSON.parse(options.body);
  const term = body.term || { id: "letter", label: body.label || "Letter", active: body.active !== false };
  return {
    ok: true,
    json: async () => ({ vocabulary: { id: "document_types", terms: [term] }, meta: { revision: `revision-${writes.length}` } }),
  };
});
await writeClient.addTerm("document_types", "revision-0", { id: "diary", label: "Diary" }, "csrf");
await writeClient.renameTerm("document_types", "diary", "revision-1", "Journal", "csrf");
await writeClient.deactivateTerm("document_types", "diary", "revision-2", "csrf");
assert.equal(writes[0].url, "/api/vocabularies/document_types/terms");
assert.equal(writes[0].options.headers["X-CSRF-Token"], "csrf");
assert.deepEqual(JSON.parse(writes[1].options.body), { base_revision: "revision-1", label: "Journal" });
assert.deepEqual(JSON.parse(writes[2].options.body), { base_revision: "revision-2", active: false });

let fetchReceiver = "not-called";
const receiverClient = new VocabularyClient(function () {
  fetchReceiver = this;
  return { ok: true, json: async () => [] };
});
await receiverClient.catalog();
assert.equal(fetchReceiver, undefined);

const storage = new MemoryStorage();
const moduleDescriptor = { module: "test", fields: [field] };
const state = new FormState(moduleDescriptor, { data: { kind: { id: "letter", vocabulary_id: "document_types" } } });
const store = new PresetStore(moduleDescriptor, "editor", storage);
store.saveFromState(state);
assert.deepEqual(store.load().values["data.kind"], { id: "letter", vocabulary_id: "document_types" });
const renamedField = { ...field, vocabulary_terms: [{ ...terms[0], label: "Schreiben" }] };
assert.equal(vocabularyFieldOptions(renamedField, store.load().values["data.kind"]).options[0].label, "Schreiben");

const invalidState = new FormState(moduleDescriptor, { data: { kind: { id: "missing", vocabulary_id: "document_types" } } });
assert.match(invalidState.validate()[0].message, /Unbekannte Term-ID/);

console.log("generic vocabulary state: ok");
