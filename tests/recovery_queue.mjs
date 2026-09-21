import assert from "node:assert/strict";
import {FormState} from "../app/generic/form-state.js";
import {RecordCreate} from "../app/generic/record-create.js";
import {classifyQueuedUpdateReadBack} from "../app/generic/record-update.js";
import {createCreateQueueEntry, createSaveQueueProcessor, createUpdateQueueEntry, normalizeQueueEntry} from "../app/generic/module-save-queue.js";

const clone = value => structuredClone(value);
class MemoryStore {
  constructor(entries = []) { this.entries = new Map(entries.map(entry => [entry.operation_id, clone(entry)])); }
  async put(entry) { this.entries.set(entry.operation_id, clone(entry)); return clone(entry); }
  async get(id) { return this.entries.has(id) ? clone(this.entries.get(id)) : null; }
  async list() { return [...this.entries.values()].map(clone).sort((a, b) => a.queue_sequence - b.queue_sequence); }
  async update(id, changes) {
    const updated = {...this.entries.get(id), ...clone(changes)};
    this.entries.set(id, updated);
    return clone(updated);
  }
  async remove(id) { this.entries.delete(id); }
}

const descriptor = {fields: [
  {path: "daten.text", visible: true, editable: true},
  {path: "id", visible: true, editable: false},
  {path: "technik.geaendert_am", visible: false, editable: false}
]};
const updateEntry = (status, sequence = 1) => ({
  ...createUpdateQueueEntry({operationId: `update-${status}-${sequence}`, moduleId: "module", recordId: "record-1", baseRevision: "base-1", snapshot: {daten: {text: "local"}}, queueSequence: sequence}),
  status
});

// queued is provably unsent and may resume automatically after reload.
const queuedStore = new MemoryStore([updateEntry("queued")]);
let queuedWrites = 0;
const queuedProcessor = createSaveQueueProcessor({
  store: queuedStore,
  sendUpdate: async entry => {
    queuedWrites += 1;
    return {module: "module", record_id: entry.record_id, record: {daten: {text: "local"}}, meta: {revision: "next-1"}};
  }
});
await queuedProcessor.initializeRecovery();
await queuedProcessor.process();
assert.equal(queuedWrites, 1);
assert.equal((await queuedStore.list()).length, 0);

// saving is uncertain and is never sent by startup processing.
const appliedStore = new MemoryStore([updateEntry("saving")]);
let blindWrites = 0;
const appliedProcessor = createSaveQueueProcessor({
  store: appliedStore,
  sendUpdate: async () => { blindWrites += 1; },
  resolveUpdate: async entry => ({outcome: "applied", result: {
    module: "module", record_id: entry.record_id,
    record: {daten: {text: "local"}, technik: {geaendert_am: "server-only"}}, meta: {revision: "committed-1"}
  }})
});
await appliedProcessor.initializeRecovery();
await appliedProcessor.process();
assert.equal(blindWrites, 0);
await appliedProcessor.retryFirst();
assert.equal(blindWrites, 0, "successful lost-response PUT is resolved by read-back, not written twice");
assert.equal((await appliedStore.list()).length, 0);

// A failed local remove remains confirmed and is later read back without a second PUT.
const cleanupStore = new MemoryStore([updateEntry("queued")]);
let failRemove = true;
cleanupStore.remove = async function(id) {
  if (failRemove) throw new Error("IndexedDB remove failed");
  this.entries.delete(id);
};
let cleanupWrites = 0;
const cleanupFirst = createSaveQueueProcessor({
  store: cleanupStore,
  sendUpdate: async entry => {
    cleanupWrites += 1;
    return {record: entry.snapshot, meta: {revision: "cleanup-revision"}};
  }
});
await cleanupFirst.initializeRecovery();
assert.equal(await cleanupFirst.process(), false);
assert.equal((await cleanupStore.list())[0].status, "confirmed");
failRemove = false;
const cleanupRecovery = createSaveQueueProcessor({
  store: cleanupStore,
  sendUpdate: async () => { cleanupWrites += 1; },
  resolveUpdate: async entry => ({outcome: "applied", result: {record: entry.snapshot, meta: {revision: "cleanup-revision"}}})
});
await cleanupRecovery.initializeRecovery();
await cleanupRecovery.retryFirst();
assert.equal(cleanupWrites, 1);
assert.equal((await cleanupStore.list()).length, 0);

const appliedClassification = classifyQueuedUpdateReadBack(updateEntry("saving"), {
  module: "module", record_id: "record-1",
  record: {daten: {text: "local"}, technik: {geaendert_am: "ignored"}}, meta: {revision: "new-revision"}
}, descriptor);
assert.equal(appliedClassification.outcome, "applied");
assert.equal(classifyQueuedUpdateReadBack(updateEntry("saving"), {
  module: "module", record_id: "record-1", record: {daten: {text: "old"}}, meta: {revision: "base-1"}
}, descriptor).outcome, "not_applied");
assert.equal(classifyQueuedUpdateReadBack(updateEntry("saving"), {
  module: "module", record_id: "record-1", record: {daten: {text: "other"}}, meta: {revision: "other-revision"}
}, descriptor).outcome, "conflict");

// An unchanged base revision is safely requeued with the original operation, snapshot and base revision.
const notApplied = updateEntry("saving");
const notAppliedStore = new MemoryStore([notApplied]);
let resent;
const notAppliedProcessor = createSaveQueueProcessor({
  store: notAppliedStore,
  resolveUpdate: async entry => ({outcome: "not_applied", result: {meta: {revision: entry.base_revision}}}),
  sendUpdate: async entry => {
    resent = entry;
    return {record: {daten: {text: "local"}}, meta: {revision: "next-2"}};
  }
});
await notAppliedProcessor.initializeRecovery();
await notAppliedProcessor.retryFirst();
assert.equal(resent.operation_id, notApplied.operation_id);
assert.equal(resent.base_revision, "base-1");
assert.deepEqual(resent.snapshot, notApplied.snapshot);

// A changed revision plus a different snapshot becomes a durable conflict.
const conflictStore = new MemoryStore([updateEntry("saving")]);
const conflictProcessor = createSaveQueueProcessor({
  store: conflictStore,
  resolveUpdate: async () => ({outcome: "conflict", result: {}})
});
await conflictProcessor.initializeRecovery();
assert.equal(await conflictProcessor.retryFirst(), false);
assert.equal((await conflictStore.list())[0].status, "conflict");
assert.equal(await conflictProcessor.retryFirst(), false);

// Reservation recovery repeats the same idempotency key and advances counters only once.
const reserving = createCreateQueueEntry({
  operationId: "reserve-reload", moduleId: "reserve-module", identityAssignment: "reserve_before_create",
  snapshot: {daten: {text: "draft"}}, queueSequence: 1
});
const reserveStore = new MemoryStore([reserving]);
const reservations = new Map([["reserve-reload", {record_id: "record-1", identity: {id: "record-1"}}]]);
let counter = 2;
let reservedCreate;
const reserveProcessor = createSaveQueueProcessor({
  store: reserveStore,
  reserveIdentity: async entry => {
    if (!reservations.has(entry.operation_id)) reservations.set(entry.operation_id, {record_id: `record-${counter++}`, identity: {id: "record-1"}});
    return reservations.get(entry.operation_id);
  },
  sendCreate: async entry => {
    reservedCreate = entry;
    return {record_id: entry.record_id, record: {...entry.snapshot, id: entry.record_id}, meta: {revision: "create-r1"}};
  }
});
await reserveProcessor.initializeRecovery();
await reserveProcessor.process();
assert.equal(counter, 2, "lost reservation response must not advance the counter again");
assert.equal(reservedCreate.operation_id, "reserve-reload");
assert.deepEqual(reservedCreate.identity, {id: "record-1"});
assert.equal((await reserveStore.list()).length, 0);

// A reserved entry never reserves again; an uncertain Create is retried idempotently.
const persistedReserved = normalizeQueueEntry({...reserving, status: "reserving", record_id: "record-1", identity: {id: "record-1"}});
assert.equal(persistedReserved.status, "queued");
const createSaving = {...createCreateQueueEntry({
  operationId: "create-lost-response", moduleId: "module", identityAssignment: "on_create", snapshot: {daten: {text: "created"}}, queueSequence: 1
}), status: "saving"};
const createStore = new MemoryStore([createSaving]);
const createdOperations = new Map([["create-lost-response", {record_id: "record-existing", record: {daten: {text: "created"}}, meta: {revision: "blob-existing"}}]]);
let newCreates = 0;
let retriedCreateEntry;
const createProcessor = createSaveQueueProcessor({
  store: createStore,
  sendCreate: async entry => {
    retriedCreateEntry = entry;
    if (!createdOperations.has(entry.operation_id)) {
      newCreates += 1;
      createdOperations.set(entry.operation_id, {record_id: "new", record: entry.snapshot, meta: {revision: "new"}});
    }
    return createdOperations.get(entry.operation_id);
  }
});
await createProcessor.initializeRecovery();
await createProcessor.process();
await createProcessor.retryFirst();
assert.equal(retriedCreateEntry.operation_id, "create-lost-response");
assert.equal(newCreates, 0);
assert.equal((await createStore.list()).length, 0);

// Auth/network failures keep the first entry and block later FIFO work; retry reuses it.
const authStore = new MemoryStore();
let authenticated = false;
const attempted = [];
const authProcessor = createSaveQueueProcessor({
  store: authStore,
  sendUpdate: async entry => {
    attempted.push(entry.operation_id);
    if (!authenticated) { const error = new Error("login"); error.status = 401; throw error; }
    return {record: entry.snapshot, meta: {revision: "ok"}};
  }
});
await authProcessor.enqueueUpdate({operationId: "auth-first", moduleId: "module", recordId: "A", baseRevision: "a", snapshot: {daten: {text: "A"}}});
await authProcessor.enqueueUpdate({operationId: "later", moduleId: "module", recordId: "B", baseRevision: "b", snapshot: {daten: {text: "B"}}});
assert.equal(await authProcessor.process(), false);
assert.deepEqual(attempted, ["auth-first"]);
const authEntry = (await authStore.list())[0];
assert.equal(authEntry.status, "auth_error");
assert.deepEqual(authEntry.snapshot, {daten: {text: "A"}});
authenticated = true;
await authProcessor.retryFirst();
assert.deepEqual(attempted, ["auth-first", "auth-first", "later"]);

for (const status of [403, 422]) {
  const store = new MemoryStore();
  const processor = createSaveQueueProcessor({store, sendUpdate: async () => {
    const error = new Error("blocked"); error.status = status; throw error;
  }});
  await processor.enqueueUpdate({operationId: `http-${status}`, moduleId: "module", recordId: `R-${status}`, baseRevision: "base", snapshot: {daten: {text: "keep"}}});
  await processor.process();
  const blocked = (await store.list())[0];
  assert.equal(blocked.status, status === 403 ? "auth_error" : "validation_error");
  if (status === 422) assert.equal(await processor.retryFirst(), false);
}

const validationStore = new MemoryStore();
const validationUiStates = [];
let validationProcessor;
validationProcessor = createSaveQueueProcessor({
  store: validationStore,
  sendUpdate: async () => {
    const error = new Error("invalid");
    error.status = 422;
    throw error;
  },
  onChange: async (entry, entries) => {
    const first = entries[0];
    validationUiStates.push({
      notifiedStatus: entry?.status || null,
      queueStatus: first?.status || null,
      running: validationProcessor.isRunning(),
      discardDisabled: !first || validationProcessor.isRunning(),
      retryDisabled: !first || validationProcessor.isRunning() ||
        ["conflict", "validation_error"].includes(first.status),
    });
  },
});
await validationProcessor.enqueueUpdate({
  operationId: "validation-ui",
  moduleId: "module",
  recordId: "validation-record",
  baseRevision: "base",
  snapshot: { daten: { text: "keep" } },
});
await validationProcessor.process();
assert.equal(
  validationUiStates.some(state => state.queueStatus === "saving" && state.running),
  true,
);
assert.equal(
  validationUiStates.some(state => state.notifiedStatus === "validation_error" && state.running),
  true,
);
const finalValidationUi = validationUiStates.at(-1);
assert.deepEqual(finalValidationUi, {
  notifiedStatus: null,
  queueStatus: "validation_error",
  running: false,
  discardDisabled: false,
  retryDisabled: true,
});
assert.equal(validationProcessor.isRunning(), false);
assert.equal(await validationProcessor.retryFirst(), false);

const networkStore = new MemoryStore();
const networkProcessor = createSaveQueueProcessor({store: networkStore, sendUpdate: async () => { throw new Error("network"); }});
await networkProcessor.enqueueUpdate({operationId: "network", moduleId: "module", recordId: "N", baseRevision: "n", snapshot: {daten: {text: "keep"}}});
await networkProcessor.process();
assert.equal((await networkStore.list())[0].last_error.uncertain, true);

// Full validation recovery: open, edit, explicitly discard the old operation, then save as a new Create.
const recoveryDescriptor = {module: "module", fields: [
  {path: "daten.text", visible: true, editable: true, required: true},
  {path: "erschliessung.ort.name", visible: true, editable: true},
]};
const oldOperationId = "validation-create-old";
const validationCreate = {
  ...createCreateQueueEntry({
    operationId: oldOperationId,
    moduleId: "module",
    identityAssignment: "on_create",
    snapshot: {daten: {text: "draft"}, erschliessung: {ort: {name: ""}}},
    queueSequence: 1,
  }),
  status: "validation_error",
};
const recoveryStore = new MemoryStore([validationCreate]);
const recoveryContexts = new Map();
let recoveryEntries = [];
let recoveryControls = {};
let recoveryState = null;
let recoveryCreate = null;
let backendCreates = 0;
let sentCreate = null;
let recoveryProcessor;

function updateRecoveryControls(entries) {
  recoveryEntries = entries;
  const first = entries[0];
  const running = recoveryProcessor.isRunning();
  recoveryControls = {
    retryDisabled: !first || running || ["conflict", "validation_error"].includes(first.status),
    openDisabled: !first,
    discardDisabled: !first || running,
  };
}

function recoverySaveDisabled() {
  const hasContext = [...recoveryContexts.values()].some(context => (
    context.formState === recoveryState && context.create === recoveryCreate
  ));
  return hasContext || !recoveryCreate?.canSave("edit");
}

recoveryProcessor = createSaveQueueProcessor({
  store: recoveryStore,
  sendCreate: async entry => {
    backendCreates += 1;
    sentCreate = entry;
    return {record_id: "created-1", record: entry.snapshot, meta: {revision: "created-r1"}};
  },
  onChange: async (_entry, entries) => updateRecoveryControls(entries),
});
await recoveryProcessor.initializeRecovery();
assert.equal(recoveryProcessor.isRunning(), false);
assert.deepEqual(recoveryControls, {retryDisabled: true, openDisabled: false, discardDisabled: false});
assert.equal(await recoveryProcessor.retryFirst(), false);

// Mirror openQueuedSnapshot(): restore the persisted Create and explicitly refresh queue controls.
recoveryControls.discardDisabled = true; // stale DOM state from the worker callback
recoveryState = new FormState(recoveryDescriptor, {});
recoveryState.loadWorkingSnapshot(validationCreate.snapshot);
recoveryState.beginCreateSave();
recoveryCreate = new RecordCreate("module", recoveryState);
recoveryContexts.set(oldOperationId, {operationId: oldOperationId, formState: recoveryState, create: recoveryCreate});
updateRecoveryControls(recoveryEntries);
assert.equal(recoveryControls.discardDisabled, false, "opening recomputes stale queue controls with running=false");
assert.equal(recoverySaveDisabled(), true, "the old queue context prevents a duplicate Create");

recoveryState.setValue("daten.text", "corrected");
assert.equal(recoveryState.hasUnpersistedChanges(), true);
assert.equal(recoverySaveDisabled(), true, "editing does not bypass the old queue context");

const openedContext = recoveryContexts.get(oldOperationId);
if (openedContext.formState === recoveryState) recoveryState.cancelSave();
await recoveryProcessor.discard(oldOperationId);
recoveryContexts.delete(oldOperationId);
assert.equal((await recoveryStore.list()).length, 0);
assert.equal(recoveryContexts.has(oldOperationId), false);
assert.equal(recoveryState.getValue("daten.text"), "corrected", "discard keeps the edited working record");
assert.equal(backendCreates, 0, "discard does not call the backend");
assert.equal(recoverySaveDisabled(), false, "normal Save is enabled after removing the old context");

const newOperationId = "validation-create-new";
const correctedSnapshot = recoveryState.beginCreateSave();
await recoveryProcessor.enqueueCreate({
  operationId: newOperationId,
  moduleId: "module",
  identityAssignment: "on_create",
  snapshot: correctedSnapshot,
});
assert.equal((await recoveryStore.list())[0].operation_id, newOperationId);
assert.notEqual(newOperationId, oldOperationId);
await recoveryProcessor.process();
assert.equal(backendCreates, 1, "the recovery flow sends exactly one corrected Create");
assert.equal(sentCreate.operation_id, newOperationId);
assert.notEqual(sentCreate.operation_id, oldOperationId);
assert.deepEqual(sentCreate.snapshot, {daten: {text: "corrected"}}, "the new Create uses current cleanup rules");
assert.equal((await recoveryStore.list()).length, 0);

console.log("Recovery reload, read-back, idempotent create/reservation, auth, errors, FIFO, open and discard assertions passed");
