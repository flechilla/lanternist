import { useEffect, useRef, useState } from "react";
import type { Job } from "../api";

const STAGES: [string, string][] = [
  ["write", "Writing"],
  ["narration", "Narration"],
  ["cast", "Cast sheet"],
  ["keyframes", "Pictures"],
  ["motion", "Animation"],
  ["clips", "Scene clips"],
  ["mix", "Final mix"],
];

export function jobTitle(job: Job): string {
  switch (job.kind) {
    case "write":
      return "Writing the story";
    case "rewrite":
      return `Rewriting scene ${job.params.n ?? ""}`;
    case "cast":
      return "Drawing the cast sheet";
    case "board":
      return "Preparing the board";
    case "render":
      return "Rendering the film";
  }
}

export function Stages({ job }: { job: Job }) {
  const stages = job.progress?.stages ?? {};
  const shown = STAGES.filter(([key]) => stages[key]);
  if (!shown.length)
    return (
      <p className="muted">{job.status === "queued" ? "Waiting for the job ahead of it." : "Starting…"}</p>
    );
  return (
    <div className="stages">
      {shown.map(([key, name]) => {
        const st = stages[key];
        const pct = st.total ? Math.round((100 * st.done) / st.total) : st.status === "done" ? 100 : 0;
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
            <span className="count">
              {st.total ? `${st.done}/${st.total}` : st.status === "done" ? "done" : "working"}
            </span>
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
