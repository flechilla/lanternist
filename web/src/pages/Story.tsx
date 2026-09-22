import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  api,
  ApiError,
  fmtSeconds,
  isActive,
  LANGUAGE_NAMES,
  type Job,
  type Mode,
  type StoryDetail,
  type Storyboard,
} from "../api";
import BoardView from "../components/BoardView";
import FilmView from "../components/FilmView";
import { Dock, Log, Stages } from "../components/JobProgress";
import ScriptEditor from "../components/ScriptEditor";
import { useAction, useJobStreams, useOptions } from "../hooks";

type Step = "script" | "board" | "film";
const STEPS: { id: Step; name: string }[] = [
  { id: "script", name: "Script" },
  { id: "board", name: "Board" },
  { id: "film", name: "Film" },
];

export default function Story() {
  const { id = "", step: stepParam } = useParams();
  const navigate = useNavigate();
  const opts = useOptions();
  const [detail, setDetail] = useState<StoryDetail | null>(null);
  const [draft, setDraft] = useState<Storyboard | null>(null);
  const [dirty, setDirty] = useState(false);
  const [started, setStarted] = useState<Job[]>([]);
  const [stale, setStale] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const { busy, error, setError, run } = useAction();
  const dirtyRef = useRef(false);
  dirtyRef.current = dirty;

  const load = useCallback(async () => {
    const d = await api.story(id);
    setDetail(d);
    if (!dirtyRef.current) setDraft(d.storyboard ? structuredClone(d.storyboard) : null);
    setStarted((s) => s.filter((j) => !d.jobs.some((x) => x.id === j.id)));
    return d;
  }, [id]);

  useEffect(() => {
    load().catch((e) =>
      setError(
        e instanceof ApiError && e.status === 404 ? "This story no longer exists." : String(e.message),
      ),
    );
  }, [load, setError]);

  const allJobs = useMemo(() => [...started, ...(detail?.jobs ?? [])], [started, detail]);
  const live = useJobStreams(allJobs, () => {
    load().catch(() => undefined);
  });
  const jobs = allJobs.map((j) => live[j.id] ?? j);
  const active = jobs.filter(isActive).sort((a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? ""));
  const current = active.find((j) => j.status === "running") ?? active[0];

  // What jobs for this exact version have produced so far, before the next refetch shows it.
  const liveAssets = useMemo(() => {
    const keyframes: Record<string, string> = {};
    let cast: string | undefined;
    for (const j of [...jobs].reverse()) {
      if (!detail || j.version !== detail.version || j.status === "failed") continue;
      Object.assign(keyframes, j.progress?.stages?.keyframes?.assets ?? {});
      cast = j.progress?.stages?.cast?.asset ?? cast;
    }
    return { keyframes, cast };
  }, [jobs, detail]);

  if (error && !detail)
    return (
      <p className="error">
        {error} <Link to="/">Back to your stories</Link>
      </p>
    );
  if (!detail) return <p className="muted">Opening the story…</p>;

  const writing = detail.version === 0;
  const hasPictures = !!detail.board?.scenes.some((s) => s.keyframe);
  const step: Step = (stepParam as Step) ?? (detail.film ? "film" : hasPictures ? "board" : "script");
  const drawingNow =
    !!current && (current.kind === "board" || current.kind === "render" || current.kind === "cast");

  function edit(fn: (sb: Storyboard) => void) {
    setDraft((d) => {
      if (!d) return d;
      const copy = structuredClone(d);
      fn(copy);
      return copy;
    });
    setDirty(true);
  }

  async function saveBoard(sb: Storyboard, note: string) {
    try {
      await api.save(id, sb, detail!.version, note);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setStale(true);
      throw e;
    }
    dirtyRef.current = false;
    setDirty(false);
    await load();
  }

  const save = () => run(() => saveBoard(draft!, "edited"));
  const discard = () => {
    setDirty(false);
    dirtyRef.current = false;
    setDraft(structuredClone(detail.storyboard));
  };
  const ensureSaved = async () => {
    if (dirtyRef.current && draft) await saveBoard(draft, "edited");
  };

  const startJob = (fn: () => Promise<Job>, then?: () => void) =>
    run(async () => {
      await ensureSaved();
      const job = await fn();
      setStarted((s) => [job, ...s]);
      then?.();
    });

  const withVersion = (fn: () => Promise<{ version: number; job: Job }>) =>
    run(async () => {
      await ensureSaved();
      const r = await fn();
      setStarted((s) => [r.job, ...s]);
      await load();
    });

  const setMode = (n: number, mode: Mode) =>
    run(async () => {
      const sb = structuredClone(draft!);
      const sc = sb.scenes.find((s) => s.n === n);
      if (!sc) return;
      sc.mode = mode;
      setDraft(sb);
      await saveBoard(sb, `scene ${n} set to ${mode}`);
    });

  const actions = {
    board: () => startJob(() => api.run(id, "board")),
    render: () =>
      startJob(
        () => api.run(id, "render"),
        () => navigate(`/stories/${id}/film`),
      ),
    cast: () => startJob(() => api.run(id, "cast")),
    rerollCast: () => withVersion(() => api.rerollCast(id)),
    reroll: (n: number) => withVersion(() => api.reroll(id, n)),
    rewrite: (n: number, instruction: string) => startJob(() => api.rewrite(id, n, instruction)),
    setMode,
  };

  const cancel = (job: Job) =>
    run(async () => {
      await api.cancel(job.id);
      await load();
    });
  const remove = () =>
    run(async () => {
      await api.remove(id);
      navigate("/");
    });

  const sb = draft ?? detail.storyboard;
  const writeJob = jobs.find((j) => j.kind === "write");

  return (
    <>
      <div className="story-head">
        <h1>{sb?.title ?? detail.story.title}</h1>
        <div className="facts">
          <span>{LANGUAGE_NAMES[detail.story.language] ?? detail.story.language}</span>
          {sb && <span>{sb.scenes.length} scenes</span>}
          {detail.board?.total && <span>{fmtSeconds(detail.board.total)} with narration</span>}
          {!writing && <span>version {detail.version}</span>}
          <span className="spacer" />
          {confirmDelete ? (
            <span className="row">
              Delete this story and its films?
              <button className="small danger" onClick={remove} disabled={busy}>
                Delete
              </button>
              <button className="small" onClick={() => setConfirmDelete(false)}>
                Keep it
              </button>
            </span>
          ) : (
            <button className="quiet danger small" onClick={() => setConfirmDelete(true)}>
              Delete story
            </button>
          )}
        </div>
      </div>

      {stale && (
        <p className="error">
          This story changed somewhere else since you opened it.{" "}
          <button
            className="small"
            onClick={() => {
              setStale(false);
              setError(null);
              discard();
              load();
            }}
          >
            Load the latest version
          </button>
        </p>
      )}
      {error && !stale && <p className="error">{error}</p>}

      {writing ? (
        <section className="panel stack" style={{ maxWidth: 720 }}>
          {writeJob && writeJob.status !== "failed" && writeJob.status !== "cancelled" ? (
            <>
              <h2>Writing your story</h2>
              <p className="muted">
                The writer drafts the story first, then the cast and a picture, motion and sound note for
                every scene.
              </p>
              <Stages job={writeJob} />
              <Log job={writeJob} />
            </>
          ) : (
            <>
              <h2>The story wasn't written</h2>
              {writeJob?.error && <pre className="log">{writeJob.error.split("\n\n")[0]}</pre>}
              <p>Delete this story and try again from New story.</p>
            </>
          )}
        </section>
      ) : (
        <>
          <nav className="steps" aria-label="Steps">
            {STEPS.map((s, i) => (
              <Link
                key={s.id}
                to={`/stories/${id}/${s.id}`}
                className={step === s.id ? "active" : undefined}
                aria-current={step === s.id ? "page" : undefined}
              >
                <span className="num">{i + 1}</span>
                {s.name}
              </Link>
            ))}
          </nav>

          {step === "script" && draft && (
            <ScriptEditor
              draft={draft}
              edit={edit}
              opts={opts}
              dirty={dirty}
              busy={busy}
              onSave={save}
              onDiscard={discard}
              cast={detail.board?.cast ?? liveAssets.cast ?? null}
              castDrawing={
                !!current &&
                (current.kind === "cast" || current.kind === "board" || current.kind === "render") &&
                !detail.board?.cast
              }
              jobActive={!!current}
              onDrawCast={actions.cast}
              onRerollCast={actions.rerollCast}
              onRewrite={actions.rewrite}
            />
          )}
          {step === "board" && draft && detail.board && (
            <BoardView
              draft={draft}
              board={detail.board}
              liveKeyframes={liveAssets.keyframes}
              drawing={drawingNow}
              jobActive={!!current}
              busy={busy}
              dirty={dirty}
              onMode={actions.setMode}
              onReroll={actions.reroll}
              onBoard={actions.board}
              onRender={actions.render}
            />
          )}
          {step === "film" && (
            <FilmView detail={detail} jobs={jobs} busy={busy} onRender={actions.render} onCancel={cancel} />
          )}
        </>
      )}

      {current && !writing && !(step === "film" && current.kind === "render") && (
        <Dock job={current} queued={active.length - 1} onCancel={() => cancel(current)} />
      )}
    </>
  );
}
