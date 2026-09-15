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

export function createCreateQueueEntry({operationId, moduleId, identityAssignment, snapshot, queueSequence = 0, now}) {
  const timestamp = nowIso(now);
  return {
    operation_id: operationId,
    module_id: moduleId,
    operation: "create",
    record_id: null,
    identity: null,
    base_revision: null,
    snapshot: deepCopy(snapshot),
    identity_assignment: identityAssignment,
    created_at: timestamp,
    updated_at: timestamp,
    status: identityAssignment === "reserve_before_create" ? "reserving" : "queued",
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

const KNOWN_STATUSES = new Set(["reserving", "queued", "saving", "confirmed", "auth_error", "conflict", "validation_error", "error"]);

export function normalizeQueueEntry(entry, now) {
  const normalized = deepCopy(entry);
  normalized.attempt_count = Number.isInteger(normalized.attempt_count) && normalized.attempt_count >= 0 ? normalized.attempt_count : 0;
  normalized.last_error = normalized.last_error || null;
  normalized.updated_at = normalized.updated_at || normalized.created_at || nowIso(now);
  if (normalized.operation === "create" && normalized.identity_assignment === "reserve_before_create" &&
      normalized.status === "reserving" && normalized.record_id && normalized.identity) {
    normalized.status = "queued";
  }
  const snapshotValid = normalized.snapshot && typeof normalized.snapshot === "object" && !Array.isArray(normalized.snapshot);
  const updateValid = normalized.operation !== "update" || Boolean(normalized.record_id && normalized.base_revision);
  const createValid = normalized.operation !== "create" || ["on_create", "reserve_before_create"].includes(normalized.identity_assignment);
  const reservationPairValid = normalized.operation !== "create" || normalized.identity_assignment !== "reserve_before_create" ||
    Boolean(normalized.record_id) === Boolean(normalized.identity);
  const reservingValid = normalized.status !== "reserving" || (
    normalized.operation === "create" && normalized.identity_assignment === "reserve_before_create"
  );
  if (!["create", "update"].includes(normalized.operation) || !normalized.operation_id || !normalized.module_id ||
      !snapshotValid || !updateValid || !createValid || !reservationPairValid || !reservingValid || !KNOWN_STATUSES.has(normalized.status)) {
    normalized.status = "error";
    normalized.last_error = {
      message: "Persistierter Queue-Eintrag ist unvollständig oder unbekannt.",
      http_status: null,
      uncertain: true,
      occurred_at: nowIso(now)
    };
  }
  return normalized;
}

function sameEntry(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function safelyRestartable(entry) {
  return entry.status === "queued" || (
    entry.status === "reserving" && entry.operation === "create" &&
    entry.identity_assignment === "reserve_before_create" && !entry.record_id && !entry.identity
  );
}

export function queueRecordKey(moduleId, recordId) {
  return `${moduleId}\u0000${recordId}`;
}

export function queueEntryMatchesContext(entry, context, current) {
  const common = Boolean(
    context &&
    entry.operation_id === context.operationId &&
    entry.module_id === current.moduleId &&
    context.formState === current.formState
  );
  if (!common) return false;
  if (entry.operation === "create") {
    return context.create === current.create && current.creating === true && (
      current.recordId === null || entry.record_id === null || entry.record_id === current.recordId
    );
  }
  return entry.record_id === current.recordId && context.update === current.update;
}

export function queueStatusMessage(entries, workerRunning = false) {
  if (!entries.length) return "Alle vorgemerkten Datensätze übertragen";
  const first = entries[0];
  const label = entries.length === 1 ? "1 Speichervorgang ausstehend" : `${entries.length} Speichervorgänge ausstehend`;
  if (first.status === "saving" && workerRunning) return `${label} – Übertragung läuft`;
  if (first.status === "saving") return `${label} – Ergebnis der letzten Übertragung ungeklärt`;
  if (first.status === "reserving" && workerRunning) return `${label} – Identität wird reserviert`;
  if (first.status === "reserving") return `${label} – lokal gesichert, Identitätsreservation ausstehend`;
  if (first.status === "queued") return `${label} – lokal gesichert, Übertragung ausstehend`;
  if (first.status === "auth_error") return `${label} – pausiert: Anmeldung erforderlich`;
  if (first.status === "conflict") return `${label} – pausiert: Serverstand wurde geändert`;
  if (first.status === "validation_error") return `${label} – pausiert: lokaler Stand muss bearbeitet werden`;
  if (first.status === "confirmed") return `${label} – serverseitig bestätigt, lokale Bereinigung fehlgeschlagen`;
  if (first.status === "error" && first.last_error?.uncertain) return `${label} – Ergebnis der letzten Übertragung ungeklärt`;
  return `${label} – pausiert: Übertragung fehlgeschlagen`;
}

export function createSaveQueueProcessor({store, sendUpdate, sendCreate, reserveIdentity, resolveUpdate, onChange = async () => {}, onReserved = async () => {}, onSuccess = async () => {}, onError = async () => {}, lockManager = null, now}) {
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

  async function enqueueCreate({operationId, moduleId, identityAssignment, snapshot}) {
    if (!["on_create", "reserve_before_create"].includes(identityAssignment)) {
      throw new Error(`Unbekannte Create-Strategie: ${identityAssignment}`);
    }
    const entries = await store.list();
    const queueSequence = Math.max(0, ...entries.map(entry => Number(entry.queue_sequence) || 0)) + 1;
    const entry = createCreateQueueEntry({operationId, moduleId, identityAssignment, snapshot, queueSequence, now});
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

  async function confirmAndRemove(entry, result) {
    let confirmed;
    try {
      confirmed = await store.update(entry.operation_id, {
        status: "confirmed",
        updated_at: nowIso(now),
        confirmed_revision: result?.meta?.revision || null,
        last_error: null
      });
      await onSuccess(deepCopy(confirmed), result);
      await store.remove(entry.operation_id);
      await notify(null);
      return true;
    } catch (error) {
      await onError(deepCopy(confirmed || entry), error, {stage: "cleanup", remoteConfirmed: true});
      await notify(confirmed || entry);
      return false;
    }
  }

  async function runSequentially() {
    if (running) return false;
    running = true;
    try {
      while (true) {
        const entries = await store.list();
        const next = entries[0];
        if (!next || !["queued", "reserving"].includes(next.status)) return true;
        if (!eligibleOperationIds.has(next.operation_id)) return false;
        if (next.status === "reserving") {
          const reserving = await store.update(next.operation_id, {
            attempt_count: next.attempt_count + 1,
            updated_at: nowIso(now),
            last_error: null
          });
          await notify(reserving);
          try {
            if (!reserveIdentity) throw new Error("Reservationshandler fehlt.");
            const reservation = await reserveIdentity(deepCopy(reserving));
            const queued = await store.update(reserving.operation_id, {
              record_id: reservation.record_id,
              identity: deepCopy(reservation.identity),
              status: "queued",
              updated_at: nowIso(now),
              last_error: null
            });
            await onReserved(deepCopy(queued), reservation);
            await notify(queued);
            continue;
          } catch (error) {
            eligibleOperationIds.delete(reserving.operation_id);
            await fail(reserving, error);
            return false;
          }
        }
        const saving = await store.update(next.operation_id, {
          status: "saving",
          attempt_count: next.attempt_count + 1,
          updated_at: nowIso(now),
          last_error: null
        });
        await notify(saving);
        let result;
        try {
          const handler = saving.operation === "update" ? sendUpdate : sendCreate;
          if (!handler) throw new Error(`Handler fuer Queue-Operation fehlt: ${saving.operation}`);
          result = await handler(deepCopy(saving));
        } catch (error) {
          eligibleOperationIds.delete(saving.operation_id);
          await fail(saving, error);
          return false;
        }

        eligibleOperationIds.delete(saving.operation_id);
        if (!await confirmAndRemove(saving, result)) return false;
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

  async function initializeRecovery() {
    const entries = await store.list();
    for (const entry of entries) {
      const normalized = normalizeQueueEntry(entry, now);
      const persisted = sameEntry(entry, normalized) ? normalized : await store.update(entry.operation_id, normalized);
      if (safelyRestartable(persisted)) eligibleOperationIds.add(persisted.operation_id);
    }
    await notify(null);
    return store.list();
  }

  async function retryFirst() {
    if (running) return false;
    const next = (await store.list())[0];
    if (!next || ["conflict", "validation_error"].includes(next.status)) return false;

    if (next.operation === "update" && ["saving", "confirmed", "error"].includes(next.status)) {
      try {
        if (!resolveUpdate) throw new Error("PUT-Read-back-Handler fehlt.");
        const resolution = await resolveUpdate(deepCopy(next));
        if (resolution.outcome === "applied") return confirmAndRemove(next, resolution.result);
        if (resolution.outcome === "conflict") {
          const conflict = new Error("Serverstand weicht vom lokalen Queue-Snapshot ab.");
          conflict.status = 409;
          conflict.userMessage = conflict.message;
          await fail(next, conflict);
          return false;
        }
        if (resolution.outcome !== "not_applied") throw new Error("PUT-Read-back lieferte keine eindeutige Auflösung.");
      } catch (error) {
        await fail(next, error);
        return false;
      }
    }

    let status = "queued";
    if (next.operation === "create" && next.identity_assignment === "reserve_before_create" && !next.identity) status = "reserving";
    const retrying = await store.update(next.operation_id, {status, updated_at: nowIso(now), last_error: null});
    eligibleOperationIds.add(retrying.operation_id);
    await notify(retrying);
    return process();
  }

  async function discard(operationId) {
    if (running) throw new Error("Eine laufende Übertragung kann nicht lokal verworfen werden.");
    const entry = await store.get(operationId);
    if (!entry) return false;
    eligibleOperationIds.delete(operationId);
    await store.remove(operationId);
    await notify(null);
    return true;
  }

  return {enqueueUpdate, enqueueCreate, process, initializeRecovery, retryFirst, discard, isRunning: () => running};
}
