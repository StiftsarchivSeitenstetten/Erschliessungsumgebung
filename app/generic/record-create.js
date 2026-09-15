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
    const body = JSON.stringify({record: this.formState.beginSave()});
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
      this.formState.confirmSave(data.record);
      this.recordId = data.record_id;
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

async function checkedJson(response) {
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || "");
    const error = new Error(detail || `HTTP ${response.status}`);
    error.status = response.status;
    error.userMessage = detail;
    throw error;
  }
  return response.json();
}

export async function reserveQueuedRecordIdentity(entry, csrfToken, request = (url, options) => fetch(url, options)) {
  const response = await request(`/api/modules/${encodeURIComponent(entry.module_id)}/reservations`, {
    method: "POST",
    credentials: "same-origin",
    headers: {"Content-Type": "application/json", "X-CSRF-Token": csrfToken},
    body: JSON.stringify({operation_id: entry.operation_id, record: entry.snapshot})
  });
  const data = await checkedJson(response);
  if (data.module !== entry.module_id || data.operation_id !== entry.operation_id || !data.record_id || !data.identity) {
    throw new Error("Reservationsantwort unvollständig. Der Queue-Eintrag bleibt erhalten.");
  }
  return data;
}

export async function sendQueuedRecordCreate(entry, csrfToken, request = (url, options) => fetch(url, options)) {
  const response = await request(`/api/modules/${encodeURIComponent(entry.module_id)}/records`, {
    method: "POST",
    credentials: "same-origin",
    headers: {"Content-Type": "application/json", "X-CSRF-Token": csrfToken},
    body: JSON.stringify({record: entry.snapshot, operation_id: entry.operation_id, identity: entry.identity})
  });
  const data = await checkedJson(response);
  if (data.module !== entry.module_id || !data.record_id || !data.record || !data.meta?.revision) {
    throw new Error("Serverantwort unvollständig. Der Queue-Eintrag bleibt erhalten.");
  }
  if (entry.record_id && data.record_id !== entry.record_id) {
    throw new Error("Server bestätigte eine andere als die reservierte Record-ID.");
  }
  return data;
}
