import { FormRenderer } from "../generic/form-renderer.js";

const params = new URLSearchParams(window.location.search);
const moduleKey = params.get("module");
const title = document.querySelector("#module-title");
const description = document.querySelector("#module-description");
const recordList = document.querySelector("#record-list");
const preview = document.querySelector("#record-preview");
const errorOutput = document.querySelector("#module-error");
const renderer = new FormRenderer({ readOnly: true });

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
  preview.innerHTML = "";
  preview.append(renderer.render(moduleDescriptor, data.record));
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
