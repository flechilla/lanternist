/* The invitation form, which all three pages share. It checks the address, posts it to worker.js and
 * says what happened; when the Worker refuses, the visitor reads the Worker's own sentence. */

export const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const LOST = "That didn't reach us. Try again in a minute.";

export function join(form, status, { sending, sent, after }) {
  const say = (kind, text) => {
    status.classList.add(kind);
    status.textContent = text;
  };
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(form));
    status.className = "status";
    if (!EMAIL.test(data.email))
      return say("err", "That email address looks incomplete. Check it and try again.");
    status.textContent = sending;
    let res;
    try {
      res = await fetch("/api/waitlist", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ...data, lang: navigator.language }),
      });
    } catch {
      return say("err", LOST);
    }
    if (!res.ok) return say("err", (await res.json().catch(() => ({}))).error ?? LOST);
    say("ok", sent(data.email));
    after();
  });
}
