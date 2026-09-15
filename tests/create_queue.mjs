import assert from "node:assert/strict";
import {FormState} from "../app/generic/form-state.js";
import {RecordUpdate} from "../app/generic/record-update.js";
import {
  createSaveQueueProcessor,
  createCreateQueueEntry,
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
    if (!this.entries.has(id)) throw new Error("missing");
    const value = {...this.entries.get(id), ...clone(changes)};
    this.entries.set(id, value);
    return clone(value);
  }
  async remove(id) { this.entries.delete(id); }
}

const descriptor = {fields: [
  {path: "text", visible: true, editable: true},
  {path: "id", visible: true, editable: false},
  {path: "identity.display", visible: true, editable: false}
]};

const source = {text: "draft"};
const schemaEntry = createCreateQueueEntry({
  operationId: "schema", moduleId: "on-create", identityAssignment: "on_create", snapshot: source
});
source.text = "changed";
assert.equal(schemaEntry.snapshot.text, "draft");
assert.equal(schemaEntry.operation, "create");
assert.equal(schemaEntry.status, "queued");
assert.equal(schemaEntry.record_id, null);
assert.equal(schemaEntry.identity, null);
assert.equal(schemaEntry.base_revision, null);

const onCreateForm = new FormState(descriptor, {});
onCreateForm.setValue("text", "new record");
const onCreateStore = new MemoryStore();
let createEntrySent;
let createdId = null;
let createdRevision = null;
const onCreateEvents = [];
const onCreateProcessor = createSaveQueueProcessor({
  store: onCreateStore,
  sendCreate: async entry => {
    createEntrySent = entry;
    return {record_id: "server-1", record: {id: "server-1", text: "new record"}, meta: {revision: "blob-1"}};
  },
  onSuccess: async (entry, result) => {
    onCreateForm.confirmSave(result.record);
    createdId = result.record_id;
    createdRevision = result.meta.revision;
  },
  onChange: async entry => { if (entry) onCreateEvents.push(entry.status); }
});
const onCreateSnapshot = onCreateForm.beginSave();
await onCreateProcessor.enqueueCreate({
  operationId: "on-create-operation", moduleId: "on-create", identityAssignment: "on_create", snapshot: onCreateSnapshot
});
assert.equal(onCreateForm.hasUnpersistedChanges(), false);
assert.equal(createEntrySent, undefined, "local persistence precedes POST");
await onCreateProcessor.process();
assert.equal(createEntrySent.operation_id, "on-create-operation");
assert.deepEqual(createEntrySent.snapshot, {text: "new record"});
assert.equal(createdId, "server-1");
assert.equal(createdRevision, "blob-1");
assert.equal(onCreateForm.isDirty(), false);
assert.deepEqual(onCreateEvents, ["queued", "saving"]);
assert.equal((await onCreateStore.list()).length, 0);
const followingUpdate = new RecordUpdate("on-create", createdId, onCreateForm, createdRevision, async () => ({
  ok: true,
  json: async () => ({record_id: createdId, record: {id: createdId, text: "updated"}, meta: {revision: "blob-2"}})
}));
onCreateForm.setValue("text", "updated");
await followingUpdate.save("edit", "csrf");
assert.equal(followingUpdate.revision, "blob-2");
assert.equal(onCreateForm.isDirty(), false);

const reserveForm = new FormState(descriptor, {});
reserveForm.setValue("text", "reserved record");
const reserveStore = new MemoryStore();
const reserveEvents = [];
let reservationOperation;
let finalCreateEntry;
const reservedIdentity = {id: "reserved-1", "identity.display": "R.1"};
const reserveProcessor = createSaveQueueProcessor({
  store: reserveStore,
  reserveIdentity: async entry => {
    reservationOperation = entry.operation_id;
    assert.equal(entry.status, "reserving");
    return {operation_id: entry.operation_id, record_id: "reserved-1", identity: reservedIdentity};
  },
  sendCreate: async entry => {
    finalCreateEntry = entry;
    return {record_id: "reserved-1", record: {id: "reserved-1", text: "reserved record", identity: {display: "R.1"}}, meta: {revision: "blob-r"}};
  },
  onReserved: async (entry, reservation) => {
    reserveEvents.push("reserved");
    reserveForm.applyServerValues(reservation.identity);
    assert.equal(entry.record_id, "reserved-1");
    assert.deepEqual((await reserveStore.get(entry.operation_id)).identity, reservedIdentity);
  },
  onChange: async entry => { if (entry) reserveEvents.push(entry.status); },
  onSuccess: async (entry, result) => reserveForm.confirmSave(result.record)
});
await reserveProcessor.enqueueCreate({
  operationId: "reserve-operation", moduleId: "reserve-module", identityAssignment: "reserve_before_create", snapshot: reserveForm.beginSave()
});
assert.equal((await reserveStore.get("reserve-operation")).status, "reserving");
await reserveProcessor.process();
assert.equal(reservationOperation, "reserve-operation");
assert.equal(finalCreateEntry.operation_id, reservationOperation);
assert.equal(finalCreateEntry.record_id, "reserved-1");
assert.deepEqual(finalCreateEntry.identity, reservedIdentity);
assert.deepEqual(finalCreateEntry.snapshot, {text: "reserved record"});
assert.deepEqual(reserveEvents, ["reserving", "reserving", "reserved", "queued", "saving"]);
assert.equal(reserveForm.getValue("identity.display"), "R.1");
assert.equal(reserveForm.isDirty(), false);
assert.equal((await reserveStore.list()).length, 0);

const context = {operationId: "create-a", formState: {}, create: {}};
const createA = {operation_id: "create-a", operation: "create", module_id: "module", record_id: null};
assert.equal(queueEntryMatchesContext(createA, context, {
  moduleId: "module", recordId: null, formState: context.formState, create: context.create, creating: true
}), true);
assert.equal(queueEntryMatchesContext(createA, context, {
  moduleId: "module", recordId: "B", formState: {}, create: {}, creating: false
}), false, "Create A cannot overwrite record B");

const reservationFailureStore = new MemoryStore();
const reservationFailureProcessor = createSaveQueueProcessor({
  store: reservationFailureStore,
  reserveIdentity: async () => { const error = new Error("reservation failed"); error.status = 409; throw error; }
});
await reservationFailureProcessor.enqueueCreate({
  operationId: "reservation-failure", moduleId: "reserve-module", identityAssignment: "reserve_before_create", snapshot: {text: "keep"}
});
assert.equal(await reservationFailureProcessor.process(), false);
const reservationFailure = await reservationFailureStore.get("reservation-failure");
assert.equal(reservationFailure.status, "conflict");
assert.deepEqual(reservationFailure.snapshot, {text: "keep"});
assert.equal(reservationFailure.identity, null);
assert.equal(reservationFailure.attempt_count, 1);

const createFailureStore = new MemoryStore();
const createFailureProcessor = createSaveQueueProcessor({
  store: createFailureStore,
  reserveIdentity: async entry => ({record_id: "reserved-2", identity: {id: "reserved-2"}}),
  sendCreate: async () => { const error = new Error("create failed"); error.status = 500; throw error; }
});
await createFailureProcessor.enqueueCreate({
  operationId: "create-failure", moduleId: "reserve-module", identityAssignment: "reserve_before_create", snapshot: {text: "keep"}
});
assert.equal(await createFailureProcessor.process(), false);
const createFailure = await createFailureStore.get("create-failure");
assert.equal(createFailure.status, "error");
assert.equal(createFailure.record_id, "reserved-2");
assert.deepEqual(createFailure.identity, {id: "reserved-2"});
assert.deepEqual(createFailure.snapshot, {text: "keep"});
assert.equal(createFailure.attempt_count, 2);

const fifoStore = new MemoryStore();
const fifo = [];
const fifoProcessor = createSaveQueueProcessor({
  store: fifoStore,
  sendUpdate: async entry => { fifo.push(`update:${entry.record_id}`); return {meta: {revision: "next"}}; },
  sendCreate: async entry => { fifo.push(`create:${entry.operation_id}`); return {record_id: "new", meta: {revision: "new"}}; }
});
await fifoProcessor.enqueueUpdate({operationId: "fifo-1", moduleId: "module", recordId: "A", baseRevision: "a", snapshot: {}});
await fifoProcessor.enqueueCreate({operationId: "fifo-2", moduleId: "module", identityAssignment: "on_create", snapshot: {}});
await fifoProcessor.enqueueUpdate({operationId: "fifo-3", moduleId: "module", recordId: "C", baseRevision: "c", snapshot: {}});
await fifoProcessor.process();
assert.deepEqual(fifo, ["update:A", "create:fifo-2", "update:C"]);

const failedStore = new MemoryStore();
failedStore.put = async () => { throw new Error("IndexedDB failed"); };
let forbiddenRemote = false;
const failedProcessor = createSaveQueueProcessor({
  store: failedStore,
  sendCreate: async () => { forbiddenRemote = true; },
  reserveIdentity: async () => { forbiddenRemote = true; }
});
await assert.rejects(() => failedProcessor.enqueueCreate({
  operationId: "not-local", moduleId: "module", identityAssignment: "reserve_before_create", snapshot: {}
}));
await failedProcessor.process();
assert.equal(forbiddenRemote, false);

const reloadEntries = new Map();
const reloadStore = new MemoryStore(reloadEntries);
await reloadStore.put(createCreateQueueEntry({
  operationId: "reload-create", moduleId: "module", identityAssignment: "reserve_before_create", snapshot: {text: "persisted"}
}));
let reloadedRemote = false;
const reloadedProcessor = createSaveQueueProcessor({
  store: new MemoryStore(reloadEntries),
  sendCreate: async () => { reloadedRemote = true; },
  reserveIdentity: async () => { reloadedRemote = true; }
});
assert.equal((await reloadStore.list()).length, 1);
assert.equal(await reloadedProcessor.process(), false);
assert.equal(reloadedRemote, false);
assert.match(queueStatusMessage([schemaEntry, createFailure]), /^2 Speichervorgänge ausstehend/);

console.log("Create queue strategies, reservation lifecycle, FIFO, errors, correlation, reload and POST-to-PUT assertions passed");
