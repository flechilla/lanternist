import { useCallback, useEffect, useState } from "react";
import { api, errorMessage, type Check } from "../api";

const MARK = { ok: "✓", warn: "!", fail: "✗" } as const;
const WORD = { ok: "ready", warn: "warning", fail: "problem" } as const;

export default function Doctor() {
  const [checks, setChecks] = useState<Check[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(true);

  const check = useCallback(
    () =>
      api
        .doctor()
        .then(setChecks, (e: unknown) => setError(errorMessage(e)))
        .finally(() => setRunning(false)),
    [],
  );
  useEffect(() => {
    void check();
  }, [check]);

  function again() {
    setRunning(true);
    setError(null);
    void check();
  }

  const fails = checks?.filter((c) => c.status === "fail").length ?? 0;
  const warns = checks?.filter((c) => c.status === "warn").length ?? 0;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>System check</h1>
          <p>
            {checks === null
              ? "Checking the GPU, the models and the tools a film needs. This takes a few seconds."
              : fails
                ? `${fails} ${fails === 1 ? "problem stops" : "problems stop"} films from rendering. Each line says what to fix.`
                : `Everything a film needs is installed and reachable.${warns ? ` ${warns === 1 ? "One warning" : `${warns} warnings`} below won't stop a render.` : ""}`}
          </p>
        </div>
        <div className="spacer" />
        <button onClick={again} disabled={running}>
          {running ? "Checking…" : "Check again"}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {checks && (
        <div className="checklist">
          {checks.map((c) => (
            <div key={c.name} className={`checkrow ${c.status}`}>
              <span className="mark" aria-label={WORD[c.status]}>
                {MARK[c.status]}
              </span>
              <b>{c.name}</b>
              <span className="detail">{c.detail}</span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
