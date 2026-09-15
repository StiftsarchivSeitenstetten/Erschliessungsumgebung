export class RecordUpdate {
  constructor(moduleKey, recordId, formState, revision, request = (url, options) => fetch(url, options)) {
    Object.assign(this, {moduleKey, recordId, formState, revision, request});
    this.saving = false;
  }

  canSave(mode) {
    return mode === "edit" && Boolean(this.recordId && this.revision) && this.formState.isDirty() && !this.saving;
  }

  async save(mode, csrfToken) {
    if (!this.canSave(mode)) return null;
    const body = JSON.stringify({base_revision: this.revision, record: this.formState.beginSave()});
    this.saving = true;
    try {
      let response;
      try {
        response = await this.request(`/api/modules/${encodeURIComponent(this.moduleKey)}/records/${encodeURIComponent(this.recordId)}`, {
        method: "PUT", credentials: "same-origin",
        headers: {"Content-Type": "application/json", "X-CSRF-Token": csrfToken}, body
        });
      } catch {
        throw new Error("Netzwerkfehler beim Speichern. Ihre Änderungen bleiben erhalten; bitte den Speicherstand vor einem erneuten Versuch prüfen.");
      }
      if (response.status === 409) throw new Error("Der Datensatz wurde zwischenzeitlich geändert. Ihre Änderungen bleiben erhalten; es wurde nichts überschrieben.");
      if (response.status === 422 || response.status === 403) {
        const data = await response.json();
        const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || "");
        throw new Error(`Speichern abgelehnt: ${detail}`);
      }
      if (response.status === 401) throw new Error("Anmeldung abgelaufen. Ihre Änderungen bleiben erhalten.");
      if (!response.ok) throw new Error("Speichern fehlgeschlagen. Ihre Änderungen bleiben erhalten. Bitte erneut versuchen.");
      const data = await response.json();
      if (data.record_id !== this.recordId || !data.record || typeof data.record !== "object" || Array.isArray(data.record) || !data.meta?.revision) {
        throw new Error("Serverantwort unvollständig. Speicherstand unklar; Ihre Änderungen bleiben erhalten.");
      }
      this.formState.confirmSave(data.record);
      this.revision = data.meta.revision;
      return data;
    } catch (error) {
      this.formState.cancelSave();
      throw error;
    } finally {
      this.saving = false;
    }
  }
}
