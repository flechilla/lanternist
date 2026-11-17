/* The site's one piece of server: it keeps the invitation list. Everything else is static files in
 * public/, which Cloudflare serves before this Worker runs, so it only ever sees /api/waitlist and
 * addresses that match no file. */

import { EMAIL } from "./public/join.js";

const json = (data, status = 200) => Response.json(data, { status });

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/api/waitlist")
      return new Response("There is nothing at this address.", { status: 404 });
    if (request.method !== "POST") return new Response(null, { status: 405, headers: { Allow: "POST" } });
    // Only the site's own form may post here: a browser always names the page's origin on a POST.
    if (request.headers.get("Origin") !== url.origin)
      return json({ error: "Ask for an invitation from the site's own form." }, 403);
    const { success } = await env.LIMIT.limit({ key: request.headers.get("CF-Connecting-IP") ?? "unknown" });
    if (!success) return json({ error: "Too many tries from here. Wait a minute and try again." }, 429);

    let body;
    try {
      body = await request.json();
    } catch {
      body = null;
    }
    if (typeof body !== "object" || body === null)
      return json({ error: "The form didn't arrive whole. Reload the page and try again." }, 400);
    // The form has a field people can't see; whatever fills it is a bot, so thank it and keep nothing.
    if (body.website) return json({ ok: true });
    const email = String(body.email ?? "")
      .trim()
      .toLowerCase();
    if (email.length > 254 || !EMAIL.test(email))
      return json({ error: "That email address doesn't look right." }, 400);
    const idea = String(body.idea ?? "")
      .trim()
      .slice(0, 200);
    const lang = String(body.lang ?? "").slice(0, 16);

    try {
      await env.DB.prepare(
        "INSERT INTO waitlist (email, idea, lang) VALUES (?1, ?2, ?3) " +
          "ON CONFLICT (email) DO UPDATE SET idea = excluded.idea, lang = excluded.lang",
      )
        .bind(email, idea, lang)
        .run();
    } catch (err) {
      console.error("waitlist insert failed", err);
      return json({ error: "We couldn't write that down just now. Try again in a few minutes." }, 503);
    }
    return json({ ok: true });
  },
};
