export async function validateActionSnapshot(module, payload, csrfToken, request = fetch) {
  const response = await request(`/api/modules/${encodeURIComponent(module)}/validate-action`, {
    method: "POST", credentials: "same-origin",
    headers: {"Content-Type": "application/json", "X-CSRF-Token": csrfToken},
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(Array.isArray(error.detail) ? error.detail.join("\n") : String(error.detail));
  }
}
