(function exposeSaveQueueStore(global) {
  const DEFAULT_DATABASE_NAME = "Erschliessungsumgebung";
  const DEFAULT_DATABASE_VERSION = 1;
  const DEFAULT_STORE_NAME = "save_queue";

  function requestResult(request) {
    return new Promise((resolve, reject) => {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error("IndexedDB-Anfrage fehlgeschlagen."));
    });
  }

  function transactionDone(transaction) {
    return new Promise((resolve, reject) => {
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error || new Error("IndexedDB-Transaktion fehlgeschlagen."));
      transaction.onabort = () => reject(transaction.error || new Error("IndexedDB-Transaktion wurde abgebrochen."));
    });
  }

  function cloneValue(value) {
    if (typeof structuredClone === "function") return structuredClone(value);
    return JSON.parse(JSON.stringify(value));
  }

  function createIndexedDbSaveQueueStore({
    indexedDB,
    databaseName = DEFAULT_DATABASE_NAME,
    databaseVersion = DEFAULT_DATABASE_VERSION,
    storeName = DEFAULT_STORE_NAME
  }) {
    if (!indexedDB) throw new Error("IndexedDB ist in diesem Browser nicht verfügbar.");
    let databasePromise = null;

    function open() {
      if (databasePromise) return databasePromise;
      databasePromise = new Promise((resolve, reject) => {
        const request = indexedDB.open(databaseName, databaseVersion);
        request.onupgradeneeded = () => {
          const database = request.result;
          if (!database.objectStoreNames.contains(storeName)) {
            const store = database.createObjectStore(storeName, { keyPath: "operation_id" });
            store.createIndex("status", "status", { unique: false });
            store.createIndex("created_at", "created_at", { unique: false });
          }
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error || new Error("IndexedDB konnte nicht geöffnet werden."));
      });
      return databasePromise;
    }

    async function put(entry) {
      const database = await open();
      const transaction = database.transaction(storeName, "readwrite");
      transaction.objectStore(storeName).put(cloneValue(entry));
      await transactionDone(transaction);
      return cloneValue(entry);
    }

    async function get(operationId) {
      const database = await open();
      const transaction = database.transaction(storeName, "readonly");
      const result = await requestResult(transaction.objectStore(storeName).get(operationId));
      await transactionDone(transaction);
      return result ? cloneValue(result) : null;
    }

    async function list() {
      const database = await open();
      const transaction = database.transaction(storeName, "readonly");
      const result = await requestResult(transaction.objectStore(storeName).getAll());
      await transactionDone(transaction);
      return result.map(cloneValue).sort((left, right) => left.created_at.localeCompare(right.created_at));
    }

    async function update(operationId, changes) {
      const database = await open();
      const transaction = database.transaction(storeName, "readwrite");
      const store = transaction.objectStore(storeName);
      const existing = await requestResult(store.get(operationId));
      if (!existing) {
        transaction.abort();
        throw new Error(`Queue-Eintrag nicht gefunden: ${operationId}`);
      }
      const updated = { ...existing, ...cloneValue(changes) };
      store.put(updated);
      await transactionDone(transaction);
      return cloneValue(updated);
    }

    async function remove(operationId) {
      const database = await open();
      const transaction = database.transaction(storeName, "readwrite");
      transaction.objectStore(storeName).delete(operationId);
      await transactionDone(transaction);
    }

    return {
      databaseName,
      databaseVersion,
      storeName,
      open,
      put,
      get,
      list,
      update,
      remove
    };
  }

  global.createIndexedDbSaveQueueStore = createIndexedDbSaveQueueStore;
})(typeof globalThis === "undefined" ? window : globalThis);
