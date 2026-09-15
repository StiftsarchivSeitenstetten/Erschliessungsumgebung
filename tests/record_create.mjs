import assert from "node:assert/strict";
import {RecordCreate, reserveQueuedRecordIdentity, sendQueuedRecordCreate} from "../app/generic/record-create.js";
import {RecordUpdate} from "../app/generic/record-update.js";
import {FormState} from "../app/generic/form-state.js";

const descriptor = {fields: [
  {path: "daten.text", visible: true, editable: true},
  {path: "signatur.anzeige", visible: true, editable: false},
  {path: "id", visible: true, editable: false},
  {path: "technik.erstellt_von", visible: false, editable: false}
]};

function fixture(request) {
  const form = new FormState(descriptor, {});
  return new RecordCreate("other-module", form, request);
}

const response = {
  module: "other-module",
  record_id: "other-0001",
  record: {id: "other-0001", signatur: {anzeige: "OTHER.A.1"}, daten: {text: "new value"}},
  meta: {revision: "revision-a"}
};
let calls = [];
const creator = fixture(async (url, options) => {
  calls.push({url, options});
  return {ok: true, status: 201, json: async () => response};
});
assert.deepEqual(creator.formState.current, {});
assert.equal(creator.canSave("edit"), false);
creator.formState.setValue("daten.text", "new value");
assert.equal(creator.canSave("read"), false);
assert.equal(creator.canSave("edit"), true);
const created = await creator.save("edit", "csrf-test");
assert.equal(calls[0].url, "/api/modules/other-module/records");
assert.equal(calls[0].options.method, "POST");
assert.equal(calls[0].options.headers["X-CSRF-Token"], "csrf-test");
assert.deepEqual(JSON.parse(calls[0].options.body), {record: {daten: {text: "new value"}}});
assert.equal(JSON.parse(calls[0].options.body).base_revision, undefined);
assert.equal(created.record_id, "other-0001");
assert.equal(creator.recordId, "other-0001");
assert.equal(creator.revision, "revision-a");
assert.deepEqual(creator.formState.original, response.record);
assert.deepEqual(creator.formState.serverSnapshot, response.record);
assert.deepEqual(creator.formState.workingRecord, response.record);
assert.equal(creator.formState.pendingSnapshot, null);
assert.equal(creator.formState.getValue("signatur.anzeige"), "OTHER.A.1");
assert.equal(creator.formState.isDirty(), false);
assert.equal(await creator.save("edit", "csrf-test"), null);
assert.equal(calls.length, 1);

for (const status of [401, 403, 422, 500]) {
  const failed = fixture(async () => ({ok: false, status, json: async () => ({detail: ["invalid"]})}));
  failed.formState.setValue("daten.text", "keep draft");
  await assert.rejects(() => failed.save("edit", "csrf-test"));
  assert.equal(failed.formState.getValue("daten.text"), "keep draft");
  assert.equal(failed.formState.isDirty(), true);
  assert.equal(failed.formState.pendingSnapshot, null);
  assert.equal(failed.recordId, null);
  assert.equal(failed.revision, null);
  assert.equal(failed.canSave("edit"), true);
}

const network = fixture(async () => { throw new Error("network"); });
network.formState.setValue("daten.text", "keep draft");
await assert.rejects(() => network.save("edit", "csrf-test"));
assert.equal(network.formState.isDirty(), true);
assert.equal(network.canSave("edit"), true);

let finish;
let callCount = 0;
const delayed = fixture(() => {
  callCount += 1;
  return new Promise(resolve => { finish = resolve; });
});
delayed.formState.setValue("daten.text", "new value");
const first = delayed.save("edit", "csrf-test");
assert.equal(delayed.canSave("edit"), false);
assert.equal(await delayed.save("edit", "csrf-test"), null);
assert.equal(callCount, 1);
finish({ok: true, status: 201, json: async () => response});
await first;
assert.equal(delayed.formState.isDirty(), false);

delayed.formState.setValue("daten.text", "after create");
let updateBody;
const updater = new RecordUpdate("other-module", delayed.recordId, delayed.formState, delayed.revision, async (url, options) => {
  updateBody = JSON.parse(options.body);
  return {ok: true, json: async () => ({
    record_id: "other-0001",
    record: {...response.record, daten: {text: "after create"}},
    meta: {revision: "revision-b"}
  })};
});
await updater.save("edit", "csrf-test");
assert.deepEqual(updateBody, {base_revision: "revision-a", record: {daten: {text: "after create"}}});
assert.equal(updater.revision, "revision-b");
assert.equal(delayed.formState.isDirty(), false);

const discard = fixture(async () => { throw new Error("not called"); });
discard.formState.setValue("daten.text", "discard me");
discard.formState.discardChanges();
assert.deepEqual(discard.formState.current, {});
assert.equal(discard.formState.isDirty(), false);

const queuedEntry = {
  operation_id: "operation-1",
  module_id: "other-module",
  record_id: null,
  identity: null,
  snapshot: {daten: {text: "queued value"}}
};
let reservationRequest;
const reservation = await reserveQueuedRecordIdentity(queuedEntry, "csrf-reserve", async (url, options) => {
  reservationRequest = {url, options};
  return {ok: true, status: 200, json: async () => ({
    module: "other-module", operation_id: "operation-1", record_id: "other-0002",
    identity: {id: "other-0002", signatur: {anzeige: "OTHER.A.2"}}
  })};
});
assert.equal(reservationRequest.url, "/api/modules/other-module/reservations");
assert.equal(reservationRequest.options.method, "POST");
assert.equal(reservationRequest.options.headers["X-CSRF-Token"], "csrf-reserve");
assert.deepEqual(JSON.parse(reservationRequest.options.body), {
  operation_id: "operation-1", record: {daten: {text: "queued value"}}
});
assert.equal(reservation.record_id, "other-0002");

const reservedEntry = {...queuedEntry, record_id: reservation.record_id, identity: reservation.identity};
let createRequest;
const queuedCreated = await sendQueuedRecordCreate(reservedEntry, "csrf-create", async (url, options) => {
  createRequest = {url, options};
  return {ok: true, status: 201, json: async () => ({
    module: "other-module", record_id: "other-0002",
    record: {...reservedEntry.snapshot, ...reservedEntry.identity}, meta: {revision: "revision-c"}
  })};
});
assert.equal(createRequest.url, "/api/modules/other-module/records");
assert.equal(createRequest.options.method, "POST");
assert.equal(createRequest.options.headers["X-CSRF-Token"], "csrf-create");
assert.deepEqual(JSON.parse(createRequest.options.body), {
  record: {daten: {text: "queued value"}}, operation_id: "operation-1", identity: reservation.identity
});
assert.equal(queuedCreated.meta.revision, "revision-c");

console.log("POST snapshots, queued transports, reservation, errors, discard and following PUT assertions passed");
