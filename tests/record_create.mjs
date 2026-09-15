import assert from "node:assert/strict";
import {RecordCreate} from "../app/generic/record-create.js";
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
  record: {id: "other-0001", signatur: {anzeige: "OTHER.A.1"}, daten: {text: "server canonical"}},
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

const discard = fixture(async () => { throw new Error("not called"); });
discard.formState.setValue("daten.text", "discard me");
discard.formState.discardChanges();
assert.deepEqual(discard.formState.current, {});
assert.equal(discard.formState.isDirty(), false);

console.log("POST payload, server state, errors, discard and duplicate-create assertions passed");
