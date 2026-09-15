import assert from "node:assert/strict";
import {FormState} from "../app/generic/form-state.js";
import {createIndexedDbSaveQueueStore} from "../app/generic/save-queue-store.js";
import {
  createSaveQueueProcessor,
  createUpdateQueueEntry,
  queueEntryMatchesContext,
  queueStatusMessage
} from "../app/generic/save-queue.js";

const clone = value => structuredClone(value);

class MemoryStore {
  constructor(entries = new Map()) { this.entries = entries; }
  async put(entry) { this.entries.set(entry.operation_id, clone(entry)); return clone(entry); }
  async get(id) { return this.entries.has(id) ? clone(this.entries.get(id)) : null; }
  async list() {
    return [...this.entries.values()].map(clone).sort((a, b) => (
      (a.queue_sequence ?? Number.MAX_SAFE_INTEGER) - (b.queue_sequence ?? Number.MAX_SAFE_INTEGER) ||
      a.created_at.localeCompare(b.created_at) || a.operation_id.localeCompare(b.operation_id)
    ));
  }
  async update(id, changes) {
    if (!this.entries.has(id)) throw new Error("missing queue entry");
    const updated = {...this.entries.get(id), ...clone(changes)};
    this.entries.set(id, updated);
    return clone(updated);
  }
  async remove(id) { this.entries.delete(id); }
}

class FakeTransaction {
  constructor(data) { this.data = data; this.error = null; this.completionScheduled = false; }
  objectStore() { return new FakeObjectStore(this); }
  abort() { this.error = new Error("aborted"); this.onabort?.(); }
  completeLater() {
    if (this.completionScheduled) return;
    this.completionScheduled = true;
    setImmediate(() => this.oncomplete?.());
  }
}

class FakeObjectStore {
  constructor(transaction) { this.transaction = transaction; }
  createIndex() {}
  request(result) {
    const request = {result: undefined, error: null};
    queueMicrotask(() => { request.result = clone(result); request.onsuccess?.(); });
    this.transaction.completeLater();
    return request;
  }
  put(entry) { this.transaction.data.set(entry.operation_id, clone(entry)); this.transaction.completeLater(); return {}; }
  get(id) { return this.request(this.transaction.data.get(id)); }
  getAll() { return this.request([...this.transaction.data.values()]); }
  delete(id) { this.transaction.data.delete(id); this.transaction.completeLater(); return {}; }
}

class FakeDatabase {
  constructor() {
    this.stores = new Map();
    this.keyPaths = new Map();
    this.objectStoreNames = {contains: name => this.stores.has(name)};
  }
  createObjectStore(name, {keyPath}) {
    this.stores.set(name, new Map());
    this.keyPaths.set(name, keyPath);
    return {createIndex() {}};
  }
  transaction(name) { return new FakeTransaction(this.stores.get(name)); }
}

class FakeIndexedDB {
  constructor() { this.database = null; this.openCalls = []; }
  open(name, version) {
    this.openCalls.push({name, version});
    const request = {result: null, error: null};
    queueMicrotask(() => {
      if (!this.database) {
        this.database = new FakeDatabase();
        request.result = this.database;
        request.onupgradeneeded?.();
      } else request.result = this.database;
      request.onsuccess?.();
    });
    return request;
  }
}

const fakeIndexedDB = new FakeIndexedDB();
const indexedStore = createIndexedDbSaveQueueStore({indexedDB: fakeIndexedDB});
await indexedStore.open();
assert.deepEqual(fakeIndexedDB.openCalls, [{name: "Erschliessungsumgebung", version: 1}]);
assert.equal(fakeIndexedDB.database.objectStoreNames.contains("save_queue"), true);
assert.equal(fakeIndexedDB.database.keyPaths.get("save_queue"), "operation_id");
const indexedEntry = createUpdateQueueEntry({
  operationId: "indexed", moduleId: "module", recordId: "record", baseRevision: "blob-a", snapshot: {text: "A"}
});
await indexedStore.put(indexedEntry);
assert.deepEqual((await indexedStore.get("indexed")).snapshot, {text: "A"});
assert.equal((await indexedStore.list()).length, 1);
await indexedStore.update("indexed", {status: "saving"});
assert.equal((await indexedStore.get("indexed")).status, "saving");
await indexedStore.remove("indexed");
assert.equal(await indexedStore.get("indexed"), null);

const source = {nested: {text: "original"}};
const copied = createUpdateQueueEntry({
  operationId: "copy", moduleId: "module", recordId: "record", baseRevision: "blob-a", snapshot: source
});
source.nested.text = "changed later";
assert.equal(copied.snapshot.nested.text, "original");
assert.deepEqual(Object.keys(copied).sort(), [
  "attempt_count", "base_revision", "created_at", "last_error", "module_id", "operation", "operation_id",
  "queue_sequence", "record_id", "snapshot", "status", "updated_at"
]);
assert.equal(copied.operation, "update");
assert.equal(queueStatusMessage([]), "Alle vorgemerkten Datensätze übertragen");
assert.match(queueStatusMessage([copied]), /^1 Speichervorgang ausstehend/);
assert.match(queueStatusMessage([copied, copied, copied]), /^3 Speichervorgänge ausstehend/);

let releasePut;
let remoteStarted = false;
const gatedStore = new MemoryStore();
gatedStore.put = entry => new Promise(resolve => {
  releasePut = () => { gatedStore.entries.set(entry.operation_id, clone(entry)); resolve(clone(entry)); };
});
const gatedProcessor = createSaveQueueProcessor({store: gatedStore, sendUpdate: async () => { remoteStarted = true; }});
const enqueueing = gatedProcessor.enqueueUpdate({
  operationId: "gated", moduleId: "module", recordId: "record", baseRevision: "blob-a", snapshot: {text: "A"}
});
await Promise.resolve();
assert.equal(remoteStarted, false);
releasePut();
await enqueueing;
assert.equal(remoteStarted, false, "enqueue alone never starts the remote write");
await gatedProcessor.process();
assert.equal(remoteStarted, true);

const failedPersistence = new MemoryStore();
failedPersistence.put = async () => { throw new Error("IndexedDB write failed"); };
let forbiddenRemote = false;
const failedPersistenceProcessor = createSaveQueueProcessor({
  store: failedPersistence,
  sendUpdate: async () => { forbiddenRemote = true; }
});
await assert.rejects(() => failedPersistenceProcessor.enqueueUpdate({
  operationId: "not-persisted", moduleId: "module", recordId: "record", baseRevision: "blob-a", snapshot: {}
}));
await failedPersistenceProcessor.process();
assert.equal(forbiddenRemote, false);

let failedOpenRemote = false;
const failingIndexedDB = {open() {
  const request = {error: new Error("open failed")};
  queueMicrotask(() => request.onerror?.());
  return request;
}};
await assert.rejects(() => createIndexedDbSaveQueueStore({indexedDB: failingIndexedDB}).open(), /open failed/);
const failedReadStore = new MemoryStore();
failedReadStore.list = async () => { throw new Error("read failed"); };
await assert.rejects(() => createSaveQueueProcessor({
  store: failedReadStore,
  sendUpdate: async () => { failedOpenRemote = true; }
}).process(), /read failed/);
assert.equal(failedOpenRemote, false);

const descriptor = {fields: [{path: "text", visible: true, editable: true}]};
const form = new FormState(descriptor, {text: "server"});
form.setValue("text", "queued value");
const queueEvents = [];
const lifecycleStore = new MemoryStore();
let revision = "blob-a";
let finishRemote;
const lifecycleProcessor = createSaveQueueProcessor({
  store: lifecycleStore,
  sendUpdate: entry => new Promise(resolve => {
    assert.equal(entry.base_revision, "blob-a");
    assert.deepEqual(entry.snapshot, {text: "queued value"});
    finishRemote = resolve;
  }),
  onChange: async entry => { if (entry) queueEvents.push(entry.status); },
  onSuccess: async (entry, response) => {
    form.confirmSave(response.record);
    revision = response.meta.revision;
    assert.equal(entry.status, "confirmed");
  }
});
const pendingPayload = form.beginSave();
await lifecycleProcessor.enqueueUpdate({
  operationId: "lifecycle", moduleId: "module", recordId: "record", baseRevision: revision, snapshot: pendingPayload
});
assert.equal(form.isDirty(), true);
assert.equal(form.hasUnpersistedChanges(), false, "queued data permits navigation");
const lifecycleRun = lifecycleProcessor.process();
await new Promise(resolve => setImmediate(resolve));
form.setValue("text", "newer value");
assert.equal(form.hasUnpersistedChanges(), true, "later edits still block navigation");
finishRemote({record: {text: "queued value"}, meta: {revision: "blob-b"}});
await lifecycleRun;
assert.deepEqual(queueEvents, ["queued", "saving"]);
assert.equal(revision, "blob-b");
assert.equal(form.getValue("text"), "newer value");
assert.equal(form.isDirty(), true);
assert.equal(form.pendingSnapshot, null);
assert.equal((await lifecycleStore.list()).length, 0);

const cleanForm = new FormState(descriptor, {text: "server"});
cleanForm.setValue("text", "saved");
const cleanStore = new MemoryStore();
const cleanProcessor = createSaveQueueProcessor({
  store: cleanStore,
  sendUpdate: async () => ({record: {text: "saved"}, meta: {revision: "blob-clean"}}),
  onSuccess: async (entry, response) => cleanForm.confirmSave(response.record)
});
await cleanProcessor.enqueueUpdate({
  operationId: "clean", moduleId: "module", recordId: "clean", baseRevision: "blob-a", snapshot: cleanForm.beginSave()
});
await cleanProcessor.process();
assert.equal(cleanForm.isDirty(), false, "dirty -> queued -> saving -> clean completes");

const context = {operationId: "record-a-operation", formState: {}, update: {}};
const entryA = {operation_id: "record-a-operation", module_id: "module", record_id: "A"};
assert.equal(queueEntryMatchesContext(entryA, context, {
  moduleId: "module", recordId: "B", formState: context.formState, update: context.update
}), false, "record A may not update record B");
assert.equal(queueEntryMatchesContext(entryA, context, {
  moduleId: "module", recordId: "A", formState: context.formState, update: context.update
}), true);

const sequentialStore = new MemoryStore();
const order = [];
let releaseFirst;
const sequentialProcessor = createSaveQueueProcessor({store: sequentialStore, sendUpdate: async entry => {
  order.push(`start:${entry.operation_id}`);
  if (entry.operation_id === "one") await new Promise(resolve => { releaseFirst = resolve; });
  order.push(`end:${entry.operation_id}`);
  return {meta: {revision: `next-${entry.operation_id}`}};
}});
await sequentialProcessor.enqueueUpdate({operationId: "one", moduleId: "module", recordId: "one", baseRevision: "a", snapshot: {}});
await sequentialProcessor.enqueueUpdate({operationId: "two", moduleId: "module", recordId: "two", baseRevision: "b", snapshot: {}});
const sequentialRun = sequentialProcessor.process();
await new Promise(resolve => setImmediate(resolve));
assert.deepEqual(order, ["start:one"]);
releaseFirst();
await sequentialRun;
assert.deepEqual(order, ["start:one", "end:one", "start:two", "end:two"]);

for (const [httpStatus, expectedStatus] of [[401, "auth_error"], [403, "auth_error"], [409, "conflict"], [422, "validation_error"], [500, "error"], [null, "error"]]) {
  const errorStore = new MemoryStore();
  const attempted = [];
  const processor = createSaveQueueProcessor({store: errorStore, sendUpdate: async entry => {
    attempted.push(entry.operation_id);
    const error = new Error(httpStatus ? `HTTP ${httpStatus}` : "network");
    if (httpStatus) error.status = httpStatus;
    throw error;
  }});
  await processor.enqueueUpdate({
    operationId: `error-${httpStatus}`, moduleId: "module", recordId: "bad", baseRevision: "a", snapshot: {complete: true}
  });
  await processor.enqueueUpdate({
    operationId: `later-${httpStatus}`, moduleId: "module", recordId: "later", baseRevision: "b", snapshot: {}
  });
  assert.equal(await processor.process(), false);
  assert.deepEqual(attempted, [`error-${httpStatus}`]);
  const retained = await errorStore.get(`error-${httpStatus}`);
  assert.equal(retained.status, expectedStatus);
  assert.equal(retained.attempt_count, 1);
  assert.equal(retained.last_error.http_status, httpStatus);
  assert.deepEqual(retained.snapshot, {complete: true});
  assert.ok(await errorStore.get(`later-${httpStatus}`));
}

const duplicateStore = new MemoryStore();
const duplicateProcessor = createSaveQueueProcessor({store: duplicateStore, sendUpdate: async () => {}});
await duplicateProcessor.enqueueUpdate({
  operationId: "active", moduleId: "module", recordId: "same", baseRevision: "a", snapshot: {}
});
await assert.rejects(() => duplicateProcessor.enqueueUpdate({
  operationId: "duplicate", moduleId: "module", recordId: "same", baseRevision: "a", snapshot: {}
}), /bereits/);

const persisted = new Map();
await new MemoryStore(persisted).put(createUpdateQueueEntry({
  operationId: "reload", moduleId: "module", recordId: "record", baseRevision: "a", snapshot: {text: "persisted"}
}));
let reloadRemote = false;
const afterReload = new MemoryStore(persisted);
const reloadProcessor = createSaveQueueProcessor({store: afterReload, sendUpdate: async () => { reloadRemote = true; }});
assert.equal((await afterReload.list()).length, 1);
assert.equal(reloadRemote, false, "opening the queue does not resume or delete entries");
await reloadProcessor.enqueueUpdate({
  operationId: "fresh", moduleId: "module", recordId: "fresh", baseRevision: "b", snapshot: {}
});
assert.equal(await reloadProcessor.process(), false);
assert.equal(reloadRemote, false, "a fresh save does not indirectly resume a reload entry");
assert.equal((await afterReload.list()).length, 2);

const cleanupStore = new MemoryStore();
cleanupStore.remove = async () => { throw new Error("remove failed"); };
let cleanupFailure;
const cleanupProcessor = createSaveQueueProcessor({
  store: cleanupStore,
  sendUpdate: async () => ({meta: {revision: "blob-b"}}),
  onError: async (entry, error, details) => { cleanupFailure = {entry, error, details}; }
});
await cleanupProcessor.enqueueUpdate({
  operationId: "cleanup", moduleId: "module", recordId: "record", baseRevision: "a", snapshot: {}
});
assert.equal(await cleanupProcessor.process(), false);
assert.equal((await cleanupStore.get("cleanup")).status, "confirmed");
assert.equal(cleanupFailure.details.remoteConfirmed, true);
assert.equal(await cleanupProcessor.process(), true, "confirmed cleanup failures are never resent");

console.log("IndexedDB store, persistent PUT queue, FIFO, correlation, lifecycle, reload and failure assertions passed");
