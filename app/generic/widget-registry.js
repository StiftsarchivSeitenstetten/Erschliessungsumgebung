import {
  cloneValue,
  formatDateRangeValue,
  formatDateValue,
  formatStructuredValue,
  getPathValue,
  isEmptyValue
} from "./path-utils.js";

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

function editable(context) {
  return context.mode === "edit" && context.field.editable === true;
}

function emptyTextValue(context, value) {
  if (value !== "") return value;
  return context.originalValue === null ? null : "";
}

function encodeOptionValue(value) {
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function valuesEquivalent(left, right) {
  if (typeof right === "object" && right !== null && "code" in right) return left === right.code;
  if (typeof right === "object" && right !== null && "id" in right) return left === right.id;
  return encodeOptionValue(left) === encodeOptionValue(right);
}

function selectValueFromOptions(encoded, field) {
  const option = (field.options || []).find((item) => encodeOptionValue(item.value) === encoded);
  return option ? cloneValue(option.value) : encoded;
}

function structuredFromText(text, originalValue) {
  if (typeof originalValue === "object" && originalValue !== null) {
    if (!text.trim()) return null;
    return JSON.parse(text);
  }
  return text;
}

function parseNullableInteger(value) {
  if (value === "") return null;
  const parsed = Number.parseInt(value, 10);
  return Number.isNaN(parsed) ? null : parsed;
}

function dateKey(original, english, german) {
  return original && Object.prototype.hasOwnProperty.call(original, german) ? german : english;
}

function setLocalPathValue(data, path, value) {
  const parts = path.split(".");
  let current = data;
  parts.slice(0, -1).forEach((part) => {
    current[part] = current[part] || {};
    current = current[part];
  });
  current[parts[parts.length - 1]] = value;
}

function renderStructuredText(context, tagName = "input") {
  const attrs = {
    id: context.inputId,
    "data-widget-control": "main",
    readonly: !editable(context),
    disabled: !editable(context)
  };
  if (tagName === "input") attrs.type = "text";
  else attrs.rows = context.field.rows || 3;
  const control = element(tagName, attrs);
  control.value = typeof context.value === "object" && context.value !== null
    ? JSON.stringify(context.value)
    : formatStructuredValue(context.value);
  return control;
}

function renderDateInputs(context, prefix, value) {
  const original = value || {};
  return [
    element("input", { type: "number", "data-date-part": `${prefix}.year`, value: original.year ?? original.jahr ?? "", disabled: !editable(context) }),
    element("input", { type: "number", "data-date-part": `${prefix}.month`, value: original.month ?? original.monat ?? "", disabled: !editable(context) }),
    element("input", { type: "number", "data-date-part": `${prefix}.day`, value: original.day ?? original.tag ?? "", disabled: !editable(context) }),
    element("input", { type: "text", "data-date-part": `${prefix}.display`, value: original.display ?? original.original ?? "", disabled: !editable(context) }),
    element("input", { type: "text", "data-date-part": `${prefix}.certainty`, value: original.certainty ?? original.unsicherheit ?? "", disabled: !editable(context) }),
    element("input", { type: "text", "data-date-part": `${prefix}.note`, value: original.hinweis ?? original.anmerkung ?? "", disabled: !editable(context) })
  ];
}

function retainOptionalPart(value, original, key, raw, numeric = false) {
  if (raw === "" && !(key in original)) return;
  value[key] = raw === "" ? (original[key] === "" ? "" : null) : numeric ? parseNullableInteger(raw) : raw;
}

function readDateInputs(root, prefix, originalValue) {
  const original = originalValue || {};
  const value = { ...original };
  for (const [english, german] of [["year", "jahr"], ["month", "monat"], ["day", "tag"]]) {
    retainOptionalPart(value, original, dateKey(original, english, german), root.querySelector(`[data-date-part='${prefix}.${english}']`).value, true);
  }
  for (const [part, key] of [["display", "original" in original ? "original" : "display"],
    ["certainty", "unsicherheit" in original ? "unsicherheit" : "certainty"],
    ["note", "anmerkung" in original ? "anmerkung" : "hinweis"]]) {
    retainOptionalPart(value, original, key, root.querySelector(`[data-date-part='${prefix}.${part}']`).value);
  }
  return Object.keys(value).length ? value : cloneValue(originalValue);
}

const textWidget = {
  render: (context) => renderStructuredText(context, "input"),
  readValue(context, root) {
    return emptyTextValue(context, structuredFromText(root.querySelector("[data-widget-control='main']").value, context.originalValue));
  },
  setValue(context, root, value) {
    root.querySelector("[data-widget-control='main']").value = typeof value === "object" && value !== null ? JSON.stringify(value) : formatStructuredValue(value);
  }
};

const textareaWidget = {
  render: (context) => renderStructuredText(context, "textarea"),
  readValue(context, root) {
    return emptyTextValue(context, structuredFromText(root.querySelector("[data-widget-control='main']").value, context.originalValue));
  },
  setValue(context, root, value) {
    root.querySelector("[data-widget-control='main']").value = typeof value === "object" && value !== null ? JSON.stringify(value) : formatStructuredValue(value);
  }
};

const checkboxWidget = {
  render(context) {
    const checkbox = element("input", {
      id: context.inputId,
      type: "checkbox",
      "data-widget-control": "main",
      disabled: !editable(context)
    });
    checkbox.checked = Boolean(context.value);
    return checkbox;
  },
  readValue(_context, root) {
    return root.querySelector("[data-widget-control='main']").checked;
  },
  setValue(_context, root, value) {
    root.querySelector("[data-widget-control='main']").checked = Boolean(value);
  }
};

const selectWidget = {
  render(context) {
    const select = element("select", { id: context.inputId, "data-widget-control": "main", disabled: !editable(context) });
    const options = context.field.options?.length ? context.field.options : [{ value: context.value ?? "", label: formatStructuredValue(context.value) }];
    options.forEach((option) => {
      const optionNode = element("option", { value: encodeOptionValue(option.value), textContent: option.label });
      if (valuesEquivalent(option.value, context.value)) optionNode.selected = true;
      select.append(optionNode);
    });
    return select;
  },
  readValue(context, root) {
    const selected = selectValueFromOptions(root.querySelector("[data-widget-control='main']").value, context.field);
    if (context.originalValue && typeof context.originalValue === "object" && "code" in context.originalValue) {
      return { ...context.originalValue, code: selected };
    }
    return selected;
  },
  setValue(_context, root, value) {
    root.querySelector("[data-widget-control='main']").value = encodeOptionValue(value);
  }
};

const dateWidget = {
  render(context) {
    if (context.mode === "read") return element("output", { id: context.inputId, textContent: formatDateValue(context.value) });
    return element("fieldset", { id: context.inputId, className: "generic-date" }, renderDateInputs(context, "date", context.value));
  },
  readValue(context, root) {
    return readDateInputs(root, "date", context.originalValue);
  },
  setValue(context, root, value) {
    context.value = value;
    root.replaceWith(dateWidget.render(context));
  }
};

const dateRangeWidget = {
  render(context) {
    if (context.mode === "read") return element("output", { id: context.inputId, textContent: formatDateRangeValue(context.value) });
    return element("fieldset", { id: context.inputId, className: "generic-date-range" }, [
      element("legend", { textContent: "Zeitraum" }),
      ...renderDateInputs(context, "from", context.value?.from || context.value?.von || {}),
      ...renderDateInputs(context, "to", context.value?.to || context.value?.bis || {}),
      element("input", { type: "text", "data-range-part": "display", value: context.value?.display ?? "", disabled: !editable(context) }),
      element("input", { type: "text", "data-range-part": "certainty", value: context.value?.certainty ?? "", disabled: !editable(context) }),
      element("input", { type: "text", "data-range-part": "note", value: context.value?.hinweis ?? context.value?.note ?? "", disabled: !editable(context) })
    ]);
  },
  readValue(context, root) {
    const original = context.originalValue || {};
    const value = {...original};
    for (const [part, key] of [["from", "von" in original ? "von" : "from"], ["to", "bis" in original ? "bis" : "to"]]) {
      const date = readDateInputs(root, part, original[key]);
      if (date !== undefined) value[key] = date;
    }
    for (const [part, key] of [["display", "display"], ["certainty", "certainty"], ["note", "note" in original ? "note" : "hinweis"]]) {
      retainOptionalPart(value, original, key, root.querySelector(`[data-range-part='${part}']`).value);
    }
    return Object.keys(value).length ? value : cloneValue(context.originalValue);
  },
  setValue(context, root, value) {
    context.value = value;
    root.replaceWith(dateRangeWidget.render(context));
  }
};

const vocabularySelectWidget = {
  render(context) {
    const currentId = context.value && typeof context.value === "object" ? context.value.id : context.value;
    const field = context.field.options?.length ? context.field : { ...context.field, options: [{ value: currentId ?? "", label: formatStructuredValue(context.value) }] };
    return selectWidget.render({ ...context, field, value: currentId });
  },
  readValue(context, root) {
    const selected = selectValueFromOptions(root.querySelector("[data-widget-control='main']").value, context.field);
    if (context.originalValue && typeof context.originalValue === "object") {
      return { ...context.originalValue, id: selected };
    }
    return selected;
  },
  setValue(_context, root, value) {
    const selected = value && typeof value === "object" ? value.id : value;
    root.querySelector("[data-widget-control='main']").value = encodeOptionValue(selected);
  }
};

function renumberRepeaterItems(list) {
  list.querySelectorAll(":scope > .generic-repeater-item").forEach((group, index) => {
    group.querySelector(":scope > legend").textContent = `Eintrag ${index + 1}`;
  });
}

function renderRepeaterItem(context, item, index, originalIndex = null, inputIndex = index) {
  const group = element("fieldset", { className: "generic-repeater-item", "data-original-index": originalIndex });
  group.append(element("legend", { textContent: `Eintrag ${index + 1}` }));
  context.field.item_fields.forEach((itemField) => {
    if (itemField.visible === false) return;
    const value = getPathValue(item, itemField.path);
    group.append(context.renderField(itemField, item, value, `${context.inputId}-${inputIndex}-${itemField.id}`));
  });
  if (editable(context)) {
    const removeButton = element("button", { type: "button", className: "secondary danger", textContent: "Eintrag entfernen" });
    removeButton.addEventListener("click", () => {
      const list = group.parentElement;
      group.remove();
      renumberRepeaterItems(list);
    });
    group.append(removeButton);
  }
  return group;
}

const repeaterWidget = {
  render(context) {
    const list = element("div", { className: "generic-repeater", id: context.inputId, "data-widget-control": "repeater" });
    const values = Array.isArray(context.value) ? context.value : [];
    let nextItemId = values.length;
    values.forEach((item, index) => list.append(renderRepeaterItem(context, item, index, index)));
    if (!values.length) list.append(element("p", { className: "generic-empty", textContent: "Keine Einträge." }));
    if (editable(context)) {
      const addButton = element("button", { type: "button", className: "secondary", textContent: "Eintrag hinzufügen" });
      addButton.addEventListener("click", () => {
        list.querySelector(".generic-empty")?.remove();
        list.insertBefore(renderRepeaterItem(context, {}, list.querySelectorAll(".generic-repeater-item").length, null, nextItemId++), addButton);
      });
      list.append(addButton);
    }
    return list;
  },
  readValue(context, root) {
    const list = root.querySelector("[data-widget-control='repeater']");
    return Array.from(list.querySelectorAll(":scope > .generic-repeater-item")).map((group) => {
      const originalIndex = group.getAttribute("data-original-index");
      const originalItem = originalIndex === null ? {} : context.originalValue?.[Number(originalIndex)] || {};
      const item = cloneValue(originalItem);
      context.field.item_fields.forEach((itemField) => {
        const fieldRoot = group.querySelector(`[data-field-id='${itemField.id}']`);
        if (!fieldRoot) return;
        setLocalPathValue(item, itemField.path, context.readField(itemField, fieldRoot, getPathValue(originalItem, itemField.path)));
      });
      return item;
    });
  },
  setValue(context, root, value) {
    context.value = Array.isArray(value) ? value : [];
    root.replaceWith(repeaterWidget.render(context));
  }
};

export class WidgetRegistry {
  constructor() {
    this.widgets = new Map();
  }

  register(name, widget) {
    this.widgets.set(name, widget);
  }

  widget(name) {
    const widget = this.widgets.get(name);
    if (!widget) throw new Error(`Unbekanntes Widget: ${name}`);
    return widget;
  }

  render(name, context) {
    return this.widget(name).render(context);
  }

  readValue(name, context, root) {
    return this.widget(name).readValue(context, root);
  }

  setValue(name, context, root, value) {
    return this.widget(name).setValue(context, root, value);
  }
}

export function createDefaultWidgetRegistry() {
  const registry = new WidgetRegistry();
  registry.register("text", textWidget);
  registry.register("textarea", textareaWidget);
  registry.register("checkbox", checkboxWidget);
  registry.register("select", selectWidget);
  registry.register("date", dateWidget);
  registry.register("date_range", dateRangeWidget);
  registry.register("vocabulary_select", vocabularySelectWidget);
  registry.register("repeater", repeaterWidget);
  return registry;
}

export { formatStructuredValue, isEmptyValue };
