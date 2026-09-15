function deepCopy(value) {
  if (typeof structuredClone === "function") return structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}

function nowIso(now = () => new Date()) {
  return now().toISOString();
}

export function createUpdateQueueEntry({operationId, moduleId, recordId, baseRevision, snapshot, queueSequence = 0, now}) {
  const timestamp = nowIso(now);
  return {
    operation_id: operationId,
    module_id: moduleId,
    operation: "update",
    record_id: recordId,
    base_revision: baseRevision,
    snapshot: deepCopy(snapshot),
    created_at: timestamp,
    updated_at: timestamp,
    status: "queued",
    attempt_count: 0,
    last_error: null,
    queue_sequence: queueSequence
  };
}

function statusForError(error) {
  if (error.status === 401 || error.status === 403) return "auth_error";
  if (error.status === 409) return "conflict";
  if (error.status === 422) return "validation_error";
  return "error";
}

function queueError(error, now) {
  return {
    message: error.userMessage || error.message || "Speichern derzeit nicht möglich.",
    http_status: error.status || null,
    uncertain: !error.status,
    occurred_at: nowIso(now)
  };
}

export function queueRecordKey(moduleId, recordId) {
  return `${moduleId}\u0000${recordId}`;
}

export function queueEntryMatchesContext(entry, context, current) {
  return Boolean(
    context &&
    entry.operation_id === context.operationId &&
    entry.module_id === current.moduleId &&
    entry.record_id === current.recordId &&
    context.formState === current.formState &&
    context.update === current.update
  );
}

export function queueStatusMessage(entries, workerRunning = false) {
  if (!entries.length) return "Alle vorgemerkten Datensätze übertragen";
  const first = entries[0];
  const label = entries.length === 1 ? "1 Speichervorgang ausstehend" : `${entries.length} Speichervorgänge ausstehend`;
  if (first.status === "saving" && workerRunning) return `${label} – Übertragung läuft`;
  if (first.status === "queued") return `${label} – lokal gesichert, Übertragung ausstehend`;
  if (first.status === "auth_error") return `${label} – pausiert: Anmeldung erforderlich`;
  if (first.status === "conflict") return `${label} – pausiert: Serverstand wurde geändert`;
  if (first.status === "validation_error") return `${label} – pausiert: lokaler Stand muss bearbeitet werden`;
  if (first.status === "confirmed") return `${label} – serverseitig bestätigt, lokale Bereinigung fehlgeschlagen`;
  return `${label} – pausiert: Übertragung fehlgeschlagen`;
}

export function createSaveQueueProcessor({store, sendUpdate, onChange = async () => {}, onSuccess = async () => {}, onError = async () => {}, lockManager = null, now}) {
  let running = false;
  const eligibleOperationIds = new Set();

  async function notify(entry = null) {
    await onChange(entry ? deepCopy(entry) : null, await store.list());
  }

  async function enqueueUpdate({operationId, moduleId, recordId, baseRevision, snapshot}) {
    const entries = await store.list();
    const key = queueRecordKey(moduleId, recordId);
    if (entries.some(entry => queueRecordKey(entry.module_id, entry.record_id) === key)) {
      throw new Error("Für diesen Datensatz ist bereits ein Speichervorgang vorgemerkt.");
    }
    const queueSequence = Math.max(0, ...entries.map(entry => Number(entry.queue_sequence) || 0)) + 1;
    const entry = createUpdateQueueEntry({operationId, moduleId, recordId, baseRevision, snapshot, queueSequence, now});
    const persisted = await store.put(entry);
    try {
      await notify(persisted);
    } catch (error) {
      error.queuePersisted = true;
      error.persistedEntry = deepCopy(persisted);
      throw error;
    }
    eligibleOperationIds.add(persisted.operation_id);
    return persisted;
  }

  async function fail(entry, error) {
    const failed = await store.update(entry.operation_id, {
      status: statusForError(error),
      updated_at: nowIso(now),
      last_error: queueError(error, now)
    });
    await notify(failed);
    await onError(deepCopy(failed), error, {stage: "remote"});
    return failed;
  }

  async function runSequentially() {
    if (running) return false;
    running = true;
    try {
      while (true) {
        const entries = await store.list();
        const next = entries[0];
        if (!next || next.status !== "queued") return true;
        if (!eligibleOperationIds.has(next.operation_id)) return false;
        const saving = await store.update(next.operation_id, {
          status: "saving",
          attempt_count: next.attempt_count + 1,
          updated_at: nowIso(now),
          last_error: null
        });
        await notify(saving);
        let result;
        try {
          result = await sendUpdate(deepCopy(saving));
        } catch (error) {
          eligibleOperationIds.delete(saving.operation_id);
          await fail(saving, error);
          return false;
        }

        eligibleOperationIds.delete(saving.operation_id);
        let confirmed;
        try {
          confirmed = await store.update(saving.operation_id, {
            status: "confirmed",
            updated_at: nowIso(now),
            confirmed_revision: result?.meta?.revision || null,
            last_error: null
          });
          await onSuccess(deepCopy(confirmed), result);
          await store.remove(saving.operation_id);
          await notify(null);
        } catch (error) {
          await onError(deepCopy(confirmed || saving), error, {stage: "cleanup", remoteConfirmed: true});
          await notify(confirmed || saving);
          return false;
        }
      }
    } finally {
      running = false;
    }
  }

  async function process() {
    if (!lockManager?.request) return runSequentially();
    return lockManager.request("erschliessung-save-queue", {ifAvailable: true}, lock => (
      lock ? runSequentially() : false
    ));
  }

  return {enqueueUpdate, process, isRunning: () => running};
}
