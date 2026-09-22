import { useCallback, useEffect, useEffectEvent, useState } from "react";
import { api, errorMessage, isActive, type Job, type Options } from "./api";

/** Follow a set of jobs over SSE. Returns the freshest copy of each; calls onEnd when one finishes. */
export function useJobStreams(jobs: Job[], onEnd: (job: Job) => void): Record<string, Job> {
  const [live, setLive] = useState<Record<string, Job>>({});
  const onJobEnd = useEffectEvent(onEnd);
  const ids = jobs
    .filter(isActive)
    .map((j) => j.id)
    .sort()
    .join(",");

  useEffect(() => {
    if (!ids) return;
    const sources = ids.split(",").map((id) => {
      const es = new EventSource(`/api/jobs/${id}/events`);
      es.addEventListener("job", (e) => {
        const job = JSON.parse(e.data as string) as Job;
        setLive((prev) => ({ ...prev, [job.id]: job }));
        if (!isActive(job)) {
          // Close before the server ends the stream, or EventSource would reconnect.
          es.close();
          onJobEnd(job);
        }
      });
      es.addEventListener("gone", () => es.close());
      return es;
    });
    return () => sources.forEach((es) => es.close());
  }, [ids]);

  return live;
}

let optionsCache: Promise<Options> | null = null;

export function useOptions(): Options | null {
  const [opts, setOpts] = useState<Options | null>(null);
  useEffect(() => {
    optionsCache ??= api.options().catch((e) => {
      optionsCache = null;
      throw e;
    });
    optionsCache.then(setOpts, () => setOpts(null));
  }, []);
  return opts;
}

/** Run an async action, tracking busy state and the last error message. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async <T>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(errorMessage(e));
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, setError, run };
}
