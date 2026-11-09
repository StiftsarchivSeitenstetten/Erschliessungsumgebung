// Keep invalid input as text so editing and rendering never discard it.
export function parseDecimal(raw) {
  if (!raw.trim()) return null;
  if (!/^[+-]?\d+(?:[.,]\d+)?$/.test(raw.trim())) return raw;
  const value = Number(raw.trim().replace(",", "."));
  return Number.isFinite(value) ? value : raw;
}

export function decimalIssue(field, value) {
  if (value === null || value === undefined) return field.required ? "Pflichtfeld ist leer." : "";
  if (typeof value !== "number" || !Number.isFinite(value)) return "Bitte eine vollständige Dezimalzahl ohne Tausendertrennzeichen eingeben.";
  if (field.exclusiveMinimum !== undefined && value <= field.exclusiveMinimum) {
    return `Der Wert muss größer als ${field.exclusiveMinimum} sein.`;
  }
  return "";
}
