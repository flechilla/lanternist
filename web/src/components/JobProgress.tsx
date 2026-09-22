import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { BoardPeek, Job, Storyboard } from "../api";
import {
  headline,
  sceneStates,
  sceneWords,
  stageCount,
  stageShare,
  TELLING,
  timeLeft,
  type SceneState,
} from "../reel";

function jobTitle(job: Job): string {
  switch (job.kind) {
    case "write":
      return "Writing the story";
    case "rewrite":
      return typeof job.params.n === "number" ? `Rewriting scene ${job.params.n}` : "Rewriting a scene";
    case "cast":
      return "Drawing the cast sheet";
    case "board":
      return "Preparing the board";
    case "render":
      return "Rendering the film";
    case "sample":
      return "Making a voice sample";
  }
}

export function Stages({ job }: { job: Job }) {
  // In the order the stages ran, under the names the backend gives them.
  const shown = Object.entries(job.progress?.stages ?? {});
  if (!shown.length)
    return (
      <p className="muted">{job.status === "queued" ? "Waiting for the job ahead of it." : "Starting…"}</p>
    );
  return (
    <div className="stages">
      {shown.map(([key, st]) => {
        const name = st.label ?? key;
        const pct = Math.round(stageShare(st) * 100);
        const unknown = !st.total && st.status === "running";
        return (
          <div key={key} className={`stage ${st.status}`}>
            <span className="name">{name}</span>
            {unknown ? (
              <span className="bar indeterminate" role="progressbar" aria-label={name}>
                <i />
              </span>
            ) : (
              <span
                className="bar"
                role="progressbar"
                aria-label={name}
                aria-valuenow={pct}
                aria-valuemin={0}
                aria-valuemax={100}
              >
                <i style={{ width: `${pct}%` }} />
              </span>
            )}
            <span className="count">{stageCount(st)}</span>
          </div>
        );
      })}
    </div>
  );
}

export function Log({ job }: { job: Job }) {
  const lines = job.progress?.log ?? [];
  const ref = useRef<HTMLPreElement>(null);
  // Keep the newest line in view, like a terminal.
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight });
  }, [lines.length]);
  if (!lines.length) return null;
  return (
    <pre ref={ref} className="log">
      {lines.join("\n")}
    </pre>
  );
}

// A scene's square on the dock's mini reel: how far it has got, as far as the pips on its slide.
function square(s: SceneState): number {
  if (s.cut === "done") return 4;
  if (s.motion === "done") return 3;
  if (s.picture === "done" && s.again === null) return 2;
  return s.voice === "done" ? 1 : 0;
}

const busy = (s: SceneState) =>
  [s.voice, s.picture, s.motion, s.cut].some((p) => p === "working" || p === "waiting");

interface DockProps {
  job: Job;
  queued: number;
  sb: Storyboard | null;
  board: BoardPeek | null;
  /** Where a render's reel is, to open it from here. */
  reel: string | null;
  telling: boolean;
  onTell: () => void;
  onCancel: () => void;
}

// The jobs whose progress is told scene by scene; the others (writing, rewriting) say it in a line.
const BY_SCENE: Job["kind"][] = ["cast", "board", "render"];

/** The running job, docked at the bottom of the story page wherever the user is: what it's doing in
 * a sentence, and a mini reel of the scenes. A render's reel opens from here; any other job's stage
 * bars and log are under Details. `sb` is the storyboard of the version the job runs on, or null. */
export function Dock({ job, queued, sb, board, reel, telling, onTell, onCancel }: DockProps) {
  const [open, setOpen] = useState(false);
  const [tip, setTip] = useState<{ n: number; x: number } | null>(null);
  const bySceneNow = !!sb && BY_SCENE.includes(job.kind) && job.status === "running";
  const scenes = bySceneNow && job.progress?.scenes ? sceneStates(sb, board, job) : [];
  const names = Object.fromEntries((sb?.cast ?? []).map((c) => [c.id, c.name]));
  const now = bySceneNow ? headline(job, scenes, names) : null;
  const tipped = tip && scenes.find((s) => s.n === tip.n);
  const message =
    job.status === "queued"
      ? "Queued"
      : now
        ? [now.doing, now.detail].filter(Boolean).join(" · ")
        : job.progress?.message || "Starting…";
  return (
    <section className="dock" aria-label="Job in progress">
      <div className="dock-head">
        <i className={`lamp-dot ${job.status}`} aria-hidden="true" />
        <span className="sr-only" aria-live="polite">
          {now?.doing}
        </span>
        <div className="what">
          <b>
            {jobTitle(job)}
            {queued > 0 ? ` (${queued} more queued)` : ""}
          </b>
          <span>{message}</span>
        </div>
        {job.progress?.eta_s && <span className="left">{timeLeft(job.progress.eta_s)}</span>}
        <button className="small quiet" onClick={() => !telling && onTell()} aria-disabled={telling}>
          {telling ? TELLING : "Tell me when it's ready"}
        </button>
        {reel ? (
          <Link className="btn small primary" to={reel}>
            Open the reel
          </Link>
        ) : (
          <button className="small" onClick={() => setOpen(!open)} aria-expanded={open}>
            {open ? "Hide details" : "Details"}
          </button>
        )}
        <button className="small danger" onClick={onCancel}>
          Cancel
        </button>
      </div>
      {scenes.length > 0 && (
        <div className="minireel" role="list" aria-label="Scenes" onPointerLeave={() => setTip(null)}>
          {scenes.map((s) => (
            <span
              key={s.n}
              role="listitem"
              className="dotb"
              data-s={square(s)}
              data-w={busy(s) || undefined}
              data-f={s.again !== null || s.failing !== null || undefined}
              aria-label={`Scene ${s.n}: ${sceneWords(s)}`}
              onPointerEnter={(e) =>
                e.pointerType !== "touch" &&
                setTip({ n: s.n, x: e.currentTarget.offsetLeft + e.currentTarget.offsetWidth / 2 })
              }
            />
          ))}
          {tip && tipped && (
            <span className="tip" style={{ left: tip.x }} aria-hidden="true">
              Scene {tip.n} · {sceneWords(tipped)}
            </span>
          )}
        </div>
      )}
      {open && (
        <div className="body">
          <Stages job={job} />
          <Log job={job} />
        </div>
      )}
    </section>
  );
}
