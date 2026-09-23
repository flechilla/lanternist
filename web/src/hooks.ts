import { useCallback, useEffect, useEffectEvent, useRef, useState, useSyncExternalStore } from "react";
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

/** The options, or why the API didn't give them; both null until it answers. */
export function useOptionsOrError(): { opts: Options | null; error: string | null } {
  const [state, setState] = useState<{ opts: Options | null; error: string | null }>({
    opts: null,
    error: null,
  });
  useEffect(() => {
    optionsCache ??= api.options().catch((e) => {
      optionsCache = null;
      throw e;
    });
    optionsCache.then(
      (opts) => setState({ opts, error: null }),
      (e) => setState({ opts: null, error: errorMessage(e) }),
    );
  }, []);
  return state;
}

export function useOptions(): Options | null {
  return useOptionsOrError().opts;
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

/** A setting this browser remembers for the viewer, such as a panel left open. Storage can be blocked
 * or empty (a private window), so it falls back to `initial` and still works for the visit. */
export function useStored<T>(key: string, initial: T): [T, (value: T) => void] {
  const name = `lanternist.${key}`;
  const [value, setValue] = useState<T>(() => {
    try {
      const saved = localStorage.getItem(name);
      return saved === null ? initial : (JSON.parse(saved) as T);
    } catch {
      return initial;
    }
  });
  const store = useCallback(
    (v: T) => {
      setValue(v);
      try {
        localStorage.setItem(name, JSON.stringify(v));
      } catch {
        /* not remembered past this visit */
      }
    },
    [name],
  );
  return [value, store];
}

/** An element's width as it changes; 0 until it's laid out. */
export function useWidth(ref: React.RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

function onVisibility(change: () => void) {
  document.addEventListener("visibilitychange", change);
  return () => document.removeEventListener("visibilitychange", change);
}

/** Whether the page is on screen. What arrives while it's hidden shouldn't all animate when it's back. */
export function useVisible(): boolean {
  return useSyncExternalStore(onVisibility, () => document.visibilityState === "visible");
}

function onMotionPreference(change: () => void) {
  const query = matchMedia("(prefers-reduced-motion: reduce)");
  query.addEventListener("change", change);
  return () => query.removeEventListener("change", change);
}

/** Whether the viewer asked their system for less motion. */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(
    onMotionPreference,
    () => matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
}
