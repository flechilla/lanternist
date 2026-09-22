import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  api,
  ApiError,
  errorMessage,
  fmtSeconds,
  fmtUsd,
  isActive,
  LANGUAGE_NAMES,
  type Estimate,
  type Job,
  type Mode,
  type Models,
  type StoryDetail,
  type Storyboard,
} from "../api";
import BoardView, { type Catalogs } from "../components/BoardView";
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

/** A system notification that a job the viewer asked about has ended, when they've gone elsewhere. */
function tell(job: Job, title: string) {
  if (!document.hidden || Notification.permission !== "granted") return;
  const what = job.kind === "render" ? "Your film" : job.kind === "board" ? "The board" : "The job";
  const heading = job.status === "done" ? `${what} is ready` : `${what} stopped`;
  new Notification(heading, { body: job.status === "done" ? title : (job.error?.split("\n")[0] ?? title) });
}

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
  // `apply` and `ensureSaved` must see an edit made since the last render, so the flag lives in a ref too.
  const dirtyRef = useRef(false);
  const markDirty = (value: boolean) => {
    dirtyRef.current = value;
    setDirty(value);
  };

  // The version the draft was taken from: a save is based on it, so a version saved meanwhile (a
  // picture check's new seeds) makes the save a conflict instead of being overwritten.
  const draftVersion = useRef<number | null>(null);

  const apply = useCallback((d: StoryDetail) => {
    setDetail(d);
    if (!dirtyRef.current) {
      setDraft(d.storyboard ? structuredClone(d.storyboard) : null);
      draftVersion.current = d.version;
    }
    setStarted((s) => s.filter((j) => !d.jobs.some((x) => x.id === j.id)));
  }, []);
  const load = useCallback(() => api.story(id).then(apply), [id, apply]);

  useEffect(() => {
    load().catch((e: unknown) =>
      setError(e instanceof ApiError && e.status === 404 ? "This story no longer exists." : errorMessage(e)),
    );
  }, [load, setError]);

  // What preparing the board and rendering would cost now; fetched again whenever the story reloads.
  const [estimates, setEstimates] = useState<{ board: Estimate; render: Estimate } | null>(null);
  const [estimateError, setEstimateError] = useState<string | null>(null);
  useEffect(() => {
    if (!detail?.version) return;
    Promise.all([api.estimate(id, "board"), api.estimate(id, "render")]).then(
      ([board, render]) => {
        setEstimates({ board, render });
        setEstimateError(null);
      },
      (e: unknown) => setEstimateError(errorMessage(e)),
    );
  }, [id, detail]);

  // The models each stage can use, for the Board's pickers.
  const [catalogs, setCatalogs] = useState<Catalogs | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  useEffect(() => {
    Promise.all([
      api.models("image.keyframe"),
      api.models("video.image_to_video"),
      api.models("audio.ambience"),
      api.models("tts.speak"),
    ]).then(
      ([image, video, ambience, tts]) => setCatalogs({ image, video, ambience, tts }),
      (e: unknown) => setCatalogError(errorMessage(e)),
    );
  }, []);

  const allJobs = useMemo(() => [...started, ...(detail?.jobs ?? [])], [started, detail]);
  // The last job that ended while the page was open: a render's reel stays up, finished.
  const [ended, setEnded] = useState<Job | null>(null);
  // The jobs the viewer asked to be told about when they end, if the page is in the background then.
  const [telling, setTelling] = useState<Record<string, boolean>>({});
  const live = useJobStreams(allJobs, (job) => {
    setEnded(job);
    if (telling[job.id]) tell(job, detail?.storyboard?.title ?? detail?.story.title ?? "");
    load().catch(() => undefined);
  });
  const jobs = allJobs.map((j) => live[j.id] ?? j);
  const active = jobs.filter(isActive).sort((a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? ""));
  const current = active.find((j) => j.status === "running") ?? active[0];

  // A picture check saves its new seeds as a version while the job runs: load it, so the page (and the
  // reel, which shows a render over its own version) keeps up.
  const ahead = !!detail && !!current?.version && current.version > detail.version;
  useEffect(() => {
    if (ahead) load().catch(() => undefined);
  }, [ahead, load]);

  // What jobs for this exact version have produced so far, before the next refetch shows it.
  const liveAssets = useMemo(() => {
    const keyframes: Record<string, string> = {};
    let cast: string | undefined;
    for (const j of [...jobs].reverse()) {
      if (!detail || j.version !== detail.version || j.status === "failed") continue;
      for (const [n, steps] of Object.entries(j.progress?.scenes ?? {}))
        if (steps.keyframes?.asset) keyframes[n] = steps.keyframes.asset;
      cast = j.progress?.stages?.cast?.asset ?? cast;
    }
    return { keyframes, cast };
  }, [jobs, detail]);

  // The tab says how far a job has got, so a render can run in a background tab.
  const title = draft?.title ?? detail?.story.title;
  const fraction = current?.status === "running" ? current.progress?.fraction : undefined;
  useEffect(() => {
    if (!title) return;
    document.title = `${fraction != null ? `(${Math.round(fraction * 100)}%) ` : ""}${title} · Lanternist`;
    return () => {
      document.title = "Lanternist";
    };
  }, [title, fraction]);

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
    markDirty(true);
  }

  async function saveBoard(sb: Storyboard, note: string) {
    try {
      await api.save(id, sb, draftVersion.current ?? detail!.version, note);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setStale(true);
      throw e;
    }
    markDirty(false);
    await load();
  }

  const save = () => run(() => saveBoard(draft!, "edited"));
  const discard = () => {
    markDirty(false);
    setDraft(structuredClone(detail.storyboard));
    draftVersion.current = detail.version;
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

  const setModels = (change: Partial<Models>, note: string) =>
    run(async () => {
      const sb = structuredClone(draft!);
      sb.models = { ...sb.models, ...change };
      setDraft(sb);
      await saveBoard(sb, note);
    });

  const setBudget = (usd: number | null) =>
    run(async () => {
      await api.setBudget(id, usd);
      await load();
    });

  // The last board or render, if it stopped before a stage that would have gone over the budget.
  const lastRun = jobs.find((j) => (j.kind === "board" || j.kind === "render") && !isActive(j));
  const stopped = lastRun?.status === "failed" ? lastRun.result?.budget : undefined;
  const flagged = lastRun?.status === "done" ? Object.entries(lastRun.result?.flagged ?? {}) : [];
  const redrawn = lastRun?.status === "done" ? Object.keys(lastRun.result?.redrawn ?? {}) : [];
  // Enough for everything the job still has to make, not just the stage that stopped it.
  const raiseTo = stopped && estimates?.[lastRun?.kind === "board" ? "board" : "render"].raise_to_usd;
  const carryOn = () =>
    run(async () => {
      await api.setBudget(id, raiseTo!);
      const job = await api.run(id, lastRun!.kind as "board" | "render");
      setStarted((s) => [job, ...s]);
      await load();
    });

  const actions = {
    board: () => startJob(() => api.run(id, "board")),
    render: () =>
      startJob(
        () => api.run(id, "render"),
        () => void navigate(`/stories/${id}/film`),
      ),
    cast: () => startJob(() => api.run(id, "cast")),
    rerollCast: () => withVersion(() => api.rerollCast(id)),
    reroll: (n: number) => withVersion(() => api.reroll(id, n)),
    retake: (n: number) => withVersion(() => api.retake(id, n)),
    rewrite: (n: number, instruction: string) => startJob(() => api.rewrite(id, n, instruction)),
    setMode,
  };

  // Permission is asked for only when the viewer asks to be told, never when the page opens.
  const askToTell = (job: Job) =>
    run(async () => {
      if (!("Notification" in window)) throw new Error("This browser can't show notifications.");
      const allowed =
        Notification.permission === "default"
          ? await Notification.requestPermission()
          : Notification.permission;
      if (allowed !== "granted")
        throw new Error("Notifications are off for this page. Allow them in the browser's site settings.");
      setTelling((t) => ({ ...t, [job.id]: true }));
    });

  const cancel = (job: Job) =>
    run(async () => {
      await api.cancel(job.id);
      await load();
    });
  const remove = () =>
    run(async () => {
      await api.remove(id);
      await navigate("/");
    });

  const sb = draft ?? detail.storyboard;
  // The dock draws a job's scenes over the story, so only when it runs on the version the page shows.
  const onThisVersion = current?.version === detail.version;
  const writeJob = jobs.find((j) => j.kind === "write");
  const w = detail.writer;
  const writtenBy =
    w && `written by ${w.model}` + (w.cost_usd ? ` for ${fmtUsd(w.cost_usd)}` : w.local ? ", locally" : "");

  return (
    <>
      <div className="story-head">
        <h1>{sb?.title ?? detail.story.title}</h1>
        <div className="facts">
          <span>{LANGUAGE_NAMES[detail.story.language] ?? detail.story.language}</span>
          {sb && <span>{sb.scenes.length} scenes</span>}
          {detail.board?.total && <span>{fmtSeconds(detail.board.total)} with narration</span>}
          {!writing && <span>version {detail.version}</span>}
          {writtenBy && <span>{writtenBy}</span>}
          {detail.budget.spent_usd > 0 && <span>{fmtUsd(detail.budget.spent_usd)} spent</span>}
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
              load().catch((e: unknown) => setError(errorMessage(e)));
            }}
          >
            Load the latest version
          </button>
        </p>
      )}
      {error && !stale && <p className="error">{error}</p>}
      {stopped && lastRun && (
        <div className="error row" role="status">
          <span className="spacer">{lastRun.error}</span>
          {raiseTo && (
            <button className="small primary" onClick={carryOn} disabled={busy || !!current}>
              Raise the budget to {fmtUsd(raiseTo)} and carry on
            </button>
          )}
        </div>
      )}

      {(flagged.length > 0 || redrawn.length > 0) && (
        <div className="panel stack" role="status">
          {redrawn.length > 0 && (
            <p>
              The picture check drew scene{redrawn.length > 1 ? "s" : ""} {redrawn.join(", ")} again.
            </p>
          )}
          {flagged.length > 0 && (
            <>
              <p>These pictures still fail the check. Re-roll them on the Board, or change what they show:</p>
              <ul>
                {flagged.map(([n, why]) => (
                  <li key={n}>
                    Scene {n}: {why}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      {writing ? (
        <section className="panel stack" style={{ maxWidth: 720 }}>
          {writeJob && writeJob.status !== "failed" && writeJob.status !== "cancelled" ? (
            <>
              <h2>Writing your story</h2>
              <Passes job={writeJob} />
              <details>
                <summary>Behind the scenes</summary>
                <Stages job={writeJob} />
                <Log job={writeJob} />
              </details>
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
              narrators={catalogs?.tts ?? null}
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
              catalogs={catalogs}
              catalogError={catalogError}
              estimates={estimates}
              estimateError={estimateError}
              budget={detail.budget}
              onBudget={setBudget}
              onMode={actions.setMode}
              onModels={setModels}
              onReroll={actions.reroll}
              onRetake={actions.retake}
              onBoard={actions.board}
              onRender={actions.render}
            />
          )}
          {step === "film" && (
            <FilmView
              detail={detail}
              jobs={jobs}
              finished={ended?.kind === "render" && ended.status === "done" ? ended : undefined}
              telling={telling}
              onTell={(job) => void askToTell(job)}
              busy={busy}
              renderUsd={estimates?.render.total_usd}
              onRender={actions.render}
              onCancel={cancel}
            />
          )}
        </>
      )}

      {current && !writing && !(step === "film" && current.kind === "render") && (
        <Dock
          job={current}
          queued={active.length - 1}
          sb={onThisVersion ? detail.storyboard : null}
          board={onThisVersion ? detail.board : null}
          reel={current.kind === "render" && onThisVersion ? `/stories/${id}/film` : null}
          telling={!!telling[current.id]}
          onTell={() => void askToTell(current)}
          onCancel={() => cancel(current)}
        />
      )}
    </>
  );
}

/** The writer's passes, as the job names them: each done, now, or to come. */
function Passes({ job }: { job: Job }) {
  const write = job.progress?.stages?.write;
  const passes = write?.passes ?? [];
  const done = write?.done ?? 0;
  const running = job.status === "running";
  return (
    <>
      <p className="sr-only" aria-live="polite">
        {running ? passes[done] : ""}
      </p>
      <ol className="passes">
        {passes.map((name, i) => {
          const state = done > i ? "done" : done === i && running ? "working" : "planned";
          return (
            <li key={name} data-state={state} aria-current={state === "working" ? "step" : undefined}>
              {name}
              <span className="sr-only">
                {state === "done" ? ", done" : state === "working" ? ", now" : ", to come"}
              </span>
            </li>
          );
        })}
      </ol>
    </>
  );
}
