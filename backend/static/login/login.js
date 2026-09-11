const form = document.querySelector("#login-form");
const errorOutput = document.querySelector("#login-error");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorOutput.textContent = "";
  const payload = {
    login: document.querySelector("#login").value.trim(),
    password: document.querySelector("#password").value
  };
  try {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(payload)
    });
    if (!response.ok) {
      errorOutput.textContent = "Benutzername oder Passwort ist falsch.";
      return;
    }
    window.location.href = "/arbeitsbereiche";
  } catch {
    errorOutput.textContent = "Anmeldung ist derzeit nicht möglich.";
  }
});
