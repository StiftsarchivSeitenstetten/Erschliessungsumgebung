import { getPathValue } from "./path-utils.js";
import { createDefaultWidgetRegistry } from "./widget-registry.js";

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

function fieldId(field, suffix = "") {
  return `generic-field-${field.id}${suffix ? `-${suffix}` : ""}`;
}

export class FormRenderer {
  constructor({ widgetRegistry = createDefaultWidgetRegistry(), mode = "read", readOnly = undefined } = {}) {
    this.widgetRegistry = widgetRegistry;
    this.mode = readOnly === true ? "read" : mode;
  }

  render(moduleDescriptor, formStateOrRecord) {
    if (!moduleDescriptor?.sections || !moduleDescriptor?.fields) {
      throw new Error("Fehlerhafter Modul-Descriptor.");
    }
    const recordData = formStateOrRecord?.current || formStateOrRecord || {};
    const root = element("div", { className: "generic-form", "data-module": moduleDescriptor.module });
    const fieldsById = new Map(moduleDescriptor.fields.map((field) => [field.id, field]));
    const sections = [...moduleDescriptor.sections].sort((a, b) => a.order - b.order);
    sections.forEach((section) => {
      const sectionFields = (section.fields || [])
        .map((id) => fieldsById.get(id))
        .filter((field) => field && field.visible !== false)
        .sort((a, b) => a.order - b.order);
      if (!sectionFields.length) return;
      const sectionNode = element("section", { className: "generic-section", "data-section": section.id });
      sectionNode.append(element("h2", { textContent: section.label }));
      if (section.help) sectionNode.append(element("p", { className: "generic-help", textContent: section.help }));
      sectionFields.forEach((field) => {
        sectionNode.append(this.renderField(field, recordData, getPathValue(recordData, field.path), fieldId(field)));
      });
      root.append(sectionNode);
    });
    return root;
  }

  renderField(field, recordData, value, inputId = fieldId(field)) {
    if (field.visible === false) return document.createDocumentFragment();
    const wrapper = element("div", {
      className: "generic-field",
      "data-field-id": field.id,
      "data-field-path": field.path,
      "data-editable": field.editable ? "true" : "false",
      "data-presettable": field.presettable ? "true" : "false"
    });
    wrapper.append(element("label", { for: inputId, textContent: field.label }));
    if (field.help) wrapper.append(element("p", { className: "generic-help", textContent: field.help }));
    const control = this.widgetRegistry.render(field.widget, {
      field,
      value,
      originalValue: getPathValue(recordData, field.path),
      inputId,
      recordData,
      mode: this.mode,
      renderField: (itemField, itemData, itemValue, itemInputId) => this.renderField(itemField, itemData, itemValue, itemInputId)
    });
    wrapper.append(control);
    return wrapper;
  }

  readField(field, fieldRoot, originalValue = undefined) {
    return this.widgetRegistry.readValue(field.widget, {
      field,
      originalValue,
      mode: this.mode,
      readField: (itemField, itemRoot, itemOriginal) => this.readField(itemField, itemRoot, itemOriginal)
    }, fieldRoot);
  }

  readIntoState(formRoot, formState) {
    formState.moduleDescriptor.fields
      .filter((field) => field.visible !== false && field.editable === true)
      .forEach((field) => {
        const fieldRoot = formRoot.querySelector(`[data-field-id='${field.id}']`);
        if (!fieldRoot) return;
        const value = this.widgetRegistry.readValue(field.widget, {
          field,
          originalValue: getPathValue(formState.original, field.path),
          mode: this.mode,
          renderField: (itemField, itemData, itemValue, itemInputId) => this.renderField(itemField, itemData, itemValue, itemInputId),
          readField: (itemField, itemRoot, itemOriginal) => this.readField(itemField, itemRoot, itemOriginal)
        }, fieldRoot);
        formState.setValue(field.path, value);
      });
    return formState;
  }
}
