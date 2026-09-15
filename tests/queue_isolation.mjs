import assert from "node:assert/strict";
import {createIndexedDbSaveQueueStore} from "../app/generic/module-save-queue-store.js";
import {createSaveQueueProcessor, createUpdateQueueEntry} from "../app/generic/module-save-queue.js";

const clone = value => structuredClone(value);

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
    this.objectStoreNames = {contains: name => this.stores.has(name)};
  }
  createObjectStore(name) {
    this.stores.set(name, new Map());
    return {createIndex() {}};
  }
  transaction(name) { return new FakeTransaction(this.stores.get(name)); }
}

class FakeIndexedDB {
  constructor() { this.databases = new Map(); this.openCalls = []; }
  open(name, version) {
    this.openCalls.push({name, version});
    const request = {result: null, error: null};
    queueMicrotask(() => {
      let database = this.databases.get(name);
      if (!database) {
        database = new FakeDatabase();
        this.databases.set(name, database);
        request.result = database;
        request.onupgradeneeded?.();
      } else {
        request.result = database;
      }
      request.onsuccess?.();
    });
    return request;
  }
}

const indexedDB = new FakeIndexedDB();
const legacyStore = createIndexedDbSaveQueueStore({
  indexedDB,
  databaseName: "Erschliessungsumgebung",
  databaseVersion: 1,
});
const legacyEntry = {
  operation_id: "legacy-photo",
  operation: "update",
  record_id: "foto-000001",
  base_revision: "photo-blob",
  snapshot: {format: "A", erschliessung: {beschriftung: "lokal"}},
  created_at: "2026-09-15T08:00:00.000Z",
  updated_at: "2026-09-15T08:00:00.000Z",
  status: "queued",
  attempt_count: 0,
  last_error: null,
};
await legacyStore.put(legacyEntry);

const moduleStore = createIndexedDbSaveQueueStore({indexedDB});
await moduleStore.put(createUpdateQueueEntry({
  operationId: "generic-module",
  moduleId: "autographen_9_6",
  recordId: "autograph-000001",
  baseRevision: "autograph-blob",
  snapshot: {erschliessung: {regest: "lokal"}},
}));

assert.deepEqual(indexedDB.openCalls, [
  {name: "Erschliessungsumgebung", version: 1},
  {name: "ErschliessungsumgebungModule", version: 1},
]);
assert.notEqual(indexedDB.databases.get("Erschliessungsumgebung"), indexedDB.databases.get("ErschliessungsumgebungModule"));
assert.deepEqual((await legacyStore.list()).map(entry => entry.operation_id), ["legacy-photo"]);
assert.deepEqual((await moduleStore.list()).map(entry => entry.operation_id), ["generic-module"]);

const lockNames = [];
const lockManager = {
  async request(name, options, callback) {
    lockNames.push(name);
    const task = typeof options === "function" ? options : callback;
    return task({name});
  },
};

const genericSeen = [];
const genericProcessor = createSaveQueueProcessor({
  store: moduleStore,
  lockManager,
  sendUpdate: async entry => {
    genericSeen.push(entry.operation_id);
    return {meta: {revision: "autograph-next"}};
  },
});
await genericProcessor.initializeRecovery();
assert.deepEqual(await legacyStore.get("legacy-photo"), legacyEntry, "generic recovery must not normalize the old photo entry");
await genericProcessor.retryFirst();
assert.deepEqual(genericSeen, ["generic-module"]);
assert.equal(await moduleStore.get("generic-module"), null);
assert.deepEqual(await legacyStore.get("legacy-photo"), legacyEntry);

const photoSeen = [];
await lockManager.request("erschliessung-save-queue", async () => {
  const entry = (await legacyStore.list())[0];
  photoSeen.push(entry.operation_id);
  await legacyStore.update(entry.operation_id, {status: "saving"});
});
assert.deepEqual(photoSeen, ["legacy-photo"]);
assert.equal((await legacyStore.get("legacy-photo")).status, "saving");
assert.equal((await moduleStore.list()).length, 0);

await moduleStore.put(createUpdateQueueEntry({
  operationId: "generic-delete",
  moduleId: "autographen_9_6",
  recordId: "autograph-000002",
  baseRevision: "autograph-blob-2",
  snapshot: {},
}));
await moduleStore.remove("generic-delete");
assert.equal((await legacyStore.get("legacy-photo")).status, "saving");

await moduleStore.put(createUpdateQueueEntry({
  operationId: "generic-retained",
  moduleId: "autographen_9_6",
  recordId: "autograph-000003",
  baseRevision: "autograph-blob-3",
  snapshot: {},
}));
await legacyStore.remove("legacy-photo");
assert.equal(await legacyStore.get("legacy-photo"), null);
assert.equal((await moduleStore.get("generic-retained")).status, "queued");
assert.ok(lockNames.every(name => name === "erschliessung-save-queue"));

console.log("Legacy photo and generic module queues remain isolated across paths, databases, updates, deletes and shared locking");
