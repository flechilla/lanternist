import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  api,
  errorMessage,
  type Capability,
  type MediaCatalog,
  type Provider,
  type ProviderName,
  type SettingRow,
} from "../api";
import ModelPicker from "../components/ModelPicker";
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

/** A saved setting as text: model ids are strings and the budget a number. */
function text(rows: SettingRow[] | null, key: string): string {
  const v = rows?.find((r) => r.key === key)?.value;
  return typeof v === "string" || typeof v === "number" ? String(v) : "";
}

/** The default model of each media stage, by its setting. */
const STAGES: { key: string; capability: Capability; label: string; off?: string }[] = [
  { key: "defaults.tts", capability: "tts.speak", label: "Narration" },
  { key: "defaults.image", capability: "image.keyframe", label: "Pictures" },
  { key: "defaults.video", capability: "video.image_to_video", label: "Video" },
  {
    key: "defaults.ambience",
    capability: "audio.ambience",
    label: "Ambience, for video models with no sound of their own",
    off: "Their scenes stay silent under the narration.",
  },
];

function Defaults() {
  const [rows, setRows] = useState<SettingRow[] | null>(null);
  const [catalogs, setCatalogs] = useState<Partial<Record<Capability, MediaCatalog>>>({});
  const [budget, setBudget] = useState("");
  const { busy, error, setError, run } = useAction();

  // Each catalog names its stage's default, so they're fetched again after a save.
  const loadCatalogs = useCallback(
    () =>
      Promise.all(STAGES.map((st) => api.models(st.capability))).then(
        (all) => setCatalogs(Object.fromEntries(STAGES.map((st, i) => [st.capability, all[i]]))),
        (e: unknown) => setError(errorMessage(e)),
      ),
    [setError],
  );
  useEffect(() => {
    api.settings().then(
      (r) => {
        setRows(r);
        setBudget(text(r, "defaults.budget_usd"));
      },
      (e: unknown) => setError(errorMessage(e)),
    );
    void loadCatalogs();
  }, [loadCatalogs, setError]);

  const save = (changes: Record<string, unknown>) =>
    run(async () => {
      setRows(await api.saveSettings(changes));
      await loadCatalogs();
    });

  return (
    <section className="panel stack" aria-labelledby="defaults-title">
      <h2 id="defaults-title">Defaults for every story</h2>
      <p className="muted">A story uses these unless it picks its own on the Board step.</p>
      {STAGES.map((st) => (
        <ModelPicker
          key={st.key}
          label={st.label}
          catalog={catalogs[st.capability] ?? null}
          error={error}
          value={text(rows, st.key)}
          allowDefault={false}
          off={st.off}
          disabled={busy}
          onChange={(model) => void save({ [st.key]: model })}
        />
      ))}
      <form
        className="key-form"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          void save({ "defaults.budget_usd": Number(budget) });
        }}
      >
        <label className="field" htmlFor="default-budget">
          Budget per story, in dollars
          <small>
            A remote stage that would take a story past it stops before it spends anything. A story can have
            its own.
          </small>
        </label>
        <input
          id="default-budget"
          type="number"
          min={0}
          step={0.5}
          value={budget}
          onChange={(e) => setBudget(e.target.value)}
        />
        <button type="submit" disabled={busy || budget === "" || Number(budget) < 0}>
          Save budget
        </button>
      </form>
      {error && <p className="error">{error}</p>}
    </section>
  );
}

export default function Settings() {
  const [providers, setProviders] = useState<Provider[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.providers().then(setProviders, (e: unknown) => setError(errorMessage(e)));
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
            Keys for remote models, and the defaults every story starts from. Each key is kept on this machine
            and sent only to its own provider. Every model on this machine keeps working without them, free.
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
          <Defaults />
        </div>
      )}
    </>
  );
}
