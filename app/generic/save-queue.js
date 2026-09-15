(function exposeSaveQueue(global) {
  function deepCopy(value) {
    if (typeof structuredClone === "function") return structuredClone(value);
    return JSON.parse(JSON.stringify(value));
  }

  function nowIso() {
    return new Date().toISOString();
  }

  function createSaveQueueEntry({
    operationId,
    operation,
    recordId = null,
    signature = null,
    partition = null,
    baseRevision = null,
    snapshot,
    status = "queued"
  }) {
    const timestamp = nowIso();
    return {
      operation_id: operationId,
      operation,
      record_id: recordId,
      signature,
      partition,
      base_revision: baseRevision,
      snapshot: deepCopy(snapshot),
      created_at: timestamp,
      updated_at: timestamp,
      status,
      attempt_count: 0,
      last_error: null
    };
  }

  function queueError(error) {
    return {
      message: error.userMessage || "Speichern derzeit nicht möglich. Ihre Änderungen bleiben erhalten.",
      http_status: error.status || null,
      uncertain: !error.status,
      occurred_at: nowIso()
    };
  }

  function statusForError(error) {
    if (error.status === 401 || error.status === 403) return "auth_error";
    if (error.status === 409) return "conflict";
    if (error.status === 422) return "validation_error";
    return "error";
  }

  function createSaveQueueProcessor({ store, handlers, onChange = async () => {}, lockManager = null }) {
    let running = false;
    let remoteTail = Promise.resolve();

    function runRemote(task) {
      if (lockManager?.request) return lockManager.request("erschliessung-save-queue", task);
      const result = remoteTail.then(task, task);
      remoteTail = result.catch(() => {});
      return result;
    }

    async function notify(entry = null) {
      await onChange(entry, await store.list());
    }

    async function fail(operationId, error) {
      const failed = await store.update(operationId, {
        status: statusForError(error),
        updated_at: nowIso(),
        last_error: queueError(error)
      });
      await notify(failed);
      return failed;
    }

    async function reserve(operationId, reserveHandler) {
      const entry = await store.get(operationId);
      if (!entry || entry.status !== "reserving") throw new Error("Reservierbarer Queue-Eintrag fehlt.");
      const attempting = await store.update(operationId, {
        attempt_count: entry.attempt_count + 1,
        updated_at: nowIso(),
        last_error: null
      });
      await notify(attempting);
      try {
        const reservation = await runRemote(() => reserveHandler(deepCopy(attempting)));
        const queued = await store.update(operationId, {
          record_id: reservation.record_id,
          signature: reservation.signature,
          partition: reservation.partition,
          status: "queued",
          updated_at: nowIso(),
          last_error: null
        });
        await notify(queued);
        return { entry: deepCopy(queued), reservation: deepCopy(reservation) };
      } catch (error) {
        await fail(operationId, error);
        throw error;
      }
    }

    async function runSequentially(ownsGlobalLock = false) {
      if (running) return false;
      running = true;
      try {
        while (true) {
          const entries = await store.list();
          const next = entries[0];
          if (!next || next.status !== "queued") return true;
          const saving = await store.update(next.operation_id, {
            status: "saving",
            attempt_count: next.attempt_count + 1,
            updated_at: nowIso(),
            last_error: null
          });
          await notify(saving);
          let result;
          try {
            const handler = handlers[saving.operation];
            if (!handler) throw new Error(`Unbekannte Queue-Operation: ${saving.operation}`);
            const send = () => handler(deepCopy(saving));
            result = ownsGlobalLock ? await send() : await runRemote(send);
          } catch (error) {
            const failed = await fail(saving.operation_id, error);
            if (handlers.onError) await handlers.onError(deepCopy(failed), error);
            return false;
          }
          await store.remove(saving.operation_id);
          await notify(null);
          if (handlers.onSuccess) await handlers.onSuccess(deepCopy(saving), result);
        }
      } finally {
        running = false;
      }
    }

    async function process() {
      if (lockManager?.request) {
        return lockManager.request("erschliessung-save-queue", { ifAvailable: true }, (lock) => {
          if (!lock) return false;
          return runSequentially(true);
        });
      }
      return runSequentially(false);
    }

    async function requeue(operationId, status = "queued") {
      const entry = await store.update(operationId, {
        status,
        updated_at: nowIso(),
        last_error: null
      });
      await notify(entry);
      return entry;
    }

    async function resolve(operationId, result) {
      const entry = await store.get(operationId);
      if (!entry) return false;
      await store.remove(operationId);
      await notify(null);
      if (handlers.onSuccess) await handlers.onSuccess(deepCopy(entry), result);
      return true;
    }

    return { reserve, process, requeue, resolve, fail, isRunning: () => running };
  }

  global.deepCopySaveSnapshot = deepCopy;
  global.createSaveQueueEntry = createSaveQueueEntry;
  global.createSaveQueueProcessor = createSaveQueueProcessor;
})(typeof globalThis === "undefined" ? window : globalThis);
