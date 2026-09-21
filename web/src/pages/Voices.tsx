import { useEffect, useState, type FormEvent } from "react";
import { api, type Voice } from "../api";
import { useAction } from "../hooks";

export default function Voices() {
  const [voices, setVoices] = useState<Voice[] | null>(null);
  const [name, setName] = useState("");
  const [transcript, setTranscript] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [added, setAdded] = useState<string | null>(null);
  const { busy, error, setError, run } = useAction();

  const load = () => api.voices().then(setVoices, (e) => setError(e.message));
  useEffect(() => { load(); }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    const form = new FormData();
    form.append("name", name.trim());
    form.append("transcript", transcript);
    form.append("audio", file);
    const v = await run(() => api.addVoice(form));
    if (v) {
      setAdded(v.name);
      setName(""); setTranscript(""); setFile(null);
      (e.target as HTMLFormElement).reset();
      load();
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Voices</h1>
          <p>The narrator clones one of these reference recordings. A clean 20 to 30 seconds in a quiet room works best.</p>
        </div>
      </div>
      <div className="voices">
        <section className="checklist" aria-label="Your voices">
          {voices === null && <p className="voice-row muted">Loading…</p>}
          {voices?.length === 0 && <p className="voice-row">No voices yet. Add a recording to narrate your stories.</p>}
          {voices?.map((v) => (
            <div key={v.name} className="voice-row">
              <b>{v.name}{added === v.name ? " (just added)" : ""}</b>
              <span>{v.has_transcript ? "With transcript: closest match to the voice" : "No transcript: cloned from the sound alone"}</span>
              <audio controls preload="none" src={`/api/voices/${encodeURIComponent(v.name)}/audio`} />
              <span>{v.path}</span>
            </div>
          ))}
        </section>
        <form className="panel stack" onSubmit={submit}>
          <h2>Add a voice</h2>
          <label className="field">
            Name
            <input type="text" required value={name} onChange={(e) => setName(e.target.value)} placeholder="Grandma" />
          </label>
          <label className="field">
            Recording
            <small>Any audio file. It's converted to 24 kHz mono.</small>
            <input type="file" required accept="audio/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </label>
          <label className="field">
            What's said in it
            <small>Optional. The exact words make the clone closer.</small>
            <textarea rows={4} value={transcript} onChange={(e) => setTranscript(e.target.value)} />
          </label>
          {error && <p className="error">{error}</p>}
          <button className="primary" type="submit" disabled={busy || !file || !name.trim()}>{busy ? "Adding…" : "Add voice"}</button>
        </form>
      </div>
    </>
  );
}
