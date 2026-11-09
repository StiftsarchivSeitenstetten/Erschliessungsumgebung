import {nextRecordSeed, singleFlight, guardUnsavedChanges} from "../generic/next-record.js?v=thoma-navigation-2";
import {validateActionSnapshot} from "../generic/record-actions.js?v=thoma-review-1";
import { FormRenderer } from "../generic/form-renderer.js?v=thoma-review-1";
import { FormState, validateRepeaterSnapshot } from "../generic/form-state.js?v=thoma-review-1";
import { ResultState, renderRecordList } from "../generic/record-list.js?v=create-1";
import { RecordCreate, reserveQueuedRecordIdentity, sendQueuedRecordCreate } from "../generic/record-create.js?v=thoma-review-1";
import { RecordUpdate, classifyQueuedUpdateReadBack, readQueuedRecordUpdate, sendQueuedRecordUpdate } from "../generic/record-update.js?v=thoma-review-1";
import { createIndexedDbSaveQueueStore } from "../generic/module-save-queue-store.js?v=queue-isolation-1";
import { createSaveQueueProcessor, queueEntryMatchesContext, queueRecordKey, queueStatusMessage } from "../generic/module-save-queue.js?v=thoma-review-1";
import { PresetStore, presettableFields } from "../generic/preset-store.js?v=preset-1";
import { VocabularyClient } from "../generic/vocabulary-client.js?v=vocabulary-2";
import { reviewDateTextFields } from "../generic/widget-registry.js?v=thoma-review-1";
import { getPathValue, setPathValue } from "../generic/path-utils.js";

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
let createStarting = false;
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
  return Boolean(currentCreate?.earlyReservation && !currentCreate.recordId) || Boolean(context?.create && context.identityAssignment === "reserve_before_create" && !context.identityReserved);
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
  const mayEdit = currentDescriptor?.fields?.some(field => field.visible && field.editable);
  const awaiting = Boolean(currentCreate?.earlyReservation && !currentCreate.recordId);
  const busy = saveInProgress || createStarting || awaiting;
  const editable = mode === "edit" && Boolean(operation) && mayEdit;
  const saveDisabled = !editable || busy || currentRecordHasQueueEntry() || Boolean(currentQueueContext()) || (!currentCreate && !currentFormState?.isDirty());
  const discardDisabled = !editable || saveInProgress || !currentFormState?.hasUnpersistedChanges();
  document.querySelectorAll('[data-record-action="save"]').forEach(button => { button.disabled = saveDisabled; button.textContent = "Datensatz speichern"; });
  document.querySelectorAll('[data-record-action="discard"]').forEach(button => { button.disabled = discardDisabled; });
  toggleEdit.hidden = !currentUpdate || mode !== "read";
  toggleEdit.disabled = !mayEdit || busy;
  toggleEdit.textContent = "Datensatz bearbeiten";
  $("#new-record").disabled = busy;
  $("#back-to-list").disabled = busy;
  $("#previous-record").disabled = busy || !state.neighbor(-1);
  $("#next-record").disabled = busy || !state.neighbor(1);


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
  $("#queue-panel h2").textContent = first?.operation === "reservation" ? "Lokale Identitätsreservierung" : first && ["queued", "saving", "reserving"].includes(first.status) ? "Speicherwarteschlange" : "Speicherung fehlgeschlagen";
  $("#retry-queue").textContent = first?.operation === "reservation" ? "Reservierung wiederaufnehmen" : "Speicherung erneut versuchen";
  $("#discard-queue-entry").textContent = first?.operation === "reservation" ? "Reservierung aufgeben" : "Lokale Speicherung verwerfen";
  const workerRunning = Boolean(saveQueueProcessor?.isRunning());
  $("#queue-panel").hidden = !queueInitializationError && !entries.length;
  $("#open-queue-entry").disabled = !first;
  $("#discard-queue-entry").disabled = !first || workerRunning;
  $("#retry-queue").disabled = !first || workerRunning || (first.operation !== "reservation" && ["conflict", "validation_error"].includes(first.status));
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
  if (entry.last_error?.message?.startsWith("Lokaler Snapshot pausiert:")) return entry.last_error.message;
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
  if (entry?.operation === "reservation" && currentCreate?.earlyReservation && currentCreate.operationId === entry.operation_id) {
    showEarlyIdentity(entry);
  }
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

async function validateQueuedSnapshot(entry) {
  let descriptor;
  try {
    descriptor = currentDescriptor?.module === entry.module_id
      ? currentDescriptor
      : await queueJson(`/api/modules/${encodeURIComponent(entry.module_id)}`);
  } catch (error) {
    throw new Error(`${entry.module_id}: Modulkonfiguration konnte nicht sicher geprüft werden (${error.message}). Der gespeicherte Auftrag bleibt erhalten.`);
  }
  validateRepeaterSnapshot(descriptor, entry.snapshot);
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
      : entry.action === "complete" || entry.action === "save" ? "Abgeschlossen gespeichert" : entry.action === "draft" ? "Entwurf gespeichert" : "Gespeichert";
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
      validateSnapshot: validateQueuedSnapshot,
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
  if (entry.operation === "reservation") {
    await startCreate(push, entry);
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
  const restoredState = new FormState(currentDescriptor, baseline);
  restoredState.loadWorkingSnapshot(entry.snapshot);
  currentFormState = restoredState;
  if (entry.identity) currentFormState.applyServerValues(entry.identity);
  if (entry.operation === "create") currentFormState.beginCreateSave({draft: entry.action === "draft"});
  else currentFormState.beginSave({draft: entry.action === "draft"});
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
async function allowNavigation(starting = false) {
  if (saveInProgress || createStarting && !starting) return false;
  syncStateFromForm();
  if (currentCreateAwaitingReservation()) return false;
  return guardUnsavedChanges({
    hasChanges: () => Boolean(currentFormState?.hasUnpersistedChanges()),
    choose: async () => {
      const dialog = $("#discard-dialog");
      if (dialog.open) return "cancel";
      const saveButton = $("#save-and-next");
      saveButton.hidden = false;
      saveButton.textContent = "Speichern und weiter";
      dialog.returnValue = "cancel";
      dialog.showModal();
      try {
        return await new Promise(resolve => dialog.addEventListener("close", () => resolve(dialog.returnValue), {once: true}));
      } finally { saveButton.hidden = true; }
    },
    save: () => saveRecord()
  });
}
function updateUrl() {
  const url = new URL(state.url(), location.origin);
  if (state.creating && currentCreate?.earlyReservation) url.searchParams.set("reservation", currentCreate.operationId);
  const target = url.pathname + url.search;
  if (location.pathname + location.search !== target) history.pushState(null, "", target);
  acceptedUrl = location.href;
}
function showView() {
  const opened = Boolean(currentFormState);
  $("#list-panel").hidden = opened;
  $("#detail-panel").hidden = !opened;
  $("#previous-record").disabled = !state.neighbor(-1);
  $("#next-record").disabled = !state.neighbor(1);
  updateSaveButton();
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
function showEarlyIdentity(entry) {
  const confirmed = entry.status === "reserved" && entry.identity?.id === entry.record_id;
  preview.inert = !confirmed;
  $("#identity-reservation").hidden = false;
  $("#identity-values").textContent = confirmed
    ? Object.entries(entry.identity).filter(([path]) => path === "id" || currentDescriptor.fields.some(field => field.path === path && field.visible)).map(([path, value]) => `${currentDescriptor.fields.find(field => field.path === path)?.label || (path === "id" ? "Record-ID" : path)}: ${value}`).join(" · ")
    : "Keine verbindliche Kennung bestätigt.";
  $("#retry-reservation").hidden = confirmed;
  $("#retry-reservation").disabled = entry.status === "reserving" && createStarting;
  if (confirmed) {
    syncStateFromForm();
    currentCreate.recordId = entry.record_id;
    currentCreate.identityInputs = entry.identity_inputs;
    currentFormState.applyServerValues(entry.identity);
    Object.entries(entry.identity).forEach(([path, value]) => setPathValue(currentFormState.serverSnapshot, path, value));
    state.recordId = entry.record_id;
    renderCurrentRecord();
    const focusField = currentDescriptor.fields.find(field => field.path === currentCreate.nextFocus && field.editable && field.visible);
    if (focusField) preview.querySelector(`[data-field-id='${focusField.id}'] input, [data-field-id='${focusField.id}'] textarea`)?.focus();
  }
  $("#save-status").textContent = confirmed
    ? "Identität verbindlich reserviert. Fachlicher Datensatz noch nicht gespeichert."
    : "Reservierung noch nicht bestätigt. Lokal wiederaufnehmbar; kein Datensatz gespeichert.";
  updateSaveButton();
}

async function startCreate(push = true, resumeEntry = null, next = null) {
  if (createStarting) return;
  createStarting = true;
  try {
    if (!next && !await allowNavigation(true)) return;
    if (!resumeEntry && currentCreate?.earlyReservation && !currentQueueContext()) {
      if (!window.confirm("Reservierung aufgeben? Bereits vergebene Nummern bleiben verbraucht.")) return;
      await saveQueueProcessor.discard(currentCreate.operationId);
    }
    if (!next && currentDescriptor.create?.next_record) next = {seed: nextRecordSeed(currentDescriptor, {})};
    ++generation;
    currentFormState = new FormState(currentDescriptor, next?.seed || currentDescriptor.empty_record || {});
    currentCreate = new RecordCreate(currentDescriptor.module, currentFormState);
    currentCreate.earlyReservation = Boolean(currentDescriptor.create?.reserve_on_start || resumeEntry);
    if (resumeEntry) currentCreate.operationId = resumeEntry.operation_id;
    currentCreate.nextFocus = next ? currentDescriptor.create.next_record.focus_field : null;
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
    const presetPaths = next ? [] : presetStore.apply(currentFormState, { includeInitialDefaults: true });
    if (presetPaths.length) renderCurrentRecord();
    showView();
    updatePayloadPreview();
    updatePresetControls(presetPaths.length ? "Vorbelegungen wurden auf den neuen Datensatz angewendet." : "");
    if (push) updateUrl();
    if (currentCreate.earlyReservation) {
      if (!saveQueueProcessor || queueInitializationError) throw new Error("Lokale Reservierung nicht verfügbar. Keine Nummer angefordert.");
      const identityInputs = {};
      const signature = currentDescriptor.signature_strategy;
      const partitionPath = signature?.partition_field || "signatur.format";
      const partition = getPathValue(currentFormState.current, partitionPath);
      const partitionEditable = currentDescriptor.fields.some(field => field.editable &&
        (field.path === partitionPath || partitionPath.startsWith(`${field.path}.`)));
      if (partition !== undefined && partitionEditable) setPathValue(identityInputs, partitionPath, partition);
      const entry = resumeEntry || await saveQueueProcessor.prepareReservation({
        operationId: currentCreate.operationId, moduleId: currentDescriptor.module, identityInputs,
        identityPaths: ["id", ...(signature?.strategy ? [`${signature.output_path || "signatur"}.anzeige`] : [])]
      });
      // The durable operation is addressable before the first network request.
      updateUrl();
      showEarlyIdentity(entry);
      try {
        const reserved = await saveQueueProcessor.resumeReservation(entry.operation_id);
        showEarlyIdentity(reserved);
      } catch (error) {
        showEarlyIdentity(await saveQueueStore.get(entry.operation_id));
        $("#module-error").textContent = `${error.message} Wiederaufnahme verwendet dieselbe Operations-ID.`;
      }
    }
  } finally {
    createStarting = false;
    updateSaveButton();
    if (currentCreate?.earlyReservation && !currentCreate.recordId) $("#retry-reservation").disabled = false;
  }
}
function renderCurrentRecord() {
  $("#identity-reservation").hidden = !currentCreate?.earlyReservation;
  preview.inert = Boolean(currentCreate?.earlyReservation && !currentCreate.recordId);
  let descriptor = currentDescriptor;
  if (currentCreate?.earlyReservation && currentCreate.identityInputs) {
    descriptor = {...currentDescriptor, fields: currentDescriptor.fields.map(field => {
      const value = getPathValue(currentCreate.identityInputs, field.path);
      if (value === undefined) return field;
      currentFormState.setValue(field.path, value);
      return {...field, editable: false};
    })};
  }
  const wasClean = !currentFormState.isDirty();
  preview.replaceChildren(renderer.render(descriptor, currentFormState));
  // Empty optional controls may render absent server fields as empty strings.
  // Establish their UI baseline only while clean, never over pending edits.
  if (wasClean && mode === "edit" && currentFormState.pendingSnapshot === null) {
    renderer.readIntoState(preview, currentFormState);
    currentFormState.serverSnapshot = structuredClone(currentFormState.current);
  }
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
  renderRecordList($("#record-list"), currentDescriptor, state.records, id => run(() => openRecord(currentDescriptor, id)), state.queryString());
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
  state.contextTracked = true;
  state.searchContext = params.get("search") === "1" || Boolean(params.get("q") || params.get("lookup_value")) || (!recordId && !params.get("new"));
  await loadResults(queryFromUrl(), false);
  const queuedOperationId = params.get("queue");
  const queuedEntry = queuedOperationId ? await saveQueueStore?.get(queuedOperationId) : null;
  if (queuedEntry && queuedEntry.module_id === currentDescriptor.module) await openQueuedSnapshot(queuedEntry, false);
  else if (params.get("new") === "1") {
    const reservationId = params.get("reservation");
    const reservation = reservationId ? await saveQueueStore?.get(reservationId) : null;
    if (reservationId && (!reservation || reservation.module_id !== currentDescriptor.module)) throw new Error("Lokale Operation nicht gefunden. Für ein anderes Objekt ausdrücklich eine Neuanlage beginnen.");
    if (reservation) await openQueuedSnapshot(reservation, false);
    else await startCreate(false);
  }
  else if (recordId) await openRecord(currentDescriptor, recordId, false);
  scheduleQueueProcessing();
}
$("#new-record").addEventListener("click", () => run(() => currentDescriptor.create?.next_record ? nextObject() : startCreate()));
$("#search-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (!await allowNavigation()) return;
  state.searchContext = true;
  const lookupValue = $("#lookup-value").value.trim();
  const lookupField = $("#lookup-field").value;
  if (lookupValue && !lookupField) {
    $("#module-error").textContent = "Bitte ein Lookup-Feld wählen.";
    return;
  }
  run(() => loadResults({ q: $("#search-text").value.trim(), lookupField: lookupValue ? lookupField : "", lookupValue }));
});
$("#clear-search").addEventListener("click", async () => {
  if (await allowNavigation()) { state.searchContext = true; run(() => loadResults({ q: "", lookupField: "", lookupValue: "" })); }
});
$("#back-to-list").addEventListener("click", async () => {
  if (!await allowNavigation()) return;
  state.searchContext = true;
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
    state.searchContext = query.get("search") === "1" || Boolean(query.get("q") || query.get("lookup_value")) || (!recordId && !query.get("new"));
    if (query.get("module") !== moduleKey) { location.reload(); return; }
    if (await loadResults(queryFromUrl(), false)) {
      if (query.get("new") === "1") {
        const reservationId = query.get("reservation");
        const entry = reservationId ? await saveQueueStore?.get(reservationId) : null;
        if (reservationId && !entry) throw new Error("Lokale Operation nicht gefunden. Neue Erfassung ausdrücklich beginnen.");
        if (entry) await openQueuedSnapshot(entry, false);
        else await startCreate(false);
      }
      else if (recordId) await openRecord(currentDescriptor, recordId, false);
      acceptedUrl = location.href;
    }
  });
});
toggleEdit.addEventListener("click", () => {
  if (!currentFormState) return;
  syncStateFromForm();
  if (mode !== "read" || toggleEdit.disabled) return;
  mode = "edit";
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
function discardCurrentChanges() {
  if (!currentFormState) return;
  currentFormState.discardChanges();
  $("#save-status").textContent = "";
  $("#module-error").textContent = "";
  renderCurrentRecord();
  updatePayloadPreview();
}
document.querySelectorAll('[data-record-action="discard"]').forEach(button => button.addEventListener("click", discardCurrentChanges));
for (const event of ["input", "change", "click"]) preview.addEventListener(event, () => {
  const dateReview = reviewDateTextFields(preview);
  updatePayloadPreview();
  if (dateReview.blocking && mode === "edit" && (currentCreate || currentUpdate)) {
    updateSaveButton();
  }
});
const nextObject = singleFlight(async () => {
  if (!currentDescriptor?.create?.next_record || saveInProgress || createStarting) return;
  if (!await allowNavigation()) return;
  const config = currentDescriptor.create.next_record;
  const entries = await saveQueueStore.list();
  const oldReservation = entries.find(entry => entry.module_id === currentDescriptor.module &&
    entry.operation === "reservation" && entry.operation_id === currentCreate?.operationId)
    || entries.find(entry => entry.module_id === currentDescriptor.module && entry.operation === "reservation");
  if (oldReservation && oldReservation.status !== "reserved") {
    $("#module-error").textContent = "Reservierung noch ungeklärt. Bitte den lokalen Stand öffnen und dieselbe Reservierung wiederaufnehmen, bevor eine andere Erfassung begonnen wird.";
    return;
  }
  if (oldReservation && !window.confirm("Reservierung aufgeben? Bereits vergebene Nummern bleiben verbraucht.")) return;
  const seed = nextRecordSeed(currentDescriptor, currentFormState?.current || {});
  // Persist before replacing the previous form; local failures preserve all inputs.
  const operationId = window.crypto.randomUUID();
  const signature = currentDescriptor.signature_strategy;
  const partitionPath = signature?.partition_field || "signatur.format";
  const identityInputs = {};
  if (currentDescriptor.fields.some(f => f.path === partitionPath && f.editable)) {
    setPathValue(identityInputs, partitionPath, getPathValue(seed, partitionPath));
  }
  const entry = await saveQueueProcessor.prepareReservation({operationId, moduleId: currentDescriptor.module,
    identityInputs, identityPaths: ["id", `${signature.output_path || "signatur"}.anzeige`]});
  if (oldReservation?.operation === "reservation") await saveQueueProcessor.discard(oldReservation.operation_id);
  await startCreate(true, entry, {seed});
  const field = currentDescriptor.fields.find(f => f.path === config.focus_field && f.editable && f.visible);
  if (field && currentCreate?.recordId) preview.querySelector(`[data-field-id='${field.id}'] input, [data-field-id='${field.id}'] textarea`)?.focus();
});


document.querySelectorAll('[data-record-action="save"]').forEach(button => button.addEventListener("click", () => saveRecord()));
async function saveRecord(requestedAction) {
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
    const workflow = currentDescriptor.create?.workflow;
    const action = workflow ? (requestedAction || (getPathValue(currentFormState.original, workflow.status_path) === workflow.completed_status ? "save" : "complete")) : undefined;
    if ((!workflow && !operation?.canSave(mode)) || !operation || mode !== "edit" || currentRecordHasQueueEntry() || currentQueueContext()) return;
    saveInProgress = true;
    const wasCreate = Boolean(currentCreate);
    updateSaveButton();
    if (!saveQueueProcessor || queueInitializationError) {
      throw new Error("Lokale Speicherwarteschlange nicht verfügbar. Es wurde nichts an den Server gesendet.");
    }
    const operationId = wasCreate && currentCreate.earlyReservation ? currentCreate.operationId : window.crypto.randomUUID();
    const options = {draft: action === "draft"};
    const snapshot = wasCreate ? currentFormState.beginCreateSave(options) : currentFormState.beginSave(options);
    if (workflow) {
      currentFormState.requireValidInputs({draft: action === "draft"});
      const record = snapshot;
      await validateActionSnapshot(currentDescriptor.module, {action, record, operation_id: operationId,
        ...(wasCreate ? {identity: (await saveQueueStore.get(operationId))?.identity} : {record_id: currentUpdate.recordId, base_revision: currentUpdate.revision})}, csrfToken());
    }
    const identityAssignment = currentDescriptor.create?.identity_assignment || "on_create";
    queueContexts.set(operationId, {
      operationId,
      formState: currentFormState,
      update: currentUpdate,
      create: currentCreate,
      identityAssignment,
      identityReserved: Boolean(wasCreate && currentCreate.earlyReservation && currentCreate.recordId)
    });
    try {
      if (wasCreate) {
        await saveQueueProcessor.enqueueCreate({
          operationId,
          moduleId: currentCreate.moduleKey,
          identityAssignment,
          action,
          requireReservation: Boolean(currentCreate.earlyReservation),
          snapshot
        });
      } else {
        await saveQueueProcessor.enqueueUpdate({
          operationId,
          moduleId: currentUpdate.moduleKey,
          recordId: currentUpdate.recordId,
          action,
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
    return true;
  } catch (error) {
    currentFormState?.cancelSave();
    $("#save-status").textContent = "Nicht gespeichert";
    $("#module-error").textContent = error.message || "Netzwerkfehler. Ihre Änderungen bleiben erhalten.";
  } finally {
    saveInProgress = false;
    updateSaveButton();
  }
}
$("#show-payload").addEventListener("click", updatePayloadPreview);
$("#retry-reservation").addEventListener("click", () => run(async () => {
  if (!currentCreate?.earlyReservation) return;
  const operationId = currentCreate.operationId;
  const entry = await saveQueueProcessor.resumeReservation(operationId);
  if (currentCreate?.operationId === operationId) showEarlyIdentity(entry);
}));
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
  if (!entry || !window.confirm(entry.operation === "reservation"
    ? "Reservierung aufgeben? Bereits vergebene Nummern bleiben verbraucht. Ungespeicherte fachliche Eingaben gehen verloren."
    : "Lokale Speicherung wirklich verwerfen? Der gespeicherte Snapshot geht dabei unwiderruflich verloren.")) return;
  const context = queueContexts.get(entry.operation_id);
  if (context?.formState === currentFormState) currentFormState.cancelSave();
  await saveQueueProcessor.discard(entry.operation_id);
  if (entry.operation === "reservation" && currentCreate?.operationId === entry.operation_id) {
    currentCreate = null;
    currentFormState = null;
    state.creating = false;
    state.recordId = null;
    showView();
    updateUrl();
  }
  queueContexts.delete(entry.operation_id);
  updateSaveButton();
  $("#save-status").textContent = entry.operation === "reservation"
    ? "Lokale Reservierung aufgegeben; bereits vergebene Nummern bleiben verbraucht."
    : "Lokale Speicherung verworfen; es wurde keine Backend-Operation ausgelöst.";
  scheduleQueueProcessing();
}));
run(init);
