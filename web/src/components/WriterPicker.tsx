import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { fmtUsd, type Effort, type WriterCatalog, type WriterModel } from "../api";

const SHOWN_UNSEARCHED = 40;
const SHOWN_SEARCHED = 100; // enough to scroll through; a longer list means the search needs narrowing
const BASIS: Record<string, string> = {
  measured: "",
  trial: ", from our trial stories at its default reasoning",
  typical: ", a rough guess until you've written a story with it",
};

function cost(m: WriterModel, minutes: number): string {
  if (m.unavailable) return "isn't offered right now; pick another writer";
  if (m.local) return "free, on this machine";
  if (m.usd_per_minute == null) return "price unknown";
  return `≈ ${fmtUsd(m.usd_per_minute * minutes)} for this story`;
}

function Row({
  m,
  minutes,
  chosen,
  disabled,
  onPick,
}: {
  m: WriterModel;
  minutes: number;
  chosen: boolean;
  disabled: boolean;
  onPick: () => void;
}) {
  return (
    <button type="button" className="writer-row" aria-pressed={chosen} disabled={disabled} onClick={onPick}>
      <b>{m.label}</b>
      <small>
        {m.label !== m.model && `${m.model} · `}
        {cost(m, minutes)}
      </small>
    </button>
  );
}

/** Choose the model that writes the story: local models first, then OpenRouter's, searchable. */
export default function WriterPicker({
  catalog,
  error,
  chosen,
  effort,
  minutes,
  onChange,
}: {
  catalog: WriterCatalog | null;
  error: string | null;
  chosen: WriterModel | undefined;
  effort: Effort | null;
  minutes: number;
  onChange: (writer: string, effort: Effort | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const remoteOk = !!catalog?.providers.openrouter.configured;

  const { local, pinned, rest, matches } = useMemo(() => {
    const q = query.trim().toLowerCase();
    const all = (catalog?.models ?? []).filter(
      (m) => !q || m.label.toLowerCase().includes(q) || m.id.toLowerCase().includes(q),
    );
    const remote = all.filter((m) => !m.local && !m.recommended);
    return {
      local: all.filter((m) => m.local),
      pinned: all.filter((m) => !m.local && m.recommended),
      rest: remote.slice(0, q ? SHOWN_SEARCHED : SHOWN_UNSEARCHED),
      matches: remote.length,
    };
  }, [catalog, query]);

  function pick(m: WriterModel) {
    onChange(m.id, m.efforts?.some((x) => x.id === effort) ? effort : null);
    setOpen(false);
    setQuery("");
  }

  const row = (m: WriterModel) => (
    <Row
      key={m.id}
      m={m}
      minutes={minutes}
      chosen={m.id === chosen?.id}
      disabled={!m.local && !remoteOk}
      onPick={() => pick(m)}
    />
  );
  const defaultEffort = chosen?.efforts?.find((x) => x.id === chosen.default_effort)?.name;

  return (
    <div className="field">
      <span>Writer</span>
      <div className="writer-pick">
        <div className="what">
          <b>{chosen?.label ?? "…"}</b>
          <small>
            {chosen ? cost(chosen, minutes) : (error ?? "Loading the models…")}
            {chosen && !chosen.local && BASIS[chosen.basis]}
          </small>
        </div>
        <button type="button" className="small" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Close" : "Change"}
        </button>
      </div>

      {chosen?.efforts && (
        <label className="effort">
          Reasoning
          <select
            value={effort ?? ""}
            onChange={(e) => onChange(chosen.id, (e.target.value || null) as Effort | null)}
          >
            <option value="">Model default{defaultEffort ? ` (${defaultEffort})` : ""}</option>
            {chosen.efforts.map((x) => (
              <option key={x.id} value={x.id}>
                {x.name}
              </option>
            ))}
          </select>
        </label>
      )}

      {open && catalog && (
        <div className="writer-menu">
          <input
            autoFocus
            type="text"
            placeholder="Search models, e.g. claude, gemini, gpt"
            value={query}
            aria-label="Search writer models"
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="writer-list">
            {local.length > 0 && <p className="group">On this machine</p>}
            {local.map(row)}
            {catalog.providers.ollama.error && !query && (
              <small className="muted">{catalog.providers.ollama.error}</small>
            )}
            {(pinned.length > 0 || rest.length > 0) && <p className="group">OpenRouter</p>}
            {!remoteOk && (
              <small className="muted">
                Add an OpenRouter key in <Link to="/settings">Settings</Link> to use these.
              </small>
            )}
            {catalog.providers.openrouter.error && (
              <small className="muted">{catalog.providers.openrouter.error}</small>
            )}
            {pinned.map(row)}
            {rest.map(row)}
            {matches > rest.length && (
              <small className="muted">
                {query
                  ? `${matches - rest.length} more match; narrow the search.`
                  : `Type to search all ${matches} models.`}
              </small>
            )}
            {query && !local.length && !pinned.length && !rest.length && (
              <small className="muted">No model matches “{query}”.</small>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
