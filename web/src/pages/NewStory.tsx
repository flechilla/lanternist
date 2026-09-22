import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, STYLE_NAMES, type Brief } from "../api";
import { useAction, useOptions } from "../hooks";

const MODES: { id: Brief["mode"]; name: string; hint: string }[] = [
  {
    id: "still",
    name: "Stills with camera moves",
    hint: "Illustrations with slow pans and zooms. Fastest to render.",
  },
  {
    id: "hybrid",
    name: "Hybrid",
    hint: "Stills, with the key moments animated. You can switch any scene later.",
  },
  { id: "video", name: "Full video", hint: "Every scene animated. About 4 GPU-seconds per second of film." },
];

const AUDIENCE_NAMES: Record<string, string> = {
  toddlers: "Toddlers 2–4",
  kids_5_8: "Kids 5–8",
  kids_9_12: "9–12",
  teens: "Teens",
  adults: "Adults",
};

export default function NewStory() {
  const opts = useOptions();
  const navigate = useNavigate();
  const { busy, error, run } = useAction();
  const [brief, setBrief] = useState<Brief>({
    idea: "",
    language: "en",
    audience: "kids_5_8",
    kind: "bedtime",
    minutes: 3,
    style: "watercolour",
    notes: "",
    mode: "hybrid",
    voice: "demo",
  });
  const set = <K extends keyof Brief>(k: K, v: Brief[K]) => setBrief((b) => ({ ...b, [k]: v }));

  // The default narrator may not be installed: fall back to the first voice there is.
  const voices = opts?.voices ?? [];
  const voice = voices.some((v) => v.name === brief.voice) ? brief.voice : (voices[0]?.name ?? brief.voice);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const created = await run(() =>
      api.write({ ...brief, voice, idea: brief.idea.trim(), notes: brief.notes.trim() }),
    );
    if (created) await navigate(`/stories/${created.story.id}`);
  }

  const words = Math.round(brief.minutes * (brief.language === "en" ? 150 : 140));

  return (
    <form onSubmit={submit}>
      <div className="page-head">
        <div>
          <h1>A new story</h1>
          <p>Say what it's about. You'll review the script and every picture before anything is animated.</p>
        </div>
      </div>
      <div className="compose">
        <div className="stack">
          <label className="field idea">
            Your idea
            <textarea
              required
              value={brief.idea}
              onChange={(e) => set("idea", e.target.value)}
              placeholder="A lighthouse cat is scared of the dark, until an old gull shows her that every star is a lantern someone lit for a friend."
            />
          </label>
          <label className="field">
            Anything to include
            <small>Names, a lesson, a place, a favourite toy.</small>
            <textarea
              value={brief.notes}
              onChange={(e) => set("notes", e.target.value)}
              placeholder="Her name is Luna. A gentle lesson about asking for help."
            />
          </label>
          <fieldset className="field">
            <legend>Motion</legend>
            <div className="modes">
              {MODES.map((m) => (
                <button
                  type="button"
                  key={m.id}
                  className="mode-card"
                  aria-pressed={brief.mode === m.id}
                  onClick={() => set("mode", m.id)}
                >
                  <b>{m.name}</b>
                  <small>{m.hint}</small>
                </button>
              ))}
            </div>
          </fieldset>
        </div>

        <div className="panel stack">
          <div className="field">
            <span>Who is it for</span>
            <div className="chips">
              {(opts?.audiences ?? []).map((a) => (
                <button
                  type="button"
                  key={a.id}
                  className="chip"
                  aria-pressed={brief.audience === a.id}
                  onClick={() => set("audience", a.id)}
                >
                  {AUDIENCE_NAMES[a.id] ?? a.name}
                </button>
              ))}
            </div>
          </div>
          <div className="field">
            <span>Kind of story</span>
            <div className="chips">
              {(opts?.kinds ?? []).map((k) => (
                <button
                  type="button"
                  key={k.id}
                  className="chip"
                  aria-pressed={brief.kind === k.id}
                  onClick={() => set("kind", k.id)}
                >
                  {k.id === "learn" ? "Learn something" : k.name[0].toUpperCase() + k.name.slice(1)}
                </button>
              ))}
            </div>
          </div>
          <div className="field">
            <span>Picture style</span>
            <div className="chips">
              {(opts?.styles ?? []).map((s) => (
                <button
                  type="button"
                  key={s.id}
                  className="chip"
                  aria-pressed={brief.style === s.id}
                  title={s.prompt}
                  onClick={() => set("style", s.id)}
                >
                  {STYLE_NAMES[s.id] ?? s.name}
                </button>
              ))}
            </div>
          </div>
          <label className="field">
            Language
            <small>Narration and subtitles use it. Picture prompts stay in English.</small>
            <select value={brief.language} onChange={(e) => set("language", e.target.value)}>
              {(opts?.languages ?? [{ id: "en", name: "English" }]).map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            Length
            <div className="range-row">
              <input
                type="range"
                min={1}
                max={10}
                step={0.5}
                value={brief.minutes}
                onChange={(e) => set("minutes", Number(e.target.value))}
              />
              <output>{brief.minutes} min</output>
            </div>
            <small>
              About {words} words, {Math.max(3, Math.round(words / 32))} scenes.
            </small>
          </label>
          <label className="field">
            Narrator
            <select value={voice} onChange={(e) => set("voice", e.target.value)}>
              {voices.map((v) => (
                <option key={v.name} value={v.name}>
                  {v.name}
                </option>
              ))}
            </select>
          </label>
          {error && <p className="error">{error}</p>}
          <button className="primary wide" type="submit" disabled={busy || !brief.idea.trim()}>
            {busy ? "Starting…" : "Write my story"}
          </button>
          <small className="muted">
            Written by {opts?.writer_model ?? "the local model"} on this machine. Takes a minute or two.
          </small>
        </div>
      </div>
    </form>
  );
}
