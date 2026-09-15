export class RecordCreate {
  constructor(moduleKey, formState, request = (url, options) => fetch(url, options)) {
    Object.assign(this, {moduleKey, formState, request});
    this.saving = false;
    this.recordId = null;
    this.revision = null;
  }

  canSave(mode) {
    return mode === "edit" && this.formState.isDirty() && !this.saving;
  }

  async save(mode, csrfToken) {
    if (!this.canSave(mode)) return null;
    const body = JSON.stringify({record: this.formState.buildPayload()});
    this.saving = true;
    try {
      let response;
      try {
        response = await this.request(`/api/modules/${encodeURIComponent(this.moduleKey)}/records`, {
          method: "POST", credentials: "same-origin",
          headers: {"Content-Type": "application/json", "X-CSRF-Token": csrfToken}, body
        });
      } catch {
        throw new Error("Netzwerkfehler beim Anlegen. Ihr Entwurf bleibt erhalten; bitte erneut versuchen.");
      }
      if (response.status === 422 || response.status === 403) {
        const data = await response.json();
        const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || "");
        throw new Error(`Anlegen abgelehnt: ${detail}`);
      }
      if (response.status === 401) throw new Error("Anmeldung abgelaufen. Ihr Entwurf bleibt erhalten.");
      if (!response.ok) throw new Error("Anlegen fehlgeschlagen. Ihr Entwurf bleibt erhalten; bitte erneut versuchen.");
      const data = await response.json();
      if (data.module !== this.moduleKey || !data.record_id || !data.record || typeof data.record !== "object" || Array.isArray(data.record) || !data.meta?.revision) {
        throw new Error("Serverantwort unvollständig. Speicherstand unklar; Ihr Entwurf bleibt erhalten.");
      }
      this.formState.reset(data.record);
      this.recordId = data.record_id;
      this.revision = data.meta.revision;
      return data;
    } finally {
      this.saving = false;
    }
  }
}
