const PRESET_KEY = "erschliessung.papierabzuege.activePreset.v2";
const PROFILE_KEY = "erschliessung.papierabzuege.profile";
const LOCAL_RECORDS_KEY = "erschliessung.papierabzuege.localRecords";

let config = null;
const state = {
  format: null,
  generatedMarkdown: "",
  generatedFilename: "foto-000004.md",
  inventory: [],
  currentDraft: null,
  finalizedCurrentDraft: false
};

const form = document.querySelector("#record-form");
const errors = document.querySelector("#errors");
const preview = document.querySelector("#preview");
const generateButton = document.querySelector("#generate");
const downloadButton = document.querySelector("#download");
const finalizeButton = document.querySelector("#finalize");
const numberOutput = document.querySelector("#number-output");
const signatureOutput = document.querySelector("#signature-output");
const archivisDateOutput = document.querySelector("#archivis-date");
const presetStatus = document.querySelector("#preset-status");
const presetEditor = document.querySelector("#preset-editor");
const presetFieldList = document.querySelector("#preset-field-list");

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
  config = await loadConfig();
  state.inventory = [...config.existing_records, ...loadLocalRecords()];
  buildFormatOptions();
  addPersonRow();
  bindEvents();
  setProfile(localStorage.getItem(PROFILE_KEY) || "standard");
  applyPreset({ onlyEmpty: true });
  updateSignatureOutput();
  updateArchivisDate();
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
      updateSignatureOutput();
    });
  });

  document.querySelectorAll(".profile-button").forEach((button) => {
    button.addEventListener("click", () => setProfile(button.dataset.profile));
  });

  document.querySelector("#datierung-einfach").addEventListener("input", updateArchivisDate);

  document.querySelector("#generate").addEventListener("click", generateRecord);
  finalizeButton.addEventListener("click", finalizeRecord);
  document.querySelector("#new-record").addEventListener("click", startNewRecord);
  document.querySelector("#reset-session").addEventListener("click", resetLocalSessionRecords);
  document.querySelector("#add-person").addEventListener("click", () => addPersonRow());
  downloadButton.addEventListener("click", downloadMarkdown);

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
    !state.finalizedCurrentDraft &&
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
  const parsed = parseSimpleDate(document.querySelector("#datierung-einfach").value);
  return {
    jahr: parsed.jahr,
    monat: parsed.monat,
    tag: parsed.tag,
    anmerkung: document.querySelector("#datierung-anmerkung").value.trim() || null,
    original: document.querySelector("#original-datum").value.trim() || null,
    original_typ: document.querySelector("#original-datum").value.trim() ? "importierte_arbeitsdaten" : null
  };
}

function readRecord() {
  const draft = state.format ? currentDraftForFormat(state.format) : null;
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
  if (!record.signatur) messages.push("Bitte ein Format wählen.");
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
  if (state.finalizedCurrentDraft && state.currentDraft) {
    numberOutput.textContent = String(state.currentDraft.nummer);
    signatureOutput.textContent = state.currentDraft.signature.anzeige;
    return;
  }
  if (!state.format) {
    numberOutput.textContent = "-";
    signatureOutput.textContent = "Bitte Format wählen";
    finalizeButton.disabled = true;
    return;
  }
  const number = nextNumber(state.format);
  numberOutput.textContent = String(number);
  signatureOutput.textContent = buildSignature(state.format, number).anzeige;
  finalizeButton.disabled = state.finalizedCurrentDraft;
}

function updateArchivisDate() {
  const value = archivisDateValue(readDatierung());
  archivisDateOutput.textContent = value || "-";
}

function generateRecord() {
  const record = readRecord();
  const messages = validate(record);
  showErrors(messages);
  if (messages.length) return;
  state.generatedMarkdown = toMarkdown(record);
  state.generatedFilename = `${record.id}.md`;
  preview.value = state.generatedMarkdown;
  downloadButton.disabled = true;
  finalizeButton.disabled = state.finalizedCurrentDraft;
}

function finalizeRecord() {
  if (state.finalizedCurrentDraft) return;
  const record = readRecord();
  const messages = validate(record);
  showErrors(messages);
  if (messages.length) return;
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

function startNewRecord() {
  const selectedFormat = state.format;
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
  state.finalizedCurrentDraft = false;
  preview.value = "";
  downloadButton.disabled = true;
  generateButton.disabled = false;
  finalizeButton.disabled = true;
  errors.innerHTML = "";
  applyPreset({ onlyEmpty: false });
  updateSignatureOutput();
  updateArchivisDate();
}

function resetLocalSessionRecords() {
  const confirmed = window.confirm(
    "Lokale Pilot-Datensätze dieser Sitzung wirklich löschen? Aktive Vorbelegung und UI-Profil bleiben erhalten."
  );
  if (!confirmed) return;
  localStorage.removeItem(LOCAL_RECORDS_KEY);
  state.inventory = [...config.existing_records];
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
      if (includeEmpty || value.jahr || value.monat || value.tag || value.anmerkung || value.original) values[field] = value;
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
  const dateValue = formatSimpleDate(value || {});
  const dateInput = document.querySelector("#datierung-einfach");
  const noteInput = document.querySelector("#datierung-anmerkung");
  const originalInput = document.querySelector("#original-datum");
  if (!onlyEmpty || !dateInput.value.trim()) dateInput.value = dateValue;
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
