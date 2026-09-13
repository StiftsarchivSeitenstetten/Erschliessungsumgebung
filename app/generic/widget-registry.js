import { formatDateRangeValue, formatDateValue, formatStructuredValue, getPathValue, isEmptyValue } from "./path-utils.js";

function element(tag, attributes = {}, children = []) {
  const node = document.createElement(tag);
  Object.entries(attributes).forEach(([key, value]) => {
    if (value === false || value === null || value === undefined) return;
    if (key === "className") node.className = value;
    else if (key === "textContent") node.textContent = value;
    else node.setAttribute(key, String(value));
  });
  children.forEach((child) => node.append(child));
  return node;
}

function renderInput(context, type = "text") {
  const input = element("input", {
    id: context.inputId,
    type,
    value: formatStructuredValue(context.value),
    readonly: true,
    disabled: !context.field.editable || context.readOnly
  });
  return input;
}

function renderText(context) {
  return renderInput(context, "text");
}

function renderTextarea(context) {
  const textarea = element("textarea", {
    id: context.inputId,
    rows: context.field.rows || 3,
    readonly: true,
    disabled: !context.field.editable || context.readOnly
  });
  textarea.value = formatStructuredValue(context.value);
  return textarea;
}

function renderCheckbox(context) {
  const checkbox = element("input", {
    id: context.inputId,
    type: "checkbox",
    disabled: true
  });
  checkbox.checked = Boolean(context.value);
  return checkbox;
}

function renderSelect(context) {
  const select = element("select", { id: context.inputId, disabled: true });
  select.append(element("option", { textContent: formatStructuredValue(context.value) || "" }));
  return select;
}

function renderDate(context) {
  return element("output", { id: context.inputId, textContent: formatDateValue(context.value) });
}

function renderDateRange(context) {
  return element("output", { id: context.inputId, textContent: formatDateRangeValue(context.value) });
}

function renderVocabularySelect(context) {
  return element("output", { id: context.inputId, textContent: formatStructuredValue(context.value) });
}

function renderRepeater(context) {
  const list = element("div", { className: "generic-repeater", id: context.inputId });
  const values = Array.isArray(context.value) ? context.value : [];
  if (!values.length) {
    list.append(element("p", { className: "generic-empty", textContent: "Keine Einträge." }));
    return list;
  }
  values.forEach((item, index) => {
    const group = element("fieldset", { className: "generic-repeater-item" });
    group.append(element("legend", { textContent: `Eintrag ${index + 1}` }));
    context.field.item_fields.forEach((itemField) => {
      if (itemField.visible === false) return;
      const value = getPathValue(item, itemField.path);
      group.append(context.renderField(itemField, item, value, `${context.inputId}-${index}-${itemField.id}`));
    });
    list.append(group);
  });
  return list;
}

export class WidgetRegistry {
  constructor() {
    this.widgets = new Map();
  }

  register(name, renderer) {
    this.widgets.set(name, renderer);
  }

  render(name, context) {
    const renderer = this.widgets.get(name);
    if (!renderer) throw new Error(`Unbekanntes Widget: ${name}`);
    return renderer(context);
  }
}

export function createDefaultWidgetRegistry() {
  const registry = new WidgetRegistry();
  registry.register("text", renderText);
  registry.register("textarea", renderTextarea);
  registry.register("checkbox", renderCheckbox);
  registry.register("select", renderSelect);
  registry.register("date", renderDate);
  registry.register("date_range", renderDateRange);
  registry.register("vocabulary_select", renderVocabularySelect);
  registry.register("repeater", renderRepeater);
  return registry;
}

export { formatStructuredValue, isEmptyValue };
