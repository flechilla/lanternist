import { useState } from "react";
import { api, asset, recording, withPrice, type Job, type VoiceCatalog } from "../api";
import { useAction, useJobStreams, useOptions, usePlayer } from "../hooks";

interface Props {
  catalog: VoiceCatalog | null;
  error: string | null;
  language: string;
  /** Fetch the catalog again: a sample just made shows up in it. */
  onReload: () => void;
  /** The chosen voice; leave it out to only listen (the Voices page). */
  value?: string;
  onChange?: (voice: string) => void;
}

/** The voices of a narration model, each with a way to hear it before choosing it. A preset's sample
 * is made once on first listen, at the price shown, and plays at once after that. */
export default function VoicePicker(p: Props) {
  const { audio, playing, play } = usePlayer<string>();
  const [making, setMaking] = useState<Record<string, Job>>({});
  const { error, setError, run } = useAction();
  const opts = useOptions();
  const cat = p.catalog;

  useJobStreams(Object.values(making), (job) => {
    const voice = Object.keys(making).find((v) => making[v].id === job.id);
    setMaking((m) => Object.fromEntries(Object.entries(m).filter(([, j]) => j.id !== job.id)));
    if (voice && job.status === "done" && job.result?.audio) {
      play(voice, asset(job.result.audio)!);
      p.onReload();
    } else if (job.status !== "done") {
      setError(job.error?.split("\n")[0] ?? "The sample wasn't made. Try again.");
    }
  });

  const hear = (voice: string, sample: string | null) =>
    sample
      ? play(voice, asset(sample)!)
      : run(async () => {
          const r = await api.sample(cat!.model, voice, p.language);
          if (r.audio) {
            play(voice, asset(r.audio)!);
            p.onReload();
          } else if (r.job) {
            setMaking((m) => ({ ...m, [voice]: r.job! }));
          }
        });

  const listen = (voice: string, sample: string | null) =>
    making[voice]
      ? "Making it…"
      : playing === voice
        ? "Stop"
        : sample
          ? "Listen"
          : withPrice("Listen", cat?.sample_usd);

  const language = opts?.languages.find((l) => l.id === p.language)?.name ?? p.language;

  return (
    <div className="voice-list">
      {/* Mounted before the voices load, so its listeners above are attached. */}
      <audio ref={audio} hidden />
      {!cat && <small className="muted">{p.error ?? "Loading the voices…"}</small>}
      {cat && !cat.speaks && (
        <p className="error">
          {cat.label} doesn't speak {language}. Pick another narration model.
        </p>
      )}
      {cat?.presets.map((v) => (
        <div className="voice-item" key={v.id}>
          <button
            type="button"
            className="pick-row"
            aria-pressed={p.value === v.id}
            disabled={!p.onChange}
            onClick={() => p.onChange?.(v.id)}
          >
            <b>{v.label}</b>
          </button>
          <button
            type="button"
            className="quiet small"
            disabled={!!making[v.id]}
            aria-label={`${playing === v.id ? "Stop" : "Listen to"} ${v.label}`}
            onClick={() => void hear(v.id, v.sample)}
          >
            {listen(v.id, v.sample)}
          </button>
        </div>
      ))}
      {cat?.recordings.map((v) => (
        <div className="voice-item" key={v.name}>
          <button
            type="button"
            className="pick-row"
            aria-pressed={p.value === v.name}
            disabled={!p.onChange}
            onClick={() => p.onChange?.(v.name)}
          >
            <b>{v.name}</b>
            <small>
              Your recording, cloned{v.has_transcript ? " with its transcript" : " from the sound alone"}
            </small>
          </button>
          <button
            type="button"
            className="quiet small"
            aria-label={`${playing === `rec:${v.name}` ? "Stop" : "Play"} the recording ${v.name}`}
            onClick={() => play(`rec:${v.name}`, recording(v.name))}
          >
            {playing === `rec:${v.name}` ? "Stop" : "Recording"}
          </button>
          {!cat.local && (
            <button
              type="button"
              className="quiet small"
              disabled={!!making[v.name]}
              aria-label={`Listen to ${v.name} as ${cat.label} says it`}
              onClick={() => void hear(v.name, v.sample)}
            >
              {listen(v.name, v.sample)}
            </button>
          )}
        </div>
      ))}
      {cat?.clone && !cat.recordings.length && (
        <small className="muted">No recordings yet. Add one on the Voices page to clone it.</small>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  );
}
