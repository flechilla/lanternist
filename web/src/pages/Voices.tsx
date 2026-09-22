import { useEffect, useState, type FormEvent } from "react";
import { api, errorMessage, type MediaCatalog } from "../api";
import LanguageSelect from "../components/LanguageSelect";
import ModelPicker from "../components/ModelPicker";
import VoicePicker from "../components/VoicePicker";
import { useAction, useVoiceCatalog } from "../hooks";

export default function Voices() {
  const [model, setModel] = useState("");
  const [language, setLanguage] = useState("en");
  const [narrators, setNarrators] = useState<MediaCatalog | null>(null);
  const [name, setName] = useState("");
  const [transcript, setTranscript] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [added, setAdded] = useState<string | null>(null);
  const { busy, error, setError, run } = useAction();
  const voices = useVoiceCatalog(model, language);

  useEffect(() => {
    api.models("tts.speak").then(setNarrators, (e: unknown) => setError(errorMessage(e)));
  }, [setError]);

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
      setName("");
      setTranscript("");
      setFile(null);
      (e.target as HTMLFormElement).reset();
      await voices.reload();
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Voices</h1>
          <p>
            Hear every narrator before you choose one. Models on fal speak in voices of their own, and some
            clone your recordings; the narrator on this machine clones a recording. A clean 20 to 30 seconds
            in a quiet room works best.
          </p>
        </div>
      </div>
      <div className="voices">
        <section className="panel stack" aria-label="Narrators and their voices">
          <ModelPicker
            label="Narration model"
            catalog={narrators}
            error={error}
            value={model}
            onChange={(m) => setModel(m)}
          />
          <label className="field">
            Language of the sample
            <LanguageSelect value={language} onChange={setLanguage} />
          </label>
          {added && <p className="muted">Added {added}. It's among the recordings below.</p>}
          <VoicePicker
            catalog={voices.catalog}
            error={voices.error}
            language={language}
            onReload={() => void voices.reload()}
          />
        </section>
        <form className="panel stack" onSubmit={submit}>
          <h2>Add a voice</h2>
          <label className="field">
            Name
            <input
              type="text"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Grandma"
            />
          </label>
          <label className="field">
            Recording
            <small>Any audio file. It's converted to 24 kHz mono.</small>
            <input
              type="file"
              required
              accept="audio/*"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <label className="field">
            What's said in it
            <small>Optional. The exact words make the clone closer.</small>
            <textarea rows={4} value={transcript} onChange={(e) => setTranscript(e.target.value)} />
          </label>
          {error && <p className="error">{error}</p>}
          <button className="primary" type="submit" disabled={busy || !file || !name.trim()}>
            {busy ? "Adding…" : "Add voice"}
          </button>
        </form>
      </div>
    </>
  );
}
