export class VocabularyAdminState {
  constructor(client) {
    this.client = client;
    this.catalog = [];
    this.vocabulary = null;
    this.revision = null;
    this.status = "loading";
    this.message = "";
    this.error = "";
    this.lastStatus = null;
    this.addDraft = { id: "", label: "" };
    this.renameDrafts = new Map();
    this.pendingDeactivate = null;
  }

  get rights() {
    return this.vocabulary?.rights || { use: false, add: false, rename: false, deactivate: false };
  }

  get hasDrafts() {
    return Boolean(this.addDraft.id || this.addDraft.label || this.renameDrafts.size);
  }

  async loadCatalog() {
    this.status = "loading";
    this.error = "";
    try {
      this.catalog = await this.client.catalog();
      this.lastStatus = null;
      this.status = "ready";
      return true;
    } catch (error) {
      this._fail(error);
      return false;
    }
  }

  async open(vocabularyId, { reload = false, discardDrafts = false } = {}) {
    this.status = "loading";
    this.error = "";
    try {
      const vocabulary = reload
        ? await this.client.reload(vocabularyId)
        : await this.client.load(vocabularyId);
      if (!vocabulary.meta?.revision || !vocabulary.rights) throw new Error("Vocabulary-Revision oder Rechte fehlen.");
      this.vocabulary = vocabulary;
      this.revision = vocabulary.meta.revision;
      if (discardDrafts) {
        this.addDraft = { id: "", label: "" };
        this.renameDrafts.clear();
      }
      this.pendingDeactivate = null;
      this.message = "";
      this.lastStatus = null;
      this.status = "ready";
      return true;
    } catch (error) {
      this._fail(error);
      return false;
    }
  }

  setAddDraft(values) {
    this.addDraft = { id: values.id ?? "", label: values.label ?? "" };
  }

  setRenameDraft(termId, label) {
    this.renameDrafts.set(termId, label);
  }

  async add(csrfToken) {
    if (!this.rights.add) return this._deny("Hinzufügen ist nicht freigegeben.");
    const term = { id: this.addDraft.id, label: this.addDraft.label };
    return this._save(
      () => this.client.addTerm(this.vocabulary.id, this.revision, term, csrfToken),
      () => { this.addDraft = { id: "", label: "" }; },
    );
  }

  async rename(termId, csrfToken) {
    if (!this.rights.rename) return this._deny("Umbenennen ist nicht freigegeben.");
    const term = this.vocabulary.terms.find(item => item.id === termId);
    const label = this.renameDrafts.get(termId) ?? term?.label ?? "";
    return this._save(
      () => this.client.renameTerm(this.vocabulary.id, termId, this.revision, label, csrfToken),
      () => { this.renameDrafts.delete(termId); },
    );
  }

  requestDeactivate(termId) {
    const term = this.vocabulary?.terms.find(item => item.id === termId);
    if (!this.rights.deactivate || !term?.active) return false;
    this.pendingDeactivate = termId;
    return true;
  }

  cancelDeactivate() {
    this.pendingDeactivate = null;
  }

  async confirmDeactivate(csrfToken) {
    if (!this.pendingDeactivate) return false;
    const termId = this.pendingDeactivate;
    const success = await this._save(
      () => this.client.deactivateTerm(this.vocabulary.id, termId, this.revision, csrfToken),
    );
    if (success) this.pendingDeactivate = null;
    return success;
  }

  async _save(request, onSuccess = () => {}) {
    this.status = "saving";
    this.message = "Speichern …";
    this.error = "";
    const previousRevision = this.revision;
    try {
      const result = await request();
      this.vocabulary = { ...result.vocabulary, meta: result.meta };
      this.revision = result.meta.revision;
      onSuccess();
      this.status = "ready";
      this.message = "Gespeichert.";
      this.lastStatus = null;
      return true;
    } catch (error) {
      this.revision = previousRevision;
      this._fail(error);
      return false;
    }
  }

  _deny(message) {
    this.status = "error";
    this.error = message;
    return false;
  }

  _fail(error) {
    this.message = "";
    this.lastStatus = error.status || null;
    if (error.status === 409 && /bereits vorhanden/i.test(error.message || "")) {
      this.status = "validation_error";
      this.error = error.message;
    } else if (error.status === 409) {
      this.status = "conflict";
      this.error = "Das Vokabular wurde inzwischen anderweitig geändert. Bitte den Serverstand neu laden.";
    } else if (error.status === 422) {
      this.status = "validation_error";
      this.error = error.message || "Die Eingabe ist ungültig.";
    } else if (error.status === 403) {
      this.status = "error";
      this.error = "Der Server hat diese Vocabulary-Änderung nicht erlaubt.";
    } else if (error.status === 404) {
      this.status = "error";
      this.error = "Vokabular oder Begriff wurde nicht gefunden.";
    } else {
      this.status = "error";
      this.error = error.message || "Die Vocabulary-Anfrage ist fehlgeschlagen.";
    }
  }
}
