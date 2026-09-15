import assert from "node:assert/strict";
import { VocabularyAdminState } from "../app/generic/vocabulary-admin.js";

const clone = value => JSON.parse(JSON.stringify(value));
const rights = { use: true, add: true, rename: true, deactivate: true };

class FakeClient {
  constructor() {
    this.vocabulary = {
      id: "types", label: "Typen", description: null, rights,
      meta: { revision: "revision-a" },
      terms: [
        { id: "letter", label: "Brief", active: true, description: null, aliases: [], sort_order: 10 },
        { id: "fax", label: "Telefax", active: false, description: "Historisch", aliases: [], sort_order: 20 },
      ],
    };
    this.calls = [];
    this.failure = null;
    this.counter = 0;
  }

  async catalog() { return [{ id: "types", label: "Typen", rights }]; }
  async load() { return clone(this.vocabulary); }
  async reload() { this.calls.push({ operation: "reload" }); return clone(this.vocabulary); }

  result() {
    this.counter += 1;
    this.vocabulary.meta.revision = `revision-${this.counter}`;
    return { vocabulary: clone(this.vocabulary), meta: clone(this.vocabulary.meta) };
  }

  maybeFail() {
    if (!this.failure) return;
    const error = new Error(this.failure.message);
    error.status = this.failure.status;
    this.failure = null;
    throw error;
  }

  async addTerm(id, baseRevision, term) {
    this.calls.push({ operation: "add", id, baseRevision, term: clone(term) });
    this.maybeFail();
    this.vocabulary.terms.push({ ...term, active: true, description: null, aliases: [], sort_order: null });
    return this.result();
  }

  async renameTerm(id, termId, baseRevision, label) {
    this.calls.push({ operation: "rename", id, termId, baseRevision, label });
    this.maybeFail();
    this.vocabulary.terms.find(term => term.id === termId).label = label;
    return this.result();
  }

  async deactivateTerm(id, termId, baseRevision) {
    this.calls.push({ operation: "deactivate", id, termId, baseRevision });
    this.maybeFail();
    this.vocabulary.terms.find(term => term.id === termId).active = false;
    return this.result();
  }
}

const client = new FakeClient();
const state = new VocabularyAdminState(client);
assert.equal(await state.loadCatalog(), true);
assert.deepEqual(state.catalog.map(item => item.id), ["types"]);
assert.equal(await state.open("types"), true);
assert.equal(state.revision, "revision-a");
assert.equal(state.vocabulary.terms.filter(term => !term.active)[0].id, "fax");

state.setAddDraft({ id: "diary", label: "Tagebuch" });
assert.equal(await state.add("csrf"), true);
assert.equal(state.revision, "revision-1");
assert.equal(state.vocabulary.terms.at(-1).id, "diary");
assert.deepEqual(state.addDraft, { id: "", label: "" });

state.setRenameDraft("diary", "Journal");
assert.equal(await state.rename("diary", "csrf"), true);
assert.equal(client.calls.at(-1).baseRevision, "revision-1");
assert.equal(state.revision, "revision-2");
assert.equal(state.vocabulary.terms.at(-1).id, "diary");
assert.equal(state.vocabulary.terms.at(-1).label, "Journal");
state.setRenameDraft("letter", "Schreiben");
assert.equal(await state.rename("letter", "csrf"), true);
assert.equal(client.calls.at(-1).baseRevision, "revision-2");
assert.equal(state.revision, "revision-3");

assert.equal(state.requestDeactivate("diary"), true);
assert.equal(client.calls.at(-1).operation, "rename");
assert.equal(await state.confirmDeactivate("csrf"), true);
assert.equal(client.calls.at(-1).operation, "deactivate");
assert.equal(state.vocabulary.terms.find(term => term.id === "diary").active, false);
assert.equal(state.vocabulary.terms.some(term => term.id === "diary"), true);

state.setAddDraft({ id: "duplicate", label: "Eingabe bleibt" });
client.failure = { status: 422, message: "Term-ID ist ungültig." };
const revisionBeforeValidation = state.revision;
assert.equal(await state.add("csrf"), false);
assert.equal(state.status, "validation_error");
assert.deepEqual(state.addDraft, { id: "duplicate", label: "Eingabe bleibt" });
assert.equal(state.revision, revisionBeforeValidation);

client.failure = { status: 409, message: "Term-ID 'duplicate' ist bereits vorhanden." };
assert.equal(await state.add("csrf"), false);
assert.equal(state.status, "validation_error");
assert.match(state.error, /bereits vorhanden/);
assert.deepEqual(state.addDraft, { id: "duplicate", label: "Eingabe bleibt" });

state.setRenameDraft("letter", "Lokaler Konfliktentwurf");
client.failure = { status: 409, message: "conflict" };
assert.equal(await state.rename("letter", "csrf"), false);
assert.equal(state.status, "conflict");
assert.match(state.error, /anderweitig geändert/);
assert.equal(state.renameDrafts.get("letter"), "Lokaler Konfliktentwurf");
assert.equal(state.revision, revisionBeforeValidation);
assert.equal(await state.open("types", { reload: true, discardDrafts: true }), true);
assert.equal(state.renameDrafts.size, 0);

const readOnlyClient = new FakeClient();
readOnlyClient.vocabulary.rights = { use: true, add: false, rename: false, deactivate: false };
const readOnly = new VocabularyAdminState(readOnlyClient);
await readOnly.open("types");
readOnly.setAddDraft({ id: "x", label: "X" });
assert.equal(await readOnly.add("csrf"), false);
assert.equal(readOnlyClient.calls.length, 0);
assert.equal(readOnly.requestDeactivate("letter"), false);

const forbiddenClient = new FakeClient();
const forbidden = new VocabularyAdminState(forbiddenClient);
await forbidden.open("types");
forbidden.setRenameDraft("letter", "Nicht erlaubt");
forbiddenClient.failure = { status: 403, message: "forbidden" };
assert.equal(await forbidden.rename("letter", "csrf"), false);
assert.match(forbidden.error, /Server/);
assert.equal(forbidden.revision, "revision-a");
assert.equal("deleteTerm" in forbiddenClient, false);

console.log("Vocabulary administration state: ok");
