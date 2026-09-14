import { formatStructuredValue, formatDateValue, formatDateRangeValue } from "./path-utils.js";

export class ResultState {
  constructor(module, sort = null) {
    this.module = module;
    this.sort = sort;
    this.q = "";
    this.lookupField = "";
    this.lookupValue = "";
    this.records = [];
    this.recordId = null;
    this.lastRecordId = null;
  }
  get position() { return this.records.findIndex(row => row.record_id === this.recordId); }
  neighbor(offset) {
    const position = this.position;
    return position < 0 ? null : this.records[position + offset]?.record_id || null;
  }
  replace(records, query) {
    this.records = records;
    Object.assign(this, query);
    this.recordId = null;
  }
  queryString() {
    const query = new URLSearchParams();
    if (this.q) query.set("q", this.q);
    if (this.lookupField && this.lookupValue) {
      query.set("lookup_field", this.lookupField);
      query.set("lookup_value", this.lookupValue);
    }
    return query.toString();
  }
  url() {
    const query = new URLSearchParams(this.queryString());
    query.set("module", this.module);
    if (this.recordId) query.set("record", this.recordId);
    return `/app/module/?${query}`;
  }
}

export function listColumns(descriptor) {
  return (descriptor.list?.columns || []).map(column => ({
    ...column,
    label: column.label || descriptor.fields.find(field => field.path === column.path)?.label || column.path
  }));
}

export function listValue(value) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    if ("from" in value || "von" in value) return formatDateRangeValue(value);
    if ("year" in value || "jahr" in value) return formatDateValue(value);
  }
  return formatStructuredValue(value);
}

export function renderRecordList(container, descriptor, records, openRecord) {
  container.replaceChildren();
  if (!records.length) {
    container.textContent = "Keine Treffer.";
    return;
  }
  const configured = listColumns(descriptor);
  const columns = configured.length ? configured : [{path: null, label: "Datensatz"}];
  const table = document.createElement("table");
  const head = table.createTHead().insertRow();
  columns.map(column => column.label).forEach(label => {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = label;
    head.append(cell);
  });
  const body = table.createTBody();
  records.forEach(record => {
    const row = body.insertRow();
    const link = document.createElement("a");
    const query = new URLSearchParams({ module: descriptor.module, record: record.record_id });
    link.href = `/app/module/?${query}`;
    link.textContent = listValue(record.values?.[columns[0].path]) || record.record_id;
    link.dataset.recordId = record.record_id;
    link.addEventListener("click", event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      openRecord(record.record_id);
    });
    row.insertCell().append(link);
    columns.slice(1).forEach(column => { row.insertCell().textContent = listValue(record.values?.[column.path]); });
  });
  container.append(table);
}
