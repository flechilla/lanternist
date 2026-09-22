import { useEffect, useRef, useState } from "react";
import type { Job } from "../api";
import { stageCount, stageShare } from "../reel";

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

/** The running job, docked at the bottom of the story page wherever the user is. */
export function Dock({ job, queued, onCancel }: { job: Job; queued: number; onCancel: () => void }) {
  const [open, setOpen] = useState(false);
  const message = job.status === "queued" ? "Queued" : job.progress?.message || "Starting…";
  return (
    <section className="dock" aria-live="polite" aria-label="Job in progress">
      <div className="dock-head">
        <i className={`lamp-dot ${job.status}`} aria-hidden="true" />
        <div className="what">
          <b>
            {jobTitle(job)}
            {queued > 0 ? ` (${queued} more queued)` : ""}
          </b>
          <span>{message}</span>
        </div>
        <button className="small" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? "Hide details" : "Details"}
        </button>
        <button className="small danger" onClick={onCancel}>
          Cancel
        </button>
      </div>
      {open && (
        <div className="body">
          <Stages job={job} />
          <Log job={job} />
        </div>
      )}
    </section>
  );
}
