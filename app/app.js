const PRESET_KEY = "erschliessung.papierabzuege.activePreset.v2";
const PROFILE_KEY = "erschliessung.papierabzuege.profile";
const LOCAL_RECORDS_KEY = "erschliessung.papierabzuege.localRecords";

let config = null;
const state = {
  format: null,
  generatedMarkdown: "",
  generatedFilename: "foto-000004.md",
  inventory: []
};

const form = document.querySelector("#record-form");
const errors = document.querySelector("#errors");
const preview = document.querySelector("#preview");
const downloadButton = document.querySelector("#download");
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
  dargestellte_personen: { label: "Dargestellte Personen", kind: "list", selector: "#personen" },
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
  buildPresetEditor();
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

  ["jahr", "monat", "tag"].forEach((id) => {
    document.querySelector(`#${id}`).addEventListener("input", updateArchivisDate);
  });

  document.querySelector("#generate").addEventListener("click", generateRecord);
  document.querySelector("#new-record").addEventListener("click", startNewRecord);
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

function readDatierung() {
  return {
    jahr: parseIntegerField("jahr"),
    monat: parseIntegerField("monat"),
    tag: parseIntegerField("tag"),
    original: document.querySelector("#original-datum").value.trim() || null,
    original_typ: document.querySelector("#original-datum").value.trim() ? "importierte_arbeitsdaten" : null
  };
}

function readRecord() {
  const number = state.format ? nextNumber(state.format) : null;
  const id = nextId();
  return {
    id,
    schema_version: 1,
    datensatz_typ: config.datensatz_typ,
    modul: config.module_id,
    signatur: state.format ? buildSignature(state.format, number) : null,
    erschliessung: {
      titel: readScalar("titel"),
      beschriftung: readScalar("beschriftung"),
      beschreibung: readScalar("beschreibung"),
      dargestellte_personen: splitList(document.querySelector("#personen").value).map((name) => ({ name, hinweis: null })),
      herkunft: readScalar("herkunft"),
      sammler: readScalar("sammler"),
      fotograf: readScalar("fotograf"),
      rechteinhaber: readScalar("rechteinhaber"),
      orte: splitList(document.querySelector("#orte").value),
      schlagworte: splitList(document.querySelector("#schlagworte").value),
      altsignaturen: splitList(document.querySelector("#altsignaturen").value),
      interne_bemerkung: readScalar("interne_bemerkung")
    },
    datierung: readDatierung(),
    redaktion: { stufe: config.defaults.redaktion_stufe },
    bearbeitung: { status: config.defaults.bearbeitung_status },
    publikation: { status: config.defaults.publikation_status },
    technik: { quelle: "lokaler_webpilot", erstellt_am: null, geaendert_am: null }
  };
}

function readScalar(field) {
  const definition = fieldMap[field];
  const value = document.querySelector(definition.selector).value.trim();
  return value || null;
}

function validate(record) {
  const messages = [];
  if (!record.signatur) messages.push("Bitte ein Format wählen.");
  if (record.datierung.jahr !== null && (Number.isNaN(record.datierung.jahr) || record.datierung.jahr < 1 || record.datierung.jahr > 9999)) {
    messages.push("Das Jahr muss eine Zahl zwischen 1 und 9999 sein.");
  }
  if (record.datierung.monat !== null && (Number.isNaN(record.datierung.monat) || record.datierung.monat < 1 || record.datierung.monat > 12)) {
    messages.push("Der Monat muss leer oder eine Zahl zwischen 1 und 12 sein.");
  }
  if (record.datierung.tag !== null && (Number.isNaN(record.datierung.tag) || record.datierung.tag < 1 || record.datierung.tag > 31)) {
    messages.push("Der Tag muss leer oder eine Zahl zwischen 1 und 31 sein.");
  }
  if (record.datierung.monat !== null && record.datierung.jahr === null) {
    messages.push("Ein Monat darf nicht ohne Jahr erfasst werden.");
  }
  if (record.datierung.tag !== null && record.datierung.monat === null) {
    messages.push("Ein Tag darf nicht ohne Monat erfasst werden.");
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

function toMarkdown(record) {
  const e = record.erschliessung;
  const d = record.datierung;
  const s = record.signatur;
  return `---\nschema_version: 1\nid: ${record.id}\ndatensatz_typ: ${record.datensatz_typ}\nmodul: ${record.modul}\nsignatur:\n  bestand: ${yamlScalar(s.bestand)}\n  objektgruppe: ${yamlScalar(s.objektgruppe)}\n  format: ${yamlScalar(s.format)}\n  nummer: ${s.nummer}\n  anzeige: ${yamlScalar(s.anzeige)}\n  status: ${s.status}\nerschliessung:\n  titel: ${yamlScalar(e.titel)}\n  beschriftung: ${yamlScalar(e.beschriftung)}\n  beschreibung: ${yamlScalar(e.beschreibung)}\n  dargestellte_personen: ${yamlPersonList(e.dargestellte_personen)}\n  herkunft: ${yamlScalar(e.herkunft)}\n  sammler: ${yamlScalar(e.sammler)}\n  fotograf: ${yamlScalar(e.fotograf)}\n  rechteinhaber: ${yamlScalar(e.rechteinhaber)}\n  orte: ${yamlList(e.orte, "    ")}\n  schlagworte: ${yamlList(e.schlagworte, "    ")}\n  altsignaturen: ${yamlList(e.altsignaturen, "    ")}\n  interne_bemerkung: ${yamlScalar(e.interne_bemerkung)}\ndatierung:\n  jahr: ${d.jahr ?? "null"}\n  monat: ${d.monat ?? "null"}\n  tag: ${d.tag ?? "null"}\n  original: ${yamlScalar(d.original)}\n  original_typ: ${yamlScalar(d.original_typ)}\nredaktion:\n  stufe: ${record.redaktion.stufe}\nbearbeitung:\n  status: ${record.bearbeitung.status}\npublikation:\n  status: ${record.publikation.status}\ntechnik:\n  quelle: ${yamlScalar(record.technik.quelle)}\n  erstellt_am: null\n  geaendert_am: null\n---\n`;
}

function showErrors(messages) {
  if (!messages.length) {
    errors.innerHTML = "";
    return;
  }
  errors.innerHTML = `<p>Bitte prüfen:</p><ul>${messages.map((message) => `<li>${message}</li>`).join("")}</ul>`;
}

function updateSignatureOutput() {
  if (!state.format) {
    numberOutput.textContent = "-";
    signatureOutput.textContent = "Bitte Format wählen";
    return;
  }
  const number = nextNumber(state.format);
  numberOutput.textContent = String(number);
  signatureOutput.textContent = buildSignature(state.format, number).anzeige;
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
  downloadButton.disabled = false;
  rememberLocalRecord(record);
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
  if (selectedFormat) {
    const input = document.querySelector(`input[name='format'][value='${selectedFormat}']`);
    input.checked = true;
    state.format = selectedFormat;
  }
  state.generatedMarkdown = "";
  preview.value = "";
  downloadButton.disabled = true;
  errors.innerHTML = "";
  applyPreset({ onlyEmpty: false });
  updateSignatureOutput();
  updateArchivisDate();
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
  config.presettable_fields.forEach((field) => {
    const definition = fieldMap[field];
    if (!definition) return;
    const id = `preset-${field}`;
    const wrapper = document.createElement("label");
    wrapper.className = "preset-choice";
    wrapper.innerHTML = `<input type="checkbox" id="${id}" value="${field}"><span>${definition.label}</span>`;
    presetFieldList.append(wrapper);
  });
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
  config.presettable_fields.forEach((field) => {
    const definition = fieldMap[field];
    if (!definition) return;
    if (definition.kind === "date") {
      const value = readDatierung();
      if (includeEmpty || value.jahr || value.monat || value.tag || value.original) values[field] = value;
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
    if (!definition) return;
    if (definition.kind === "date") {
      applyDatePreset(value, onlyEmpty);
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
  const fields = [
    ["jahr", value?.jahr],
    ["monat", value?.monat],
    ["tag", value?.tag],
    ["original-datum", value?.original]
  ];
  fields.forEach(([id, fieldValue]) => {
    const element = document.querySelector(`#${id}`);
    if (!onlyEmpty || !element.value.trim()) element.value = fieldValue ?? "";
  });
  updateArchivisDate();
}

function setProfile(profile) {
  document.body.classList.toggle("barrierearm", profile === "barrierearm");
  document.querySelectorAll(".profile-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.profile === profile);
  });
  localStorage.setItem(PROFILE_KEY, profile);
}

init().catch((error) => {
  errors.textContent = error.message;
});
