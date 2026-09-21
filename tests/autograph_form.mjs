import assert from "node:assert/strict";
import { FormRenderer } from "../app/generic/form-renderer.js";
import { reviewDateTextFields } from "../app/generic/widget-registry.js";
import { FormState } from "../app/generic/form-state.js";
import { PresetStore } from "../app/generic/preset-store.js";

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

const all = {
  visible: true,
  editable: true,
  presettable: false,
};

const descriptor = {
  module: "autographen_9_6",
  user: "rita",
  sections: [
    {
      id: "beteiligte",
      label: "Beteiligte",
      order: 10,
      fields: ["beteiligte"],
    },
    {
      id: "datierung",
      label: "Datierung",
      order: 20,
      fields: ["datierung"],
    },
    {
      id: "weitere",
      label: "Weitere Angaben",
      order: 30,
      fields: ["altsignatur"],
    },
  ],
  fields: [
    {
      ...all,
      id: "beteiligte",
      path: "erschliessung.beteiligte",
      label: "Beteiligte",
      widget: "repeater",
      section: "beteiligte",
      order: 10,
      item_fields: [
        {
          ...all,
          id: "agent_type",
          path: "agent.type",
          label: "Typ",
          widget: "select",
          options: [
            { value: "person", label: "Person" },
            { value: "organization", label: "Körperschaft" },
            { value: "family", label: "Familie" },
          ],
        },
        {
          ...all,
          id: "agent_name",
          path: "agent.name",
          label: "Name",
          widget: "text",
        },
        {
          ...all,
          id: "rolle",
          path: "rolle",
          label: "Rolle",
          widget: "vocabulary_select",
          vocabulary: "autographen_beteiligtenrollen",
          vocabulary_terms: [
            {
              id: "absender",
              label: "Absender",
              active: true,
            },
            {
              id: "empfaenger",
              label: "Empfänger",
              active: true,
            },
          ],
        },
        {
          ...all,
          id: "notiz",
          path: "notiz",
          label: "Notiz",
          widget: "text",
        },
      ],
    },
    {
      ...all,
      id: "datierung",
      path: "datierung",
      label: "Datierung",
      widget: "date_range",
      section: "datierung",
      order: 10,
    },
    {
      ...all,
      id: "altsignatur",
      path: "erschliessung.altsignatur",
      label: "Altsignatur",
      widget: "text",
      section: "weitere",
      order: 10,
      presettable: true,
    },
  ],
};

const state = new FormState(
  descriptor,
  {
    erschliessung: {
      beteiligte: [],
      altsignatur: null,
    },
  },
);

const renderer = new FormRenderer({ mode: "edit" });
const root = renderer.render(descriptor, state);

const repeater = root.querySelector(
  "[data-widget-control='repeater']",
);

const add = repeater.children.find(
  node => node.textContent === "Eintrag hinzufügen",
);

add.events.click();
add.events.click();

assert.equal(
  repeater.querySelectorAll(
    ":scope > .generic-repeater-item",
  ).length,
  2,
);

const groups = repeater.querySelectorAll(
  ":scope > .generic-repeater-item",
);

groups[0]
  .querySelector("[data-field-id='agent_name']")
  .querySelector("[data-widget-control='main']")
  .value = "Max Mustermann";

groups[0]
  .querySelector("[data-field-id='rolle']")
  .querySelector("[data-widget-control='main']")
  .value = "absender";

groups[1]
  .querySelector("[data-field-id='agent_type']")
  .querySelector("[data-widget-control='main']")
  .value = "organization";

groups[1]
  .querySelector("[data-field-id='agent_name']")
  .querySelector("[data-widget-control='main']")
  .value = "Stift Seitenstetten";

groups[1]
  .querySelector("[data-field-id='rolle']")
  .querySelector("[data-widget-control='main']")
  .value = "empfaenger";

renderer.readIntoState(root, state);

assert.deepEqual(
  state
    .getValue("erschliessung.beteiligte")
    .map(item => [
      item.agent.type,
      item.agent.name,
      item.rolle.id,
    ]),
  [
    ["person", "Max Mustermann", "absender"],
    [
      "organization",
      "Stift Seitenstetten",
      "empfaenger",
    ],
  ],
);

groups[0]
  .children
  .find(node => node.textContent === "Eintrag entfernen")
  .events
  .click();

renderer.readIntoState(root, state);

assert.deepEqual(
  state
    .getValue("erschliessung.beteiligte")
    .map(item => item.agent.name),
  ["Stift Seitenstetten"],
);

root.querySelector(
  "[data-date-text='from']",
).value = "1875";

root.querySelector(
  "[data-date-text='to']",
).value = "1876";

root.querySelector(
  "[data-date-text='note']",
).value = "unsicher";

renderer.readIntoState(root, state);

assert.deepEqual(
  state.getValue("datierung").from,
  { year: 1875 },
);

assert.deepEqual(
  state.getValue("datierung").to,
  { year: 1876 },
);

assert.equal(
  state.getValue("datierung").hinweis,
  "unsicher",
);

assert.deepEqual(
  reviewDateTextFields(root).warnings,
  [],
);

root.querySelector(
  "[data-date-text='from']",
).value = "1900";

root.querySelector(
  "[data-date-text='to']",
).value = "1890";

assert.match(
  reviewDateTextFields(
    root,
    { show: true },
  ).warnings[0],
  /liegt nach/,
);

class MemoryStorage {
  constructor() {
    this.data = new Map();
  }

  getItem(key) {
    return this.data.get(key) ?? null;
  }

  setItem(key, value) {
    this.data.set(key, value);
  }

  removeItem(key) {
    this.data.delete(key);
  }

  get length() {
    return this.data.size;
  }

  key(index) {
    return [...this.data.keys()][index] ?? null;
  }
}

state.setValue(
  "erschliessung.altsignatur",
  "Altbestand X",
);

const presets = new PresetStore(
  descriptor,
  "rita",
  new MemoryStorage(),
);

presets.saveFromState(state);

const next = new FormState(
  descriptor,
  {
    erschliessung: {
      beteiligte: [],
      altsignatur: null,
    },
  },
);

presets.apply(
  next,
  { includeInitialDefaults: true },
);

assert.equal(
  next.getValue("erschliessung.altsignatur"),
  "Altbestand X",
);

next.setValue(
  "erschliessung.altsignatur",
  "Manuell geändert",
);

assert.equal(
  next.getValue("erschliessung.altsignatur"),
  "Manuell geändert",
);

console.log(
  "Autograph generic form, repeaters, date range and preset: ok",
);
