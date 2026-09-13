export function getPathValue(data, path) {
  if (!path) return data;
  return path.split(".").reduce((value, part) => {
    if (value === null || value === undefined || typeof value !== "object") return undefined;
    return value[part];
  }, data);
}

export function setPathValue(data, path, value) {
  const parts = path.split(".");
  let current = data;
  parts.slice(0, -1).forEach((part) => {
    if (!current[part] || typeof current[part] !== "object" || Array.isArray(current[part])) {
      current[part] = {};
    }
    current = current[part];
  });
  current[parts[parts.length - 1]] = value;
}

export function cloneValue(value) {
  if (value === undefined) return undefined;
  return JSON.parse(JSON.stringify(value));
}

export function stableStringify(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(",")}}`;
}

export function valuesEqual(left, right) {
  return stableStringify(left) === stableStringify(right);
}

export function isEmptyValue(value) {
  return value === null || value === undefined || value === "" || (Array.isArray(value) && value.length === 0);
}

export function formatStructuredValue(value) {
  if (isEmptyValue(value)) return "";
  if (typeof value === "boolean") return value ? "Ja" : "Nein";
  if (typeof value !== "object") return String(value);
  if (Array.isArray(value)) return value.map(formatStructuredValue).filter(Boolean).join(", ");
  if (value.display) return String(value.display);
  if (value.label) return String(value.label);
  if (value.name) return String(value.name);
  if (value.value) return String(value.value);
  if (value.code) return String(value.code);
  if (value.id) return String(value.id);
  if (value.record_id) return String(value.record_id);
  if (value.path) return String(value.path);
  const parts = Object.entries(value)
    .filter(([, item]) => !isEmptyValue(item))
    .map(([key, item]) => `${key}: ${formatStructuredValue(item)}`);
  return parts.join("; ");
}

export function formatDateValue(value) {
  if (isEmptyValue(value)) return "";
  if (typeof value !== "object") return String(value);
  if (value.display) return String(value.display);
  const year = value.year ?? value.jahr;
  const month = value.month ?? value.monat;
  const day = value.day ?? value.tag;
  return [year, month, day].filter((part) => part !== null && part !== undefined && part !== "").join("-");
}

export function formatDateRangeValue(value) {
  if (isEmptyValue(value)) return "";
  if (typeof value !== "object") return String(value);
  if (value.display) return String(value.display);
  const from = formatDateValue(value.from ?? value.von);
  const to = formatDateValue(value.to ?? value.bis);
  return [from, to].filter(Boolean).join(" bis ");
}
