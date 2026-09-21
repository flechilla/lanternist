import { useState } from "react";
import { STYLE_NAMES, type Camera, type Options, type Scene, type Storyboard } from "../api";
import Slide from "./Slide";

const CAMERA_NAMES: Record<Camera, string> = {
  auto: "Auto", push_in: "Push in", pull_out: "Pull out", pan_left: "Pan left", pan_right: "Pan right", static: "Static",
};

const slug = (s: string) =>
  s.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "character";

interface Props {
  draft: Storyboard;
  edit: (fn: (sb: Storyboard) => void) => void;
  opts: Options | null;
  dirty: boolean;
  busy: boolean;
  onSave: () => void;
  onDiscard: () => void;
  cast: string | null;
  castDrawing: boolean;
  jobActive: boolean;
  onDrawCast: () => void;
  onRerollCast: () => void;
  onRewrite: (n: number, instruction: string) => void;
}

export default function ScriptEditor(p: Props) {
  const { draft, edit } = p;
  const scene = (n: number, fn: (s: Scene) => void) =>
    edit((sb) => { const s = sb.scenes.find((x) => x.n === n); if (s) fn(s); });

  function renameCast(i: number) {
    // New characters get a stable id from their name the first time it's set; scenes refer to it.
    edit((sb) => {
      const c = sb.cast[i];
      if (!c.id.startsWith("new-") || !c.name.trim()) return;
      let id = slug(c.name);
      while (sb.cast.some((o, j) => j !== i && o.id === id)) id += "-2";
      sb.scenes.forEach((s) => { s.cast = s.cast.map((x) => (x === c.id ? id : x)); });
      c.id = id;
    });
  }

  function insertAfter(n: number) {
    edit((sb) => {
      const i = sb.scenes.findIndex((s) => s.n === n);
      const blank: Scene = { n: 0, narration: [{ speaker: "narrator", text: "" }], visual: "", motion: "", sound: "",
                             cast: [], camera: "auto", mode: "still", seed: null };
      sb.scenes.splice(i + 1, 0, blank);
      sb.scenes.forEach((s, k) => { s.n = k + 1; });
    });
  }

  function removeScene(n: number) {
    edit((sb) => {
      sb.scenes = sb.scenes.filter((s) => s.n !== n);
      sb.scenes.forEach((s, k) => { s.n = k + 1; });
    });
  }

  return (
    <>
      {p.dirty && (
        <div className="savebar" role="status">
          <b>Unsaved changes</b>
          <span className="spacer" />
          <button className="small" onClick={p.onDiscard} disabled={p.busy}>Discard</button>
          <button className="small primary" onClick={p.onSave} disabled={p.busy}>{p.busy ? "Saving…" : "Save"}</button>
        </div>
      )}
      <div className="script">
        <div>
          <label className="field">
            Title
            <input type="text" className="title-input" value={draft.title} onChange={(e) => edit((sb) => { sb.title = e.target.value; })} />
          </label>
          <div style={{ marginTop: 10 }}>
            {draft.scenes.map((s) => (
              <SceneEditor key={s.n} s={s} draft={draft} scene={scene} opts={p.opts} jobActive={p.jobActive}
                           onRewrite={p.onRewrite} onInsert={insertAfter} onRemove={removeScene}
                           canRemove={draft.scenes.length > 1} />
            ))}
          </div>
        </div>

        <aside>
          <section className="panel stack">
            <h2>Cast</h2>
            <Slide square image={p.cast} drawing={p.castDrawing} label="Cast sheet"
                   empty="The cast sheet keeps every character looking the same in every picture." />
            <div className="row">
              {p.cast ? (
                <button className="small" onClick={p.onRerollCast} disabled={p.busy || p.jobActive}>Draw it again</button>
              ) : (
                <button className="small primary" onClick={p.onDrawCast} disabled={p.busy || p.jobActive}>Draw cast sheet</button>
              )}
            </div>
            {draft.cast_sheet_prompt !== null && draft.cast_sheet_prompt !== undefined && (
              <label className="field">
                Cast sheet description
                <small>This story brings its own; it's used instead of the characters below.</small>
                <textarea rows={6} value={draft.cast_sheet_prompt}
                          onChange={(e) => edit((sb) => { sb.cast_sheet_prompt = e.target.value; })} />
              </label>
            )}
            <div>
              {draft.cast.map((c, i) => (
                <div className="cast-member" key={c.id}>
                  <div className="row">
                    <input type="text" aria-label="Name" value={c.name} placeholder="Name"
                           onChange={(e) => edit((sb) => { sb.cast[i].name = e.target.value; })}
                           onBlur={() => renameCast(i)} style={{ flex: 1, fontWeight: 600 }} />
                    <button className="quiet small danger" aria-label={`Remove ${c.name || "character"}`}
                            onClick={() => edit((sb) => {
                              sb.cast.splice(i, 1);
                              sb.scenes.forEach((s) => { s.cast = s.cast.filter((x) => x !== c.id); });
                            })}>Remove</button>
                  </div>
                  <textarea aria-label={`How ${c.name || "they"} look`} rows={3} value={c.look}
                            placeholder="How they look: age or species, colours, clothes, one detail"
                            onChange={(e) => edit((sb) => { sb.cast[i].look = e.target.value; })} />
                </div>
              ))}
            </div>
            <button className="small" onClick={() => edit((sb) => { sb.cast.push({ id: `new-${Date.now()}`, name: "", look: "" }); })}>
              Add a character
            </button>
          </section>

          <section className="panel stack">
            <h2>Look and voice</h2>
            <label className="field">
              Narrator
              <select value={draft.voice} onChange={(e) => edit((sb) => { sb.voice = e.target.value; })}>
                {(p.opts?.voices ?? [{ name: draft.voice }]).map((v) => <option key={v.name}>{v.name}</option>)}
                {p.opts && !p.opts.voices.some((v) => v.name === draft.voice) && <option>{draft.voice}</option>}
              </select>
            </label>
            <label className="field">
              Subtitles
              <select value={draft.subtitles} onChange={(e) => edit((sb) => { sb.subtitles = e.target.value as Storyboard["subtitles"]; })}>
                <option value="sidecar">Separate file, shown by the player</option>
                <option value="burned">Burned into the picture</option>
                <option value="off">None</option>
              </select>
            </label>
            <label className="field">
              Picture style
              <small>Added to every picture and animation prompt.</small>
              <textarea rows={4} value={draft.style} onChange={(e) => edit((sb) => { sb.style = e.target.value; })} />
            </label>
            {p.opts && (
              <div className="chips">
                {p.opts.styles.map((s) => (
                  <button key={s.id} type="button" className="chip" aria-pressed={draft.style === s.prompt}
                          onClick={() => edit((sb) => { sb.style = s.prompt; })}>{STYLE_NAMES[s.id] ?? s.name}</button>
                ))}
              </div>
            )}
          </section>
        </aside>
      </div>
    </>
  );
}

interface SceneProps {
  s: Scene;
  draft: Storyboard;
  scene: (n: number, fn: (s: Scene) => void) => void;
  opts: Options | null;
  jobActive: boolean;
  onRewrite: (n: number, instruction: string) => void;
  onInsert: (n: number) => void;
  onRemove: (n: number) => void;
  canRemove: boolean;
}

function SceneEditor({ s, draft, scene, opts, jobActive, onRewrite, onInsert, onRemove, canRemove }: SceneProps) {
  const [instruction, setInstruction] = useState("");
  const text = s.narration.map((l) => l.text).join(" ");
  return (
    <section className="scene-edit" aria-label={`Scene ${s.n}`}>
      <div className="n" aria-hidden="true">{s.n}</div>
      <div className="stack">
        <label className="field narr">
          <span className="sr-only">Narration for scene {s.n}</span>
          <textarea value={text} placeholder="What the narrator says in this scene"
                    onChange={(e) => scene(s.n, (x) => { x.narration = [{ speaker: "narrator", text: e.target.value }]; })} />
        </label>
        <div className="scene-fields">
          <label className="field">
            Picture
            <textarea rows={4} value={s.visual} placeholder="Shot, setting, light, who does what"
                      onChange={(e) => scene(s.n, (x) => { x.visual = e.target.value; })} />
          </label>
          <label className="field">
            Motion
            <textarea rows={4} value={s.motion} placeholder="What moves, and how the camera moves"
                      onChange={(e) => scene(s.n, (x) => { x.motion = e.target.value; })} />
          </label>
          <label className="field">
            Sound
            <textarea rows={4} value={s.sound} placeholder="Ambience only: wind, waves, birdsong"
                      onChange={(e) => scene(s.n, (x) => { x.sound = e.target.value; })} />
          </label>
        </div>
        <div className="scene-meta">
          <div className="segmented" role="group" aria-label="Still or video">
            {(["still", "video"] as const).map((m) => (
              <button key={m} type="button" aria-pressed={s.mode === m} onClick={() => scene(s.n, (x) => { x.mode = m; })}>
                {m === "still" ? "Still" : "Video"}
              </button>
            ))}
          </div>
          <label className="row" style={{ gap: 6 }}>
            Camera
            <select value={s.camera} onChange={(e) => scene(s.n, (x) => { x.camera = e.target.value as Camera; })}>
              {(opts?.cameras ?? (Object.keys(CAMERA_NAMES) as Camera[])).map((c) => <option key={c} value={c}>{CAMERA_NAMES[c]}</option>)}
            </select>
          </label>
          {draft.cast.length > 0 && (
            <div className="checks" role="group" aria-label="Characters in the picture">
              {draft.cast.map((c) => (
                <label key={c.id}>
                  <input type="checkbox" checked={s.cast.includes(c.id)}
                         onChange={(e) => scene(s.n, (x) => {
                           x.cast = e.target.checked ? [...x.cast, c.id] : x.cast.filter((id) => id !== c.id);
                         })} />
                  {c.name || "Unnamed"}
                </label>
              ))}
            </div>
          )}
        </div>
        <details>
          <summary>Rewrite with AI, add or remove</summary>
          <div className="stack" style={{ marginTop: 10 }}>
            <form className="rewrite" onSubmit={(e) => { e.preventDefault(); if (instruction.trim()) { onRewrite(s.n, instruction.trim()); setInstruction(""); } }}>
              <input type="text" value={instruction} onChange={(e) => setInstruction(e.target.value)}
                     placeholder="Make the gull a bit funnier" aria-label={`How to rewrite scene ${s.n}`} />
              <button type="submit" className="small" disabled={!instruction.trim() || jobActive}>Rewrite scene {s.n}</button>
            </form>
            <div className="row">
              <button type="button" className="small" onClick={() => onInsert(s.n)}>Add a scene after this one</button>
              {canRemove && <button type="button" className="small danger" onClick={() => onRemove(s.n)}>Remove scene {s.n}</button>}
            </div>
          </div>
        </details>
      </div>
    </section>
  );
}
