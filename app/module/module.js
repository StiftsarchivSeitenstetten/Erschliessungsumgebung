import { FormRenderer } from "../generic/form-renderer.js?v=date-roundtrip-1";
import { FormState } from "../generic/form-state.js";
import { ResultState, renderRecordList } from "../generic/record-list.js?v=navigation-1";
import { RecordUpdate } from "../generic/record-update.js?v=update-2";

const params = new URLSearchParams(window.location.search);
const moduleKey = params.get("module");
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
let csrfCookieName = null;
let saveInProgress = false;

function updateSaveButton() {
  $("#save-record").disabled = saveInProgress || !currentUpdate?.canSave(mode);
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
  if (!currentFormState?.isDirty()) return true;
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
  $("#record-position").textContent = opened ? `${state.recordId} · ${state.position < 0 ? "Außerhalb der Trefferliste" : `${state.position + 1} / ${state.records.length}`}` : "";
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
  $("#save-status").textContent = "";
  state.recordId = recordId;
  state.lastRecordId = recordId;
  mode = "read";
  renderer = new FormRenderer({ mode });
  payloadPreview.textContent = "";
  toggleEdit.textContent = "Edit-Modus aktivieren";
  discardChanges.disabled = true;
  renderCurrentRecord();
  showView();
  updateSaveButton();
  if (push) updateUrl();
}
function renderCurrentRecord() {
  preview.replaceChildren(renderer.render(currentDescriptor, currentFormState));
}
function updatePayloadPreview() {
  syncStateFromForm();
  if (!currentFormState) return;
  payloadPreview.textContent = JSON.stringify({ dirty: currentFormState.isDirty(), changed_paths: currentFormState.changedPaths(),
    validation_errors: currentFormState.validate(), payload: currentFormState.buildPayload() }, null, 2);
  discardChanges.disabled = !currentFormState.isDirty();
  updateSaveButton();
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
  else { currentFormState = null; currentUpdate = null; }
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
  csrfCookieName = (await apiFetch("/api/auth/me")).csrf_cookie_name;
  currentDescriptor = await apiFetch(`/api/modules/${encodeURIComponent(moduleKey)}`);
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
  if (recordId) await openRecord(currentDescriptor, recordId, false);
}
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
  state.recordId = null;
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
    location.href = $("#change-module").href;
  }
});
window.addEventListener("beforeunload", event => {
  syncStateFromForm();
  if (currentFormState?.isDirty() || saveInProgress) { event.preventDefault(); event.returnValue = ""; }
});
window.addEventListener("popstate", async () => {
  if (!await allowNavigation()) { history.pushState(null, "", acceptedUrl); return; }
  run(async () => {
    const query = new URLSearchParams(location.search);
    const recordId = query.get("record");
    if (query.get("module") !== moduleKey) { location.reload(); return; }
    if (await loadResults(queryFromUrl(), false)) {
      if (recordId) await openRecord(currentDescriptor, recordId, false);
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
discardChanges.addEventListener("click", () => {
  if (!currentFormState) return;
  currentFormState.discardChanges();
  $("#save-status").textContent = "";
  $("#module-error").textContent = "";
  renderCurrentRecord();
  updatePayloadPreview();
});
for (const event of ["input", "change", "click"]) preview.addEventListener(event, () => {
  if (currentUpdate?.saving) return;
  updatePayloadPreview();
});
$("#save-record").addEventListener("click", async () => {
  if (saveInProgress) return;
  $("#module-error").textContent = "";
  try {
    syncStateFromForm();
    if (!currentUpdate?.canSave(mode)) return;
    const cookie = document.cookie.split(";").map(part => part.trim()).find(part => part.startsWith(`${csrfCookieName}=`));
    if (!cookie) throw new Error("Anmeldung konnte nicht bestätigt werden. Ihre Änderungen bleiben erhalten.");
    saveInProgress = true;
    const saving = currentUpdate.save(mode, decodeURIComponent(cookie.slice(csrfCookieName.length + 1)));
    updateSaveButton();
    $("#detail-panel").inert = true;
    $("#save-status").textContent = "Speichert …";
    await saving;
    renderCurrentRecord();
    updatePayloadPreview();
    $("#save-status").textContent = "Gespeichert.";
    try {
      await loadResults({q:state.q, lookupField:state.lookupField, lookupValue:state.lookupValue}, false, true);
    } catch {
      state.records = [];
      renderRecordList($("#record-list"), currentDescriptor, [], () => {});
      showView();
      $("#result-count").textContent = "Trefferliste nicht aktuell.";
      $("#save-status").textContent = "Gespeichert. Trefferliste konnte nicht aktualisiert werden; bitte die Suche erneut ausführen.";
    }
  } catch (error) {
    $("#save-status").textContent = "Nicht als gespeichert bestätigt.";
    $("#module-error").textContent = error.message || "Netzwerkfehler. Ihre Änderungen bleiben erhalten.";
  } finally {
    saveInProgress = false;
    $("#detail-panel").inert = false;
    updateSaveButton();
  }
});
$("#show-payload").addEventListener("click", updatePayloadPreview);
run(init);
