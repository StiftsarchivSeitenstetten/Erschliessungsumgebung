import { cloneValue } from "./path-utils.js";

export function vocabularyTermId(value) {
  return value && typeof value === "object" ? value.id : value;
}

export function canonicalTermReference(field, selectedId) {
  if (selectedId === null || selectedId === undefined || selectedId === "") return null;
  return { id: String(selectedId), vocabulary_id: field.vocabulary };
}

export function vocabularyFieldOptions(field, value) {
  const currentId = vocabularyTermId(value);
  const terms = field.vocabulary_terms || [];
  const currentTerm = terms.find(term => term.id === currentId);
  const options = terms.filter(term => term.active).map(term => ({ value: term.id, label: term.label }));
  let issue = "";
  if (currentId && currentTerm && !currentTerm.active) {
    options.push({ value: currentTerm.id, label: `${currentTerm.label} (inaktiv)` });
  } else if (currentId && !currentTerm) {
    options.push({ value: currentId, label: `${currentId} (unbekannter Begriff)` });
    issue = `Unbekannte Term-ID: ${currentId}`;
  }
  if (value && typeof value === "object" && value.vocabulary_id && value.vocabulary_id !== field.vocabulary) {
    issue = `Falsche Vocabulary-ID: ${value.vocabulary_id}`;
  }
  return { options, issue };
}

function walkFields(fields) {
  return (fields || []).flatMap(field => [field, ...walkFields(field.item_fields)]);
}

export class VocabularyClient {
  constructor(fetchImpl = globalThis.fetch) {
    this.fetchImpl = fetchImpl;
    this.cache = new Map();
  }

  async load(vocabularyId) {
    if (!this.cache.has(vocabularyId)) {
      const fetchImpl = this.fetchImpl;
      this.cache.set(vocabularyId, fetchImpl(`/api/vocabularies/${encodeURIComponent(vocabularyId)}`, {
        credentials: "same-origin",
      }).then(async response => {
        if (!response.ok) throw new Error(`Vokabular ${vocabularyId} konnte nicht geladen werden.`);
        const vocabulary = await response.json();
        if (vocabulary.id !== vocabularyId || !Array.isArray(vocabulary.terms)) {
          throw new Error(`Vokabular ${vocabularyId} ist ungültig.`);
        }
        return vocabulary;
      }));
    }
    return this.cache.get(vocabularyId);
  }

  async write(vocabularyId, suffix, method, body, csrfToken) {
    const response = await this.fetchImpl(`/api/vocabularies/${encodeURIComponent(vocabularyId)}${suffix}`, {
      method,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken || "" },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`Vokabular ${vocabularyId} konnte nicht gespeichert werden.`);
    const result = await response.json();
    if (!result.vocabulary || result.vocabulary.id !== vocabularyId || !result.meta?.revision) {
      throw new Error(`Ungültige Schreibantwort für Vokabular ${vocabularyId}.`);
    }
    this.cache.set(vocabularyId, Promise.resolve(result.vocabulary));
    return result;
  }

  addTerm(vocabularyId, baseRevision, term, csrfToken) {
    return this.write(vocabularyId, "/terms", "POST", { base_revision: baseRevision, term }, csrfToken);
  }

  renameTerm(vocabularyId, termId, baseRevision, label, csrfToken) {
    return this.write(
      vocabularyId, `/terms/${encodeURIComponent(termId)}`, "PATCH",
      { base_revision: baseRevision, label }, csrfToken,
    );
  }

  deactivateTerm(vocabularyId, termId, baseRevision, csrfToken) {
    return this.write(
      vocabularyId, `/terms/${encodeURIComponent(termId)}`, "PATCH",
      { base_revision: baseRevision, active: false }, csrfToken,
    );
  }

  async hydrateDescriptor(moduleDescriptor) {
    const fields = walkFields(moduleDescriptor.fields);
    const ids = [...new Set(fields.filter(field => field.widget === "vocabulary_select").map(field => field.vocabulary))];
    const vocabularies = new Map(await Promise.all(ids.map(async id => [id, await this.load(id)])));
    fields.forEach(field => {
      if (field.widget === "vocabulary_select") {
        field.vocabulary_terms = cloneValue(vocabularies.get(field.vocabulary).terms);
      }
    });
    return moduleDescriptor;
  }
}
