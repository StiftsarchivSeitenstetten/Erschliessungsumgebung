let currentUser = null;

function csrfToken() {
  const cookieName = currentUser.csrf_cookie_name;
  return document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${cookieName}=`))
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

async function loadModuleCatalog() {
  const response = await fetch("/api/modules", { credentials: "same-origin" });
  if (response.status === 401) {
    window.location.href = "/login/";
    return [];
  }
  if (!response.ok) throw new Error("modules failed");
  return response.json();
}

async function loadVocabularyCatalog() {
  const response = await fetch("/api/vocabularies", { credentials: "same-origin" });
  if (response.status === 401) {
    window.location.href = "/login/";
    return [];
  }
  if (!response.ok) return [];
  return response.json();
}

function moduleUrl(module) {
  if (module.entrypoint === "generic" || new URLSearchParams(location.search).get("view") === "generic") {
    return `/app/module/?module=${encodeURIComponent(module.id)}`;
  }
  return `/app/?module=${encodeURIComponent(module.id)}`;
}

function renderWorkspaces(user, modules, vocabularies) {
  document.querySelector("#user-name").textContent = user.display_name;
  const list = document.querySelector("#workspace-list");
  list.innerHTML = "";
  modules.forEach((module) => {
    const link = document.createElement("a");
    link.href = moduleUrl(module);
    link.dataset.module = module.id;
    const title = document.createElement("strong");
    title.textContent = module.label || module.id;
    link.append(title);
    if (module.description) {
      const description = document.createElement("span");
      description.textContent = module.description;
      link.append(description);
    }
    list.append(link);
  });
  if (vocabularies.length) {
    const link = document.createElement("a");
    link.href = "/app/vocabularies/";
    link.dataset.area = "vocabularies";
    const title = document.createElement("strong");
    title.textContent = "Vokabulare";
    const description = document.createElement("span");
    description.textContent = "Kontrollierte Begriffe anzeigen und – je nach Recht – redaktionell pflegen.";
    link.append(title, description);
    list.append(link);
  }
  if (modules.length === 1 && !vocabularies.length && new URLSearchParams(location.search).get("view") !== "generic") {
    window.location.href = moduleUrl(modules[0]);
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

Promise.all([loadMe(), loadModuleCatalog(), loadVocabularyCatalog()])
  .then(([user, catalog, vocabularies]) => {
    if (user) {
      currentUser = user;
      renderWorkspaces(
        user,
        Array.isArray(catalog) ? catalog : [],
        Array.isArray(vocabularies) ? vocabularies : [],
      );
    }
  })
  .catch(() => {
    document.querySelector("#workspace-error").textContent = "Arbeitsbereiche konnten nicht geladen werden.";
  });
