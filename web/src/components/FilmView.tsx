import { useRef } from "react";
import { asset, fmtSeconds, isActive, withPrice, type Job, type StoryDetail } from "../api";
import Reel from "./Reel";

interface Props {
  detail: StoryDetail;
  jobs: Job[];
  /** A render that finished while the page was open: its reel stays up, finished, above the film. */
  finished: Job | undefined;
  busy: boolean;
  /** What rendering again would cost now. */
  renderUsd: number | undefined;
  onRender: () => void;
  onCancel: (job: Job) => void;
}

export default function FilmView({ detail, jobs, finished, busy, renderUsd, onRender, onCancel }: Props) {
  const player = useRef<HTMLVideoElement>(null);
  const renders = jobs.filter((j) => j.kind === "render");
  const running = renders.find(isActive);
  const film = renders.find((j) => j.status === "done" && j.result?.film) ?? detail.film;
  const lastFinished = renders.find((j) => !isActive(j));
  // A budget stop is shown at the top of the story, with the way to carry on; and a new render replaces it.
  const failed =
    !running && lastFinished?.status === "failed" && !lastFinished.result?.budget ? lastFinished : undefined;
  const result = film?.result;
  const name = detail.story.slug || "film";
  const reel = running ?? finished;

  function watch() {
    const v = player.current;
    if (!v) return;
    v.scrollIntoView({
      block: "center",
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
    });
    void v.play().catch(() => undefined);
  }

  return (
    <div className="stack">
      {reel && detail.storyboard && (
        <Reel
          key={reel.id}
          sb={detail.storyboard}
          board={detail.board}
          job={reel}
          budget={detail.budget}
          onCancel={() => onCancel(reel)}
          onWatch={watch}
        />
      )}

      {failed && (
        <section className="error">
          <b>The last render failed.</b> {failed.error?.split("\n")[0]}
          <details style={{ marginTop: 8 }}>
            <summary>Details</summary>
            <pre className="log">{failed.error}</pre>
          </details>
        </section>
      )}

      {result?.film ? (
        <section className="hall">
          <video
            ref={player}
            key={result.film}
            controls
            preload="metadata"
            playsInline
            poster={asset(detail.board?.scenes[0]?.keyframe)}
          >
            <source src={asset(result.film)} type="video/mp4" />
            {result.vtt && (
              <track
                kind="subtitles"
                src={asset(result.vtt)}
                srcLang={detail.story.language}
                label="Subtitles"
                default
              />
            )}
          </video>
          <div className="caption">
            <span>{fmtSeconds(result.duration)}</span>
            <a href={asset(result.film, `${name}-v${film!.version}.mp4`)}>Download MP4</a>
            {result.srt && (
              <a href={asset(result.srt, `${name}-v${film!.version}.srt`)}>Download subtitles</a>
            )}
            <span className="spacer" />
            <button className="small" onClick={onRender} disabled={busy || !!running}>
              {withPrice("Render again", renderUsd)}
            </button>
          </div>
          <p className="note" style={{ marginTop: 10 }}>
            Made from version {film!.version}
            {film!.version !== detail.version
              ? `. The script is now at version ${detail.version}; render again to include the changes.`
              : "."}
            {result.path && <> Saved at {result.path}</>}
          </p>
        </section>
      ) : !running ? (
        <section className="hall empty">
          <h2 style={{ marginBottom: 10 }}>No film yet</h2>
          <p>
            Rendering animates the video scenes, gives stills their camera moves, and mixes the narration with
            each scene's ambience.
          </p>
          <button className="primary" onClick={onRender} disabled={busy}>
            {withPrice("Approve and render", renderUsd)}
          </button>
        </section>
      ) : null}
    </div>
  );
}
