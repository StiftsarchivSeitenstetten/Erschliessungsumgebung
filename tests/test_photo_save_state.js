const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
require("../app/generic/save-queue.js");

const clone = (value) => JSON.parse(JSON.stringify(value));
class Element {
  constructor(selector = "") {
    this.selector = selector; this.value = ""; this.checked = false; this.disabled = false;
    this.hidden = false; this.dataset = {}; this.textContent = ""; this.rows = []; this.children = {}; this._innerHTML = "";
    this.classList = { add() {}, remove() {}, toggle() {} };
  }
  addEventListener() {}
  append(...items) { if (this.selector === "#personen-list") this.rows.push(...items); }
  setAttribute() {}
  set innerHTML(value) {
    this._innerHTML = value;
    if (this.selector === "#personen-list" && value === "") this.rows = [];
    if (value.includes("person-name")) {
      const values = [...value.matchAll(/value="([^"]*)"/g)].map((match) => match[1]);
      this.children[".person-name"] = Object.assign(new Element(), { value: values[0] || "" });
      this.children[".person-hinweis"] = Object.assign(new Element(), { value: values[1] || "" });
      this.children[".remove-person"] = new Element();
    }
  }
  get innerHTML() { return this._innerHTML; }
  querySelector(selector) { return this.children[selector] || new Element(selector); }
}

const selectors = [
  "#record-form", "#errors", "#preview", "#generate", "#download", "#finalize", "#discard-changes", "#save-status",
  "#queue-status", "#queue-recovery-actions", "#retry-queue", "#open-queued-snapshot", "#discard-queued-save",
  "#number-output", "#signature-output", "#archivis-date", "#preset-status", "#preset-editor",
  "#preset-field-list", "#current-user", "#record-browser", "#record-search", "#record-list", "#record-nav-top",
  "#record-nav-bottom", "#personen-list", "#beschriftung", "#titel", "#beschreibung", "#herkunft", "#sammler",
  "#fotograf", "#rechteinhaber", "#orte", "#schlagworte", "#altsignaturen", "#interne-bemerkung",
  "#korrespondenzstueck", "#datierung-einfach", "#datierung-anmerkung", "#original-datum", "#mode-new", "#mode-edit"
];
const elements = Object.fromEntries(selectors.map((selector) => [selector, new Element(selector)]));
elements["#record-form"].reset = () => {
  for (const selector of selectors) {
    if (!["#record-form", "#personen-list"].includes(selector)) { elements[selector].value = ""; elements[selector].checked = false; }
  }
};
const formatInput = Object.assign(new Element(), { value: "A", checked: true });
const document = {
  cookie: "csrf=test", body: new Element("body"),
  querySelector(selector) {
    if (selector.startsWith("input[name='format'][value=")) return formatInput;
    return elements[selector] || new Element(selector);
  },
  querySelectorAll(selector) {
    if (selector === ".person-row") return elements["#personen-list"].rows;
    if (selector === "input[name='format']") return [formatInput];
    return [];
  },
  createElement(selector) { return new Element(selector); }
};
let operationNumber = 0;
const window = {
  location: { href: "http://localhost/app/?record=foto-000001", pathname: "/app/", search: "?record=foto-000001" },
  history: { replaceState() {} }, navigator: {}, addEventListener() {}, confirm() { return true; }, setTimeout,
  crypto: { randomUUID() { operationNumber += 1; return `operation-${operationNumber}`; } }
};
const localStorage = { getItem() { return "redaktion"; }, setItem() {}, removeItem() {} };

class MemoryStore {
  constructor(events) { this.entries = new Map(); this.events = events; }
  async put(entry) { this.events.push(`put:${entry.operation_id}`); this.entries.set(entry.operation_id, clone(entry)); return clone(entry); }
  async get(id) { return this.entries.has(id) ? clone(this.entries.get(id)) : null; }
  async list() { return [...this.entries.values()].map(clone).sort((a, b) => a.created_at.localeCompare(b.created_at)); }
  async update(id, changes) { const value = { ...this.entries.get(id), ...clone(changes) }; this.entries.set(id, value); return clone(value); }
  async remove(id) { this.events.push(`remove:${id}`); this.entries.delete(id); }
}

const source = fs.readFileSync(path.join(__dirname, "..", "app", "app.js"), "utf8").replace(/\ninit\(\)\.catch\([\s\S]*$/, "\n");
const test = `
function testRecord(title, id = "foto-000001", number = 1) {
  return {
    id, signatur: { bestand: "9", objektgruppe: "4.2", format: "A", nummer: number, anzeige: "9.4.2.A." + number, status: "vergeben" },
    erschliessung: { titel: title, beschriftung: "Beschriftung", beschreibung: null, dargestellte_personen: [], herkunft: null,
      sammler: null, fotograf: null, rechteinhaber: null, orte: [], schlagworte: [], altsignaturen: [], interne_bemerkung: null },
    korrespondenzstueck: false,
    datierung: { jahr: null, monat: null, tag: null, anmerkung: null, original: null, original_typ: null },
    redaktion: { stufe: "erschlossen" }
  };
}
function configureQueue(events) {
  state.queueRecoveryRunning = false;
  saveQueueStore = new MemoryStore(events);
  saveQueueProcessor = createSaveQueueProcessor({
    store: saveQueueStore,
    handlers: { update: sendQueuedUpdate, create: sendQueuedCreate, onSuccess: handleQueuedSaveSuccess, onError: handleQueuedSaveError },
    onChange: handleQueueChange
  });
  scheduleQueueProcessing = () => {};
}
function workingSnapshot(title) {
  const record = testRecord(title);
  return {
    format: "A", erschliessung: record.erschliessung, korrespondenzstueck: false, datierung: record.datierung
  };
}
function queueEntry(operationId, operation, status, snapshot, extra = {}) {
  return {
    ...createSaveQueueEntry({ operationId, operation, recordId: extra.record_id || null, signature: extra.signature || null,
      partition: "A", baseRevision: extra.base_revision || null, snapshot, status }),
    last_error: extra.last_error || null
  };
}
async function runSaveStateTests() {
  config = {
    datensatz_typ: "foto", module_id: "foto_papierabzuege",
    signature: { formats: ["A"], pattern: "{bestand}.{objektgruppe}.{format}.{nummer}", bestand: "9", objektgruppe: "4.2" },
    defaults: { redaktion_stufe: "erschlossen", bearbeitung_status: "offen", publikation_status: "intern" },
    ui_profiles: { redaktion: { editable_fields: Object.keys(fieldMap), technical_preview: true } }
  };
  state.user = { role: "redaktion", ui_profile: "redaktion", csrf_cookie_name: "csrf" };
  state.records = [testRecord("A"), testRecord("Other", "foto-000002", 2)];
  refreshRecords = async () => {};
  assert.equal(failureSaveState(401), SAVE_STATES.AUTH_ERROR);
  assert.equal(failureSaveState(403), SAVE_STATES.AUTH_ERROR);
  assert.equal(failureSaveState(409), SAVE_STATES.CONFLICT);
  assert.equal(failureSaveState(422), SAVE_STATES.VALIDATION_ERROR);
  assert.equal(failureSaveState(500), SAVE_STATES.ERROR);

  const events = [];
  configureQueue(events);
  applyLoadedRecord(testRecord("A"), "rev-a");
  elements["#titel"].value = "B";
  updateDirtyState();
  let updatePayload;
  apiFetch = async (_url, options) => {
    events.push("request:update"); updatePayload = JSON.parse(options.body);
    return { ok: true, async json() { return { record: testRecord(updatePayload.erschliessung.titel), base_revision: "rev-b" }; } };
  };
  await finalizeRecord();
  assert.deepEqual(events, ["put:operation-1"], "the update is persisted before network access");
  assert.equal(state.saveState, SAVE_STATES.QUEUED);
  assert.equal(hasUnsecuredChanges(), false, "queued navigation is allowed");
  await saveQueueProcessor.process();
  assert.equal(updatePayload.base_revision, "rev-a");
  assert.equal(state.saveState, SAVE_STATES.CLEAN);
  assert.equal((await saveQueueStore.list()).length, 0);
  assert.equal(queueStatus.textContent, "Alle vorgemerkten Datensätze übertragen");

  configureQueue([]);
  applyLoadedRecord(testRecord("A"), "rev-a");
  elements["#titel"].value = "queued snapshot"; updateDirtyState(); await finalizeRecord();
  elements["#titel"].value = "newer input"; updateDirtyState();
  assert.equal((await saveQueueStore.get("operation-2")).snapshot.erschliessung.titel, "queued snapshot", "later edits do not mutate the snapshot");
  apiFetch = async (_url, options) => {
    const payload = JSON.parse(options.body);
    return { ok: true, async json() { return { record: testRecord(payload.erschliessung.titel), base_revision: "rev-c" }; } };
  };
  await saveQueueProcessor.process();
  assert.equal(elements["#titel"].value, "newer input");
  assert.equal(state.saveState, SAVE_STATES.DIRTY, "newer input remains dirty after acknowledgement");

  configureQueue([]);
  applyLoadedRecord(testRecord("A"), "rev-a");
  elements["#titel"].value = "will conflict"; updateDirtyState(); await finalizeRecord();
  apiFetch = async () => ({ ok: false, status: 409, async json() { return { detail: "revision conflict" }; } });
  assert.equal(await saveQueueProcessor.process(), false);
  const failed = await saveQueueStore.get("operation-3");
  assert.equal(failed.status, "conflict", "failed entries remain persisted and classified");
  assert.equal(failed.last_error.http_status, 409);
  assert.equal(state.saveState, SAVE_STATES.CONFLICT);
  assert.match(queueStatus.textContent, /pausiert: Serverstand wurde geändert/);
  assert.equal(hasUnsecuredChanges(), false, "the failed but persisted snapshot can be left safely");

  configureQueue([]);
  applyLoadedRecord(testRecord("A"), "rev-a");
  elements["#titel"].value = "Photo A pending"; updateDirtyState(); await finalizeRecord();
  let release;
  apiFetch = async (_url, options) => {
    await new Promise((resolve) => { release = resolve; });
    const payload = JSON.parse(options.body);
    return { ok: true, async json() { return { record: testRecord(payload.erschliessung.titel), base_revision: "rev-new" }; } };
  };
  const background = saveQueueProcessor.process();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(state.saveState, SAVE_STATES.SAVING, "queued changes become visibly saving");
  applyLoadedRecord(testRecord("Photo B", "foto-000002", 2), "rev-b");
  release(); await background;
  assert.equal(state.editingRecord.id, "foto-000002");
  assert.equal(elements["#titel"].value, "Photo B", "Photo A response does not overwrite Photo B");

  configureQueue([]);
  elements["#korrespondenzstueck"].checked = true;
  startNewRecord();
  assert.equal(elements["#korrespondenzstueck"].checked, false, "a new record resets the correspondence checkbox");
  state.format = "A"; formatInput.checked = true; elements["#beschriftung"].value = "New photo";
  updateSignatureOutput();
  assert.equal(numberOutput.textContent, "-");
  assert.match(signatureOutput.textContent, /reserviert/);
  let createPayload;
  apiFetch = async (url, options) => {
    if (url.endsWith("/reservations")) {
      assert.ok(await saveQueueStore.get("operation-5"), "reservation starts only after local persistence");
      assert.equal(state.saveState, SAVE_STATES.RESERVING);
      assert.equal(hasUnsecuredChanges(), true, "new-record navigation stays blocked until reservation succeeds");
      return { ok: true, async json() { return {
        operation_id: "operation-5", record_id: "foto-000010", signature: "9.4.2.A.10", partition: "A",
        signature_data: { bestand: "9", objektgruppe: "4.2", format: "A", nummer: 10, anzeige: "9.4.2.A.10", status: "vergeben" }
      }; } };
    }
    createPayload = JSON.parse(options.body);
    return { ok: true, async json() { return { record: testRecord(null, "foto-000010", 10), base_revision: "rev-created" }; } };
  };
  await finalizeRecord();
  assert.equal(state.saveState, SAVE_STATES.QUEUED);
  assert.equal(state.currentDraft.id, "foto-000010");
  assert.equal(signatureOutput.textContent, "9.4.2.A.10", "reserved identity becomes visible immediately");
  assert.equal(hasUnsecuredChanges(), false);
  const createEntry = await saveQueueStore.get("operation-5");
  assert.equal(createEntry.record_id, "foto-000010");
  assert.equal(createEntry.signature, "9.4.2.A.10");
  await saveQueueProcessor.process();
  assert.equal(createPayload.operation_id, "operation-5");
  assert.equal(createPayload.record_id, "foto-000010");
  assert.equal(createPayload.signature, "9.4.2.A.10");
  assert.equal((await saveQueueStore.list()).length, 0);
  assert.equal(state.mode, "edit", "a confirmed create becomes a normal existing record");
  assert.equal(state.currentQueueOperationId, null);
  assert.equal(state.saveState, SAVE_STATES.CLEAN);

  configureQueue([]);
  await saveQueueStore.put(queueEntry("reload-queued", "update", "queued", workingSnapshot("Recovered queued"), {
    record_id: "foto-000001", base_revision: "rev-a"
  }));
  let reloadPut = 0;
  apiFetch = async (_url, options) => {
    reloadPut += 1;
    const payload = JSON.parse(options.body);
    return { ok: true, async json() { return { record: testRecord(payload.erschliessung.titel), base_revision: "rev-recovered" }; } };
  };
  await resumeSafeQueueEntries();
  assert.equal(reloadPut, 1, "an unequivocally queued reload entry resumes automatically");
  assert.equal((await saveQueueStore.list()).length, 0);

  configureQueue([]);
  await saveQueueStore.put(queueEntry("same-reservation", "create", "reserving", workingSnapshot("Reserved recovery")));
  const recoveredCreateCalls = [];
  apiFetch = async (url, options) => {
    const payload = JSON.parse(options.body); recoveredCreateCalls.push({ url, payload });
    if (url.endsWith("/reservations")) return { ok: true, async json() { return {
      operation_id: payload.operation_id, record_id: "foto-000020", signature: "9.4.2.A.20", partition: "A",
      signature_data: { bestand: "9", objektgruppe: "4.2", format: "A", nummer: 20, anzeige: "9.4.2.A.20", status: "vergeben" }
    }; } };
    return { ok: true, async json() { return { record: testRecord("Reserved recovery", "foto-000020", 20), base_revision: "rev-20" }; } };
  };
  await resumeSafeQueueEntries();
  assert.deepEqual(recoveredCreateCalls.map((call) => call.payload.operation_id), ["same-reservation", "same-reservation"]);
  assert.equal((await saveQueueStore.list()).length, 0, "reserving recovery uses one operation through final create");

  configureQueue([]);
  await saveQueueStore.put(queueEntry("lost-create", "create", "error", workingSnapshot("Already created"), {
    record_id: "foto-000021", signature: "9.4.2.A.21", last_error: { uncertain: true }
  }));
  let lostCreatePayload;
  apiFetch = async (_url, options) => {
    lostCreatePayload = JSON.parse(options.body);
    return { ok: true, async json() { return { record: testRecord("Already created", "foto-000021", 21), base_revision: "rev-21" }; } };
  };
  await retryFirstQueueEntry();
  assert.equal(lostCreatePayload.operation_id, "lost-create");
  assert.equal(lostCreatePayload.record_id, "foto-000021");
  assert.equal((await saveQueueStore.list()).length, 0, "idempotent create recovery removes the confirmed entry");

  configureQueue([]);
  const alreadyApplied = workingSnapshot("Already applied");
  await saveQueueStore.put(queueEntry("lost-put", "update", "saving", alreadyApplied, {
    record_id: "foto-000001", base_revision: "rev-old"
  }));
  const recoveryMethods = [];
  apiFetch = async (_url, options) => {
    recoveryMethods.push(options.method);
    return { ok: true, async json() {
      const record = testRecord("Already applied");
      record.datierung = { jahr: null, monat: null, tag: null, anmerkung: null };
      return { record, base_revision: "rev-after" };
    } };
  };
  await retryFirstQueueEntry();
  assert.deepEqual(recoveryMethods, ["GET"], "a lost PUT response is resolved by read-back without another PUT");
  assert.equal((await saveQueueStore.list()).length, 0);

  configureQueue([]);
  await saveQueueStore.put(queueEntry("auth-retry", "update", "queued", workingSnapshot("After login"), {
    record_id: "foto-000001", base_revision: "rev-auth"
  }));
  apiFetch = async () => ({ ok: false, status: 401, async json() { return { detail: "login required" }; } });
  await saveQueueProcessor.process();
  assert.equal((await saveQueueStore.get("auth-retry")).status, "auth_error");
  const authMethods = [];
  apiFetch = async (_url, options) => {
    authMethods.push(options.method);
    if (options.method === "GET") return { ok: true, async json() { return { record: testRecord("A"), base_revision: "rev-auth" }; } };
    return { ok: true, async json() { return { record: testRecord("After login"), base_revision: "rev-auth-next" }; } };
  };
  await retryFirstQueueEntry();
  assert.deepEqual(authMethods, ["GET", "PUT"]);
  assert.equal((await saveQueueStore.list()).length, 0, "auth recovery continues the preserved operation after login");

  configureQueue([]);
  await saveQueueStore.put(queueEntry("real-conflict", "update", "saving", workingSnapshot("Local conflict"), {
    record_id: "foto-000001", base_revision: "rev-old"
  }));
  apiFetch = async () => ({ ok: true, async json() { return { record: testRecord("Server changed"), base_revision: "rev-other" }; } });
  await retryFirstQueueEntry();
  const conflictEntry = await saveQueueStore.get("real-conflict");
  assert.equal(conflictEntry.status, "conflict");
  assert.equal(conflictEntry.snapshot.erschliessung.titel, "Local conflict");

  configureQueue([]);
  await saveQueueStore.put(queueEntry("invalid", "update", "queued", workingSnapshot("Invalid"), {
    record_id: "foto-000001", base_revision: "rev-a"
  }));
  apiFetch = async () => ({ ok: false, status: 422, async json() { return { detail: ["invalid field"] }; } });
  await saveQueueProcessor.process();
  const invalidEntry = await saveQueueStore.get("invalid");
  assert.equal(invalidEntry.status, "validation_error");
  assert.equal(invalidEntry.snapshot.erschliessung.titel, "Invalid");
  apiFetch = async () => ({ ok: true, async json() { return { record: testRecord("Server valid"), base_revision: "rev-server" }; } });
  await openFirstQueuedSnapshot();
  assert.equal(elements["#titel"].value, "Invalid", "the retained validation snapshot can be opened for editing");
  assert.equal(state.currentQueueOperationId, "invalid");
  await discardFirstQueueEntry();
  assert.equal((await saveQueueStore.list()).length, 0, "only explicit confirmation discards the blocked queue entry");
  assert.equal(elements["#titel"].value, "Invalid", "discarding the queue leaves the opened working copy available");

  configureQueue([]);
  await saveQueueStore.put(queueEntry("legacy-auth", "update", "error", workingSnapshot("Auth"), {
    record_id: "foto-000001", base_revision: "rev-a", last_error: { http_status: 403, uncertain: false }
  }));
  await normalizePersistedQueueEntries();
  assert.equal((await saveQueueStore.get("legacy-auth")).status, "auth_error", "reload normalizes persisted HTTP failures");
}
return runSaveStateTests();
`;

const runTests = new Function(
  "assert", "elements", "document", "window", "localStorage", "fetch", "console", "MemoryStore", "createSaveQueueEntry", "createSaveQueueProcessor", "formatInput", source + test
);
runTests(assert, elements, document, window, localStorage, async () => { throw new Error("unexpected fetch"); }, { error() {} }, MemoryStore, createSaveQueueEntry, createSaveQueueProcessor, formatInput)
  .catch((error) => { console.error(error); process.exitCode = 1; });
