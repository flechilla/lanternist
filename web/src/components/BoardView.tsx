import { useEffect, useRef, useState } from "react";
import {
  asset,
  chosenModel,
  fmtUsd,
  type BoardPeek,
  type Budget,
  type Estimate,
  type MediaCatalog,
  type Mode,
  type Models,
  type Storyboard,
  withPrice,
} from "../api";
import EstimateBox from "./EstimateBox";
import ModelPicker from "./ModelPicker";
import Slide from "./Slide";

interface Props {
  draft: Storyboard;
  board: BoardPeek;
  liveKeyframes: Record<string, string>;
  drawing: boolean;
  jobActive: boolean;
  busy: boolean;
  dirty: boolean;
  pictures: MediaCatalog | null;
  catalogError: string | null;
  estimates: { board: Estimate; render: Estimate } | null;
  estimateError: string | null;
  budget: Budget;
  onBudget: (usd: number | null) => void;
  onMode: (n: number, mode: Mode) => void;
  onModels: (change: Partial<Models>, note: string) => void;
  onReroll: (n: number) => void;
  onBoard: () => void;
  onRender: () => void;
}

export default function BoardView(p: Props) {
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState<number | null>(null);

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

  function play(n: number, src: string) {
    const a = audio.current!;
    if (playing === n) {
      a.pause();
      return;
    }
    a.src = src;
    a.play().then(
      () => setPlaying(n),
      () => setPlaying(null),
    );
  }

  const scenes = p.draft.scenes.map((s) => {
    const peek = p.board.scenes.find((b) => b.n === s.n);
    return { s, peek, keyframe: peek?.keyframe ?? p.liveKeyframes[String(s.n)] ?? null };
  });
  const missing = scenes.filter((x) => !x.keyframe).length;
  const unvoiced = scenes.filter((x) => !x.peek?.audio).length;
  const videos = scenes.filter((x) => x.s.mode === "video").length;
  const ready = missing === 0 && unvoiced === 0;
  const models = p.draft.models;
  const picture = chosenModel(p.pictures, models.image, models.image_quality);
  const redrawUsd = picture.price?.usd;

  let summary: string;
  if (p.dirty) summary = "You have unsaved script changes. They're saved before anything is drawn.";
  else if (ready)
    summary = `Every scene is voiced and drawn. ${videos ? `${videos} of ${scenes.length} scenes will be animated.` : "All scenes are stills with camera moves."}`;
  else if (missing === scenes.length && unvoiced === scenes.length)
    summary = "Nothing is drawn yet. Preparing the board records the narration and draws every scene.";
  else
    summary =
      [
        missing && `${missing} ${missing === 1 ? "scene needs" : "scenes need"} a picture`,
        unvoiced && `${unvoiced} ${unvoiced === 1 ? "needs" : "need"} narration`,
      ]
        .filter(Boolean)
        .join(", ") + ".";

  return (
    <>
      <div className="board-bar">
        <span className="summary">{summary}</span>
        <span className="spacer" />
        <button onClick={p.onBoard} disabled={p.busy || p.jobActive || (ready && !p.dirty)}>
          {ready ? "Board is ready" : withPrice("Prepare board", p.estimates?.board.total_usd)}
        </button>
        <button className="primary" onClick={p.onRender} disabled={p.busy || p.jobActive}>
          {withPrice("Approve and render", p.estimates?.render.total_usd)}
        </button>
      </div>
      {!p.board.voice_ok && (
        <p className="error">
          The narrator voice “{p.draft.voice}” isn't in your voices. Pick another on the Script step or add it
          on Voices.
        </p>
      )}
      <section className="panel models" aria-label="Models">
        <ModelPicker
          label="Pictures"
          catalog={p.pictures}
          error={p.catalogError}
          value={models.image}
          quality={models.image_quality}
          disabled={p.busy || p.jobActive}
          onChange={(image, image_quality) =>
            p.onModels(
              { image, image_quality },
              `pictures by ${p.pictures?.models.find((m) => m.id === (image || p.pictures?.default))?.label ?? "the default"}`,
            )
          }
        />
      </section>
      <EstimateBox
        estimate={p.estimates?.render ?? null}
        error={p.estimateError}
        budget={p.budget}
        busy={p.busy}
        onBudget={p.onBudget}
      />
      <audio ref={audio} hidden />
      <div className="board">
        {scenes.map(({ s, peek, keyframe }) => (
          <article key={s.n} className="card" aria-label={`Scene ${s.n}`}>
            <Slide
              image={keyframe}
              label={`No. ${s.n}`}
              mark={
                [
                  s.mode === "video" ? (peek?.motion ? "animated" : "to animate") : "",
                  peek?.duration ? `${peek.duration.toFixed(1)} s` : "",
                ]
                  .filter(Boolean)
                  .join(", ") || undefined
              }
              drawing={!keyframe && p.drawing}
              alt={s.visual}
            />
            <p className="line">{s.narration.map((l) => l.text).join(" ")}</p>
            <div className="tools">
              <div className="segmented" role="group" aria-label={`Scene ${s.n}: still or video`}>
                {(["still", "video"] as const).map((m) => (
                  <button
                    key={m}
                    aria-pressed={s.mode === m}
                    disabled={p.busy}
                    onClick={() => s.mode !== m && p.onMode(s.n, m)}
                  >
                    {m === "still" ? "Still" : "Video"}
                  </button>
                ))}
              </div>
              <span className="spacer" />
              {peek?.audio && (
                <button
                  className="quiet small"
                  onClick={() => play(s.n, asset(peek.audio)!)}
                  aria-label={`${playing === s.n ? "Stop" : "Play"} narration for scene ${s.n}`}
                >
                  {playing === s.n ? "Stop" : "Listen"}
                </button>
              )}
              <button
                className="quiet small"
                onClick={() => p.onReroll(s.n)}
                disabled={p.busy || p.jobActive}
                title="Draw this scene again with a new seed"
              >
                {redrawUsd ? `Redraw · ${fmtUsd(redrawUsd)}` : "Redraw"}
              </button>
            </div>
          </article>
        ))}
      </div>
    </>
  );
}
