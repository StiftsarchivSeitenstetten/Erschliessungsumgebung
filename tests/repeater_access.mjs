import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {FormRenderer} from "../app/generic/form-renderer.js";
import {createSaveQueueProcessor, createUpdateQueueEntry, createCreateQueueEntry} from "../app/generic/module-save-queue.js";
import {FormState, validateRepeaterSnapshot} from "../app/generic/form-state.js";
function matches(node, selector) {
  const attribute = selector.match(/^\[([^=]+)='([^']+)'\]$/);
  if (attribute) return node.attributes[attribute[1]] === attribute[2];
  if (selector.startsWith(".")) return node.className.split(" ").includes(selector.slice(1));
  return node.tag === selector;
}

class Element {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.attributes = {};
    this.events = {};
    this.className = "";
    this.parentElement = null;
    this.value = "";
    this.textContent = "";
  }

  setAttribute(key, value) {
    this.attributes[key] = String(value);
    if (key === "class") this.className = String(value);
    if (key === "value") this.value = String(value);
  }

  getAttribute(key) {
    return this.attributes[key] ?? null;
  }

  append(...nodes) {
    nodes.forEach(node => {
      node.parentElement = this;
      this.children.push(node);
      if (
        this.tag === "select"
        && node.tag === "option"
        && (!this.value || node.selected)
      ) {
        this.value = node.value;
      }
    });
  }

  insertBefore(node, before) {
    node.parentElement = this;
    const index = this.children.indexOf(before);
    this.children.splice(
      index < 0 ? this.children.length : index,
      0,
      node,
    );
  }

  remove() {
    if (this.parentElement) {
      this.parentElement.children.splice(
        this.parentElement.children.indexOf(this),
        1,
      );
    }
    this.parentElement = null;
  }

  replaceWith(node) {
    const index = this.parentElement.children.indexOf(this);
    node.parentElement = this.parentElement;
    this.parentElement.children[index] = node;
    this.parentElement = null;
  }

  addEventListener(name, callback) {
    this.events[name] = callback;
  }

  querySelectorAll(selector) {
    if (selector.startsWith(":scope > ")) {
      return this.children.filter(
        child => matches(child, selector.slice(9)),
      );
    }

    return this.children
      .flatMap(child => [child, ...child.querySelectorAll("*")])
      .filter(
        child => selector === "*" || matches(child, selector),
      );
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }
}

globalThis.document = {
  createElement: tag => new Element(tag),
  createDocumentFragment: () => new Element("fragment"),
};



const {descriptor, record} = JSON.parse(readFileSync(process.argv[2], "utf8"));
const state = new FormState(descriptor, record);
const renderer = new FormRenderer({mode: "edit"});
let root = renderer.render(descriptor, state);
const fieldControl = (node, id) => node.querySelector(`[data-field-id='${id}']`).querySelector("[data-widget-control='main']");
assert.equal(fieldControl(root, "readonly").value, "server fixed");
assert.equal(fieldControl(root, "readonly").getAttribute("disabled"), "true");
assert.equal(root.querySelector("[data-field-id='hidden']"), null);
const list = root.querySelector("[data-field-id='rows']").querySelector("[data-widget-control='repeater']");
const first = list.querySelectorAll(":scope > .generic-repeater-item")[0];
assert.equal(fieldControl(first, "locked").getAttribute("disabled"), "true");
assert.equal(fieldControl(first, "text").getAttribute("disabled"), null);
// Tampering with the disabled DOM control does not become a form-state write.
fieldControl(first, "locked").value = "forged";
list.children.find(node => node.textContent === "Eintrag hinzufügen").events.click();
renderer.readIntoState(root, state);
assert.equal(state.current.rows[0].locked, "fixed");
assert.equal(state.current.rows[1].locked, "fixed");
assert.deepEqual(state.current.rows[1].nested, []);
assert.equal(state.current.rows[1].hidden, undefined);
state.current.rows[1].text = "Additional group";
state.current.rows[1].nested = [{text: "Additional nested", locked: "nested fixed"}];
const payload = state.buildPayload();
assert.equal(payload.readonly, undefined);
assert.equal(payload.hidden, undefined);
for (const row of payload.rows) {
  assert.equal(row.locked, undefined);
  assert.equal(row.hidden, undefined);
  for (const item of row.nested) {
    assert.equal(item.locked, undefined);
    assert.equal(item.hidden, undefined);
  }
}
const restored = new FormState(descriptor, record);
restored.loadWorkingSnapshot(payload);
assert.equal(restored.current.rows[0].locked, "fixed");
assert.equal(restored.current.rows[1].locked, "fixed");
assert.equal(restored.current.rows[1].nested[0].locked, "nested fixed");
const before = structuredClone(state.current);
root = renderer.render(descriptor, state);
renderer.readIntoState(root, state);
assert.deepEqual(state.current, before);
state.beginSave();
const confirmed = structuredClone(state.current);
const divergent = structuredClone(confirmed);
divergent.rows[0].locked = "Server authoritative";
assert.throws(() => state.confirmSave(divergent), /Geschützter lokaler Wert/);
state.current.rows[0].text = "Edited during save";
state.confirmSave(confirmed);
assert.equal(state.current.rows[0].text, "Edited during save");
assert.equal(state.current.rows[0].locked, "fixed");
// A read-only parent grants neither add nor remove controls to its descendants.
const lockedDescriptor = structuredClone(descriptor);
const lock = field => {
  field.editable = false;
  (field.item_fields || []).forEach(lock);
};
lock(lockedDescriptor.fields.find(f => f.path === "rows"));
root = renderer.render(lockedDescriptor, state);
assert.equal(root.querySelectorAll("button").length, 0);
console.log("Recursive repeater visibility, readonly defaults, payload filtering, recovery and confirmation passed");

// Unsafe old snapshots are preserved and paused, never positionally repaired.
const unsafeDescriptor = structuredClone(descriptor);
const unsafeRows = unsafeDescriptor.fields.find(field => field.path === "rows");
delete unsafeRows.repeater_policy;
delete unsafeRows.item_fields.find(field => field.path === "locked").const;
assert.throws(() => new FormState(unsafeDescriptor, record).loadWorkingSnapshot(payload), /nicht unterstützt/);
const unknownPayload = structuredClone(payload);
unknownPayload.rows[0].legacy = "unique old information";
assert.throws(() => restored.loadWorkingSnapshot(unknownPayload), /Nicht deklarierte/);
class Store {
  constructor(entry) { this.entry = structuredClone(entry); }
  async list() { return this.entry ? [structuredClone(this.entry)] : []; }
  async update(id, changes) { assert.equal(id, this.entry.operation_id); Object.assign(this.entry, structuredClone(changes)); return structuredClone(this.entry); }
  async remove(id) { assert.equal(id, this.entry.operation_id); this.entry = null; }
}
let writes = 0;
for (const operation of ["create", "update"]) {
  for (const status of ["queued", "saving"]) {
    const entry = operation === "update"
      ? createUpdateQueueEntry({operationId: "preserve-operation", moduleId: "fixture", recordId: "record", baseRevision: "base", snapshot: payload})
      : createCreateQueueEntry({operationId: "preserve-operation", moduleId: "fixture", identityAssignment: "on_create", snapshot: payload});
    entry.status = status;
    const store = new Store(entry);
    const processor = createSaveQueueProcessor({store,
      validateSnapshot: entry => validateRepeaterSnapshot(unsafeDescriptor, entry.snapshot),
      sendCreate: async () => { writes++; }, sendUpdate: async () => { writes++; },
      resolveUpdate: async () => ({outcome: "not_applied"})});
    await processor.initializeRecovery();
    await processor.process();
    if (status === "saving") {
      assert.equal(store.entry.status, "saving", "startup preserves ambiguous outcomes");
      await processor.retryFirst();
      assert.equal(store.entry.last_error.uncertain, true);
    } else assert.equal(store.entry.status, "validation_error");
    assert.match(store.entry.last_error.message, /nicht unterstützt/);
    assert.deepEqual(store.entry.snapshot, payload);
    assert.equal(store.entry.operation_id, entry.operation_id);
    assert.equal(store.entry.base_revision, entry.base_revision);
  }
}
assert.equal(writes, 0);
// A previously applied ambiguous Update still resolves by read-back, without a resend.
const applied = new Store({...createUpdateQueueEntry({operationId: "already-applied", moduleId: "fixture", recordId: "record", baseRevision: "base", snapshot: payload}), status: "saving"});
const appliedProcessor = createSaveQueueProcessor({store: applied,
  validateSnapshot: entry => validateRepeaterSnapshot(unsafeDescriptor, entry.snapshot),
  resolveUpdate: async () => ({outcome: "applied", result: {}})});
await appliedProcessor.initializeRecovery();
await appliedProcessor.retryFirst();
assert.equal(applied.entry, null);
const valid = new Store(createUpdateQueueEntry({operationId: "safe", moduleId: "fixture", recordId: "record", baseRevision: "base", snapshot: payload}));
const validProcessor = createSaveQueueProcessor({store: valid,
  validateSnapshot: entry => validateRepeaterSnapshot(descriptor, entry.snapshot),
  sendUpdate: async entry => { writes++; assert.deepEqual(entry.snapshot, payload); return {}; }});
await validProcessor.initializeRecovery();
await validProcessor.process();
assert.equal(writes, 1);
assert.equal(valid.entry, null);
console.log("Canonical repeater queue recovery, explicit rejection and ambiguous outcomes passed");
