const FORMATS = ["A", "B", "C", "D", "E", "F"];
const MODULE_ID = "papierabzuege_9_4_2";
const PRESET_KEY = "erschliessung.papierabzuege.activePreset";
const PROFILE_KEY = "erschliessung.papierabzuege.profile";

const existingRecords = [
  { id: "foto-000001", format: "A", nummer: 8468 },
  { id: "foto-000002", format: "C", nummer: 500 },
  { id: "foto-000003", format: "B", nummer: 1025 }
];

const state = {
  format: null,
  generatedMarkdown: "",
  generatedFilename: "foto-000004.md"
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
const presetHerkunft = document.querySelector("#preset-herkunft");

function nextNumber(format) {
  const numbers = existingRecords
    .filter((record) => record.format === format)
    .map((record) => record.nummer);
  return Math.max(0, ...numbers) + 1;
}

function nextId() {
  const maxId = existingRecords
    .map((record) => Number(record.id.replace("foto-", "")))
    .reduce((max, value) => Math.max(max, value), 0);
  return `foto-${String(maxId + 1).padStart(6, "0")}`;
}

function buildSignature(format, number) {
  return `9.4.2.${format}.${number}`;
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

function scalar(value) {
  if (value === null || value === undefined || value === "") return "null";
  return `"${String(value).replaceAll("\\", "\\\\").replaceAll('"', '\\"')}"`;
}

function list(values, indent = "  ") {
  if (!values.length) return "[]";
  return `\n${values.map((value) => `${indent}- ${scalar(value)}`).join("\n")}`;
}

function personList(values) {
  if (!values.length) return "[]";
  return `\n${values.map((value) => `    - name: ${scalar(value)}\n      hinweis: null`).join("\n")}`;
}

function readRecord() {
  const number = state.format ? nextNumber(state.format) : null;
  const id = nextId();
  const datierung = {
    jahr: parseIntegerField("jahr"),
    monat: parseIntegerField("monat"),
    tag: parseIntegerField("tag")
  };
  return {
    id,
    schema_version: 1,
    datensatz_typ: "foto",
    modul: MODULE_ID,
    signatur: state.format
      ? {
          bestand: "9.4",
          objektgruppe: "2",
          format: state.format,
          nummer: number,
          anzeige: buildSignature(state.format, number),
          status: "vorgeschlagen"
        }
      : null,
    erschliessung: {
      titel: document.querySelector("#titel").value.trim() || null,
      beschriftung: document.querySelector("#beschriftung").value.trim() || null,
      beschreibung: document.querySelector("#beschreibung").value.trim() || null,
      dargestellte_personen: splitList(document.querySelector("#personen").value),
      herkunft: document.querySelector("#herkunft").value.trim() || null,
      sammler: document.querySelector("#sammler").value.trim() || null,
      fotograf: document.querySelector("#fotograf").value.trim() || null,
      rechteinhaber: document.querySelector("#rechteinhaber").value.trim() || null,
      orte: splitList(document.querySelector("#orte").value),
      schlagworte: splitList(document.querySelector("#schlagworte").value),
      altsignaturen: splitList(document.querySelector("#altsignaturen").value),
      interne_bemerkung: document.querySelector("#interne-bemerkung").value.trim() || null
    },
    datierung: {
      ...datierung,
      original: document.querySelector("#original-datum").value.trim() || null,
      original_typ: document.querySelector("#original-datum").value.trim() ? "importierte_arbeitsdaten" : null
    },
    redaktion: { stufe: "ehrenamtlich" },
    bearbeitung: { status: "in_bearbeitung" },
    publikation: { status: "intern" },
    technik: { quelle: "lokaler_webpilot", erstellt_am: null, geaendert_am: null }
  };
}

function validate(record) {
  const messages = [];
  if (!record.signatur) messages.push("Bitte ein Format A-F wählen.");
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

function toMarkdown(record) {
  const e = record.erschliessung;
  const d = record.datierung;
  const s = record.signatur;
  return `---\nschema_version: 1\nid: ${record.id}\ndatensatz_typ: foto\nmodul: ${MODULE_ID}\nsignatur:\n  bestand: "9.4"\n  objektgruppe: "2"\n  format: "${s.format}"\n  nummer: ${s.nummer}\n  anzeige: "${s.anzeige}"\n  status: ${s.status}\nerschliessung:\n  titel: ${scalar(e.titel)}\n  beschriftung: ${scalar(e.beschriftung)}\n  beschreibung: ${scalar(e.beschreibung)}\n  dargestellte_personen: ${personList(e.dargestellte_personen)}\n  herkunft: ${scalar(e.herkunft)}\n  sammler: ${scalar(e.sammler)}\n  fotograf: ${scalar(e.fotograf)}\n  rechteinhaber: ${scalar(e.rechteinhaber)}\n  orte: ${list(e.orte, "    ")}\n  schlagworte: ${list(e.schlagworte, "    ")}\n  altsignaturen: ${list(e.altsignaturen, "    ")}\n  interne_bemerkung: ${scalar(e.interne_bemerkung)}\ndatierung:\n  jahr: ${d.jahr ?? "null"}\n  monat: ${d.monat ?? "null"}\n  tag: ${d.tag ?? "null"}\n  original: ${scalar(d.original)}\n  original_typ: ${scalar(d.original_typ)}\nredaktion:\n  stufe: ehrenamtlich\nbearbeitung:\n  status: in_bearbeitung\npublikation:\n  status: intern\ntechnik:\n  quelle: "lokaler_webpilot"\n  erstellt_am: null\n  geaendert_am: null\n---\n\n## Beschreibung\n\n${e.beschreibung || ""}\n\n## Beschriftung\n\n${e.beschriftung || ""}\n\n## Anmerkungen\n\n${e.interne_bemerkung || ""}\n`;
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
  signatureOutput.textContent = buildSignature(state.format, number);
}

function updateArchivisDate() {
  const value = archivisDateValue({
    jahr: parseIntegerField("jahr"),
    monat: parseIntegerField("monat"),
    tag: parseIntegerField("tag")
  });
  archivisDateOutput.textContent = value || "-";
}

function loadPreset() {
  try {
    return JSON.parse(localStorage.getItem(PRESET_KEY) || "null");
  } catch {
    return null;
  }
}

function savePreset(preset) {
  localStorage.setItem(PRESET_KEY, JSON.stringify(preset));
  applyPreset();
}

function applyPreset() {
  const preset = loadPreset();
  if (!preset || !preset.herkunft) {
    presetStatus.textContent = "Keine aktive Vorbelegung.";
    return;
  }
  presetStatus.textContent = `Aktive Vorbelegung: Herkunft = ${preset.herkunft}`;
  const herkunft = document.querySelector("#herkunft");
  if (!herkunft.value.trim()) herkunft.value = preset.herkunft;
}

function setProfile(profile) {
  document.body.classList.toggle("barrierearm", profile === "barrierearm");
  document.querySelectorAll(".profile-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.profile === profile);
  });
  localStorage.setItem(PROFILE_KEY, profile);
}

document.querySelectorAll(".format-button").forEach((button) => {
  button.addEventListener("click", () => {
    state.format = button.dataset.format;
    document.querySelectorAll(".format-button").forEach((candidate) => {
      candidate.setAttribute("aria-pressed", String(candidate === button));
    });
    updateSignatureOutput();
  });
});

document.querySelectorAll(".profile-button").forEach((button) => {
  button.addEventListener("click", () => setProfile(button.dataset.profile));
});

["jahr", "monat", "tag"].forEach((id) => {
  document.querySelector(`#${id}`).addEventListener("input", updateArchivisDate);
});

document.querySelector("#generate").addEventListener("click", () => {
  const record = readRecord();
  const messages = validate(record);
  showErrors(messages);
  if (messages.length) return;
  state.generatedMarkdown = toMarkdown(record);
  state.generatedFilename = `${record.id}.md`;
  preview.value = state.generatedMarkdown;
  downloadButton.disabled = false;
});

downloadButton.addEventListener("click", () => {
  const blob = new Blob([state.generatedMarkdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = state.generatedFilename;
  link.click();
  URL.revokeObjectURL(url);
});

form.addEventListener("reset", () => {
  setTimeout(() => {
    state.generatedMarkdown = "";
    preview.value = "";
    downloadButton.disabled = true;
    errors.innerHTML = "";
    applyPreset();
    updateArchivisDate();
  });
});

document.querySelector("#edit-preset").addEventListener("click", () => {
  const preset = loadPreset();
  presetHerkunft.value = preset?.herkunft || document.querySelector("#herkunft").value.trim();
  presetEditor.hidden = !presetEditor.hidden;
});

document.querySelector("#save-preset").addEventListener("click", () => {
  savePreset({ herkunft: presetHerkunft.value.trim() });
  presetEditor.hidden = true;
});

document.querySelector("#disable-preset").addEventListener("click", () => {
  localStorage.removeItem(PRESET_KEY);
  presetStatus.textContent = "Keine aktive Vorbelegung.";
});

document.querySelector("#adopt-preset").addEventListener("click", () => {
  const herkunft = document.querySelector("#herkunft").value.trim();
  if (herkunft) savePreset({ herkunft });
});

setProfile(localStorage.getItem(PROFILE_KEY) || "standard");
applyPreset();
updateSignatureOutput();
updateArchivisDate();
