import {cloneValue, getPathValue, setPathValue} from './path-utils.js';

export function nextRecordSeed(descriptor, current) {
  const config = descriptor.create?.next_record;
  if (!config) throw new Error('Fortlaufende Erfassung ist nicht aktiviert.');
  const seed = cloneValue(descriptor.empty_record || {});
  for (const path of config.carry_fields) {
    const value = getPathValue(current, path);
    if (value !== undefined) setPathValue(seed, path, cloneValue(value));
  }
  return seed;
}

export function singleFlight(action) {
  let pending = false;
  return async (...args) => {
    if (pending) return false;
    pending = true;
    try { return await action(...args); } finally { pending = false; }
  };
}

// All generic navigation uses the same durable-snapshot boundary.
export async function guardUnsavedChanges({hasChanges, choose, save}) {
  if (!hasChanges()) return true;
  const choice = await choose();
  if (choice === "discard") return true;
  if (choice !== "save") return false;
  if (!await save()) return false;
  return !hasChanges();
}
