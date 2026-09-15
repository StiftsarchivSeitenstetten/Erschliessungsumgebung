(function exposeDateTextFields(global) {
  function parse(text) {
    const source = String(text || "").trim();
    if (!source) return { empty: true, valid: true, value: null, precision: null };
    let match = source.match(/^([0-9]{4})$/);
    if (match) return { empty: false, valid: true, value: { year: Number(match[1]), month: null, day: null }, precision: "year" };
    match = source.match(/^([0-9]{1,2})\.([0-9]{4})$/);
    if (match) return { empty: false, valid: true, value: { year: Number(match[2]), month: Number(match[1]), day: null }, precision: "month" };
    match = source.match(/^([0-9]{1,2})\.([0-9]{1,2})\.([0-9]{4})$/);
    if (match) return { empty: false, valid: true, value: { year: Number(match[3]), month: Number(match[2]), day: Number(match[1]) }, precision: "day" };
    return { empty: false, valid: false, value: null, precision: null };
  }

  function validCalendarDate(value) {
    if (!value) return true;
    if (value.year < 1 || value.year > 9999) return false;
    if (value.month === null) return value.day === null;
    if (value.month < 1 || value.month > 12) return false;
    if (value.day === null) return true;
    const date = new Date(value.year, value.month - 1, value.day);
    return value.day >= 1 && date.getFullYear() === value.year && date.getMonth() === value.month - 1 && date.getDate() === value.day;
  }

  function format(value) {
    if (!value) return "";
    const year = value.year ?? value.jahr;
    const month = value.month ?? value.monat;
    const day = value.day ?? value.tag;
    if (!year) return "";
    if (!month) return String(year);
    if (!day) return `${String(month).padStart(2, "0")}.${year}`;
    return `${String(day).padStart(2, "0")}.${String(month).padStart(2, "0")}.${year}`;
  }

  function comparable(parsed) {
    if (!parsed.valid || parsed.empty || !validCalendarDate(parsed.value)) return null;
    return parsed.value.year * 10000 + (parsed.value.month || 0) * 100 + (parsed.value.day || 0);
  }

  function review(fromText, toText) {
    const from = parse(fromText);
    const to = parse(toText);
    const warnings = [];
    let blocking = false;
    for (const [label, parsed] of [["Von", from], ["Bis", to]]) {
      if (!parsed.valid || !validCalendarDate(parsed.value)) {
        warnings.push(`${label} ist nicht eindeutig als JJJJ, MM.JJJJ oder TT.MM.JJJJ interpretierbar. Verbale oder unsichere Angaben bitte im Feld Hinweis erfassen.`);
        blocking = true;
      }
    }
    const fromValue = comparable(from);
    const toValue = comparable(to);
    if (fromValue !== null && toValue !== null && fromValue > toValue) {
      warnings.push("Das Datum in „Von“ liegt nach dem Datum in „Bis“. Bitte prüfen Sie den Zeitraum.");
    }
    return { from, to, warnings, blocking };
  }

  function withKeys(parsed, original, language = "english") {
    if (parsed.empty) return null;
    if (!parsed.valid || !validCalendarDate(parsed.value)) return original || null;
    const result = { ...(original || {}) };
    const keys = language === "german" ? ["jahr", "monat", "tag"] : ["year", "month", "day"];
    result[keys[0]] = parsed.value.year;
    if (parsed.precision !== "year" || Object.prototype.hasOwnProperty.call(result, keys[1])) result[keys[1]] = parsed.value.month;
    if (parsed.precision === "day" || Object.prototype.hasOwnProperty.call(result, keys[2])) result[keys[2]] = parsed.value.day;
    return result;
  }

  global.DateTextFields = Object.freeze({ parse, format, review, validCalendarDate, withKeys });
})(globalThis);
