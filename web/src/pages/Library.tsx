import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, fmtSeconds, LANGUAGE_NAMES, type StoryListItem } from "../api";
import Slide from "../components/Slide";
import { useAction } from "../hooks";

export default function Library() {
  const [stories, setStories] = useState<StoryListItem[] | null>(null);
  const { error, setError, run } = useAction();
  const file = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const load = useCallback(() => {
    api.stories().then(setStories, (e) => setError(String(e.message ?? e)));
  }, [setError]);

  useEffect(load, [load]);
  // While something is working, keep the list fresh.
  useEffect(() => {
    if (!stories?.some((s) => s.active_jobs)) return;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [stories, load]);

  async function importFile(f: File) {
    const created = await run(async () => {
      let data: unknown;
      try {
        data = JSON.parse(await f.text());
      } catch {
        throw new Error(`${f.name} isn't valid JSON. Choose a storyboard .json file.`);
      }
      return api.importStoryboard(data);
    });
    if (created) navigate(`/stories/${created.story.id}/board`);
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Your stories</h1>
          <p>Each story becomes a narrated film, drawn and voiced on this machine.</p>
        </div>
        <div className="spacer" />
        <input
          ref={file}
          type="file"
          accept="application/json,.json"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) importFile(f);
            e.target.value = "";
          }}
        />
        <button onClick={() => file.current?.click()}>Import storyboard</button>
        <Link className="btn primary" to="/new">
          New story
        </Link>
      </div>
      {error && <p className="error">{error}</p>}
      {stories === null && !error && <p className="muted">Loading your stories…</p>}
      {stories?.length === 0 && (
        <div className="empty-state">
          <h2>No stories yet</h2>
          <p>Start with a one-line idea. The writer drafts the story, then you shape it scene by scene.</p>
          <Link className="btn primary" to="/new">
            Write your first story
          </Link>
        </div>
      )}
      <div className="library">
        {stories?.map((s) => (
          <Link key={s.id} to={`/stories/${s.id}${s.film ? "/film" : ""}`} className="story-row">
            <Slide
              image={s.poster}
              video={s.poster ? null : s.film?.film}
              empty={s.version ? "No film yet" : "Being written"}
              alt=""
            />
            <div>
              <h2>{s.title}</h2>
              <div className="facts">
                <span>{LANGUAGE_NAMES[s.language] ?? s.language}</span>
                <span>{s.scenes} scenes</span>
                {s.film && <span>{fmtSeconds(s.film.duration)} film</span>}
                <span>edited {new Date(s.updated_at + "Z").toLocaleDateString()}</span>
              </div>
            </div>
            {s.active_jobs > 0 ? (
              <span className="status-pill working">Working</span>
            ) : s.film ? (
              <span className="status-pill ready">Film ready</span>
            ) : null}
          </Link>
        ))}
      </div>
    </>
  );
}
