import assert from "node:assert/strict";
import {createSaveQueueProcessor} from "../app/generic/module-save-queue.js";
import {reserveQueuedRecordIdentity} from "../app/generic/record-create.js";

const clone = value => structuredClone(value);
class MemoryStore {
  entries = new Map();
  async get(id) { return clone(this.entries.get(id) || null); }
  async list() { return [...this.entries.values()].map(clone); }
  async put(entry) { this.entries.set(entry.operation_id, clone(entry)); return clone(entry); }
  async update(id, changes) {
    if (!this.entries.has(id)) throw new Error("missing entry");
    return this.put({...await this.get(id), ...clone(changes)});
  }
  async remove(id) { this.entries.delete(id); }
}
const store = new MemoryStore();
const remote = new Map();
let reservations = 0, creates = 0, updates = 0, calls = 0, loseResponse = false, conflict = false;
const reserveIdentity = async entry => {
  calls++;
  assert.equal((await store.get(entry.operation_id)).operation, "reservation", "persist before network");
  if (conflict) { conflict = false; throw Object.assign(new Error("parallel commit"), {status: 409}); }
  if (!remote.has(entry.operation_id)) {
    const n = ++reservations;
    remote.set(entry.operation_id, {record_id: `test-${n}`, identity: {id: `test-${n}`, "signatur.anzeige": `Test A/${n}`}});
  }
  if (loseResponse) { loseResponse = false; throw new Error("lost response"); }
  return clone(remote.get(entry.operation_id));
};
const handlers = {store, reserveIdentity,
  sendCreate: async entry => { creates++; return {record_id: entry.record_id, record: {id: entry.record_id, ...entry.snapshot}, meta: {revision: "v1"}}; },
  sendUpdate: async entry => { updates++; assert.equal(entry.base_revision, "v1"); return {record: entry.snapshot, meta: {revision: "v2"}}; },
};
let processor = createSaveQueueProcessor(handlers);
const prepare = (id, module = "synthetic") => processor.prepareReservation({operationId: id, moduleId: module, identityInputs: {signatur: {format: "A"}}});
const prepared = await prepare("one");
assert.equal(prepared.snapshot, undefined);
assert.equal(calls, 0);
await processor.process();
assert.equal(creates, 0);
assert.equal(calls, 0, "background worker must not turn reservation into create");
// Reload before sending; the persisted operation is resumed unchanged.
processor = createSaveQueueProcessor(handlers);
await processor.initializeRecovery();
await Promise.all([processor.resumeReservation("one"), processor.resumeReservation("one")]);
assert.equal(calls, 1);
assert.equal(reservations, 1);
const reserved = await store.get("one");
assert.equal(reserved.status, "reserved");
assert.equal(reserved.snapshot, undefined);
assert.equal(creates, 0);
// Reload after confirmation requires no network or new number.
processor = createSaveQueueProcessor(handlers);
await processor.initializeRecovery();
assert.deepEqual(await processor.resumeReservation("one"), reserved);
assert.equal(calls, 1);
const snapshot = {text: "Current text at save time"};
await processor.enqueueCreate({operationId: "one", moduleId: "synthetic", identityAssignment: "reserve_before_create", snapshot});
snapshot.text = "Later edit";
const queued = await store.get("one");
assert.equal(queued.operation, "create");
assert.equal(queued.record_id, reserved.record_id);
assert.deepEqual(queued.identity, reserved.identity);
assert.equal(queued.snapshot.text, "Current text at save time");
await assert.rejects(() => processor.enqueueCreate({operationId: "one", moduleId: "synthetic", identityAssignment: "reserve_before_create", snapshot}));
await processor.process();
assert.equal(creates, 1);
assert.equal(reservations, 1);
await processor.enqueueUpdate({operationId: "update", moduleId: "synthetic", recordId: reserved.record_id, baseRevision: "v1", snapshot: {text: "Updated"}});
await processor.process();
assert.equal(updates, 1);
// Server committed, but response vanished. Reload and repeat same operation.
await prepare("lost");
loseResponse = true;
await assert.rejects(() => processor.resumeReservation("lost"));
assert.equal((await store.get("lost")).status, "error");
processor = createSaveQueueProcessor(handlers);
await processor.initializeRecovery();
await processor.resumeReservation("lost");
assert.equal(reservations, 2);
assert.equal((await store.get("lost")).record_id, "test-2");
// 409 does not spin; explicit retry uses same ID.
await prepare("conflict");
conflict = true;
const beforeCalls = calls;
await assert.rejects(() => processor.resumeReservation("conflict"));
assert.equal(calls, beforeCalls + 1);
assert.equal((await store.get("conflict")).status, "conflict");
await processor.resumeReservation("conflict");
assert.equal(reservations, 3);
// Independent concurrent objects get independent identities.
await Promise.all([prepare("parallel-a"), prepare("parallel-b")]);
await Promise.all([processor.resumeReservation("parallel-a"), processor.resumeReservation("parallel-b")]);
assert.notEqual((await store.get("parallel-a")).record_id, (await store.get("parallel-b")).record_id);
// Abandoning is local only; a fresh operation cannot reclaim that number.
const abandonedId = (await store.get("parallel-a")).record_id;
await processor.discard("parallel-a");
await prepare("fresh");
assert.notEqual((await processor.resumeReservation("fresh")).record_id, abandonedId);
assert.equal(remote.has("parallel-a"), true);
// Local failure prevents any network request.
const broken = createSaveQueueProcessor({...handlers, store: {...store, get: async () => null, put: async () => {throw new Error("disk full");}}});
const callCount = calls;
await assert.rejects(() => broken.prepareReservation({operationId: "broken", moduleId: "synthetic", identityInputs: {}}));
assert.equal(calls, callCount);
// Existing reservation transport sends only the persisted allocation inputs.
let requestBody;
await reserveQueuedRecordIdentity(reserved, "csrf", async (_url, options) => {
  requestBody = JSON.parse(options.body);
  return {ok: true, json: async () => ({module: reserved.module_id, operation_id: reserved.operation_id, record_id: reserved.record_id, identity: reserved.identity})};
});
assert.deepEqual(requestBody, {operation_id: "one", record: {signatur: {format: "A"}}});
console.log("Early reservation: persistence, duplicate triggers, reload, lost response, conflict, parallel identities, promotion, update and abandonment passed");

const incompleteStore = new MemoryStore();
const incomplete = createSaveQueueProcessor({store: incompleteStore, reserveIdentity: async () => ({record_id: 'id-only', identity: {id: 'id-only'}})});
await incomplete.prepareReservation({operationId: 'partial', moduleId: 'synthetic', identityInputs: {}, identityPaths: ['id', 'signatur.anzeige']});
await assert.rejects(() => incomplete.resumeReservation('partial'));
assert.equal((await incompleteStore.get('partial')).record_id, null);
assert.equal((await incompleteStore.get('partial')).status, 'error');
// A reservation-only entry must not block unrelated regular queue work.
let regularUpdates = 0;
await incomplete.enqueueUpdate({operationId: 'regular-update', moduleId: 'other', recordId: 'existing', baseRevision: 'v1', snapshot: {}});
const worker = createSaveQueueProcessor({store: incompleteStore, sendUpdate: async () => { regularUpdates++; return {meta: {revision: 'v2'}}; }});
await worker.initializeRecovery();
await worker.process();
assert.equal(regularUpdates, 1);
assert.equal((await incompleteStore.get('partial')).operation, 'reservation');
