import {
  asset,
  chosenModel,
  type BoardPeek,
  type Budget,
  type Estimate,
  type MediaCatalog,
  type Mode,
  type Models,
  type Storyboard,
  withPrice,
} from "../api";
import { usePlayer } from "../hooks";
import EstimateBox from "./EstimateBox";
import ModelPicker from "./ModelPicker";
import Slide from "./Slide";

/** The models each media stage can use. */
export interface Catalogs {
  image: MediaCatalog;
  video: MediaCatalog;
  ambience: MediaCatalog;
  tts: MediaCatalog;
}

interface Props {
  draft: Storyboard;
  board: BoardPeek;
  liveKeyframes: Record<string, string>;
  drawing: boolean;
  jobActive: boolean;
  busy: boolean;
  dirty: boolean;
  catalogs: Catalogs | null;
  catalogError: string | null;
  estimates: { board: Estimate; render: Estimate } | null;
  estimateError: string | null;
  budget: Budget;
  onBudget: (usd: number | null) => void;
  onMode: (n: number, mode: Mode) => void;
  onModels: (change: Partial<Models>, note: string) => void;
  onReroll: (n: number) => void;
  onRetake: (n: number) => void;
  onBoard: () => void;
  onRender: () => void;
}

export default function BoardView(p: Props) {
  const { audio, playing, play } = usePlayer<number>();

  const scenes = p.draft.scenes.map((s) => {
    const peek = p.board.scenes.find((b) => b.n === s.n);
    return { s, peek, keyframe: peek?.keyframe ?? p.liveKeyframes[String(s.n)] ?? null };
  });
  const missing = scenes.filter((x) => !x.keyframe).length;
  const unvoiced = scenes.filter((x) => !x.peek?.audio).length;
  const videos = scenes.filter((x) => x.s.mode === "video").length;
  const ready = missing === 0 && unvoiced === 0;
  const models = p.draft.models;
  const cat = p.catalogs;
  const redrawUsd = chosenModel(cat?.image ?? null, models.image, models.image_quality).price?.usd;
  const videoModel = chosenModel(cat?.video ?? null, models.video, models.video_quality).model;
  const retakes = Object.fromEntries((p.estimates?.render.retakes ?? []).map((r) => [r.scene, r.cost_usd]));
  const labelOf = (c: MediaCatalog | undefined, id: string) =>
    c?.models.find((m) => m.id === (id || c.default))?.label ?? "the default";
  const locked = p.busy || p.jobActive;

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
          The narrator voice “{p.draft.voice}” can't be used by this narration model. Pick another on the
          Script step, or add the recording on Voices.
        </p>
      )}
      <section className="panel models" aria-label="Models">
        <ModelPicker
          label="Pictures"
          catalog={cat?.image ?? null}
          error={p.catalogError}
          value={models.image}
          quality={models.image_quality}
          disabled={locked}
          onChange={(image, image_quality) =>
            p.onModels({ image, image_quality }, `pictures by ${labelOf(cat?.image, image)}`)
          }
        />
        {videos > 0 && (
          <ModelPicker
            label="Video"
            catalog={cat?.video ?? null}
            error={p.catalogError}
            value={models.video}
            quality={models.video_quality}
            disabled={locked}
            onChange={(video, video_quality) =>
              p.onModels({ video, video_quality }, `video by ${labelOf(cat?.video, video)}`)
            }
          />
        )}
        {videos > 0 &&
          (videoModel?.sound ? (
            <div className="field">
              <span>Ambience</span>
              <small>{videoModel.label} makes its own sound bed, so its scenes need no other.</small>
            </div>
          ) : (
            <ModelPicker
              label="Ambience"
              catalog={cat?.ambience ?? null}
              error={p.catalogError}
              value={models.ambience}
              disabled={locked}
              off="Video scenes stay silent under the narration."
              onChange={(ambience) =>
                p.onModels(
                  { ambience },
                  ambience === "none" ? "no ambience" : `ambience by ${labelOf(cat?.ambience, ambience)}`,
                )
              }
            />
          ))}
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
              {peek?.motion && (
                <a className="btn quiet small" href={asset(peek.motion)} target="_blank" rel="noreferrer">
                  Watch
                </a>
              )}
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
                {withPrice("Redraw", redrawUsd)}
              </button>
              {s.mode === "video" && peek?.motion && (
                <button
                  className="quiet small"
                  onClick={() => p.onRetake(s.n)}
                  disabled={locked}
                  title="Animate this scene again with a new seed, then render the film"
                >
                  {withPrice("New take", retakes[s.n])}
                </button>
              )}
            </div>
          </article>
        ))}
      </div>
    </>
  );
}
