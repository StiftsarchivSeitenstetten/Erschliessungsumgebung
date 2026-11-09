// Queue worker used exclusively by the generic module application.
function deepCopy(value) {
  if (typeof structuredClone === "function") return structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}

function nowIso(now = () => new Date()) {
  return now().toISOString();
}

export function createUpdateQueueEntry({operationId, moduleId, recordId, baseRevision, snapshot, queueSequence = 0, now, action}) {
  const timestamp = nowIso(now);
  return {
    ...(action ? {action} : {}),
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

export function createCreateQueueEntry({operationId, moduleId, identityAssignment, snapshot, queueSequence = 0, now, action}) {
  const timestamp = nowIso(now);
  return {
    ...(action ? {action} : {}),
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

const KNOWN_STATUSES = new Set(["reserving", "reserved", "queued", "saving", "confirmed", "auth_error", "conflict", "validation_error", "error"]);

function completeReservation(entry) {
  return typeof entry.record_id === "string" && Boolean(entry.record_id) && entry.identity?.id === entry.record_id &&
    (entry.identity_paths || ["id"]).every(path => typeof entry.identity?.[path] === "string" && Boolean(entry.identity[path]));
}

export function normalizeQueueEntry(entry, now) {
  const normalized = deepCopy(entry);
  normalized.attempt_count = Number.isInteger(normalized.attempt_count) && normalized.attempt_count >= 0 ? normalized.attempt_count : 0;
  normalized.last_error = normalized.last_error || null;
  normalized.updated_at = normalized.updated_at || normalized.created_at || nowIso(now);
  if (normalized.operation === "reservation") {
    const valid = normalized.operation_id && normalized.module_id && normalized.identity_inputs &&
      typeof normalized.identity_inputs === "object" && !Array.isArray(normalized.identity_inputs) &&
      ["reserving", "reserved", "auth_error", "conflict", "validation_error", "error"].includes(normalized.status) &&
      (normalized.status !== "reserved" || completeReservation(normalized));
    if (!valid) {
      normalized.status = "error";
      normalized.last_error = {message: "Lokale Reservierung ist unvollständig.", uncertain: true};
    }
    return normalized;
  }
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
  if (entries[0].operation === "reservation") {
    return entries[0].status === "reserved"
      ? "Identität reserviert; fachlicher Datensatz noch nicht gespeichert."
      : "Lokale Reservierung vorhanden; Identität noch nicht bestätigt. Wiederaufnahme möglich.";
  }
  const first = entries[0];
  const label = entries.length === 1 ? "1 Speichervorgang ausstehend" : `${entries.length} Speichervorgänge ausstehend`;
  if (first.last_error?.message?.startsWith("Lokaler Snapshot pausiert:")) return `${label} – ${first.last_error.message}${first.last_error.uncertain ? " Ergebnis der bisherigen Übertragung bleibt ungeklärt." : ""}`;
  if (first.status === "saving" && workerRunning) return `${label} – Übertragung läuft`;
  if (first.status === "saving") return `${label} – Ergebnis der letzten Übertragung ungeklärt`;
  if (first.status === "reserving" && workerRunning) return `${label} – Identität wird reserviert`;
  if (first.status === "reserving") return `${label} – lokal gesichert, Identitätsreservation ausstehend`;
  if (first.status === "queued") return `${label} – lokal gesichert, Übertragung ausstehend`;
  if (first.status === "auth_error") return `${label} – pausiert: Anmeldung erforderlich`;
  if (first.status === "conflict") return `${label} – pausiert: Serverstand wurde geändert`;
  if (first.status === "validation_error") return `${label} – pausiert: ${first.last_error?.message || "lokaler Stand muss bearbeitet werden"}`;
  if (first.status === "confirmed") return `${label} – serverseitig bestätigt, lokale Bereinigung fehlgeschlagen`;
  if (first.status === "error" && first.last_error?.uncertain) return `${label} – Ergebnis der letzten Übertragung ungeklärt`;
  return `${label} – pausiert: Übertragung fehlgeschlagen`;
}

export function createSaveQueueProcessor({store, sendUpdate, sendCreate, reserveIdentity, resolveUpdate, validateSnapshot = async () => {}, onChange = async () => {}, onReserved = async () => {}, onSuccess = async () => {}, onError = async () => {}, lockManager = null, now}) {
  let running = false;
  const eligibleOperationIds = new Set();
  const reservationRequests = new Map();

  async function checkSnapshot(entry) {
    try {
      await validateSnapshot(deepCopy(entry));
      return true;
    } catch (error) {
      // Never change the request, identity or operation ID. An ambiguous remote
      // outcome must remain ambiguous and use the existing read-back/retry path.
      const uncertain = entry.status === "saving" || entry.status === "confirmed" || Boolean(entry.last_error?.uncertain);
      const paused = await store.update(entry.operation_id, {
        status: uncertain ? "error" : "validation_error",
        last_error: {...queueError(error, now), uncertain, message: `Lokaler Snapshot pausiert: ${error.message}`}
      });
      eligibleOperationIds.delete(entry.operation_id);
      await notify(paused);
      await onError(deepCopy(paused), error, {stage: "validation"});
      return false;
    }
  }

  async function prepareReservationUnlocked({operationId, moduleId, identityInputs, identityPaths = ["id"]}) {
    const existing = await store.get(operationId);
    if (existing) {
      if (existing.operation !== "reservation" || existing.module_id !== moduleId || !sameEntry(existing.identity_inputs, identityInputs)) {
        throw new Error("Operations-ID wird bereits für eine andere Operation verwendet.");
      }
      return existing;
    }
    const timestamp = nowIso(now);
    const entry = await store.put({
      operation_id: operationId, module_id: moduleId, operation: "reservation",
      identity_inputs: deepCopy(identityInputs), identity_assignment: "reserve_before_create",
      identity_paths: deepCopy(identityPaths),
      record_id: null, identity: null, status: "reserving", attempt_count: 0,
      created_at: timestamp, updated_at: timestamp, last_error: null
    });
    await notify(entry);
    return entry;
  }

  async function prepareReservation(options) {
    return lockManager?.request
      ? lockManager.request(`erschliessung-reservation:${options.operationId}`, () => prepareReservationUnlocked(options))
      : prepareReservationUnlocked(options);
  }

  async function resumeReservation(operationId) {
    if (reservationRequests.has(operationId)) return reservationRequests.get(operationId);
    const attempt = async () => {
      let entry = await store.get(operationId);
      if (!entry || entry.operation !== "reservation") throw new Error("Lokale Reservierung nicht gefunden.");
      if (entry.status === "reserved" && completeReservation(entry)) return entry;
      if (!entry.identity_inputs || typeof entry.identity_inputs !== "object" || Array.isArray(entry.identity_inputs)) {
        throw new Error("Vergabeeingaben fehlen; Reservierung kann nicht wiederholt werden.");
      }
      entry = await store.update(operationId, {status: "reserving", attempt_count: entry.attempt_count + 1, last_error: null});
      await notify(entry);
      try {
        // One attempt per explicit resume. A conflict never changes the operation ID.
        const reservation = await reserveIdentity(deepCopy(entry));
        if (!completeReservation({...entry, record_id: reservation.record_id, identity: reservation.identity})) {
          throw new Error("Reservationsantwort unvollständig.");
        }
        const reserved = await store.update(operationId, {
          status: "reserved", record_id: reservation.record_id, identity: deepCopy(reservation.identity),
          updated_at: nowIso(now), last_error: null
        });
        await notify(reserved);
        return reserved;
      } catch (error) {
        await fail(entry, error);
        throw error;
      }
    };
    const promise = lockManager?.request
      ? lockManager.request(`erschliessung-reservation:${operationId}`, attempt)
      : attempt();
    reservationRequests.set(operationId, promise);
    try { return await promise; } finally {
      reservationRequests.delete(operationId);
      await notify(null);
    }
  }

  async function notify(entry = null) {
    await onChange(entry ? deepCopy(entry) : null, await store.list());
  }

  async function enqueueUpdate({operationId, moduleId, recordId, baseRevision, snapshot, action}) {
    const entries = await store.list();
    const key = queueRecordKey(moduleId, recordId);
    if (entries.some(entry => queueRecordKey(entry.module_id, entry.record_id) === key)) {
      throw new Error("Für diesen Datensatz ist bereits ein Speichervorgang vorgemerkt.");
    }
    const queueSequence = Math.max(0, ...entries.map(entry => Number(entry.queue_sequence) || 0)) + 1;
    const entry = createUpdateQueueEntry({operationId, moduleId, recordId, baseRevision, snapshot, queueSequence, now, action});
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

  async function enqueueCreateUnlocked({operationId, moduleId, identityAssignment, snapshot, requireReservation = false, action}) {
    if (!["on_create", "reserve_before_create"].includes(identityAssignment)) {
      throw new Error(`Unbekannte Create-Strategie: ${identityAssignment}`);
    }
    const entries = await store.list();
    const reservation = entries.find(entry => entry.operation_id === operationId);
    if (requireReservation && !reservation) throw new Error("Lokale Reservierung fehlt. Keine erneute Vergabe gestartet.");
    if (reservation && (reservation.operation !== "reservation" || reservation.module_id !== moduleId ||
        reservation.status !== "reserved" || !completeReservation(reservation) || identityAssignment !== "reserve_before_create")) {
      throw new Error("Create benötigt eine bestätigte, noch nicht übernommene Reservierung.");
    }
    const queueSequence = Math.max(0, ...entries.map(entry => Number(entry.queue_sequence) || 0)) + 1;
    const entry = createCreateQueueEntry({operationId, moduleId, identityAssignment, snapshot, queueSequence, now, action});
    if (reservation) {
      entry.record_id = reservation.record_id;
      entry.identity = deepCopy(reservation.identity);
      entry.status = "queued";
    }
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

  async function enqueueCreate(options) {
    return lockManager?.request
      ? lockManager.request(`erschliessung-reservation:${options.operationId}`, () => enqueueCreateUnlocked(options))
      : enqueueCreateUnlocked(options);
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
        const next = entries.find(entry => entry.operation !== "reservation");
        if (!next || !["queued", "reserving"].includes(next.status)) return true;
        if (!eligibleOperationIds.has(next.operation_id)) return false;
        if (!await checkSnapshot(next)) return false;
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
      await notify(null);
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
      if (safelyRestartable(persisted) && await checkSnapshot(persisted)) eligibleOperationIds.add(persisted.operation_id);
    }
    await notify(null);
    return store.list();
  }

  async function retryFirst() {
    if (running) return false;
    const next = (await store.list())[0];
    if (next?.operation === "reservation") {
      await resumeReservation(next.operation_id);
      return true;
    }
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

    if (!await checkSnapshot(next)) return false;
    let status = "queued";
    if (next.operation === "create" && next.identity_assignment === "reserve_before_create" && !next.identity) status = "reserving";
    const retrying = await store.update(next.operation_id, {status, updated_at: nowIso(now), last_error: null});
    eligibleOperationIds.add(retrying.operation_id);
    await notify(retrying);
    return process();
  }

  async function discard(operationId) {
    if (running || reservationRequests.has(operationId)) throw new Error("Eine laufende Übertragung kann nicht lokal verworfen werden.");
    const entry = await store.get(operationId);
    if (!entry) return false;
    eligibleOperationIds.delete(operationId);
    await store.remove(operationId);
    await notify(null);
    return true;
  }

  return {prepareReservation, resumeReservation, enqueueUpdate, enqueueCreate, process, initializeRecovery, retryFirst, discard, isRunning: () => running || reservationRequests.size > 0};
}
