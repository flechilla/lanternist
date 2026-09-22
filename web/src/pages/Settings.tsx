import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type Provider, type ProviderName } from "../api";
import { useAction } from "../hooks";

const ABOUT: Record<ProviderName, { what: string; keys: string; tip: string }> = {
  openrouter: {
    what: "Writes stories with frontier models such as Claude, GPT and Gemini. OpenRouter bills you per token.",
    keys: "https://openrouter.ai/settings/keys",
    tip: "Give the key a spending limit on openrouter.ai to cap what it can spend.",
  },
  fal: {
    what: "Draws pictures, narrates and animates on fal's GPUs, so no stage needs yours. fal bills you per image, second or character.",
    keys: "https://fal.ai/dashboard/keys",
    tip: "Lanternist asks fal to delete what it makes after a day, once a copy is in your library.",
  },
};

const SOURCE: Record<string, string> = {
  env: "from the environment",
  keychain: "in your OS keychain",
  file: "in ~/.config/lanternist/secrets.toml",
  fake: "a test key (test mode)",
};

function ProviderCard({ p, onChange }: { p: Provider; onChange: (p?: Provider) => void }) {
  const [key, setKey] = useState("");
  const { busy, error, run } = useAction();
  const about = ABOUT[p.name];
  const state = !p.configured ? "none" : p.ok ? "ok" : "fail";
  const envName = p.name === "fal" ? "FAL_KEY" : "OPENROUTER_API_KEY";

  async function save(e: FormEvent) {
    e.preventDefault();
    const row = await run(() => api.setKey(p.name, key.trim()));
    if (row) {
      setKey("");
      onChange(row);
    }
  }

  async function remove() {
    const removed = await run(async () => {
      await api.clearKey(p.name);
      return true;
    });
    if (removed) onChange();
  }

  return (
    <section className="panel stack" aria-labelledby={`${p.name}-title`}>
      <h2 id={`${p.name}-title`}>{p.label}</h2>
      <p className="muted">{about.what}</p>
      <div className={`provider-status ${state}`} role="status">
        <span className="mark" aria-hidden="true">
          {state === "ok" ? "✓" : state === "fail" ? "✗" : "·"}
        </span>
        <span className="detail">
          {!p.configured
            ? p.needed
              ? "No key yet, and a default model needs one."
              : "No key yet. Local models don't need one."
            : p.detail}
          {p.configured && p.source && (
            <>
              {" "}
              · key {SOURCE[p.source] ?? p.source}, ending {p.last4}
            </>
          )}
        </span>
      </div>
      {p.source === "env" ? (
        <p className="muted">
          This key comes from <code>{envName}</code> in the environment Lanternist started in. Change it
          there.
        </p>
      ) : (
        <form className="key-form" onSubmit={save}>
          <label className="sr-only" htmlFor={`${p.name}-key`}>
            {p.configured ? "Replace the key" : "Paste your key"}
          </label>
          <input
            id={`${p.name}-key`}
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder={p.configured ? "Paste a new key to replace it" : "Paste your key"}
          />
          <button className="primary" type="submit" disabled={busy || !key.trim()}>
            {busy ? "Checking…" : "Save key"}
          </button>
          {p.configured && p.source !== "fake" && (
            <button type="button" className="quiet danger" onClick={remove} disabled={busy}>
              Remove
            </button>
          )}
        </form>
      )}
      {error && <p className="error">{error}</p>}
      <p className="muted">
        <a href={about.keys} target="_blank" rel="noreferrer">
          Get a key
        </a>
        . {about.tip}
      </p>
    </section>
  );
}

export default function Settings() {
  const [providers, setProviders] = useState<Provider[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.providers().then(setProviders, (e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  function changed(row?: Provider) {
    if (row) setProviders((ps) => ps?.map((p) => (p.name === row.name ? row : p)) ?? null);
    else load();
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p>
            Keys for remote models. Each key is kept on this machine and sent only to its own provider. Every
            model on this machine keeps working without them, free.
          </p>
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      {providers === null && !error && <p className="muted">Checking your keys…</p>}
      {providers && (
        <div className="providers">
          {providers.map((p) => (
            <ProviderCard key={p.name} p={p} onChange={changed} />
          ))}
        </div>
      )}
    </>
  );
}
