const moduleLabels = {
  foto_papierabzuege: "Einzelne Papierabzüge"
};

function csrfToken() {
  return document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith("erschliessung_csrf="))
    ?.split("=")[1];
}

async function loadMe() {
  const response = await fetch("/api/auth/me", { credentials: "same-origin" });
  if (response.status === 401) {
    window.location.href = "/login/";
    return null;
  }
  if (!response.ok) throw new Error("me failed");
  return response.json();
}

function renderWorkspaces(user) {
  document.querySelector("#user-name").textContent = user.display_name;
  const list = document.querySelector("#workspace-list");
  list.innerHTML = "";
  user.modules.forEach((moduleKey) => {
    const link = document.createElement("a");
    link.href = moduleKey === "foto_papierabzuege" ? "/app/" : "#";
    link.textContent = moduleLabels[moduleKey] || moduleKey;
    list.append(link);
  });
  if (user.modules.length === 1 && user.modules[0] === "foto_papierabzuege") {
    window.location.href = "/app/";
  }
}

document.querySelector("#logout").addEventListener("click", async () => {
  await fetch("/api/auth/logout", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrfToken() || "" }
  });
  window.location.href = "/login/";
});

loadMe()
  .then((user) => {
    if (user) renderWorkspaces(user);
  })
  .catch(() => {
    document.querySelector("#workspace-error").textContent = "Arbeitsbereiche konnten nicht geladen werden.";
  });
