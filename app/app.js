const PRESET_KEY = "erschliessung.papierabzuege.activePreset.v2";
const PROFILE_KEY = "erschliessung.papierabzuege.profile";
const LOCAL_RECORDS_KEY = "erschliessung.papierabzuege.localRecords";
const REQUIRED_MODULE = "foto_papierabzuege";
const SAVE_STATES = Object.freeze({
  CLEAN: "clean",
  DIRTY: "dirty",
  RESERVING: "reserving",
  QUEUED: "queued",
  SAVING: "saving",
  AUTH_ERROR: "auth_error",
  CONFLICT: "conflict",
  VALIDATION_ERROR: "validation_error",
  ERROR: "error"
});
const SAVE_STATE_MESSAGES = Object.freeze({
  [SAVE_STATES.CLEAN]: "Gespeichert",
  [SAVE_STATES.DIRTY]: "Änderungen noch nicht gespeichert",
  [SAVE_STATES.RESERVING]: "Speichern …",
  [SAVE_STATES.QUEUED]: "Speichern …",
  [SAVE_STATES.SAVING]: "Speichern …",
  [SAVE_STATES.AUTH_ERROR]: "Anmeldung erforderlich – Änderungen nicht gespeichert",
  [SAVE_STATES.CONFLICT]: "Speicherkonflikt – Änderungen nicht gespeichert",
  [SAVE_STATES.VALIDATION_ERROR]: "Datensatz kann so nicht gespeichert werden",
  [SAVE_STATES.ERROR]: "Speichern fehlgeschlagen – Änderungen bleiben erhalten"
});
const SAVE_FAILURE_MESSAGES = Object.freeze({
  [SAVE_STATES.AUTH_ERROR]: "Anmeldung erforderlich. Ihre Änderungen bleiben erhalten.",
  [SAVE_STATES.CONFLICT]: "Der Datensatz wurde inzwischen anderweitig geändert. Ihre Änderungen bleiben erhalten.",
  [SAVE_STATES.VALIDATION_ERROR]: "Der Datensatz enthält Angaben, die nicht gespeichert werden können.",
  [SAVE_STATES.ERROR]: "Speichern derzeit nicht möglich. Ihre Änderungen bleiben erhalten."
});
const FAILURE_SAVE_STATES = new Set([
  SAVE_STATES.AUTH_ERROR,
  SAVE_STATES.CONFLICT,
  SAVE_STATES.VALIDATION_ERROR,
  SAVE_STATES.ERROR
]);
const USER_PROFILE_MAP = {
  "ehrenamt-standard": "standard",
  "ehrenamt-barrierearm": "barrierearm",
  redaktion: "redaktion"
};

let config = null;
const state = {
  format: null,
  generatedMarkdown: "",
  generatedFilename: "foto-000004.md",
  inventory: [],
  records: [],
  currentDraft: null,
  finalizedCurrentDraft: false,
  user: null,
  backendMode: true,
  mode: "new",
  editingRecord: null,
  baseRevision: null,
  serverSnapshot: null,
  queuedSnapshot: null,
  currentQueueOperationId: null,
  queueRecoveryRunning: false,
  signatureSuggestion: null,
  signatureManuallyEdited: false,
  signatureSuggestionRequest: 0,
  saveState: SAVE_STATES.DIRTY,
  maySaveEditingRecord: false
};

const form = document.querySelector("#record-form");
const errors = document.querySelector("#errors");
const preview = document.querySelector("#preview");
const generateButton = document.querySelector("#generate");
const downloadButton = document.querySelector("#download");
const finalizeButton = document.querySelector("#finalize");
const discardButton = document.querySelector("#discard-changes");
const saveStatus = document.querySelector("#save-status");
const queueStatus = document.querySelector("#queue-status");
const queueRecoveryActions = document.querySelector("#queue-recovery-actions");
const retryQueueButton = document.querySelector("#retry-queue");
const openQueuedSnapshotButton = document.querySelector("#open-queued-snapshot");
const discardQueuedSaveButton = document.querySelector("#discard-queued-save");
const numberOutput = document.querySelector("#number-output");
const signatureOutput = document.querySelector("#signature-output");
const legacyStatusPanel = document.querySelector("#legacy-status-panel");
const dateWarnings = document.querySelector("#date-warnings");
const archivisDateOutput = document.querySelector("#archivis-date");
const presetStatus = document.querySelector("#preset-status");
const presetEditor = document.querySelector("#preset-editor");
const presetFieldList = document.querySelector("#preset-field-list");
const currentUserOutput = document.querySelector("#current-user");
const recordBrowser = document.querySelector("#record-browser");
const recordSearch = document.querySelector("#record-search");
const recordList = document.querySelector("#record-list");
const recordNavTop = document.querySelector("#record-nav-top");
const recordNavBottom = document.querySelector("#record-nav-bottom");
let saveQueueStore = null;
let saveQueueProcessor = null;

const fieldMap = {
  titel: { label: "Titel", kind: "scalar", selector: "#titel" },
  beschriftung: { label: "Beschriftung", kind: "scalar", selector: "#beschriftung" },
  beschreibung: { label: "Beschreibung", kind: "scalar", selector: "#beschreibung" },
  dargestellte_personen: { label: "Dargestellte Personen", kind: "persons", selector: "#personen-list" },
  herkunft: { label: "Herkunft", kind: "scalar", selector: "#herkunft" },
  sammler: { label: "Sammler", kind: "scalar", selector: "#sammler" },
  fotograf: { label: "Fotograf", kind: "scalar", selector: "#fotograf" },
  rechteinhaber: { label: "Rechteinhaber", kind: "scalar", selector: "#rechteinhaber" },
  orte: { label: "Orte", kind: "list", selector: "#orte" },
  schlagworte: { label: "Schlagworte", kind: "list", selector: "#schlagworte" },
  altsignaturen: { label: "Altsignaturen", kind: "list", selector: "#altsignaturen" },
  interne_bemerkung: { label: "Interne Bemerkung", kind: "scalar", selector: "#interne-bemerkung" },
  datierung: { label: "Datierung", kind: "date" }
};

async function init() {
  await initializeSaveQueue();
  state.user = await loadCurrentUser();
  config = await loadConfig();
  await refreshRecords();
  buildFormatOptions();
  addPersonRow();
  bindEvents();
  const profile = USER_PROFILE_MAP[state.user.ui_profile] || "standard";
  setProfile(profile);
  currentUserOutput.textContent = state.user.display_name;
  applyPreset({ onlyEmpty: true });
  updateSignatureOutput();
  updateArchivisDate();
  const initialRecordId = new URLSearchParams(window.location.search).get("record");
  if (initialRecordId) {
    await openExistingRecord(initialRecordId, { preserveDirty: false });
  }
  scheduleSafeQueueRecovery();
}

async function loadCurrentUser() {
  const response = await fetch("/api/auth/me", { credentials: "same-origin" });
  if (response.status === 401) {
    window.location.href = "/login/";
    const error = new Error("Nicht angemeldet");
    error.status = response.status;
    throw error;
  }
  if (!response.ok) throw new Error("Benutzer konnte nicht geladen werden.");
  const user = await response.json();
  if (!user.modules.includes(REQUIRED_MODULE)) {
    window.location.href = "/arbeitsbereiche";
    throw new Error("Arbeitsbereich nicht freigegeben");
  }
  const moduleResponse = await fetch(`/api/modules/${REQUIRED_MODULE}`, { credentials: "same-origin" });
  if (!moduleResponse.ok) {
    window.location.href = "/arbeitsbereiche";
    throw new Error("Arbeitsbereich nicht freigegeben");
  }
  return user;
}

function csrfToken() {
  const cookieName = state.user.csrf_cookie_name;
  return document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${cookieName}=`))
    ?.split("=")[1];
}

async function apiFetch(url, options = {}) {
  const { redirectOnAuth = true, ...fetchOptions } = options;
  const headers = { ...(fetchOptions.headers || {}) };
  if (fetchOptions.method && fetchOptions.method !== "GET") headers["X-CSRF-Token"] = csrfToken() || "";
  const response = await fetch(url, {
    credentials: "same-origin",
    ...fetchOptions,
    headers
  });
  if (redirectOnAuth && response.status === 401 && (!fetchOptions.method || fetchOptions.method === "GET")) {
    window.location.href = "/login/";
    const error = new Error("Nicht angemeldet");
    error.status = response.status;
    throw error;
  }
  return response;
}

async function refreshRecords() {
  const response = await apiFetch("/api/records/photos");
  if (!response.ok) throw new Error("Datensatzliste konnte nicht geladen werden.");
  const data = await response.json();
  state.records = data.records || [];
  state.inventory = state.records
    .map((record) => {
      const match = String(record.signatur || "").match(/^9\.4\.2\.([A-F])\.([0-9]+)[a-z]*$/);
      return match ? { id: record.id, format: match[1], nummer: Number(match[2]) } : null;
    })
    .filter(Boolean);
  renderRecordList();
  updateRecordNavigation();
}

async function loadConfig() {
  const response = await fetch("../config/foto-papierabzuege.json", { cache: "no-store" });
  if (!response.ok) throw new Error("Fachkonfiguration konnte nicht geladen werden.");
  return response.json();
}

function buildFormatOptions() {
  const container = document.querySelector("#format-options");
  container.innerHTML = "";
  config.signature.formats.forEach((format) => {
    const label = document.createElement("label");
    label.className = "format-option";
    label.innerHTML = `<input type="radio" name="format" value="${format}"><span>${format}</span>`;
    container.append(label);
  });
}

function bindEvents() {
  document.querySelectorAll("input[name='format']").forEach((input) => {
    input.addEventListener("change", () => {
      state.format = input.value;
      if (!(state.mode === "edit" && state.editingRecord) && !state.signatureManuallyEdited) {
        refreshSignatureSuggestion(input.value);
      } else {
        updateSignatureOutput();
      }
    });
  });

  document.querySelectorAll(".profile-button").forEach((button) => {
    button.addEventListener("click", () => setProfile(button.dataset.profile));
  });

  document.querySelector("#datierung-von").addEventListener("input", updateArchivisDate);
  document.querySelector("#datierung-bis").addEventListener("input", updateArchivisDate);
  signatureOutput.addEventListener("input", () => {
    if (state.mode === "new" && state.signatureSuggestion && signatureOutput.value !== state.signatureSuggestion.anzeige) {
      state.signatureManuallyEdited = true;
    }
  });

  document.querySelector("#generate").addEventListener("click", generateRecord);
  finalizeButton.addEventListener("click", finalizeRecord);
  discardButton.addEventListener("click", discardChanges);
  retryQueueButton.addEventListener("click", retryFirstQueueEntry);
  openQueuedSnapshotButton.addEventListener("click", openFirstQueuedSnapshot);
  discardQueuedSaveButton.addEventListener("click", discardFirstQueueEntry);
  document.querySelector("#new-record").addEventListener("click", startNewRecord);
  document.querySelector("#reset-session").addEventListener("click", resetLocalSessionRecords);
  document.querySelector("#add-person").addEventListener("click", () => {
    addPersonRow();
    updateDirtyState();
  });
  document.querySelector("#logout").addEventListener("click", logout);
  document.querySelector("#mode-new").addEventListener("click", () => setMode("new"));
  document.querySelector("#mode-edit").addEventListener("click", () => setMode("edit"));
  recordSearch.addEventListener("input", renderRecordList);
  downloadButton.addEventListener("click", downloadMarkdown);
  document.querySelectorAll(".record-nav-button").forEach((button) => {
    button.addEventListener("click", () => navigateAdjacentRecord(button.dataset.direction));
  });
  form.addEventListener("input", updateDirtyState);
  form.addEventListener("change", updateDirtyState);
  window.addEventListener("beforeunload", (event) => {
    if (!hasUnsecuredChanges()) return;
    event.preventDefault();
    event.returnValue = "";
  });

  document.querySelector("#edit-preset").addEventListener("click", () => {
    syncPresetEditor();
    presetEditor.hidden = !presetEditor.hidden;
  });

  document.querySelector("#save-preset").addEventListener("click", () => {
    savePreset(readPresetEditor());
    presetEditor.hidden = true;
  });

  document.querySelector("#disable-preset").addEventListener("click", () => {
    localStorage.removeItem(PRESET_KEY);
    presetStatus.textContent = "Keine aktive Vorbelegung.";
  });

  document.querySelector("#adopt-preset").addEventListener("click", () => {
    savePreset(readCurrentValuesAsPreset({ includeEmpty: false }));
    syncPresetEditor();
  });
}

async function logout() {
  await fetch("/api/auth/logout", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrfToken() || "" }
  });
  window.location.href = "/login/";
}

function setMode(mode) {
  if (mode === "new" && mode !== state.mode) {
    if (!confirmDiscardUnsavedChanges()) return;
    startNewRecord({ skipConfirmation: true });
    renderRecordList();
    return;
  }
  if (mode !== state.mode && !confirmDiscardUnsavedChanges()) return;
  state.mode = mode;
  document.querySelector("#mode-new").classList.toggle("active", mode === "new");
  document.querySelector("#mode-edit").classList.toggle("active", mode === "edit");
  recordBrowser.hidden = mode !== "edit";
  if (mode === "new") startNewRecord();
  renderRecordList();
}

function renderRecordList() {
  if (!recordList) return;
  const query = recordSearch.value.trim().toLowerCase();
  const records = state.records.filter((record) => {
    return !query || String(record.id).toLowerCase().includes(query) || String(record.signatur).toLowerCase().includes(query);
  });
  recordList.innerHTML = "";
  if (!records.length) {
    recordList.innerHTML = "<p class=\"help-text\">Keine passenden Datensätze gefunden.</p>";
    return;
  }
  records.forEach((record) => {
    const item = document.createElement("div");
    item.className = "record-list-item";
    const label = document.createElement("span");
    label.textContent = `${record.signatur || "-"} · ${record.id}`;
    const link = document.createElement("a");
    link.href = recordUrl(record.id);
    link.target = "_blank";
    link.rel = "noopener";
    link.className = "button-like";
    link.textContent = "Datensatz öffnen";
    link.setAttribute("aria-label", `Datensatz ${record.id} in neuem Tab öffnen`);
    const hint = document.createElement("span");
    hint.className = "visually-hidden";
    hint.textContent = "öffnet in neuem Tab";
    link.append(hint);
    item.append(label, link);
    recordList.append(item);
  });
}

function recordUrl(recordId) {
  return `${window.location.pathname}?record=${encodeURIComponent(recordId)}`;
}

async function openExistingRecord(recordId, { preserveDirty = true } = {}) {
  if (preserveDirty && !confirmDiscardUnsavedChanges()) return;
  const response = await apiFetch(`/api/records/photos/${recordId}`);
  if (!response.ok) {
    errors.innerHTML = "<p>Datensatz konnte nicht geladen werden.</p>";
    return;
  }
  const data = await response.json();
  applyLoadedRecord(data.record, data.base_revision);
  const url = new URL(window.location.href);
  url.searchParams.set("record", recordId);
  window.history.replaceState({}, "", url);
}

function applyLoadedRecord(record, baseRevision) {
  state.signatureSuggestionRequest += 1;
  state.mode = "edit";
  state.editingRecord = record;
  state.baseRevision = baseRevision;
  state.currentDraft = {
    id: record.id,
    format: record.signatur.format,
    nummer: record.signatur.nummer,
    signature: record.signatur
  };
  state.format = record.signatur.format;
  state.signatureSuggestion = null;
  state.signatureManuallyEdited = false;
  state.finalizedCurrentDraft = false;
  form.reset();
  document.querySelector("#personen-list").innerHTML = "";
  fillFormFromRecord(record);
  state.serverSnapshot = formSnapshot();
  state.queuedSnapshot = null;
  state.currentQueueOperationId = null;
  updateSignatureOutput();
  updateArchivisDate();
  updateRecordNavigation();
  const maySave = !(state.user.role === "ehrenamtlich" && record.redaktion?.stufe === "redaktionell");
  state.maySaveEditingRecord = maySave;
  setSaveState(SAVE_STATES.CLEAN);
  errors.innerHTML = maySave
    ? "<p>Datensatz geladen.</p>"
    : "<p>Dieser redaktionelle Datensatz kann mit deiner Rolle gelesen, aber nicht gespeichert werden.</p>";
}

function currentRecordIndex() {
  if (!state.editingRecord) return -1;
  return state.records.findIndex((record) => record.id === state.editingRecord.id);
}

function adjacentRecordId(direction) {
  const index = currentRecordIndex();
  if (index < 0) return null;
  const nextIndex = direction === "previous" ? index - 1 : index + 1;
  return state.records[nextIndex]?.id || null;
}

function updateRecordNavigation() {
  const isEditing = state.mode === "edit" && state.editingRecord;
  [recordNavTop, recordNavBottom].forEach((nav) => {
    nav.hidden = !isEditing;
  });
  document.querySelectorAll(".record-nav-button").forEach((button) => {
    const target = isEditing ? adjacentRecordId(button.dataset.direction) : null;
    button.disabled = !target;
    button.dataset.targetRecordId = target || "";
  });
}

async function navigateAdjacentRecord(direction) {
  const target = adjacentRecordId(direction);
  if (!target) return;
  await openExistingRecord(target);
}

function fillFormFromRecord(record) {
  const e = record.erschliessung || {};
  document.querySelector("#beschriftung").value = e.beschriftung || "";
  document.querySelector("#titel").value = e.titel || "";
  document.querySelector("#beschreibung").value = e.beschreibung || "";
  document.querySelector("#herkunft").value = e.herkunft || "";
  document.querySelector("#sammler").value = e.sammler || "";
  document.querySelector("#fotograf").value = e.fotograf || "";
  document.querySelector("#rechteinhaber").value = e.rechteinhaber || "";
  document.querySelector("#orte").value = joinList(e.orte || []);
  document.querySelector("#schlagworte").value = joinList(e.schlagworte || []);
  document.querySelector("#altsignaturen").value = joinList(e.altsignaturen || []);
  document.querySelector("#interne-bemerkung").value = e.interne_bemerkung || "";
  const list = document.querySelector("#personen-list");
  list.innerHTML = "";
  const persons = e.dargestellte_personen?.length ? e.dargestellte_personen : [{ name: "", hinweis: "" }];
  persons.forEach((person) => addPersonRow(person));
  document.querySelector("#korrespondenzstueck").checked = Boolean(record.korrespondenzstueck);
  document.querySelector("#datierung-von").value = DateTextFields.format(record.datierung || {});
  document.querySelector("#datierung-bis").value = DateTextFields.format({
    jahr: record.datierung?.bis_jahr,
    monat: record.datierung?.bis_monat,
    tag: record.datierung?.bis_tag
  });
  document.querySelector("#datierung-hinweis").value = record.datierung?.anmerkung || "";
  document.querySelector("#original-datum").value = record.datierung?.original || "";
  const input = document.querySelector(`input[name='format'][value='${record.signatur.format}']`);
  if (input) input.checked = true;
}

function formSnapshot() {
  if (!(state.mode === "edit" && state.editingRecord)) return null;
  return JSON.stringify(readWorkingRecord());
}

function hasUnsavedChanges() {
  if (!(state.mode === "edit" && state.editingRecord) || state.serverSnapshot === null) return false;
  return formSnapshot() !== state.serverSnapshot;
}

function currentWorkingSnapshot() {
  return JSON.stringify(readWorkingRecord());
}

function hasUnsecuredChanges() {
  if (state.saveState === SAVE_STATES.RESERVING && state.currentQueueOperationId) return true;
  if (state.queuedSnapshot !== null && currentWorkingSnapshot() === state.queuedSnapshot) return false;
  if (state.mode === "edit" && state.editingRecord) return hasUnsavedChanges();
  return state.mode === "new" && Boolean(state.format);
}

function isSaveInProgress() {
  return [SAVE_STATES.RESERVING, SAVE_STATES.SAVING, SAVE_STATES.QUEUED].includes(state.saveState);
}

function updateSaveControls(dirty = hasUnsavedChanges()) {
  form.dataset.dirty = dirty ? "true" : "false";
  if (state.mode === "edit" && state.editingRecord) {
    finalizeButton.disabled = Boolean(state.currentQueueOperationId) || isSaveInProgress() || !state.maySaveEditingRecord || !dirty;
    discardButton.disabled = isSaveInProgress() || !dirty;
  } else {
    discardButton.disabled = true;
    if (state.currentQueueOperationId) finalizeButton.disabled = true;
  }
}

function setSaveState(nextState) {
  if (!Object.values(SAVE_STATES).includes(nextState)) throw new Error(`Unbekannter Speicherzustand: ${nextState}`);
  if (FAILURE_SAVE_STATES.has(state.saveState) && state.saveState !== nextState) errors.innerHTML = "";
  state.saveState = nextState;
  form.dataset.saveState = nextState;
  saveStatus.dataset.state = nextState;
  saveStatus.textContent = SAVE_STATE_MESSAGES[nextState];
  updateSaveControls();
}

function updateDirtyState() {
  if (!(state.mode === "edit" && state.editingRecord)) {
    setSaveState(SAVE_STATES.DIRTY);
    return;
  }
  const dirty = hasUnsavedChanges();
  if (isSaveInProgress()) updateSaveControls(dirty);
  else setSaveState(dirty ? SAVE_STATES.DIRTY : SAVE_STATES.CLEAN);
}

function discardChanges() {
  if (!(state.mode === "edit" && state.editingRecord) || isSaveInProgress()) return;
  fillFormFromRecord(state.editingRecord);
  updateSignatureOutput();
  updateArchivisDate();
  updateDirtyState();
  errors.innerHTML = "<p>Ungespeicherte Änderungen wurden verworfen.</p>";
}

function confirmDiscardUnsavedChanges() {
  if (state.saveState === SAVE_STATES.RESERVING && state.currentQueueOperationId) {
    errors.innerHTML = "<p>Bitte warten, bis ID und Signatur verbindlich reserviert sind.</p>";
    return false;
  }
  if (!hasUnsecuredChanges()) return true;
  return window.confirm("Ungespeicherte Änderungen verwerfen und den Datensatz wechseln?");
}

function nextNumber(format) {
  const numbers = state.inventory
    .filter((record) => record.format === format)
    .map((record) => record.nummer);
  return Math.max(0, ...numbers) + 1;
}

function nextId() {
  const maxId = state.inventory
    .map((record) => Number(String(record.id).replace("foto-", "")))
    .filter((number) => Number.isInteger(number))
    .reduce((max, value) => Math.max(max, value), 0);
  return `foto-${String(maxId + 1).padStart(6, "0")}`;
}

function currentDraftForFormat(format) {
  if (
    state.currentDraft &&
    state.currentDraft.format === format
  ) {
    return state.currentDraft;
  }
  const number = nextNumber(format);
  state.currentDraft = {
    id: nextId(),
    format,
    nummer: number,
    signature: buildSignature(format, number)
  };
  state.finalizedCurrentDraft = false;
  return state.currentDraft;
}

function buildSignature(format, number, status = "vorgeschlagen") {
  const signature = config.signature;
  const anzeige = signature.pattern
    .replace("{bestand}", signature.bestand)
    .replace("{objektgruppe}", signature.objektgruppe)
    .replace("{format}", format)
    .replace("{nummer}", String(number));
  return {
    bestand: signature.bestand,
    objektgruppe: signature.objektgruppe,
    format,
    nummer: number,
    anzeige,
    status
  };
}

async function refreshSignatureSuggestion(format) {
  if (state.mode === "edit" && state.editingRecord || state.signatureManuallyEdited) return;
  const request = ++state.signatureSuggestionRequest;
  state.signatureSuggestion = null;
  numberOutput.textContent = "–";
  signatureOutput.value = "Vorschlag wird geladen …";
  signatureOutput.readOnly = true;
  try {
    const response = await apiFetch(`/api/modules/${REQUIRED_MODULE}?signature_partition=${encodeURIComponent(format)}`);
    if (!response.ok) throw new Error("Kein Signaturvorschlag verfügbar");
    const data = await response.json();
    if (request !== state.signatureSuggestionRequest || state.format !== format) return;
    const suggestion = data.identity_suggestion;
    if (!suggestion?.["signatur.anzeige"]) {
      signatureOutput.value = "Kein Signaturvorschlag verfügbar";
      return;
    }
    state.signatureSuggestion = {
      format,
      nummer: suggestion["signatur.nummer"] ?? null,
      anzeige: suggestion["signatur.anzeige"]
    };
    numberOutput.textContent = state.signatureSuggestion.nummer === null ? "–" : String(state.signatureSuggestion.nummer);
    signatureOutput.value = state.signatureSuggestion.anzeige;
  } catch {
    if (request === state.signatureSuggestionRequest) signatureOutput.value = "Kein Signaturvorschlag verfügbar";
  } finally {
    if (request === state.signatureSuggestionRequest) signatureOutput.readOnly = false;
  }
}

function parseIntegerField(id) {
  const value = document.querySelector(`#${id}`).value.trim();
  if (!value) return null;
  if (!/^[0-9]+$/.test(value)) return Number.NaN;
  return Number(value);
}

function parseSimpleDate(value) {
  const trimmed = value.trim();
  if (!trimmed) return { jahr: null, monat: null, tag: null };
  let match = trimmed.match(/^([0-9]{4})$/);
  if (match) return { jahr: Number(match[1]), monat: null, tag: null };
  match = trimmed.match(/^([0-9]{1,2})\.([0-9]{4})$/);
  if (match) return { jahr: Number(match[2]), monat: Number(match[1]), tag: null };
  match = trimmed.match(/^([0-9]{1,2})\.([0-9]{1,2})\.([0-9]{4})$/);
  if (match) return { jahr: Number(match[3]), monat: Number(match[2]), tag: Number(match[1]) };
  return { jahr: Number.NaN, monat: Number.NaN, tag: Number.NaN };
}

function archivisDateValue({ jahr, monat, tag }) {
  if (!jahr) return "";
  if (!monat) return `${String(jahr).padStart(4, "0")}9999`;
  if (!tag) return `${String(jahr).padStart(4, "0")}${String(monat).padStart(2, "0")}99`;
  return `${String(jahr).padStart(4, "0")}${String(monat).padStart(2, "0")}${String(tag).padStart(2, "0")}`;
}

function splitList(value) {
  return value
    .split(";")
    .map((part) => part.trim())
    .filter(Boolean);
}

function joinList(values) {
  return Array.isArray(values) ? values.join("; ") : "";
}

function addPersonRow(person = { name: "", hinweis: "" }) {
  const list = document.querySelector("#personen-list");
  const row = document.createElement("div");
  row.className = "person-row";
  row.innerHTML = `
    <div class="field">
      <label>Name <input class="person-name" type="text" value="${escapeAttribute(person.name || "")}"></label>
    </div>
    <div class="field">
      <label>Hinweis <input class="person-hinweis" type="text" value="${escapeAttribute(person.hinweis || "")}"></label>
    </div>
    <button type="button" class="remove-person">Person entfernen</button>
  `;
  row.querySelector(".remove-person").addEventListener("click", () => {
    row.remove();
    if (!list.querySelector(".person-row")) addPersonRow();
    updateDirtyState();
  });
  list.append(row);
}

function escapeAttribute(value) {
  return String(value).replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;");
}

function readPersons() {
  return Array.from(document.querySelectorAll(".person-row"))
    .map((row) => ({
      name: row.querySelector(".person-name").value.trim(),
      hinweis: row.querySelector(".person-hinweis").value.trim() || null
    }))
    .filter((person) => person.name || person.hinweis)
    .map((person) => ({ name: person.name, hinweis: person.hinweis }));
}

function readDatierung() {
  const review = DateTextFields.review(
    document.querySelector("#datierung-von").value,
    document.querySelector("#datierung-bis").value
  );
  const original = state.editingRecord?.datierung || {};
  const from = DateTextFields.withKeys(review.from, original, "german") || {};
  const oldTo = { jahr: original.bis_jahr, monat: original.bis_monat, tag: original.bis_tag };
  const to = DateTextFields.withKeys(review.to, oldTo, "german");
  const originalText = document.querySelector("#original-datum").value.trim();
  const value = {
    ...original,
    jahr: from.jahr ?? null,
    monat: from.monat ?? null,
    tag: from.tag ?? null,
    anmerkung: document.querySelector("#datierung-hinweis").value.trim() || null,
    original: originalText || null,
    original_typ: originalText ? (original.original_typ || "importierte_arbeitsdaten") : null
  };
  if (to || Object.prototype.hasOwnProperty.call(original, "bis_jahr")) {
    value.bis_jahr = to?.jahr ?? null;
    value.bis_monat = to?.monat ?? null;
    value.bis_tag = to?.tag ?? null;
  }
  return value;
}

function readRecord() {
  const draft = state.currentDraft || (!state.backendMode && state.format ? currentDraftForFormat(state.format) : null);
  return {
    id: draft?.id || null,
    schema_version: 1,
    datensatz_typ: config.datensatz_typ,
    modul: config.module_id,
    signatur: draft ? draft.signature : null,
    erschliessung: {
      titel: readScalar("titel"),
      beschriftung: readScalar("beschriftung"),
      beschreibung: readScalar("beschreibung"),
      dargestellte_personen: readPersons(),
      herkunft: readScalar("herkunft"),
      sammler: readScalar("sammler"),
      fotograf: readScalar("fotograf"),
      rechteinhaber: readScalar("rechteinhaber"),
      orte: splitList(document.querySelector("#orte").value),
      schlagworte: splitList(document.querySelector("#schlagworte").value),
      altsignaturen: splitList(document.querySelector("#altsignaturen").value),
      interne_bemerkung: readScalar("interne_bemerkung")
    },
    korrespondenzstueck: document.querySelector("#korrespondenzstueck").checked,
    datierung: readDatierung(),
    redaktion: { stufe: config.defaults.redaktion_stufe },
    bearbeitung: { status: config.defaults.bearbeitung_status },
    publikation: { status: config.defaults.publikation_status },
    technik: { quelle: "lokaler_webpilot", erstellt_am: null, geaendert_am: null }
  };
}

function readScalar(field) {
  if (!isFieldEditable(field)) return null;
  const definition = fieldMap[field];
  const value = document.querySelector(definition.selector).value.trim();
  return value || null;
}

function isFieldEditable(field) {
  const profile = localStorage.getItem(PROFILE_KEY) || "standard";
  return editableFieldsForProfile(profile).includes(field);
}

function validate(record) {
  const messages = [];
  if (!state.format) messages.push("Bitte ein Format wählen.");
  if (
    Number.isNaN(record.datierung.jahr) ||
    Number.isNaN(record.datierung.monat) ||
    Number.isNaN(record.datierung.tag)
  ) {
    messages.push("Die Datierung muss als JJJJ, MM.JJJJ oder TT.MM.JJJJ eingegeben werden.");
  } else if (record.datierung.jahr !== null && (record.datierung.jahr < 1 || record.datierung.jahr > 9999)) {
    messages.push("Das Jahr muss eine Zahl zwischen 1 und 9999 sein.");
  } else if (record.datierung.monat !== null && (record.datierung.monat < 1 || record.datierung.monat > 12)) {
    messages.push("Der Monat muss leer oder eine Zahl zwischen 1 und 12 sein.");
  } else if (record.datierung.tag !== null) {
    const date = new Date(record.datierung.jahr, record.datierung.monat - 1, record.datierung.tag);
    if (
      record.datierung.tag < 1 ||
      date.getFullYear() !== record.datierung.jahr ||
      date.getMonth() !== record.datierung.monat - 1 ||
      date.getDate() !== record.datierung.tag
    ) {
      messages.push("Der Tag passt nicht zum angegebenen Monat und Jahr.");
    }
  }
  if (record.datierung.bis_jahr !== null && (record.datierung.bis_jahr < 1 || record.datierung.bis_jahr > 9999)) {
    messages.push("Das Bis-Jahr muss zwischen 1 und 9999 liegen.");
  } else if (record.datierung.bis_monat !== null && (record.datierung.bis_monat < 1 || record.datierung.bis_monat > 12)) {
    messages.push("Der Bis-Monat muss zwischen 1 und 12 liegen.");
  }
  if (!record.erschliessung.beschriftung && !record.erschliessung.beschreibung) {
    messages.push("Bitte mindestens Beschriftung oder Beschreibung erfassen.");
  }
  return messages;
}

function yamlScalar(value) {
  if (value === null || value === undefined || value === "") return "null";
  return `"${String(value).replaceAll("\\", "\\\\").replaceAll('"', '\\"')}"`;
}

function yamlList(values, indent = "  ") {
  if (!values.length) return "[]";
  return `\n${values.map((value) => `${indent}- ${yamlScalar(value)}`).join("\n")}`;
}

function yamlPersonList(values) {
  if (!values.length) return "[]";
  return `\n${values.map((person) => `    - name: ${yamlScalar(person.name)}\n      hinweis: ${yamlScalar(person.hinweis)}`).join("\n")}`;
}

function yamlDatierung(datierung) {
  const lines = [
    "datierung:",
    `  jahr: ${datierung.jahr ?? "null"}`,
    `  monat: ${datierung.monat ?? "null"}`,
    `  tag: ${datierung.tag ?? "null"}`,
    `  anmerkung: ${yamlScalar(datierung.anmerkung)}`
  ];
  if (Object.prototype.hasOwnProperty.call(datierung, "bis_jahr")) {
    lines.splice(4, 0,
      `  bis_jahr: ${datierung.bis_jahr ?? "null"}`,
      `  bis_monat: ${datierung.bis_monat ?? "null"}`,
      `  bis_tag: ${datierung.bis_tag ?? "null"}`
    );
  }
  if (datierung.original) lines.push(`  original: ${yamlScalar(datierung.original)}`);
  if (datierung.original_typ) lines.push(`  original_typ: ${yamlScalar(datierung.original_typ)}`);
  return lines.join("\n");
}

function toMarkdown(record) {
  const e = record.erschliessung;
  const d = record.datierung;
  const s = record.signatur;
  return `---\nschema_version: 1\nid: ${record.id}\ndatensatz_typ: ${record.datensatz_typ}\nmodul: ${record.modul}\nsignatur:\n  bestand: ${yamlScalar(s.bestand)}\n  objektgruppe: ${yamlScalar(s.objektgruppe)}\n  format: ${yamlScalar(s.format)}\n  nummer: ${s.nummer}\n  anzeige: ${yamlScalar(s.anzeige)}\n  status: ${s.status}\nerschliessung:\n  titel: ${yamlScalar(e.titel)}\n  beschriftung: ${yamlScalar(e.beschriftung)}\n  beschreibung: ${yamlScalar(e.beschreibung)}\n  dargestellte_personen: ${yamlPersonList(e.dargestellte_personen)}\n  herkunft: ${yamlScalar(e.herkunft)}\n  sammler: ${yamlScalar(e.sammler)}\n  fotograf: ${yamlScalar(e.fotograf)}\n  rechteinhaber: ${yamlScalar(e.rechteinhaber)}\n  orte: ${yamlList(e.orte, "    ")}\n  schlagworte: ${yamlList(e.schlagworte, "    ")}\n  altsignaturen: ${yamlList(e.altsignaturen, "    ")}\n  interne_bemerkung: ${yamlScalar(e.interne_bemerkung)}\nkorrespondenzstueck: ${record.korrespondenzstueck ? "true" : "false"}\n${yamlDatierung(d)}\nredaktion:\n  stufe: ${record.redaktion.stufe}\nbearbeitung:\n  status: ${record.bearbeitung.status}\npublikation:\n  status: ${record.publikation.status}\ntechnik:\n  quelle: ${yamlScalar(record.technik.quelle)}\n  erstellt_am: null\n  geaendert_am: null\n---\n`;
}

function showErrors(messages) {
  if (!messages.length) {
    errors.innerHTML = "";
    return;
  }
  errors.innerHTML = `<p>Bitte prüfen:</p><ul>${messages.map((message) => `<li>${message}</li>`).join("")}</ul>`;
}

function updateSignatureOutput() {
  if (state.mode === "edit" && state.editingRecord) {
    numberOutput.textContent = String(state.editingRecord.signatur.nummer);
    signatureOutput.value = state.editingRecord.signatur.anzeige;
    signatureOutput.readOnly = true;
    return;
  }
  if (state.finalizedCurrentDraft && state.currentDraft) {
    numberOutput.textContent = String(state.currentDraft.nummer);
    signatureOutput.value = state.currentDraft.signature.anzeige;
    signatureOutput.readOnly = true;
    return;
  }
  signatureOutput.readOnly = false;
  if (!state.format) {
    numberOutput.textContent = "-";
    signatureOutput.value = "Bitte Format wählen";
    finalizeButton.disabled = true;
    return;
  }
  if (state.signatureSuggestion && !state.signatureManuallyEdited) {
    numberOutput.textContent = state.signatureSuggestion.nummer === null ? "–" : String(state.signatureSuggestion.nummer);
    signatureOutput.value = state.signatureSuggestion.anzeige;
  } else if (!state.signatureManuallyEdited) {
    numberOutput.textContent = "–";
    signatureOutput.value = "Kein Signaturvorschlag verfügbar";
  }
  finalizeButton.disabled = state.finalizedCurrentDraft;
}

function updateArchivisDate() {
  const value = archivisDateValue(readDatierung());
  archivisDateOutput.textContent = value || "-";
}

function reviewVisibleDate({ show = false } = {}) {
  const result = DateTextFields.review(
    document.querySelector("#datierung-von").value,
    document.querySelector("#datierung-bis").value
  );
  if (show) {
    dateWarnings.hidden = result.warnings.length === 0;
    dateWarnings.innerHTML = result.warnings.length
      ? `<p>Hinweis zur Datierung:</p><ul>${result.warnings.map(message => `<li>${message}</li>`).join("")}</ul>`
      : "";
  }
  return result;
}

function generateRecord() {
  const dateReview = reviewVisibleDate({ show: true });
  if (dateReview.blocking) return;
  const record = readRecord();
  const messages = validate(record);
  showErrors(messages);
  if (messages.length) {
    setSaveState(SAVE_STATES.VALIDATION_ERROR);
    return;
  }
  state.generatedMarkdown = toMarkdown(record);
  state.generatedFilename = `${record.id}.md`;
  preview.value = state.generatedMarkdown;
  downloadButton.disabled = true;
  finalizeButton.disabled = state.finalizedCurrentDraft;
}

function readWorkingRecord() {
  const record = readRecord();
  return {
    format: state.format,
    erschliessung: record.erschliessung,
    korrespondenzstueck: record.korrespondenzstueck,
    datierung: record.datierung
  };
}

async function initializeSaveQueue() {
  saveQueueStore = createIndexedDbSaveQueueStore({ indexedDB: window.indexedDB });
  await saveQueueStore.open();
  saveQueueProcessor = createSaveQueueProcessor({
    store: saveQueueStore,
    lockManager: window.navigator?.locks || null,
    handlers: {
      update: sendQueuedUpdate,
      create: sendQueuedCreate,
      onSuccess: handleQueuedSaveSuccess,
      onError: handleQueuedSaveError
    },
    onChange: handleQueueChange
  });
  await normalizePersistedQueueEntries();
  await refreshQueueStatus();
}

async function normalizePersistedQueueEntries() {
  const entries = await saveQueueStore.list();
  for (const entry of entries) {
    let status = entry.status;
    if (status === "reserving" && entry.record_id && entry.signature) status = "queued";
    if (status === "error") {
      const httpStatus = entry.last_error?.http_status;
      if (httpStatus === 401 || httpStatus === 403) status = "auth_error";
      if (httpStatus === 409) status = "conflict";
      if (httpStatus === 422) status = "validation_error";
    }
    if (status !== entry.status) {
      await saveQueueStore.update(entry.operation_id, { status, updated_at: new Date().toISOString() });
    }
  }
}

async function refreshQueueStatus(entries = null) {
  const queueEntries = entries || (saveQueueStore ? await saveQueueStore.list() : []);
  const count = queueEntries.length;
  const first = queueEntries[0] || null;
  const label = count === 1 ? "1 Speichervorgang ausstehend" : `${count} Speichervorgänge ausstehend`;
  const activelySaving = Boolean(first?.status === "saving" && saveQueueProcessor?.isRunning());
  const paused = Boolean(first && !["queued", "reserving"].includes(first.status) && !activelySaving);
  queueStatus.dataset.count = String(count);
  queueStatus.dataset.paused = paused ? "true" : "false";
  legacyStatusPanel.dataset.recovery = paused ? "true" : "false";
  if (!first) {
    queueStatus.textContent = "Alle vorgemerkten Datensätze übertragen";
  } else if (first.status === "auth_error") {
    queueStatus.textContent = `${label} – pausiert: Anmeldung erforderlich`;
  } else if (first.status === "conflict") {
    queueStatus.textContent = `${label} – pausiert: Serverstand wurde geändert`;
  } else if (first.status === "validation_error") {
    queueStatus.textContent = `${label} – pausiert: lokaler Stand muss bearbeitet werden`;
  } else if (activelySaving) {
    queueStatus.textContent = `${label} – Übertragung läuft`;
  } else if (first.status === "saving" || first.last_error?.uncertain) {
    queueStatus.textContent = `${label} – pausiert: Ergebnis der letzten Übertragung ist ungeklärt`;
  } else if (first.status === "error") {
    queueStatus.textContent = `${label} – pausiert: manueller Wiederholungsversuch erforderlich`;
  } else if (first.status === "reserving") {
    queueStatus.textContent = `${label} – sichere Reservierung wird fortgesetzt`;
  } else {
    queueStatus.textContent = `${label} – sichere Übertragung wird fortgesetzt`;
  }

  queueRecoveryActions.hidden = !paused;
  retryQueueButton.hidden = !first || ["conflict", "validation_error"].includes(first.status);
  openQueuedSnapshotButton.hidden = !first;
  discardQueuedSaveButton.hidden = !first;
  retryQueueButton.disabled = state.queueRecoveryRunning;
  openQueuedSnapshotButton.disabled = state.queueRecoveryRunning;
  discardQueuedSaveButton.disabled = state.queueRecoveryRunning;
}

async function handleQueueChange(entry, entries) {
  await refreshQueueStatus(entries);
  if (!entry || entry.operation_id !== state.currentQueueOperationId) return;
  if (entry.status === "reserving") setSaveState(SAVE_STATES.RESERVING);
  if (entry.status === "queued") setSaveState(SAVE_STATES.QUEUED);
  if (entry.status === "saving") setSaveState(SAVE_STATES.SAVING);
  if (["auth_error", "conflict", "validation_error", "error"].includes(entry.status)) {
    const failedState = queueEntrySaveState(entry);
    setSaveState(failedState);
    showSaveFailure(failedState, entry.last_error?.message);
  }
}

async function responseError(response) {
  const data = await response.json().catch(() => ({}));
  const error = new Error(data.detail || `HTTP ${response.status}`);
  error.status = response.status;
  error.userMessage = Array.isArray(data.detail) ? data.detail.join("; ") : data.detail;
  return error;
}

async function sendQueuedUpdate(entry) {
  const response = await apiFetch(`/api/records/photos/${entry.record_id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...entry.snapshot, base_revision: entry.base_revision })
  });
  if (!response.ok) throw await responseError(response);
  const saved = await response.json();
  if (saved.record?.id !== entry.record_id) throw new Error("Backend bestätigte einen anderen Datensatz.");
  return saved;
}

async function sendQueuedCreate(entry) {
  const response = await apiFetch("/api/records/photos", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...entry.snapshot,
      operation_id: entry.operation_id,
      record_id: entry.record_id,
      signature: entry.signature
    })
  });
  if (!response.ok) throw await responseError(response);
  const saved = await response.json();
  if (saved.record?.id !== entry.record_id || saved.record?.signatur?.anzeige !== entry.signature) {
    throw new Error("Backend bestätigte nicht die reservierte Identität.");
  }
  return saved;
}

async function reserveQueuedCreate(entry) {
  const response = await apiFetch("/api/records/photos/reservations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ operation_id: entry.operation_id, partition: entry.partition })
  });
  if (!response.ok) throw await responseError(response);
  const reservation = await response.json();
  if (!reservation.record_id || !reservation.signature || !reservation.signature_data) {
    throw new Error("Reservierungsantwort enthält keine vollständige Identität.");
  }
  return reservation;
}

function queueEntrySaveState(entry) {
  if (entry.status === "auth_error") return SAVE_STATES.AUTH_ERROR;
  if (entry.status === "conflict") return SAVE_STATES.CONFLICT;
  if (entry.status === "validation_error") return SAVE_STATES.VALIDATION_ERROR;
  return SAVE_STATES.ERROR;
}

function applyReservationToCurrentEntry(entry, reservation) {
  if (entry.operation_id !== state.currentQueueOperationId) return;
  state.signatureSuggestionRequest += 1;
  state.currentDraft = {
    id: reservation.record_id,
    format: reservation.signature_data.format,
    nummer: reservation.signature_data.nummer,
    signature: reservation.signature_data
  };
  state.format = reservation.signature_data.format;
  state.finalizedCurrentDraft = true;
  state.queuedSnapshot = JSON.stringify(entry.snapshot);
  errors.innerHTML = "";
  updateSignatureOutput();
  setSaveState(SAVE_STATES.QUEUED);
}

function scheduleSafeQueueRecovery() {
  window.setTimeout(() => {
    resumeSafeQueueEntries().catch((error) => console.error("Sichere Queue-Wiederaufnahme fehlgeschlagen.", error));
  }, 0);
}

async function resumeSafeQueueEntries() {
  if (state.queueRecoveryRunning) return false;
  state.queueRecoveryRunning = true;
  await refreshQueueStatus();
  try {
    while (true) {
      const entries = await saveQueueStore.list();
      const first = entries[0];
      if (!first) return true;
      if (first.status === "reserving" && first.operation === "create" && !first.record_id && !first.signature) {
        try {
          const reserved = await saveQueueProcessor.reserve(first.operation_id, reserveQueuedCreate);
          applyReservationToCurrentEntry(reserved.entry, reserved.reservation);
        } catch (error) {
          return false;
        }
        continue;
      }
      if (first.status !== "queued") return false;
      if (!await saveQueueProcessor.process()) return false;
    }
  } finally {
    state.queueRecoveryRunning = false;
    await refreshQueueStatus();
  }
}

function normalizedJson(value) {
  if (Array.isArray(value)) return value.map(normalizedJson);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, normalizedJson(value[key])]));
  }
  return value;
}

function photoSnapshotFromServer(record) {
  const datierung = record.datierung || {};
  return {
    format: record.signatur?.format || null,
    erschliessung: record.erschliessung || {},
    korrespondenzstueck: Boolean(record.korrespondenzstueck),
    datierung: {
      jahr: datierung.jahr ?? null,
      monat: datierung.monat ?? null,
      tag: datierung.tag ?? null,
      anmerkung: datierung.anmerkung ?? null,
      original: datierung.original ?? null,
      original_typ: datierung.original_typ ?? null
    }
  };
}

function snapshotsEqual(left, right) {
  return JSON.stringify(normalizedJson(left)) === JSON.stringify(normalizedJson(right));
}

async function readQueueRecord(entry) {
  const response = await apiFetch(`/api/records/photos/${entry.record_id}`, {
    method: "GET",
    redirectOnAuth: false
  });
  if (!response.ok) throw await responseError(response);
  return response.json();
}

async function recoverUncertainUpdate(entry) {
  const checking = await saveQueueStore.update(entry.operation_id, {
    attempt_count: entry.attempt_count + 1,
    updated_at: new Date().toISOString()
  });
  try {
    const server = await readQueueRecord(checking);
    if (snapshotsEqual(checking.snapshot, photoSnapshotFromServer(server.record))) {
      await saveQueueProcessor.resolve(checking.operation_id, server);
      return true;
    }
    if (server.base_revision === checking.base_revision) {
      await saveQueueProcessor.requeue(checking.operation_id);
      return resumeSafeQueueEntries();
    }
    const conflict = new Error("Der Serverstand hat sich geändert; die lokale Fassung bleibt in der Warteschlange erhalten.");
    conflict.status = 409;
    conflict.userMessage = conflict.message;
    await saveQueueProcessor.fail(checking.operation_id, conflict);
    return false;
  } catch (error) {
    await saveQueueProcessor.fail(checking.operation_id, error);
    return false;
  }
}

async function retryFirstQueueEntry() {
  if (state.queueRecoveryRunning) return;
  const entry = (await saveQueueStore.list())[0];
  if (!entry) return;
  if (["conflict", "validation_error"].includes(entry.status)) return;

  state.queueRecoveryRunning = true;
  await refreshQueueStatus();
  try {
    if (entry.operation === "create") {
      if (entry.record_id && entry.signature) {
        await saveQueueProcessor.requeue(entry.operation_id);
      } else {
        const reserving = await saveQueueProcessor.requeue(entry.operation_id, "reserving");
        try {
          const reserved = await saveQueueProcessor.reserve(reserving.operation_id, reserveQueuedCreate);
          applyReservationToCurrentEntry(reserved.entry, reserved.reservation);
        } catch (error) {
          return;
        }
      }
    } else if (entry.status === "queued") {
      await saveQueueProcessor.requeue(entry.operation_id);
    } else {
      state.queueRecoveryRunning = false;
      await recoverUncertainUpdate(entry);
      return;
    }
  } finally {
    if (state.queueRecoveryRunning) {
      state.queueRecoveryRunning = false;
      await refreshQueueStatus();
    }
  }
  await resumeSafeQueueEntries();
}

function queuedSignatureData(entry) {
  const numberMatch = entry.signature?.match(/\.([0-9]+)$/);
  return entry.signature && numberMatch
    ? { ...buildSignature(entry.partition, Number(numberMatch[1]), "vergeben"), anzeige: entry.signature }
    : null;
}

function fillFormFromQueueSnapshot(entry) {
  state.format = entry.snapshot.format || entry.partition;
  fillFormFromRecord({
    erschliessung: entry.snapshot.erschliessung,
    korrespondenzstueck: entry.snapshot.korrespondenzstueck,
    datierung: entry.snapshot.datierung,
    signatur: { format: state.format }
  });
  state.currentQueueOperationId = entry.operation_id;
  state.queuedSnapshot = JSON.stringify(entry.snapshot);
  updateArchivisDate();
}

async function openFirstQueuedSnapshot() {
  const entry = (await saveQueueStore.list())[0];
  if (!entry) return;
  try {
    if (entry.operation === "update") {
      const server = await readQueueRecord(entry);
      applyLoadedRecord(server.record, server.base_revision);
      fillFormFromQueueSnapshot(entry);
    } else {
      startNewRecord({ skipConfirmation: true });
      fillFormFromQueueSnapshot(entry);
      const signature = queuedSignatureData(entry);
      if (signature) {
        state.currentDraft = {
          id: entry.record_id,
          format: entry.partition,
          nummer: signature.nummer,
          signature
        };
        state.finalizedCurrentDraft = true;
      }
    }
    updateSignatureOutput();
    const failedState = queueEntrySaveState(entry);
    setSaveState(failedState);
    showSaveFailure(failedState, entry.last_error?.message);
  } catch (error) {
    const failed = await saveQueueProcessor.fail(entry.operation_id, error);
    showSaveFailure(queueEntrySaveState(failed), error.userMessage);
  }
}

async function discardFirstQueueEntry() {
  const entry = (await saveQueueStore.list())[0];
  if (!entry) return;
  const confirmed = window.confirm(
    "Die lokal gesicherte Speicherung wirklich verwerfen? Dieser Queue-Snapshot kann danach nicht wiederhergestellt werden."
  );
  if (!confirmed) return;
  await saveQueueStore.remove(entry.operation_id);
  if (state.currentQueueOperationId === entry.operation_id) {
    state.currentQueueOperationId = null;
    state.queuedSnapshot = null;
    if (entry.operation === "create") {
      state.currentDraft = null;
      state.finalizedCurrentDraft = false;
      updateSignatureOutput();
      setSaveState(SAVE_STATES.DIRTY);
    } else {
      updateDirtyState();
    }
  }
  errors.innerHTML = "<p>Die lokale Speicherung wurde ausdrücklich verworfen.</p>";
  await refreshQueueStatus();
  scheduleSafeQueueRecovery();
}

async function handleQueuedSaveSuccess(entry, saved) {
  if (entry.operation_id !== state.currentQueueOperationId) return;
  if (entry.operation === "update" && state.editingRecord?.id !== entry.record_id) return;
  if (entry.operation === "create" && state.currentDraft?.id !== entry.record_id) return;

  state.editingRecord = saved.record;
  state.baseRevision = saved.base_revision;
  state.currentDraft = {
    id: saved.record.id,
    format: saved.record.signatur.format,
    nummer: saved.record.signatur.nummer,
    signature: saved.record.signatur
  };
  state.format = saved.record.signatur.format;
  state.mode = "edit";
  state.finalizedCurrentDraft = false;
  state.serverSnapshot = JSON.stringify(entry.snapshot);
  state.currentQueueOperationId = null;
  state.queuedSnapshot = null;
  state.maySaveEditingRecord = true;
  document.querySelector("#mode-new").classList.remove("active");
  document.querySelector("#mode-edit").classList.add("active");
  recordBrowser.hidden = false;
  const url = new URL(window.location.href);
  url.searchParams.set("record", saved.record.id);
  window.history.replaceState({}, "", url);
  downloadButton.disabled = true;
  errors.innerHTML = "";
  updateSignatureOutput();
  updateRecordNavigation();
  setSaveState(hasUnsavedChanges() ? SAVE_STATES.DIRTY : SAVE_STATES.CLEAN);
  await refreshRecords().catch((error) => console.error("Datensatzliste konnte nach dem Speichern nicht aktualisiert werden.", error));
}

async function handleQueuedSaveError(entry, error) {
  if (entry.operation_id !== state.currentQueueOperationId) return;
  const failedState = failureSaveState(error.status);
  setSaveState(failedState);
  showSaveFailure(failedState, error.userMessage);
  console.error("Vorgemerkter Datensatz konnte nicht gespeichert werden.", error);
}

function scheduleQueueProcessing() {
  window.setTimeout(() => {
    saveQueueProcessor.process().catch((error) => console.error("Speicherwarteschlange konnte nicht verarbeitet werden.", error));
  }, 0);
}

function newOperationId() {
  return window.crypto.randomUUID();
}

function failureSaveState(status) {
  if (status === 401 || status === 403) return SAVE_STATES.AUTH_ERROR;
  if (status === 409) return SAVE_STATES.CONFLICT;
  if (status === 422) return SAVE_STATES.VALIDATION_ERROR;
  return SAVE_STATES.ERROR;
}

function showSaveFailure(saveState, detail = null) {
  const messages = [SAVE_FAILURE_MESSAGES[saveState]];
  if (
    (saveState === SAVE_STATES.CONFLICT || saveState === SAVE_STATES.VALIDATION_ERROR) &&
    detail
  ) {
    messages.push(...(Array.isArray(detail) ? detail : [detail]));
  }
  showErrors(messages);
}

async function finalizeRecord() {
  const editingExistingRecord = state.mode === "edit" && state.editingRecord;
  if (state.currentQueueOperationId || isSaveInProgress() || (!editingExistingRecord && state.finalizedCurrentDraft)) return;
  if (editingExistingRecord && !hasUnsavedChanges()) return;
  const dateReview = reviewVisibleDate({ show: true });
  if (dateReview.blocking) {
    setSaveState(SAVE_STATES.VALIDATION_ERROR);
    return;
  }
  const record = readRecord();
  const messages = validate(record);
  showErrors(messages);
  if (messages.length) {
    setSaveState(SAVE_STATES.VALIDATION_ERROR);
    return;
  }
  if (state.backendMode) {
    const workingRecord = readWorkingRecord();
    const operationId = newOperationId();
    const entry = createSaveQueueEntry({
      operationId,
      operation: editingExistingRecord ? "update" : "create",
      recordId: editingExistingRecord ? state.editingRecord.id : null,
      partition: state.format,
      baseRevision: editingExistingRecord ? state.baseRevision : null,
      snapshot: workingRecord,
      status: editingExistingRecord ? "queued" : "reserving"
    });
    try {
      await saveQueueStore.put(entry);
      state.currentQueueOperationId = operationId;
      state.queuedSnapshot = JSON.stringify(entry.snapshot);
      await refreshQueueStatus();
      if (editingExistingRecord) {
        setSaveState(SAVE_STATES.QUEUED);
        scheduleQueueProcessing();
        return;
      }

      setSaveState(SAVE_STATES.RESERVING);
      const reserved = await saveQueueProcessor.reserve(operationId, reserveQueuedCreate);
      const reservation = reserved.reservation;
      if (state.currentQueueOperationId !== operationId) {
        scheduleQueueProcessing();
        return;
      }
      state.signatureSuggestionRequest += 1;
      state.currentDraft = {
        id: reservation.record_id,
        format: reservation.signature_data.format,
        nummer: reservation.signature_data.nummer,
        signature: reservation.signature_data
      };
      state.format = reservation.signature_data.format;
      state.finalizedCurrentDraft = true;
      errors.innerHTML = "";
      updateSignatureOutput();
      setSaveState(SAVE_STATES.QUEUED);
      scheduleQueueProcessing();
    } catch (error) {
      const failedState = failureSaveState(error.status);
      setSaveState(failedState);
      showSaveFailure(failedState, error.userMessage);
      console.error("Datensatz konnte nicht lokal vorgemerkt oder reserviert werden.", error);
    }
    return;
  }
  record.signatur = buildSignature(record.signatur.format, record.signatur.nummer, "vergeben");
  state.currentDraft.signature = record.signatur;
  state.generatedMarkdown = toMarkdown(record);
  state.generatedFilename = `${record.id}.md`;
  preview.value = state.generatedMarkdown;
  downloadButton.disabled = false;
  rememberLocalRecord(record);
  state.finalizedCurrentDraft = true;
  generateButton.disabled = true;
  finalizeButton.disabled = true;
  errors.innerHTML = "<p>Datensatz wurde lokal gespeichert. Mit „Neuer Datensatz“ kann weitergearbeitet werden.</p>";
  updateSignatureOutput();
}

function rememberLocalRecord(record) {
  if (state.backendMode) return;
  const minimal = {
    id: record.id,
    format: record.signatur.format,
    nummer: record.signatur.nummer
  };
  if (state.inventory.some((item) => item.id === minimal.id)) return;
  state.inventory.push(minimal);
  const localRecords = loadLocalRecords();
  localRecords.push(minimal);
  localStorage.setItem(LOCAL_RECORDS_KEY, JSON.stringify(localRecords));
}

function loadLocalRecords() {
  try {
    const parsed = JSON.parse(localStorage.getItem(LOCAL_RECORDS_KEY) || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function startNewRecord(options = {}) {
  if (!options.skipConfirmation && !confirmDiscardUnsavedChanges()) return;
  const selectedFormat = state.format;
  state.signatureSuggestionRequest += 1;
  form.reset();
  document.querySelector("#personen-list").innerHTML = "";
  addPersonRow();
  if (selectedFormat) {
    const input = document.querySelector(`input[name='format'][value='${selectedFormat}']`);
    input.checked = true;
    state.format = selectedFormat;
  }
  state.generatedMarkdown = "";
  state.currentDraft = null;
  state.signatureSuggestion = null;
  state.signatureManuallyEdited = false;
  state.editingRecord = null;
  state.baseRevision = null;
  state.serverSnapshot = null;
  state.queuedSnapshot = null;
  state.currentQueueOperationId = null;
  state.maySaveEditingRecord = false;
  state.mode = "new";
  document.querySelector("#mode-new").classList.add("active");
  document.querySelector("#mode-edit").classList.remove("active");
  recordBrowser.hidden = true;
  [recordNavTop, recordNavBottom].forEach((nav) => {
    nav.hidden = true;
  });
  state.finalizedCurrentDraft = false;
  preview.value = "";
  downloadButton.disabled = true;
  generateButton.disabled = false;
  finalizeButton.disabled = true;
  errors.innerHTML = "";
  form.dataset.dirty = "false";
  setSaveState(SAVE_STATES.DIRTY);
  const url = new URL(window.location.href);
  url.searchParams.delete("record");
  window.history.replaceState({}, "", url);
  applyPreset({ onlyEmpty: false });
  updateSignatureOutput();
  if (state.format) refreshSignatureSuggestion(state.format);
  updateArchivisDate();
}

function resetLocalSessionRecords() {
  const confirmed = window.confirm(
    "Lokale Pilot-Datensätze dieser Sitzung wirklich löschen? Aktive Vorbelegung und UI-Profil bleiben erhalten."
  );
  if (!confirmed) return;
  localStorage.removeItem(LOCAL_RECORDS_KEY);
  state.inventory = state.backendMode ? state.inventory : [...config.existing_records];
  state.currentDraft = null;
  state.finalizedCurrentDraft = false;
  state.generatedMarkdown = "";
  preview.value = "";
  downloadButton.disabled = true;
  generateButton.disabled = false;
  finalizeButton.disabled = true;
  errors.innerHTML = "<p>Lokale Sitzungsdaten wurden zurückgesetzt. Vorbelegung und UI-Profil bleiben erhalten.</p>";
  updateSignatureOutput();
}

function downloadMarkdown() {
  const blob = new Blob([state.generatedMarkdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = state.generatedFilename;
  link.click();
  URL.revokeObjectURL(url);
}

function buildPresetEditor() {
  presetFieldList.innerHTML = "";
  editablePresetFields().forEach((field) => {
    const definition = fieldMap[field];
    if (!definition) return;
    const id = `preset-${field}`;
    const wrapper = document.createElement("label");
    wrapper.className = "preset-choice";
    wrapper.innerHTML = `<input type="checkbox" id="${id}" value="${field}"><span>${definition.label}</span>`;
    presetFieldList.append(wrapper);
  });
}

function editableFieldsForProfile(profile) {
  return config.ui_profiles?.[profile]?.editable_fields || [];
}

function editablePresetFields() {
  const profile = localStorage.getItem(PROFILE_KEY) || "standard";
  const editable = new Set(editableFieldsForProfile(profile));
  return config.presettable_fields.filter((field) => editable.has(field));
}

function loadPreset() {
  try {
    const parsed = JSON.parse(localStorage.getItem(PRESET_KEY) || "null");
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

function savePreset(preset) {
  localStorage.setItem(PRESET_KEY, JSON.stringify(preset));
  applyPreset({ onlyEmpty: true });
}

function syncPresetEditor() {
  const preset = loadPreset() || { values: {} };
  presetFieldList.querySelectorAll("input[type='checkbox']").forEach((checkbox) => {
    checkbox.checked = Object.prototype.hasOwnProperty.call(preset.values, checkbox.value);
  });
}

function readPresetEditor() {
  const current = readCurrentValuesAsPreset({ includeEmpty: true });
  const values = {};
  presetFieldList.querySelectorAll("input[type='checkbox']:checked").forEach((checkbox) => {
    if (Object.prototype.hasOwnProperty.call(current.values, checkbox.value)) {
      values[checkbox.value] = current.values[checkbox.value];
    }
  });
  return { values };
}

function readCurrentValuesAsPreset({ includeEmpty }) {
  const values = {};
  editablePresetFields().forEach((field) => {
    const definition = fieldMap[field];
    if (!definition) return;
    if (definition.kind === "date") {
      const value = readDatierung();
      if (includeEmpty || value.jahr || value.monat || value.tag || value.bis_jahr || value.bis_monat || value.bis_tag || value.anmerkung || value.original) values[field] = value;
    } else if (definition.kind === "persons") {
      const value = readPersons();
      if (includeEmpty || value.length) values[field] = value;
    } else if (definition.kind === "list") {
      const value = splitList(document.querySelector(definition.selector).value);
      if (includeEmpty || value.length) values[field] = value;
    } else {
      const value = document.querySelector(definition.selector).value.trim() || null;
      if (includeEmpty || value) values[field] = value;
    }
  });
  return { values };
}

function applyPreset({ onlyEmpty }) {
  const preset = loadPreset();
  if (!preset || !preset.values || !Object.keys(preset.values).length) {
    presetStatus.textContent = "Keine aktive Vorbelegung.";
    return;
  }
  Object.entries(preset.values).forEach(([field, value]) => {
    const definition = fieldMap[field];
    if (!isFieldEditable(field)) return;
    if (!definition) return;
    if (definition.kind === "date") {
      applyDatePreset(value, onlyEmpty);
    } else if (definition.kind === "persons") {
      applyPersonsPreset(value, onlyEmpty);
    } else if (definition.kind === "list") {
      const element = document.querySelector(definition.selector);
      if (!onlyEmpty || !element.value.trim()) element.value = joinList(value);
    } else {
      const element = document.querySelector(definition.selector);
      if (!onlyEmpty || !element.value.trim()) element.value = value || "";
    }
  });
  presetStatus.textContent = `Aktive Vorbelegung: ${Object.keys(preset.values).map((field) => fieldMap[field]?.label || field).join(", ")}`;
}

function applyDatePreset(value, onlyEmpty) {
  const dateValue = DateTextFields.format(value || {});
  const toValue = DateTextFields.format({ jahr: value?.bis_jahr, monat: value?.bis_monat, tag: value?.bis_tag });
  const dateInput = document.querySelector("#datierung-von");
  const toInput = document.querySelector("#datierung-bis");
  const noteInput = document.querySelector("#datierung-hinweis");
  const originalInput = document.querySelector("#original-datum");
  if (!onlyEmpty || !dateInput.value.trim()) dateInput.value = dateValue;
  if (!onlyEmpty || !toInput.value.trim()) toInput.value = toValue;
  if (!onlyEmpty || !noteInput.value.trim()) noteInput.value = value?.anmerkung ?? "";
  if (!onlyEmpty || !originalInput.value.trim()) originalInput.value = value?.original ?? "";
  updateArchivisDate();
}

function formatSimpleDate(value) {
  if (!value?.jahr) return "";
  if (!value.monat) return String(value.jahr);
  if (!value.tag) return `${String(value.monat).padStart(2, "0")}.${value.jahr}`;
  return `${String(value.tag).padStart(2, "0")}.${String(value.monat).padStart(2, "0")}.${value.jahr}`;
}

function applyPersonsPreset(value, onlyEmpty) {
  const hasExisting = readPersons().length > 0;
  if (onlyEmpty && hasExisting) return;
  const list = document.querySelector("#personen-list");
  list.innerHTML = "";
  const persons = Array.isArray(value) && value.length ? value : [{ name: "", hinweis: "" }];
  persons.forEach((person) => addPersonRow(person));
}

function setProfile(profile) {
  if (!config.ui_profiles?.[profile]) profile = "standard";
  document.body.classList.toggle("barrierearm", profile === "barrierearm");
  document.querySelectorAll(".profile-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.profile === profile);
  });
  localStorage.setItem(PROFILE_KEY, profile);
  applyFieldPermissions(profile);
  applyTechnicalVisibility(profile);
  buildPresetEditor();
  syncPresetEditor();
}

function applyTechnicalVisibility(profile) {
  const isTechnicalProfile = Boolean(config.ui_profiles?.[profile]?.technical_preview);
  document.querySelectorAll(".technical-panel, .technical-date-field").forEach((element) => {
    element.hidden = !isTechnicalProfile;
    element.querySelectorAll?.("input, textarea, button").forEach((control) => {
      control.disabled = !isTechnicalProfile;
    });
  });
  generateButton.hidden = !isTechnicalProfile;
  if (!isTechnicalProfile) {
    generateButton.disabled = true;
    downloadButton.disabled = true;
  } else if (!state.finalizedCurrentDraft) {
    generateButton.disabled = false;
  }
}

function applyFieldPermissions(profile) {
  const editable = new Set(editableFieldsForProfile(profile));
  document.querySelectorAll("[data-field-wrapper]").forEach((wrapper) => {
    const field = wrapper.dataset.fieldWrapper;
    const visible = editable.has(field);
    wrapper.hidden = !visible;
    wrapper.querySelectorAll("input, textarea, select, button").forEach((control) => {
      control.disabled = !visible;
    });
  });
}

init().catch((error) => {
  errors.textContent = error.message;
});
