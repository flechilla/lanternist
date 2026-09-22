import { useCallback, useEffect, useEffectEvent, useRef, useState } from "react";
import { api, errorMessage, isActive, type Job, type Options, type VoiceCatalog } from "./api";

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

/** The voices a narration model offers in a language; `model` empty means the default narrator. */
export function useVoiceCatalog(model: string, language: string) {
  const [catalog, setCatalog] = useState<VoiceCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(
    () =>
      api.voiceCatalog(model, language).then(
        (c) => {
          setCatalog(c);
          setError(null);
        },
        (e: unknown) => setError(errorMessage(e)),
      ),
    [model, language],
  );
  useEffect(() => {
    void reload();
  }, [reload]);
  return { catalog, error, reload };
}

/** One audio element that plays one thing at a time: `play` the same key again to stop it.
 * `playing` is the key playing now, cleared when it ends or pauses. Render `<audio ref={audio} hidden />`. */
export function usePlayer<K>() {
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState<K | null>(null);

  useEffect(() => {
    const a = audio.current;
    if (!a) return;
    const stop = () => setPlaying(null);
    a.addEventListener("ended", stop);
    a.addEventListener("pause", stop);
    return () => {
      a.removeEventListener("ended", stop);
      a.removeEventListener("pause", stop);
    };
  }, []);

  function play(key: K, src: string) {
    const a = audio.current!;
    if (playing === key) {
      a.pause();
      return;
    }
    a.src = src;
    a.play().then(
      () => setPlaying(key),
      () => setPlaying(null),
    );
  }

  return { audio, playing, play };
}
