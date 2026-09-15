const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

class Element {
  constructor(selector = "") {
    this.selector = selector;
    this.value = "";
    this.checked = false;
    this.disabled = false;
    this.hidden = false;
    this.dataset = {};
    this.textContent = "";
    this.rows = [];
    this.classList = { add() {}, remove() {}, toggle() {} };
    this.children = {};
    this._innerHTML = "";
  }

  addEventListener() {}

  append(...items) {
    if (this.selector === "#personen-list") this.rows.push(...items);
  }

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

  get innerHTML() {
    return this._innerHTML;
  }

  querySelector(selector) {
    return this.children[selector] || new Element(selector);
  }
}

const selectors = [
  "#record-form", "#errors", "#preview", "#generate", "#download", "#finalize",
  "#discard-changes", "#number-output", "#signature-output", "#archivis-date",
  "#preset-status", "#preset-editor", "#preset-field-list", "#current-user",
  "#record-browser", "#record-search", "#record-list", "#record-nav-top",
  "#record-nav-bottom", "#personen-list", "#beschriftung", "#titel", "#beschreibung",
  "#herkunft", "#sammler", "#fotograf", "#rechteinhaber", "#orte", "#schlagworte",
  "#altsignaturen", "#interne-bemerkung", "#korrespondenzstueck", "#datierung-einfach",
  "#datierung-anmerkung", "#original-datum"
];
const elements = Object.fromEntries(selectors.map((selector) => [selector, new Element(selector)]));
elements["#record-form"].reset = () => {
  for (const selector of selectors) {
    if (selector.startsWith("#") && !["#record-form", "#personen-list"].includes(selector)) {
      elements[selector].value = "";
      elements[selector].checked = false;
    }
  }
};
const formatInput = Object.assign(new Element(), { value: "A", checked: true });

const document = {
  cookie: "csrf=test",
  body: new Element("body"),
  querySelector(selector) {
    if (selector.startsWith("input[name='format'][value=")) return formatInput;
    return elements[selector] || new Element(selector);
  },
  querySelectorAll(selector) {
    if (selector === ".person-row") return elements["#personen-list"].rows;
    if (selector === "input[name='format']") return [formatInput];
    return [];
  },
  createElement(selector) {
    return new Element(selector);
  }
};

const window = {
  location: { href: "http://localhost/app/", pathname: "/app/", search: "" },
  history: { replaceState() {} },
  addEventListener() {},
  confirm() { return true; }
};
const localStorage = { getItem() { return "redaktion"; }, setItem() {}, removeItem() {} };
const sourcePath = path.join(__dirname, "..", "app", "app.js");
const source = fs.readFileSync(sourcePath, "utf8").replace(/\ninit\(\)\.catch\([\s\S]*$/, "\n");

const test = `
function testRecord(title) {
  return {
    id: "foto-000001",
    signatur: { bestand: "9", objektgruppe: "4.2", format: "A", nummer: 1, anzeige: "9.4.2.A.1", status: "vergeben" },
    erschliessung: {
      titel: title, beschriftung: "Beschriftung", beschreibung: null,
      dargestellte_personen: [], herkunft: null, sammler: null, fotograf: null,
      rechteinhaber: null, orte: [], schlagworte: [], altsignaturen: [], interne_bemerkung: null
    },
    korrespondenzstueck: false,
    datierung: { jahr: null, monat: null, tag: null, anmerkung: null, original: null, original_typ: null },
    redaktion: { stufe: "erschlossen" }
  };
}

async function runSaveStateTests() {
  config = {
    datensatz_typ: "foto", module_id: "foto_papierabzuege",
    signature: { formats: ["A"], pattern: "{bestand}.{objektgruppe}.{format}.{nummer}", bestand: "9", objektgruppe: "4.2" },
    defaults: { redaktion_stufe: "erschlossen", bearbeitung_status: "offen", publikation_status: "intern" },
    ui_profiles: { redaktion: { editable_fields: Object.keys(fieldMap), technical_preview: true } }
  };
  state.user = { role: "redaktion", ui_profile: "redaktion" };
  state.records = [testRecord("A")];
  refreshRecords = async () => {};
  applyLoadedRecord(testRecord("A"), "rev-a");
  assert.equal(hasUnsavedChanges(), false, "loaded record is clean");
  assert.equal(finalizeButton.disabled, true, "clean record cannot be saved");

  const requests = [];
  let nextRevision = 1;
  apiFetch = async (_url, options) => {
    const payload = JSON.parse(options.body);
    requests.push(payload);
    const revision = "rev-" + (++nextRevision);
    return { ok: true, async json() { return { record: testRecord(payload.erschliessung.titel), base_revision: revision }; } };
  };

  elements["#titel"].value = "B";
  updateDirtyState();
  assert.equal(hasUnsavedChanges(), true, "first edit is dirty");
  assert.equal(finalizeButton.disabled, false, "first edit enables save");
  await finalizeRecord();
  assert.equal(requests[0].base_revision, "rev-a", "first save uses loaded revision");
  assert.equal(state.baseRevision, "rev-2");
  assert.equal(hasUnsavedChanges(), false, "first save establishes a clean baseline");

  elements["#titel"].value = "C";
  updateDirtyState();
  assert.equal(finalizeButton.disabled, false, "second edit enables save again");
  discardChanges();
  assert.equal(elements["#titel"].value, "B", "discard restores the last confirmed save");
  assert.equal(hasUnsavedChanges(), false);

  elements["#titel"].value = "C";
  updateDirtyState();
  await finalizeRecord();
  assert.equal(requests[1].base_revision, "rev-2", "second save uses the new revision");
  assert.equal(state.baseRevision, "rev-3");
  assert.equal(hasUnsavedChanges(), false);

  elements["#titel"].value = "D";
  updateDirtyState();
  await finalizeRecord();
  assert.equal(requests[2].base_revision, "rev-3", "third save uses the second returned revision");
  assert.equal(state.baseRevision, "rev-4");
  assert.equal(hasUnsavedChanges(), false, "third cycle ends clean");

  elements["#titel"].value = "not saved";
  updateDirtyState();
  apiFetch = async () => ({ ok: false, async json() { return { detail: "Konflikt" }; } });
  await finalizeRecord();
  assert.equal(elements["#titel"].value, "not saved", "save errors retain local input");
  assert.equal(state.baseRevision, "rev-4", "save errors retain the confirmed revision");
  assert.equal(hasUnsavedChanges(), true, "save errors remain dirty");
  assert.equal(finalizeButton.disabled, false, "failed saves remain retryable");

  let releaseResponse;
  apiFetch = async (_url, options) => {
    const payload = JSON.parse(options.body);
    requests.push(payload);
    await new Promise((resolve) => { releaseResponse = resolve; });
    return { ok: true, async json() { return { record: testRecord(payload.erschliessung.titel), base_revision: "rev-5" }; } };
  };
  elements["#titel"].value = "pending B";
  updateDirtyState();
  const saving = finalizeRecord();
  assert.equal(state.saving, true, "save enters saving state");
  assert.equal(finalizeButton.disabled, true, "save button is disabled while request is active");
  elements["#titel"].value = "newer C";
  updateDirtyState();
  releaseResponse();
  await saving;
  assert.equal(elements["#titel"].value, "newer C", "server response does not overwrite newer input");
  assert.equal(hasUnsavedChanges(), true, "newer input remains dirty after response");
  assert.equal(finalizeButton.disabled, false, "newer input can be saved next");
}

runSaveStateTests().catch((error) => { console.error(error); process.exitCode = 1; });
`;

new Function("assert", "elements", "document", "window", "localStorage", "fetch", source + test)(
  assert,
  elements,
  document,
  window,
  localStorage,
  async () => { throw new Error("unexpected fetch"); }
);
