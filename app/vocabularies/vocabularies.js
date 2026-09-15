import { VocabularyAdminState } from "../generic/vocabulary-admin.js";
import { VocabularyClient } from "../generic/vocabulary-client.js?v=vocabulary-admin-1";

const $ = selector => document.querySelector(selector);
const state = new VocabularyAdminState(new VocabularyClient());
let csrfCookieName = null;

function csrfToken() {
  const prefix = `${csrfCookieName}=`;
  const cookie = document.cookie.split(";").map(part => part.trim()).find(part => part.startsWith(prefix));
  return cookie ? decodeURIComponent(cookie.slice(prefix.length)) : "";
}

async function loadUser() {
  const response = await fetch("/api/auth/me", { credentials: "same-origin" });
  if (response.status === 401) {
    location.href = "/login/";
    return null;
  }
  if (!response.ok) throw new Error("Benutzerkonto konnte nicht geladen werden.");
  const user = await response.json();
  csrfCookieName = user.csrf_cookie_name;
  $("#current-user").textContent = user.display_name;
  document.body.classList.toggle("barrierearm", user.ui_profile === "ehrenamt-barrierearm");
  return user;
}

function rightsSummary() {
  const actions = [];
  if (state.rights.add) actions.push("hinzufügen");
  if (state.rights.rename) actions.push("umbenennen");
  if (state.rights.deactivate) actions.push("deaktivieren");
  return actions.length ? `Freigegebene Aktionen: ${actions.join(", ")}.` : "Dieses Vokabular ist nur lesbar.";
}

function renderCatalog() {
  const list = $("#vocabulary-list");
  list.replaceChildren();
  if (!state.catalog.length) {
    list.textContent = "Keine freigegebenen Vokabulare vorhanden.";
    return;
  }
  state.catalog.forEach(item => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.vocabularyId = item.id;
    const title = document.createElement("strong");
    title.textContent = item.label || item.id;
    const id = document.createElement("span");
    id.textContent = `ID: ${item.id}`;
    button.append(title, id);
    button.addEventListener("click", () => openVocabulary(item.id));
    list.append(button);
  });
}

function additionalTermDetails(term) {
  const details = [];
  if (term.description) details.push(term.description);
  if (term.aliases?.length) details.push(`Aliase: ${term.aliases.join(", ")}`);
  if (term.sort_order !== null && term.sort_order !== undefined) details.push(`Sortierung: ${term.sort_order}`);
  return details.join(" · ") || "–";
}

function renderTerms() {
  const body = $("#term-list");
  body.replaceChildren();
  state.vocabulary.terms.forEach(term => {
    const row = body.insertRow();
    row.dataset.termId = term.id;
    row.insertCell().textContent = term.id;

    const labelCell = row.insertCell();
    if (state.rights.rename) {
      const label = document.createElement("label");
      label.className = "visually-hidden";
      label.htmlFor = `term-label-${term.id}`;
      label.textContent = `Label für ${term.id}`;
      const input = document.createElement("input");
      input.id = `term-label-${term.id}`;
      input.value = state.renameDrafts.get(term.id) ?? term.label;
      input.disabled = state.status === "saving";
      input.addEventListener("input", () => state.setRenameDraft(term.id, input.value));
      labelCell.append(label, input);
    } else {
      labelCell.textContent = term.label;
    }

    const statusCell = row.insertCell();
    const status = document.createElement("span");
    status.className = `term-status${term.active ? "" : " inactive"}`;
    status.textContent = term.active ? "aktiv" : "inaktiv";
    statusCell.append(status);
    row.insertCell().textContent = additionalTermDetails(term);

    const actionCell = row.insertCell();
    const actions = document.createElement("div");
    actions.className = "term-actions";
    if (state.rights.rename) {
      const rename = document.createElement("button");
      rename.type = "button";
      rename.className = "secondary";
      rename.textContent = "Label speichern";
      rename.disabled = state.status === "saving";
      rename.addEventListener("click", async () => {
        const saving = state.rename(term.id, csrfToken());
        renderDetail();
        await saving;
        renderDetail();
      });
      actions.append(rename);
    }
    if (state.rights.deactivate && term.active) {
      const deactivate = document.createElement("button");
      deactivate.type = "button";
      deactivate.className = "secondary";
      deactivate.textContent = "Begriff deaktivieren";
      deactivate.disabled = state.status === "saving";
      deactivate.addEventListener("click", () => {
        if (!state.requestDeactivate(term.id)) return;
        $("#deactivate-term-label").textContent = `${term.label} (${term.id})`;
        $("#deactivate-dialog").showModal();
      });
      actions.append(deactivate);
    }
    actionCell.append(actions);
  });
}

function renderDetail() {
  if (!state.vocabulary) return;
  if (state.lastStatus === 401) {
    location.href = "/login/";
    return;
  }
  $("#vocabulary-panel").hidden = false;
  $("#vocabulary-heading").textContent = state.vocabulary.label;
  $("#vocabulary-description").textContent = state.vocabulary.description || `Vocabulary-ID: ${state.vocabulary.id}`;
  $("#vocabulary-revision").textContent = `Revision: ${state.revision}`;
  $("#rights-summary").textContent = rightsSummary();
  $("#save-status").textContent = state.message;
  $("#vocabulary-error").textContent = state.error;
  $("#reload-vocabulary").hidden = !["conflict", "error"].includes(state.status);
  $("#add-term-form").hidden = !state.rights.add;
  $("#new-term-id").value = state.addDraft.id;
  $("#new-term-label").value = state.addDraft.label;
  $("#add-term-form").querySelector("button").disabled = state.status === "saving";
  renderTerms();
}

async function openVocabulary(vocabularyId, options = {}) {
  const opening = state.open(vocabularyId, options);
  renderDetail();
  const opened = await opening;
  if (state.lastStatus === 401) {
    location.href = "/login/";
    return;
  }
  if (opened) {
    $("#page-error").textContent = "";
    const url = new URL(location.href);
    url.searchParams.set("vocabulary", vocabularyId);
    history.replaceState({}, "", url);
  }
  if (!opened) $("#page-error").textContent = state.error;
  renderDetail();
}

$("#add-term-form").addEventListener("submit", async event => {
  event.preventDefault();
  state.setAddDraft({ id: $("#new-term-id").value, label: $("#new-term-label").value });
  const saving = state.add(csrfToken());
  renderDetail();
  await saving;
  renderDetail();
});

$("#cancel-deactivate").addEventListener("click", () => {
  state.cancelDeactivate();
  $("#deactivate-dialog").close();
});

$("#confirm-deactivate").addEventListener("click", async () => {
  $("#confirm-deactivate").disabled = true;
  $("#cancel-deactivate").disabled = true;
  const saving = state.confirmDeactivate(csrfToken());
  renderDetail();
  await saving;
  $("#confirm-deactivate").disabled = false;
  $("#cancel-deactivate").disabled = false;
  $("#deactivate-dialog").close();
  renderDetail();
});

$("#reload-vocabulary").addEventListener("click", async () => {
  if (state.hasDrafts && !window.confirm("Lokale Eingaben verwerfen und aktuellen Serverstand laden?")) return;
  await openVocabulary(state.vocabulary.id, { reload: true, discardDrafts: true });
});

async function initialize() {
  try {
    if (!await loadUser()) return;
    await state.loadCatalog();
    if (state.lastStatus === 401) {
      location.href = "/login/";
      return;
    }
    renderCatalog();
    const requested = new URLSearchParams(location.search).get("vocabulary");
    if (requested && state.catalog.some(item => item.id === requested)) {
      await openVocabulary(requested);
    } else if (requested) {
      $("#page-error").textContent = "Das angeforderte Vokabular wurde nicht gefunden oder ist nicht freigegeben.";
    }
    if (state.status === "error") $("#page-error").textContent = state.error;
  } catch (error) {
    $("#page-error").textContent = error.message || "Vocabulary-Verwaltung konnte nicht geladen werden.";
  }
}

initialize();
