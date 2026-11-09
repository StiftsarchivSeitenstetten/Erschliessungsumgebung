import assert from "node:assert/strict";
import { FormRenderer } from "../app/generic/form-renderer.js";
import { FormState } from "../app/generic/form-state.js";
import { repeaterItemDefaults } from "../app/generic/widget-registry.js";
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


const all = {visible: true, editable: true};
const fields = [
  {id: "value", path: "value", widget: "decimal", exclusiveMinimum: 0, ...all},
  {id: "kind", path: "kind", widget: "text_select", required: true, options: [{value: "Objektmaß", label: "Objektmaß"}], ...all},
  {id: "closed", path: "closed", widget: "select", options: [{value: "A", label: "A"}], ...all},
  {id: "groups", path: "groups", widget: "repeater", ...all, item_fields: [
    {id: "name", path: "details.name", widget: "text_select", default: "", ...all},
    {id: "height", path: "height", widget: "decimal", default: null, exclusiveMinimum: 0, ...all},
    {id: "unit", path: "unit", widget: "text", default: "mm", ...all},
    {id: "note", path: "note", widget: "text", default: "", ...all},
    {id: "nested", path: "nested", widget: "repeater", default: [{label: "start"}], ...all,
      item_fields: [{id: "label", path: "label", widget: "text", default: "new", ...all}]},
  ]},
];
const descriptor = {module: "fixture", fields, sections: [{id: "main", order: 1, fields: fields.map(f => f.id)}]};
const state = new FormState(descriptor, {value: 12.5, kind: "Eigene Maßart", closed: "A", groups: []});
const renderer = new FormRenderer({mode: "edit"});
let root = renderer.render(descriptor, state);
const control = id => root.querySelector(`[data-field-id='${id}']`).querySelector("[data-widget-control='main']");
assert.equal(control("value").value, "12.5");
assert.equal(control("kind").value, "Eigene Maßart");
for (const [raw, expected] of [["12,5", 12.5], ["12.5", 12.5], ["", null], ["  ", null]]) {
  control("value").value = raw;
  control("value").events.input();
  renderer.readIntoState(root, state);
  assert.equal(state.current.value, expected);
  assert.equal(control("value").getAttribute("aria-invalid"), "false");
  assert.deepEqual(state.validate(), []);
}
for (const raw of ["abc", "12,", "12.", "-", "1.234,5", "1 234", "12x", "1e3", "0", "-2"]) {
  control("value").value = raw;
  control("value").events.input();
  renderer.readIntoState(root, state);
  assert.equal(control("value").value, raw);
  assert.equal(control("value").getAttribute("aria-invalid"), "true");
  assert.ok(state.validate().length);
  assert.throws(() => state.beginSave());
  assert.throws(() => state.beginCreateSave());
  root = renderer.render(descriptor, state);
  assert.equal(String(control("value").value), raw);
}
control("value").value = "25,75";
for (const value of ["Objektmaß", "Freie neue Bezeichnung"]) {
  control("kind").value = value;
  renderer.readIntoState(root, state);
  assert.equal(state.current.kind, value);
  assert.deepEqual(state.validate(), []);
}
control("kind").value = "   ";
renderer.readIntoState(root, state);
assert.ok(state.validate().length);
control("kind").value = "Objektmaß";
control("closed").value = "B";
renderer.readIntoState(root, state);
assert.ok(state.validate().some(error => error.path === "closed"));
control("closed").value = "A";
const groupRoot = root.querySelector("[data-field-id='groups']");
const add = groupRoot.querySelectorAll("button").find(b => b.textContent === "Eintrag hinzufügen");
add.events.click(); add.events.click();
renderer.readIntoState(root, state);
assert.equal(state.current.groups.length, 2);
assert.deepEqual(state.current.groups[0], {details: {name: ""}, height: null, unit: "mm", note: "", nested: [{label: "start"}]});
state.current.groups[0].details.name = "changed";
state.current.groups[0].nested[0].label = "changed";
assert.equal(state.current.groups[1].details.name, "");
assert.equal(state.current.groups[1].nested[0].label, "start");
const before = structuredClone(state.current);
root = renderer.render(descriptor, state);
renderer.readIntoState(root, state);
assert.deepEqual(state.current, before);
const nested = root.querySelector("[data-field-id='nested']");
nested.querySelectorAll("button").find(b => b.textContent === "Eintrag hinzufügen").events.click();
renderer.readIntoState(root, state);
assert.equal(state.current.groups[0].nested[1].label, "new");
assert.deepEqual(repeaterItemDefaults([{path: "a", ...all}]), {});
const defs = [{path: "a.b", default: [{x: 1}], ...all}];
const first = repeaterItemDefaults(defs), second = repeaterItemDefaults(defs);
first.a.b[0].x = 2;
assert.equal(second.a.b[0].x, 1);
assert.equal(defs[0].default[0].x, 1);
const locked = {...descriptor, fields: fields.map(f => ({...f, editable: false}))};
root = renderer.render(locked, state);
assert.equal(control("value").getAttribute("disabled"), "true");
assert.equal(control("kind").getAttribute("disabled"), "true");
console.log("decimal, free selection, closed select, nested repeater defaults and rights passed");
