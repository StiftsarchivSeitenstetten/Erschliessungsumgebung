import { FormRenderer } from "../generic/form-renderer.js?v=vocabulary-2";
import { FormState } from "../generic/form-state.js?v=recovery-1";
import { ResultState, renderRecordList } from "../generic/record-list.js?v=create-1";
import { RecordCreate, reserveQueuedRecordIdentity, sendQueuedRecordCreate } from "../generic/record-create.js?v=recovery-1";
import { RecordUpdate, classifyQueuedUpdateReadBack, readQueuedRecordUpdate, sendQueuedRecordUpdate } from "../generic/record-update.js?v=recovery-1";
import { createIndexedDbSaveQueueStore } from "../generic/module-save-queue-store.js?v=queue-isolation-1";
import { createSaveQueueProcessor, queueEntryMatchesContext, queueRecordKey, queueStatusMessage } from "../generic/module-save-queue.js?v=queue-recovery-2";
import { PresetStore, presettableFields } from "../generic/preset-store.js?v=preset-1";
import { VocabularyClient } from "../generic/vocabulary-client.js?v=vocabulary-2";
import { reviewDateTextFields } from "../generic/widget-registry.js?v=vocabulary-2";

const params = new URLSearchParams(window.location.search);
const moduleKey = params.get("module");
const debugMode = params.get("debug") === "1";
const $ = selector => document.querySelector(selector);
const preview = $("#record-preview");
const payloadPreview = $("#payload-preview");
const toggleEdit = $("#toggle-edit");
const discardChanges = $("#discard-changes");
const state = new ResultState(moduleKey);
let mode = "read";
let currentDescriptor = null;
let currentFormState = null;
let renderer = new FormRenderer({ mode });
let generation = 0;
let acceptedUrl = location.href;
let currentUpdate = null;
let currentCreate = null;
let csrfCookieName = null;
let saveInProgress = false;
let presetStore = null;
let saveQueueStore = null;
let saveQueueProcessor = null;
let queueInitializationError = null;
let activeQueueRecordKeys = new Set();
let queueEntries = [];
const queueContexts = new Map();
const vocabularyClient = new VocabularyClient();

function currentRecordQueueKey() {
  return currentUpdate ? queueRecordKey(currentUpdate.moduleKey, currentUpdate.recordId) : null;
}

function currentRecordHasQueueEntry() {
  const key = currentRecordQueueKey();
  return Boolean(key && activeQueueRecordKeys.has(key));
}

function currentQueueContext() {
  return [...queueContexts.values()].find(context => (
    context.formState === currentFormState &&
    ((context.update && context.update === currentUpdate) || (context.create && context.create === currentCreate))
  )) || null;
}

function currentCreateAwaitingReservation() {
  const context = currentQueueContext();
  return Boolean(context?.create && context.identityAssignment === "reserve_before_create" && !context.identityReserved);
}

function currentPreset() {
  return presetStore?.load() || { values: {} };
}

function presetLabels(preset = currentPreset()) {
  const paths = new Set(Object.keys(preset.values));
  return presettableFields(currentDescriptor || {}).filter(field => paths.has(field.path)).map(field => field.label);
}

function updatePresetControls(message = "") {
  const labels = presetLabels();
  const editable = mode === "edit" && Boolean(currentFormState);
  $("#save-preset").disabled = !editable;
  $("#apply-preset").disabled = !editable || !labels.length;
  $("#delete-preset").disabled = !labels.length;
  $("#preset-status").textContent = message || (labels.length
    ? `Gespeichert für dieses Modul: ${labels.join(", ")}.`
    : "Keine Vorbelegungen gespeichert.");
}

function updateSaveButton() {
  const operation = currentCreate || currentUpdate;
  $("#save-record").disabled = saveInProgress || currentRecordHasQueueEntry() || Boolean(currentQueueContext()) || !operation?.canSave(mode);
}

function updateQueueStatus(entries = []) {
  queueEntries = entries;
  const queueStatus = $("#queue-status");
  activeQueueRecordKeys = new Set(entries.map(entry => queueRecordKey(entry.module_id, entry.record_id)));
  queueStatus.dataset.count = String(entries.length);
  if (queueInitializationError) {
    queueStatus.textContent = "Lokale Speicherwarteschlange nicht verfügbar.";
  } else {
    queueStatus.textContent = queueStatusMessage(entries, saveQueueProcessor?.isRunning());
  }
  const first = entries[0];
  const workerRunning = Boolean(saveQueueProcessor?.isRunning());
  const needsRecovery = Boolean(queueInitializationError || first && !["queued", "reserving", "saving"].includes(first.status));
  $("#queue-panel").hidden = !needsRecovery;
  $("#open-queue-entry").disabled = !first;
  $("#discard-queue-entry").disabled = !first || workerRunning;
  $("#retry-queue").disabled = !first || workerRunning || ["conflict", "validation_error"].includes(first.status);
  updateSaveButton();
}

function queueEntryMatchesCurrent(entry, context = queueContexts.get(entry.operation_id)) {
  return queueEntryMatchesContext(entry, context, {
    formState: currentFormState,
    update: currentUpdate,
    create: currentCreate,
    recordId: state.recordId,
    moduleId: currentDescriptor?.module,
    creating: state.creating
  });
}

function queueFailureMessage(entry) {
  if (entry.status === "auth_error") return "Anmeldung abgelaufen. Der lokal gesicherte Speichervorgang bleibt erhalten.";
  if (entry.status === "conflict") return "Der Serverstand wurde geändert. Der lokale Queue-Snapshot bleibt erhalten.";
  if (entry.status === "validation_error") return "Speichern wurde abgelehnt. Der lokale Queue-Snapshot bleibt erhalten.";
  if (entry.last_error?.uncertain) return "Ergebnis der letzten Übertragung ungeklärt. Vor einem erneuten PUT erfolgt ein Read-back.";
  return "Übertragung fehlgeschlagen. Der lokale Queue-Snapshot bleibt erhalten.";
}

async function handleQueueChange(entry, entries) {
  const existingOperationIds = new Set(entries.map(item => item.operation_id));
  for (const operationId of queueContexts.keys()) {
    if (!existingOperationIds.has(operationId)) queueContexts.delete(operationId);
  }
  updateQueueStatus(entries);
  const context = entry ? queueContexts.get(entry.operation_id) : null;
  if (context) context.status = entry.status;
  if (!entry || !queueEntryMatchesCurrent(entry)) return;
  if (entry.status === "queued") $("#save-status").textContent = "Speichern …";
  if (entry.status === "saving") $("#save-status").textContent = "Speichern …";
  if (["auth_error", "conflict", "validation_error", "error"].includes(entry.status)) {
    $("#save-status").textContent = "Speicherfehler";
    $("#module-error").textContent = queueFailureMessage(entry);
  }
}

function csrfToken() {
  const cookie = document.cookie.split(";").map(part => part.trim()).find(part => part.startsWith(`${csrfCookieName}=`));
  if (!cookie) {
    const error = new Error("Anmeldung konnte nicht bestätigt werden.");
    error.status = 401;
    error.userMessage = "Anmeldung abgelaufen.";
    throw error;
  }
  return decodeURIComponent(cookie.slice(csrfCookieName.length + 1));
}

async function sendQueuedUpdate(entry) {
  return sendQueuedRecordUpdate(entry, csrfToken());
}

async function sendQueuedCreate(entry) {
  return sendQueuedRecordCreate(entry, csrfToken());
}

async function reserveQueuedIdentity(entry) {
  return reserveQueuedRecordIdentity(entry, csrfToken());
}

async function queueJson(url) {
  let response;
  try {
    response = await fetch(url, {credentials: "same-origin"});
  } catch {
    throw new Error("Netzwerkfehler beim Recovery-Read-back.");
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const error = new Error(typeof data.detail === "string" ? data.detail : `HTTP ${response.status}`);
    error.status = response.status;
    error.userMessage = error.message;
    throw error;
  }
  return response.json();
}

async function resolveQueuedUpdate(entry) {
  const descriptor = currentDescriptor?.module === entry.module_id
    ? currentDescriptor
    : await queueJson(`/api/modules/${encodeURIComponent(entry.module_id)}`);
  const data = await readQueuedRecordUpdate(entry);
  return classifyQueuedUpdateReadBack(entry, data, descriptor);
}

async function handleQueueReserved(entry, reservation) {
  const context = queueContexts.get(entry.operation_id);
  if (!queueEntryMatchesCurrent(entry, context)) return;
  context.identityReserved = true;
  context.create.recordId = reservation.record_id;
  context.formState.applyServerValues(reservation.identity);
  state.recordId = reservation.record_id;
  renderCurrentRecord();
  updatePayloadPreview();
  $("#save-status").textContent = "Identität reserviert – lokal gesicherte Übertragung ausstehend.";
}

async function handleQueueSuccess(entry, data) {
  const context = queueContexts.get(entry.operation_id);
  if (queueEntryMatchesCurrent(entry, context)) {
    context.formState.confirmSave(data.record);
    if (entry.operation === "create") {
      context.create.recordId = data.record_id;
      context.create.revision = data.meta.revision;
      state.recordId = data.record_id;
      state.lastRecordId = data.record_id;
      state.creating = false;
      currentUpdate = new RecordUpdate(currentDescriptor.module, data.record_id, currentFormState, data.meta.revision);
      currentCreate = null;
      $("#save-record").textContent = "Datensatz speichern";
      updateUrl();
    } else {
      context.update.revision = data.meta.revision;
    }
    renderCurrentRecord();
    showView();
    updatePayloadPreview();
    $("#save-status").textContent = context.formState.isDirty()
      ? "Zwischenstand gespeichert; weitere Änderungen sind noch nicht gespeichert."
      : "Gespeichert";
  }
}

async function handleQueueError(entry, error, details) {
  if (details.remoteConfirmed) {
    if (queueEntryMatchesCurrent(entry)) {
      $("#save-status").textContent = "Lokaler Bereinigungsfehler nach Serverbestätigung.";
      $("#module-error").textContent = "Serverseitig gespeichert, aber der lokale Queue-Eintrag konnte nicht sicher bereinigt werden. Keine erneute Übertragung gestartet.";
    }
    return;
  }
  if (queueEntryMatchesCurrent(entry)) {
    $("#save-status").textContent = "Speicherfehler";
    $("#module-error").textContent = queueFailureMessage(entry);
  }
  console.error("Vorgemerkter Datensatz konnte nicht gespeichert werden.", error);
}

async function initializeSaveQueue() {
  try {
    saveQueueStore = createIndexedDbSaveQueueStore({indexedDB: window.indexedDB});
    await saveQueueStore.open();
    saveQueueProcessor = createSaveQueueProcessor({
      store: saveQueueStore,
      sendUpdate: sendQueuedUpdate,
      sendCreate: sendQueuedCreate,
      reserveIdentity: reserveQueuedIdentity,
      resolveUpdate: resolveQueuedUpdate,
      onChange: handleQueueChange,
      onReserved: handleQueueReserved,
      onSuccess: handleQueueSuccess,
      onError: handleQueueError,
      lockManager: window.navigator?.locks || null
    });
    await saveQueueProcessor.initializeRecovery();
  } catch (error) {
    queueInitializationError = error;
    updateQueueStatus([]);
    console.error("Lokale Speicherwarteschlange konnte nicht geöffnet werden.", error);
  }
}

async function openQueuedSnapshot(entry, push = true) {
  if (entry.module_id !== currentDescriptor.module) {
    location.href = `/app/module/?module=${encodeURIComponent(entry.module_id)}&queue=${encodeURIComponent(entry.operation_id)}`;
    return;
  }
  let baseline = currentDescriptor.empty_record || {};
  if (entry.operation === "update") {
    try {
      baseline = (await readQueuedRecordUpdate(entry)).record;
    } catch (error) {
      if (error.status !== 409) throw error;
      baseline = {};
    }
  }
  currentFormState = new FormState(currentDescriptor, baseline);
  currentFormState.loadWorkingSnapshot(entry.snapshot);
  if (entry.identity) currentFormState.applyServerValues(entry.identity);
  if (entry.operation === "create") currentFormState.beginCreateSave();
  else currentFormState.beginSave();
  if (entry.operation === "create") {
    currentCreate = new RecordCreate(currentDescriptor.module, currentFormState);
    currentCreate.recordId = entry.record_id;
    currentUpdate = null;
    state.recordId = entry.record_id;
    state.creating = true;
    $("#save-record").textContent = "Datensatz speichern";
  } else {
    currentUpdate = new RecordUpdate(currentDescriptor.module, entry.record_id, currentFormState, entry.base_revision);
    currentCreate = null;
    state.recordId = entry.record_id;
    state.lastRecordId = entry.record_id;
    state.creating = false;
    $("#save-record").textContent = "Datensatz speichern";
  }
  queueContexts.set(entry.operation_id, {
    operationId: entry.operation_id,
    formState: currentFormState,
    update: currentUpdate,
    create: currentCreate,
    identityAssignment: entry.identity_assignment,
    identityReserved: Boolean(entry.identity),
    status: entry.status
  });
  mode = "edit";
  renderer = new FormRenderer({mode});
  toggleEdit.textContent = "Read-Modus anzeigen";
  $("#save-status").textContent = `Lokaler Queue-Snapshot geöffnet (${entry.status}).`;
  renderCurrentRecord();
  showView();
  updatePayloadPreview();
  updateQueueStatus(queueEntries);
  if (push) updateUrl();
}

function scheduleQueueProcessing() {
  window.setTimeout(() => {
    saveQueueProcessor.process().catch(error => {
      $("#module-error").textContent = "Die lokale Speicherwarteschlange konnte nicht weiter verarbeitet werden. Der Queue-Eintrag bleibt erhalten.";
      console.error("Speicherwarteschlange konnte nicht verarbeitet werden.", error);
    });
  }, 0);
}

async function apiFetch(url) {
  const response = await fetch(url, { credentials: "same-origin" });
  if (response.status === 401) {
    window.location.href = "/login/";
    throw new Error("Nicht angemeldet");
  }
  if (response.status === 403) throw new Error("Keine Berechtigung für dieses Modul.");
  if (response.status === 404) throw new Error("Datensatz oder Modul wurde nicht gefunden.");
  if (!response.ok) throw new Error("Daten konnten nicht geladen werden.");
  return response.json();
}

function syncStateFromForm() {
  if (mode === "edit" && currentFormState) renderer.readIntoState(preview, currentFormState);
}
async function allowNavigation() {
  if (saveInProgress) return false;
  syncStateFromForm();
  if (currentCreateAwaitingReservation()) return false;
  if (!currentFormState?.hasUnpersistedChanges()) return true;
  const dialog = $("#discard-dialog");
  if (dialog.open) return false;
  dialog.returnValue = "cancel";
  dialog.showModal();
  return new Promise(resolve => dialog.addEventListener("close", () => resolve(dialog.returnValue === "discard"), {once: true}));
}
function updateUrl() {
  if (location.pathname + location.search !== state.url()) history.pushState(null, "", state.url());
  acceptedUrl = location.href;
}
function showView() {
  const opened = Boolean(currentFormState);
  $("#list-panel").hidden = opened;
  $("#detail-panel").hidden = !opened;
  $("#previous-record").disabled = !state.neighbor(-1);
  $("#next-record").disabled = !state.neighbor(1);
  $("#record-position").textContent = !opened ? "" : state.creating ? "Neuer, noch nicht gespeicherter Datensatz" : `${state.recordId} · ${state.position < 0 ? "Außerhalb der Trefferliste" : `${state.position + 1} / ${state.records.length}`}`;
}
async function openRecord(moduleDescriptor, recordId, push = true) {
  if (!await allowNavigation()) return;
  const request = ++generation;
  let data;
  $("#detail-panel").inert = true;
  try {
    data = await apiFetch(`/api/modules/${encodeURIComponent(moduleDescriptor.module)}/records/${encodeURIComponent(recordId)}`);
  } finally {
    $("#detail-panel").inert = false;
  }
  if (request !== generation) return;
  currentDescriptor = moduleDescriptor;
  currentFormState = new FormState(moduleDescriptor, data.record);
  currentUpdate = new RecordUpdate(moduleDescriptor.module, recordId, currentFormState, data.meta.revision);
  currentCreate = null;
  $("#save-status").textContent = "Gespeichert";
  state.recordId = recordId;
  state.lastRecordId = recordId;
  state.creating = false;
  mode = "read";
  renderer = new FormRenderer({ mode });
  payloadPreview.textContent = "";
  toggleEdit.textContent = "Edit-Modus aktivieren";
  discardChanges.disabled = true;
  $("#save-record").textContent = "Datensatz speichern";
  renderCurrentRecord();
  showView();
  updateSaveButton();
  updatePresetControls();
  if (push) updateUrl();
}
async function startCreate(push = true) {
  if (!await allowNavigation()) return;
  ++generation;
  currentFormState = new FormState(currentDescriptor, currentDescriptor.empty_record || {});
  currentCreate = new RecordCreate(currentDescriptor.module, currentFormState);
  currentUpdate = null;
  state.recordId = null;
  state.creating = true;
  mode = "edit";
  renderer = new FormRenderer({ mode });
  payloadPreview.textContent = "";
  $("#save-status").textContent = "Änderungen noch nicht gespeichert";
  toggleEdit.textContent = "Read-Modus anzeigen";
  discardChanges.disabled = true;
  $("#save-record").textContent = "Datensatz speichern";
  renderCurrentRecord();
  renderer.readIntoState(preview, currentFormState);
  currentFormState.reset(currentFormState.current);
  const presetPaths = presetStore.apply(currentFormState, { includeInitialDefaults: true });
  if (presetPaths.length) renderCurrentRecord();
  showView();
  updatePayloadPreview();
  updatePresetControls(presetPaths.length ? "Vorbelegungen wurden auf den neuen Datensatz angewendet." : "");
  if (push) updateUrl();
}
function renderCurrentRecord() {
  preview.replaceChildren(renderer.render(currentDescriptor, currentFormState));
}
function updatePayloadPreview() {
  syncStateFromForm();
  if (!currentFormState) return;
  if (debugMode) payloadPreview.textContent = JSON.stringify({ dirty: currentFormState.isDirty(), changed_paths: currentFormState.changedPaths(),
    validation_errors: currentFormState.validate(), payload: currentFormState.buildPayload() }, null, 2);
  discardChanges.disabled = !currentFormState.hasUnpersistedChanges();
  updateSaveButton();
  updatePresetControls();
}
function queryFromUrl() {
  const query = new URLSearchParams(location.search);
  return { q: query.get("q") || "", lookupField: query.get("lookup_field") || "", lookupValue: query.get("lookup_value") || "" };
}
async function loadResults(query, push = true, preserveRecord = false) {
  const started = performance.now();
  const request = ++generation;
  const pending = new ResultState(moduleKey);
  Object.assign(pending, query);
  $("#result-count").textContent = "Wird geladen …";
  $("#record-list").inert = true;
  $("#detail-panel").inert = true;
  let listing;
  try {
    listing = await apiFetch(`/api/modules/${encodeURIComponent(moduleKey)}/records?${pending.queryString()}`);
  } finally {
    if (request === generation) {
      $("#record-list").inert = false;
      $("#detail-panel").inert = false;
    }
  }
  const received = performance.now();
  if (request !== generation) return false;
  const recordId = state.recordId;
  state.replace(listing.records || [], query);
  if (preserveRecord) state.recordId = recordId;
  else { currentFormState = null; currentUpdate = null; currentCreate = null; state.creating = false; }
  $("#search-text").value = state.q;
  $("#lookup-field").value = state.lookupField;
  $("#lookup-value").value = state.lookupValue;
  renderRecordList($("#record-list"), currentDescriptor, state.records, id => run(() => openRecord(currentDescriptor, id)));
  console.debug("Module list " + JSON.stringify({records: state.records.length, requestMs: Math.round(received - started), renderMs: Math.round(performance.now() - received), heapBytes: performance.memory?.usedJSHeapSize}));
  $("#result-count").textContent = `${state.records.length} Treffer`;
  showView();
  if (push) updateUrl();
  return true;
}
async function run(action) {
  $("#module-error").textContent = "";
  try { await action(); } catch (error) {
    $("#module-error").textContent = error.message;
    $("#result-count").textContent = `${state.records.length} Treffer (letzter geladener Stand)`;
  }
}
async function init() {
  if (!moduleKey) throw new Error("Kein Modul ausgewählt.");
  await initializeSaveQueue();
  csrfCookieName = (await apiFetch("/api/auth/me")).csrf_cookie_name;
  currentDescriptor = await apiFetch(`/api/modules/${encodeURIComponent(moduleKey)}`);
  $("#show-payload").hidden = !debugMode;
  $("#payload-panel").hidden = !debugMode;
  await vocabularyClient.hydrateDescriptor(currentDescriptor);
  presetStore = new PresetStore(currentDescriptor, currentDescriptor.user);
  state.sort = currentDescriptor.list?.default_sort || currentDescriptor.search?.default_sort;
  $("#module-title").textContent = currentDescriptor.label;
  $("#module-description").textContent = currentDescriptor.description || "";
  const lookups = currentDescriptor.search?.lookup || [];
  lookups.forEach(path => {
    const option = document.createElement("option");
    option.value = path;
    option.textContent = currentDescriptor.fields.find(field => field.path === path)?.label || path;
    $("#lookup-field").append(option);
  });
  $("#lookup-controls").hidden = !lookups.length;
  $("#fulltext-controls").hidden = !currentDescriptor.search?.fulltext?.length;
  const recordId = params.get("record");
  await loadResults(queryFromUrl(), false);
  const queuedOperationId = params.get("queue");
  const queuedEntry = queuedOperationId ? await saveQueueStore?.get(queuedOperationId) : null;
  if (queuedEntry && queuedEntry.module_id === currentDescriptor.module) await openQueuedSnapshot(queuedEntry, false);
  else if (params.get("new") === "1") await startCreate(false);
  else if (recordId) await openRecord(currentDescriptor, recordId, false);
  scheduleQueueProcessing();
}
$("#new-record").addEventListener("click", () => run(() => startCreate()));
$("#search-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (!await allowNavigation()) return;
  const lookupValue = $("#lookup-value").value.trim();
  const lookupField = $("#lookup-field").value;
  if (lookupValue && !lookupField) {
    $("#module-error").textContent = "Bitte ein Lookup-Feld wählen.";
    return;
  }
  run(() => loadResults({ q: $("#search-text").value.trim(), lookupField: lookupValue ? lookupField : "", lookupValue }));
});
$("#clear-search").addEventListener("click", async () => {
  if (await allowNavigation()) run(() => loadResults({ q: "", lookupField: "", lookupValue: "" }));
});
$("#back-to-list").addEventListener("click", async () => {
  if (!await allowNavigation()) return;
  ++generation;
  currentFormState = null;
  currentUpdate = null;
  currentCreate = null;
  state.recordId = null;
  state.creating = false;
  showView();
  updateUrl();
  Array.from($("#record-list").querySelectorAll("a")).find(link => link.dataset.recordId === state.lastRecordId)?.focus();
});
for (const [selector, offset] of [["#previous-record", -1], ["#next-record", 1]]) {
  $(selector).addEventListener("click", () => {
    const id = state.neighbor(offset);
    if (id) run(() => openRecord(currentDescriptor, id));
  });
}
$("#change-module").addEventListener("click", async event => {
  event.preventDefault();
  if (await allowNavigation()) {
    currentFormState = null;
    currentCreate = null;
    location.href = $("#change-module").href;
  }
});
window.addEventListener("beforeunload", event => {
  syncStateFromForm();
  if (currentFormState?.hasUnpersistedChanges() || currentCreateAwaitingReservation() || saveInProgress) { event.preventDefault(); event.returnValue = ""; }
});
window.addEventListener("popstate", async () => {
  if (!await allowNavigation()) { history.pushState(null, "", acceptedUrl); return; }
  run(async () => {
    const query = new URLSearchParams(location.search);
    const recordId = query.get("record");
    if (query.get("module") !== moduleKey) { location.reload(); return; }
    if (await loadResults(queryFromUrl(), false)) {
      if (query.get("new") === "1") await startCreate(false);
      else if (recordId) await openRecord(currentDescriptor, recordId, false);
      acceptedUrl = location.href;
    }
  });
});
toggleEdit.addEventListener("click", () => {
  if (!currentFormState) return;
  syncStateFromForm();
  mode = mode === "read" ? "edit" : "read";
  renderer = new FormRenderer({ mode });
  toggleEdit.textContent = mode === "read" ? "Edit-Modus aktivieren" : "Read-Modus anzeigen";
  renderCurrentRecord();
  updatePayloadPreview();
});
$("#save-preset").addEventListener("click", () => {
  if (!currentFormState || mode !== "edit") return;
  try {
    syncStateFromForm();
    const preset = presetStore.saveFromState(currentFormState);
    updatePayloadPreview();
    const count = Object.keys(preset.values).length;
    updatePresetControls(count ? `${count} Vorbelegung(en) lokal gespeichert.` : "Keine belegten, zulässigen Felder zum Speichern gefunden.");
  } catch {
    $("#module-error").textContent = "Vorbelegungen konnten nicht lokal gespeichert werden.";
  }
});
$("#apply-preset").addEventListener("click", () => {
  if (!currentFormState || mode !== "edit") return;
  syncStateFromForm();
  const changed = presetStore.apply(currentFormState);
  if (changed.length) renderCurrentRecord();
  updatePayloadPreview();
  updatePresetControls(changed.length
    ? `${changed.length} leere(s) Feld(er) mit Vorbelegungen gefüllt.`
    : "Keine leeren Felder konnten mit Vorbelegungen gefüllt werden.");
});
$("#delete-preset").addEventListener("click", () => {
  try {
    presetStore.clear();
    updatePresetControls("Vorbelegungen für dieses Modul wurden gelöscht.");
  } catch {
    $("#module-error").textContent = "Vorbelegungen konnten nicht lokal gelöscht werden.";
  }
});
discardChanges.addEventListener("click", () => {
  if (!currentFormState) return;
  currentFormState.discardChanges();
  $("#save-status").textContent = "";
  $("#module-error").textContent = "";
  renderCurrentRecord();
  updatePayloadPreview();
});
for (const event of ["input", "change", "click"]) preview.addEventListener(event, () => {
  const dateReview = reviewDateTextFields(preview);
  updatePayloadPreview();
  if (dateReview.blocking && mode === "edit" && (currentCreate || currentUpdate)) {
    $("#save-record").disabled = false;
    discardChanges.disabled = false;
  }
});
$("#save-record").addEventListener("click", async () => {
  if (saveInProgress) return;
  $("#module-error").textContent = "";
  try {
    const dateReview = reviewDateTextFields(preview, { show: true });
    if (dateReview.blocking) {
      $("#save-status").textContent = "Änderungen noch nicht gespeichert";
      return;
    }
    syncStateFromForm();
    const operation = currentCreate || currentUpdate;
    if (!operation?.canSave(mode) || currentRecordHasQueueEntry() || currentQueueContext()) return;
    saveInProgress = true;
    const wasCreate = Boolean(currentCreate);
    updateSaveButton();
    if (!saveQueueProcessor || queueInitializationError) {
      throw new Error("Lokale Speicherwarteschlange nicht verfügbar. Es wurde nichts an den Server gesendet.");
    }
    const operationId = window.crypto.randomUUID();
    const snapshot = wasCreate ? currentFormState.beginCreateSave() : currentFormState.beginSave();
    const identityAssignment = currentDescriptor.create?.identity_assignment || "on_create";
    queueContexts.set(operationId, {
      operationId,
      formState: currentFormState,
      update: currentUpdate,
      create: currentCreate,
      identityAssignment,
      identityReserved: false
    });
    try {
      if (wasCreate) {
        await saveQueueProcessor.enqueueCreate({
          operationId,
          moduleId: currentCreate.moduleKey,
          identityAssignment,
          snapshot
        });
      } else {
        await saveQueueProcessor.enqueueUpdate({
          operationId,
          moduleId: currentUpdate.moduleKey,
          recordId: currentUpdate.recordId,
          baseRevision: currentUpdate.revision,
          snapshot
        });
      }
    } catch (error) {
      if (error.queuePersisted) {
        $("#save-status").textContent = "Lokal gesichert – Queue-Status konnte nicht gelesen werden; keine Übertragung gestartet.";
        $("#module-error").textContent = "Der lokale Queue-Eintrag bleibt erhalten. Die Wiederaufnahme folgt im Recovery-Schritt.";
        return;
      }
      queueContexts.delete(operationId);
      currentFormState.cancelSave();
      throw new Error(`Lokale Vormerkung fehlgeschlagen. Es wurde nichts an den Server gesendet. ${error.message || ""}`.trim());
    }
    $("#save-status").textContent = "Speichern …";
    scheduleQueueProcessing();
  } catch (error) {
    $("#save-status").textContent = "Speicherfehler";
    $("#module-error").textContent = error.message || "Netzwerkfehler. Ihre Änderungen bleiben erhalten.";
  } finally {
    saveInProgress = false;
    updateSaveButton();
  }
});
$("#show-payload").addEventListener("click", updatePayloadPreview);
$("#retry-queue").addEventListener("click", () => run(async () => {
  const retried = await saveQueueProcessor?.retryFirst();
  if (!retried) $("#module-error").textContent = "Dieser Queue-Zustand kann nicht blind wiederholt werden. Öffnen Sie den lokalen Stand.";
}));
$("#open-queue-entry").addEventListener("click", () => run(async () => {
  const entry = queueEntries[0];
  if (entry && await allowNavigation()) await openQueuedSnapshot(entry);
}));
$("#discard-queue-entry").addEventListener("click", () => run(async () => {
  const entry = queueEntries[0];
  if (!entry || !window.confirm("Lokale Speicherung wirklich verwerfen? Der gespeicherte Snapshot geht dabei unwiderruflich verloren.")) return;
  const context = queueContexts.get(entry.operation_id);
  if (context?.formState === currentFormState) currentFormState.cancelSave();
  await saveQueueProcessor.discard(entry.operation_id);
  queueContexts.delete(entry.operation_id);
  updateSaveButton();
  $("#save-status").textContent = "Lokale Speicherung verworfen; es wurde keine Backend-Operation ausgelöst.";
  scheduleQueueProcessing();
}));
run(init);
