import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {FormRenderer} from "../app/generic/form-renderer.js";
import {FormState} from "../app/generic/form-state.js";
import {repeaterItemDefaults} from "../app/generic/widget-registry.js";
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



const fixture = JSON.parse(readFileSync(process.argv[2], "utf8"));
const descriptor = fixture.descriptor;
const measures = descriptor.fields.find(f => f.path === "erschliessung.masse");
const expected = {massart: "", hoehe: null, breite: null, einheit: "mm", bemerkung: ""};
assert.deepEqual(repeaterItemDefaults(measures.item_fields), expected);
const state = new FormState(descriptor, fixture.record);
const renderer = new FormRenderer({mode: "edit"});
let root = renderer.render(descriptor, state);
const add = root.querySelectorAll("button").find(b => b.textContent === "Eintrag hinzufügen");
add.events.click(); add.events.click();
renderer.readIntoState(root, state);
assert.deepEqual(state.current.erschliessung.masse, [
  {massart: "Objektmaß", hoehe: null, breite: null, einheit: "mm", bemerkung: ""}, expected, expected
]);
state.current.erschliessung.masse[1].massart = "Freies Rahmenmaß";
assert.equal(state.current.erschliessung.masse[2].massart, "");
const existing = structuredClone(state.current);
existing.erschliessung.masse[0] = {massart: "Objektmaß", hoehe: 12.5, breite: 8.25, einheit: "mm", bemerkung: "Erhalten"};
existing.erschliessung.masse[1] = {massart: "Eigenes Maß", hoehe: 123.5, breite: 85.25, einheit: "mm", bemerkung: "Andere Angabe"};
state.reset(existing);
root = renderer.render(descriptor, state);
renderer.readIntoState(root, state);
assert.deepEqual(state.current, existing, "loading and rendering must preserve existing values");
assert.deepEqual(descriptor.fields.find(f => f.path === "erschliessung.masse").default, fixture.record.erschliessung.masse);
console.log("Thoma descriptor: initial measure, additional measures, independent defaults and existing records passed");

assert.equal(root.querySelector("[data-field-id='sammlung']").querySelector("input").value, 'Sammlung Thoma');
assert.equal(root.querySelector("[data-field-id='erfassungsstatus']").querySelector("input").value, 'entwurf');
for (const control of root.querySelectorAll("[data-field-id='einheit']")) {
  assert.equal(control.querySelector("input").getAttribute('disabled'), 'true');
}
state.current.erschliessung.masse.forEach((measure, index) => {
  if (!measure.massart) measure.massart = 'Plattenmaß';
  measure.hoehe = 10.5 + index;
  measure.breite = 8.25 + index;
});
// Remove the first and then a middle row; add again after each removal.
state.current.erschliessung.masse[1].massart = "Objektmaß";
for (const removeIndex of [0, 1]) {
  root = renderer.render(descriptor, state);
  const groups = root.querySelectorAll(".generic-repeater-item");
  groups[removeIndex].querySelectorAll("button").find(b => b.textContent === "Eintrag entfernen").events.click();
  root.querySelectorAll("button").find(b => b.textContent === "Eintrag hinzufügen").events.click();
  renderer.readIntoState(root, state);
  assert.equal(state.current.erschliessung.masse.length, 3);
  assert.ok(state.current.erschliessung.masse.every(item => item.einheit === "mm"));
  const last = state.current.erschliessung.masse.at(-1);
  last.massart = "Freies Maß"; last.hoehe = 5.5; last.breite = 4.25;
  const restored = new FormState(descriptor, fixture.record);
  restored.loadWorkingSnapshot(state.buildPayload());
  assert.deepEqual(restored.current.erschliessung.masse, state.current.erschliessung.masse);
}
const payload = state.beginCreateSave();
assert.equal(payload.sammlung, undefined);
assert.equal(payload.erfassungsstatus, undefined);
assert.equal(payload.signatur, undefined);
payload.erschliessung.masse.forEach(measure => assert.equal(measure.einheit, undefined));
console.log('THOMA_PAYLOAD:' + JSON.stringify(payload));
