const assert = require("node:assert/strict");
require("../app/generic/save-queue.js");

function clone(value) { return JSON.parse(JSON.stringify(value)); }

class MemoryStore {
  constructor(shared = new Map()) { this.entries = shared; }
  async put(entry) { this.entries.set(entry.operation_id, clone(entry)); return clone(entry); }
  async get(id) { const entry = this.entries.get(id); return entry ? clone(entry) : null; }
  async list() { return [...this.entries.values()].map(clone).sort((a, b) => a.created_at.localeCompare(b.created_at)); }
  async update(id, changes) {
    const current = this.entries.get(id);
    if (!current) throw new Error("missing queue entry");
    const updated = { ...current, ...clone(changes) };
    this.entries.set(id, updated);
    return clone(updated);
  }
  async remove(id) { this.entries.delete(id); }
}

async function run() {
  const original = { nested: { title: "Original" } };
  const copied = createSaveQueueEntry({ operationId: "copy", operation: "update", recordId: "foto-1", partition: "A", baseRevision: "rev-1", snapshot: original });
  original.nested.title = "Changed later";
  assert.equal(copied.snapshot.nested.title, "Original", "queue snapshots are deep copies");
  assert.deepEqual(Object.keys(copied).sort(), [
    "attempt_count", "base_revision", "created_at", "last_error", "operation", "operation_id",
    "partition", "record_id", "signature", "snapshot", "status", "updated_at"
  ], "queue entries use only the generic schema");

  const shared = new Map();
  await new MemoryStore(shared).put(copied);
  assert.equal((await new MemoryStore(shared).list()).length, 1, "a fresh store instance sees persisted entries");

  const store = new MemoryStore();
  const calls = [];
  let releaseFirst;
  const firstFinished = new Promise((resolve) => { releaseFirst = resolve; });
  const processor = createSaveQueueProcessor({ store, handlers: { update: async (entry) => {
    calls.push(`start:${entry.operation_id}`);
    if (entry.operation_id === "one") await firstFinished;
    calls.push(`end:${entry.operation_id}`);
    return { ok: true };
  } } });
  await store.put(createSaveQueueEntry({ operationId: "one", operation: "update", snapshot: { n: 1 } }));
  await new Promise((resolve) => setTimeout(resolve, 2));
  await store.put(createSaveQueueEntry({ operationId: "two", operation: "update", snapshot: { n: 2 } }));
  const processing = processor.process();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(calls, ["start:one"], "the second operation waits for the first");
  releaseFirst();
  await processing;
  assert.deepEqual(calls, ["start:one", "end:one", "start:two", "end:two"], "operations run sequentially");
  assert.equal((await store.list()).length, 0, "confirmed operations are removed");

  const failedStore = new MemoryStore();
  const attempted = [];
  const failedProcessor = createSaveQueueProcessor({ store: failedStore, handlers: { update: async (entry) => {
    attempted.push(entry.operation_id);
    const error = new Error("conflict"); error.status = 409; throw error;
  } } });
  await failedStore.put(createSaveQueueEntry({ operationId: "bad", operation: "update", snapshot: {} }));
  await new Promise((resolve) => setTimeout(resolve, 2));
  await failedStore.put(createSaveQueueEntry({ operationId: "later", operation: "update", snapshot: {} }));
  assert.equal(await failedProcessor.process(), false);
  assert.deepEqual(attempted, ["bad"], "processing stops after the first error");
  const failed = await failedStore.get("bad");
  assert.equal(failed.status, "error");
  assert.equal(failed.attempt_count, 1);
  assert.equal(failed.last_error.http_status, 409);
  assert.ok(await failedStore.get("later"), "later entries remain queued");

  const networkStore = new MemoryStore();
  await networkStore.put(createSaveQueueEntry({ operationId: "uncertain", operation: "update", snapshot: {} }));
  await createSaveQueueProcessor({
    store: networkStore,
    handlers: { update: async () => { throw new Error("connection lost"); } }
  }).process();
  const uncertain = await networkStore.get("uncertain");
  assert.equal(uncertain.status, "error");
  assert.equal(uncertain.last_error.uncertain, true, "network failures are marked as technically uncertain");

  const reserveStore = new MemoryStore();
  await reserveStore.put(createSaveQueueEntry({ operationId: "create-one", operation: "create", partition: "B", snapshot: {}, status: "reserving" }));
  const reserved = await createSaveQueueProcessor({ store: reserveStore, handlers: {} }).reserve("create-one", async () => ({
    record_id: "foto-9", signature: "9.4.2.B.4", partition: "B", signature_data: { format: "B", nummer: 4 }
  }));
  assert.equal(reserved.entry.status, "queued");
  assert.equal(reserved.entry.record_id, "foto-9");
  assert.equal(reserved.reservation.signature_data.nummer, 4);
  assert.equal("signature_data" in reserved.entry, false, "domain response data is not added to the generic queue schema");

  const serializedStore = new MemoryStore();
  let releaseWrite;
  let reservationStarted = false;
  await serializedStore.put(createSaveQueueEntry({ operationId: "write-first", operation: "update", snapshot: {} }));
  await serializedStore.put(createSaveQueueEntry({ operationId: "reserve-second", operation: "create", partition: "A", snapshot: {}, status: "reserving" }));
  const serialized = createSaveQueueProcessor({
    store: serializedStore,
    handlers: { update: () => new Promise((resolve) => { releaseWrite = resolve; }) }
  });
  const activeWrite = serialized.process();
  await new Promise((resolve) => setImmediate(resolve));
  const waitingReservation = serialized.reserve("reserve-second", async () => {
    reservationStarted = true;
    return { record_id: "foto-10", signature: "9.4.2.A.10", partition: "A" };
  });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(reservationStarted, false, "reservation waits for an active remote write");
  releaseWrite({ ok: true });
  await activeWrite;
  await waitingReservation;
  assert.equal(reservationStarted, true, "reservation starts after the previous write completes");
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
