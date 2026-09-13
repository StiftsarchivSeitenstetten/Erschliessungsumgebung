import { FormRenderer } from "../generic/form-renderer.js";
import { FormState } from "../generic/form-state.js";

const params = new URLSearchParams(window.location.search);
const moduleKey = params.get("module");
const title = document.querySelector("#module-title");
const description = document.querySelector("#module-description");
const recordList = document.querySelector("#record-list");
const preview = document.querySelector("#record-preview");
const errorOutput = document.querySelector("#module-error");
const payloadPreview = document.querySelector("#payload-preview");
const toggleEdit = document.querySelector("#toggle-edit");
const discardChanges = document.querySelector("#discard-changes");
const showPayload = document.querySelector("#show-payload");
let mode = "read";
let currentDescriptor = null;
let currentFormState = null;
let renderer = new FormRenderer({ mode });

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

function renderRecords(moduleDescriptor, records) {
  recordList.innerHTML = "";
  if (!records.length) {
    recordList.textContent = "Keine Datensätze vorhanden.";
    return;
  }
  records.forEach((record) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "record-list-item";
    button.textContent = Object.values(record.values || {}).filter(Boolean).join(" · ") || record.record_id;
    button.addEventListener("click", () => openRecord(moduleDescriptor, record.record_id));
    recordList.append(button);
  });
}

async function openRecord(moduleDescriptor, recordId) {
  const data = await apiFetch(`/api/modules/${encodeURIComponent(moduleDescriptor.module)}/records/${encodeURIComponent(recordId)}`);
  currentDescriptor = moduleDescriptor;
  currentFormState = new FormState(moduleDescriptor, data.record);
  mode = "read";
  renderer = new FormRenderer({ mode });
  payloadPreview.textContent = "";
  toggleEdit.textContent = "Edit-Modus aktivieren";
  discardChanges.disabled = true;
  renderCurrentRecord();
}

function renderCurrentRecord() {
  preview.innerHTML = "";
  preview.append(renderer.render(currentDescriptor, currentFormState));
}

function syncStateFromForm() {
  if (mode === "edit" && currentFormState) {
    renderer.readIntoState(preview, currentFormState);
  }
}

function updatePayloadPreview() {
  syncStateFromForm();
  if (!currentFormState) return;
  payloadPreview.textContent = JSON.stringify({
    dirty: currentFormState.isDirty(),
    changed_paths: currentFormState.changedPaths(),
    validation_errors: currentFormState.validate(),
    payload: currentFormState.buildPayload()
  }, null, 2);
  discardChanges.disabled = !currentFormState.isDirty();
}

async function init() {
  if (!moduleKey) throw new Error("Kein Modul ausgewählt.");
  const moduleDescriptor = await apiFetch(`/api/modules/${encodeURIComponent(moduleKey)}`);
  title.textContent = moduleDescriptor.label;
  description.textContent = moduleDescriptor.description || "";
  const listing = await apiFetch(`/api/modules/${encodeURIComponent(moduleKey)}/records`);
  renderRecords(moduleDescriptor, listing.records || []);
  if (listing.records?.[0]) await openRecord(moduleDescriptor, listing.records[0].record_id);
}

init().catch((error) => {
  errorOutput.textContent = error.message;
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
  renderCurrentRecord();
  updatePayloadPreview();
});

showPayload.addEventListener("click", updatePayloadPreview);
