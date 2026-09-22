import { useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import {
  asset,
  fmtSeconds,
  fmtUsd,
  thumb,
  type BoardPeek,
  type Budget,
  type Job,
  type Storyboard,
} from "../api";
import { usePlayer, useStored, useVisible, useWidth } from "../hooks";
import { duration, headline, layout, sceneStates, slideEvents, timeLeft, type SceneState } from "../reel";
import Behind from "./Behind";
import ReelSlide from "./ReelSlide";
import { CastCard, SceneCard } from "./SceneCard";

type Pick = { kind: "scene"; n: number } | { kind: "cast"; id: string | null }; // null: the cast sheet
type Card = Pick & { pinned: boolean; x: number; y: number };

const OPEN_MS = 90; // a pointer only passing over the reel opens nothing
const CLOSE_MS = 160; // time to move the pointer onto the card
const CARD_WIDTH = 300;

interface Props {
  sb: Storyboard;
  board: BoardPeek | null;
  job: Job;
  budget: Budget;
  onCancel: () => void;
  onWatch: () => void;
}

/** A render as its story: every scene a slide on one reel, filling in as its voice, picture and motion
 * arrive, with the cast above it and one plain sentence of what's happening. Hover or focus a slide
 * for its details; the stages, models, spend and log are under Behind the scenes. */
export default function Reel({ sb, board, job, budget, onCancel, onWatch }: Props) {
  const scenes = useMemo(() => sceneStates(sb, board, job), [sb, board, job]);
  const { doing, detail } = headline(sb, job, scenes);
  const [still, setStill] = useStored("reel.still", false);
  const [behind, setBehind] = useStored("reel.behind", false);
  const [card, setCard] = useState<Card | null>(null);
  const [threads, setThreads] = useState<string[]>([]);
  const [now, setNow] = useState(() => Date.now());
  const [firstStatus] = useState(job.status);
  const wrap = useRef<HTMLDivElement>(null);
  const reel = useRef<HTMLDivElement>(null);
  const thread = useRef<SVGPathElement>(null);
  const spark = useRef<SVGCircleElement>(null);
  const slides = useRef(new Map<number, HTMLButtonElement>());
  const timers = useRef({ open: 0, close: 0 });
  const shape = layout(scenes.length, useWidth(reel));
  const { audio, playing, play } = usePlayer<number>();

  const progress = job.progress ?? {};
  const stages = progress.stages ?? {};
  const done = job.status === "done";
  const at = done ? 1 : stages.mix?.status === "done" ? 1 : (stages.mix?.at ?? 0);
  const seconds = (n: number) => board?.scenes.find((b) => b.n === n)?.duration ?? 4;
  const characters = sb.cast.filter((c) => c.kind === "character");
  // Each character gets a portrait when the story draws from portraits and has more than one of them,
  // as `pipeline.portrait_items` decides; they're on the reel from the start, like the scenes.
  const portraits =
    sb.portraits && !sb.cast_sheet_prompt && characters.length > 1
      ? characters
      : characters.filter((c) => progress.cast?.[c.id]);
  const sheet = stages.cast?.asset ?? board?.cast ?? null;
  const picked =
    card?.kind === "cast" && card.id
      ? new Set(sb.scenes.filter((s) => s.cast.includes(card.id!)).map((s) => s.n))
      : null;

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 15_000);
    return () => clearInterval(t);
  }, []);

  // The spark sits on the thread where the mix has got to.
  useEffect(() => {
    const path = thread.current;
    const dot = spark.current;
    if (!path || !dot || !(at > 0 && at < 1)) return;
    const p = path.getPointAtLength(path.getTotalLength() * at);
    dot.setAttribute("cx", String(p.x));
    dot.setAttribute("cy", String(p.y));
  }, [at, shape.path]);

  // A card opened by a click stays until a click elsewhere, or Escape.
  useEffect(() => {
    if (!card?.pinned) return;
    const away = (e: PointerEvent) => {
      const t = e.target as Element;
      if (!t.closest(".scene-card, .node, .cnode")) setCard(null);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [card?.pinned]);

  function place(el: HTMLElement) {
    const wr = wrap.current!.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    const width = Math.min(CARD_WIDTH, wr.width - 24);
    let x = r.right - wr.left + 12;
    let y = r.top - wr.top - 24;
    if (x + width > wr.width - 4) x = r.left - wr.left - 12 - width;
    if (x < 4) {
      x = Math.max(4, Math.min(wr.width - width - 4, r.left - wr.left + r.width / 2 - width / 2));
      y = r.bottom - wr.top + 10;
    }
    return { x, y: Math.max(-40, y) };
  }

  // Threads from a portrait to every scene its character is in.
  function threadsFrom(id: string, from: HTMLElement): string[] {
    const wr = wrap.current!.getBoundingClientRect();
    const f = from.getBoundingClientRect();
    const fx = f.left - wr.left + f.width / 2;
    const fy = f.bottom - wr.top;
    return sb.scenes.flatMap((sc) => {
      const el = slides.current.get(sc.n);
      if (!sc.cast.includes(id) || !el) return [];
      const r = el.getBoundingClientRect();
      const tx = r.left - wr.left + r.width / 2;
      const ty = r.top - wr.top + 3;
      return [`M${fx},${fy} C${fx},${fy + 70} ${tx},${ty - 70} ${tx},${ty}`];
    });
  }

  function open(what: Pick, el: HTMLElement, pinned: boolean) {
    clearTimeout(timers.current.close);
    if (pinned && card?.pinned && sameAs(card, what)) {
      setCard(null);
      setThreads([]);
      return;
    }
    setCard({ ...what, pinned, ...place(el) });
    setThreads(what.kind === "cast" && what.id ? threadsFrom(what.id, el) : []);
  }

  function hover(what: Pick | null, el: HTMLElement | null) {
    clearTimeout(timers.current.open);
    if (card?.pinned) return;
    if (!what || !el) {
      timers.current.close = window.setTimeout(() => {
        setCard(null);
        setThreads([]);
      }, CLOSE_MS);
      return;
    }
    clearTimeout(timers.current.close);
    timers.current.open = window.setTimeout(() => open(what, el, false), card ? 0 : OPEN_MS);
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === "Escape" && card) {
      const n = card.kind === "scene" ? card.n : null;
      setCard(null);
      setThreads([]);
      if (n) slides.current.get(n)?.focus({ preventScroll: true });
      return;
    }
    const n = Number((e.target as HTMLElement).dataset.n);
    const step = ({ ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 } as Record<string, number>)[
      e.key
    ];
    if (!n || !step) return;
    e.preventDefault();
    slides.current.get(Math.min(scenes.length, Math.max(1, n + step)))?.focus();
  }

  function showScene(n: number) {
    const el = slides.current.get(n);
    if (!el) return;
    el.scrollIntoView({
      block: "nearest",
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
    });
    open({ kind: "scene", n }, el, true);
  }

  const spent = progress.spent_usd ?? 0;
  const started = job.started_at ? Date.parse(`${job.started_at}Z`) : null;
  const took = started && job.finished_at ? (Date.parse(`${job.finished_at}Z`) - started) / 1000 : null;
  const flagged = Object.entries(job.result?.flagged ?? {});
  const since = [
    started && `started ${duration(Math.max(0, (now - started) / 1000))} ago`,
    spent > 0 && `${fmtUsd(spent)} of your ${fmtUsd(budget.usd)} budget`,
  ].filter(Boolean);

  const cardScene = card?.kind === "scene" ? scenes.find((s) => s.n === card.n) : undefined;
  const cardMember = card?.kind === "cast" && card.id ? sb.cast.find((c) => c.id === card.id) : undefined;
  const behindButton = (
    <button className="hbtn" aria-expanded={behind} aria-controls="behind" onClick={() => setBehind(!behind)}>
      Behind the scenes <Chevron />
    </button>
  );

  return (
    <section className={`hall reel-hall anim${still ? " still" : ""}`} aria-label="Your film, being made">
      <p className="sr-only" aria-live="polite">
        {done ? "Your film is ready." : doing}
      </p>
      <div className="reel-head">
        {done ? (
          <div className="done-card">
            <p className="kicker">{sb.title}</p>
            <h2 className="headline">Your film is ready</h2>
            <p className="facts">
              {job.result?.duration != null && (
                <span>
                  <b>{fmtSeconds(job.result.duration)}</b> of film
                </span>
              )}
              <span>
                <b>{scenes.length}</b> scenes
              </span>
              {took != null && (
                <span>
                  made in <b>{duration(took)}</b>
                </span>
              )}
              {spent > 0 && (
                <span>
                  <b>{fmtUsd(spent)}</b> spent
                </span>
              )}
            </p>
            {flagged.length > 0 && (
              <div className="flagged">
                <span>
                  {flagged.length === 1 ? "One picture still fails" : `${flagged.length} pictures still fail`}{" "}
                  the check. Redraw {flagged.length === 1 ? "it" : "them"} on the Board:
                </span>
                {flagged.map(([n]) => (
                  <button key={n} onClick={() => showScene(Number(n))}>
                    Scene {n}
                  </button>
                ))}
              </div>
            )}
            <div className="reel-actions">
              <button className="hbtn lamp" onClick={onWatch}>
                Watch the film
              </button>
              {behindButton}
            </div>
          </div>
        ) : (
          <>
            <div className="reel-now">
              <p className="kicker">
                {sb.title} · {scenes.length} scenes
              </p>
              <h2 key={doing} className="headline swap-in">
                {doing}
              </h2>
              <p className="reel-detail">{detail}</p>
            </div>
            <div className="reel-side">
              <div className="clockline">
                <div className="eta">{timeLeft(progress.eta_s)}</div>
                <div className="since">{since.join(" · ")}</div>
              </div>
              <div className="reel-actions">
                <button className="hbtn" aria-pressed={still} onClick={() => setStill(!still)}>
                  {still ? "Resume motion" : "Pause motion"}
                </button>
                {behindButton}
                <button className="hbtn quiet" onClick={onCancel}>
                  Cancel
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {progress.phases && progress.phases.length > 0 && (
        <div className="phases" aria-hidden="true">
          {progress.phases.map(({ stage, label, share }) => {
            const st = stages[stage];
            const fill =
              !st || done
                ? done
                  ? 1
                  : 0
                : st.status === "done"
                  ? 1
                  : stage === "mix"
                    ? at
                    : st.total
                      ? st.done / st.total
                      : 0;
            return (
              <div
                key={stage}
                className={`ph${fill >= 1 ? " done" : st?.status === "running" ? " now" : ""}`}
                style={{ flex: `${share} 1 0` }}
                title={label}
              >
                <div className="track">
                  <div className="fill" style={{ width: `${fill * 100}%` }} />
                </div>
                <div className="name">{label}</div>
              </div>
            );
          })}
        </div>
      )}

      <div className="stagewrap" ref={wrap} onKeyDown={onKey}>
        <svg className={`edges${threads.length ? " draw" : ""}`} aria-hidden="true">
          {threads.map((d) => (
            <path key={d} d={d} pathLength={1} />
          ))}
        </svg>
        {characters.length > 0 && (
          <div
            className={`castrow${card?.kind === "cast" ? " focusing" : ""}`}
            role="list"
            aria-label="The cast"
          >
            <span className="castlab">Cast</span>
            <CastSlide
              label="Cast sheet"
              image={sheet}
              drawing={!sheet && stages.cast?.status === "running"}
              open={card?.kind === "cast" && card.id === null}
              onOpen={(el, pin) => open({ kind: "cast", id: null }, el, pin)}
              onHover={(el) => hover(el && { kind: "cast", id: null }, el)}
            />
            {portraits.length > 0 && <Arrow />}
            {portraits.map((c) => {
              const step = progress.cast?.[c.id];
              return (
                <CastSlide
                  key={c.id}
                  label={c.name}
                  image={step?.asset ?? null}
                  drawing={step?.state === "working" || step?.state === "waiting"}
                  open={card?.kind === "cast" && card.id === c.id}
                  onOpen={(el, pin) => open({ kind: "cast", id: c.id }, el, pin)}
                  onHover={(el) => hover(el && { kind: "cast", id: c.id }, el)}
                />
              );
            })}
          </div>
        )}
        <div
          className={`reel${picked ? " focusing" : ""}`}
          ref={reel}
          role="list"
          aria-label="Scenes"
          style={{ height: shape.total }}
        >
          <svg className="thread" aria-hidden="true">
            <path ref={thread} className="base" d={shape.path} />
            {shape.segments.map((d, i) => (
              <path
                key={i}
                className={`tseg${lit(scenes, i + 1, at) && lit(scenes, i + 2, at) ? " on" : ""}`}
                d={d}
              />
            ))}
            <circle ref={spark} r={4.5} className={`spark${at > 0 && at < 1 ? " on" : ""}`} />
          </svg>
          {scenes.map((s, i) => {
            const p = shape.points[i];
            return (
              <div key={s.n} role="listitem">
                <ReelSlide
                  ref={(el) => {
                    if (el) slides.current.set(s.n, el);
                    return () => {
                      slides.current.delete(s.n);
                    };
                  }}
                  s={s}
                  seconds={seconds(s.n)}
                  style={
                    {
                      left: p.x - shape.width / 2,
                      top: p.y - shape.height / 2,
                      width: shape.width,
                      "--k": i,
                    } as CSSProperties
                  }
                  lit={lit(scenes, s.n, at)}
                  run={done && firstStatus !== "done"}
                  open={card?.kind === "scene" && card.n === s.n}
                  dim={!!picked && !picked.has(s.n)}
                  onOpen={(el, pin) => open({ kind: "scene", n: s.n }, el, pin)}
                  onHover={(el) => hover(el && { kind: "scene", n: s.n }, el)}
                />
              </div>
            );
          })}
        </div>
        {card && (cardScene || card.kind === "cast") && (
          <div
            className={`scene-card${card.kind === "cast" ? " tall" : ""}`}
            role="dialog"
            aria-label={cardScene ? `Scene ${cardScene.n}` : (cardMember?.name ?? "Cast sheet")}
            style={{
              left: card.x,
              top: card.y,
            }}
            onPointerEnter={() => clearTimeout(timers.current.close)}
            onPointerLeave={() => hover(null, null)}
          >
            {cardScene ? (
              <SceneCard
                sb={sb}
                s={cardScene}
                seconds={seconds(cardScene.n)}
                playing={playing === cardScene.n}
                onListen={() => cardScene.audio && play(cardScene.n, asset(cardScene.audio)!)}
              />
            ) : (
              <CastCard
                member={cardMember ?? null}
                step={cardMember ? progress.cast?.[cardMember.id] : undefined}
                image={cardMember ? (progress.cast?.[cardMember.id]?.asset ?? null) : sheet}
                drawing={cardMember ? progress.cast?.[cardMember.id]?.state === "working" : !sheet}
                scenes={cardMember ? sb.scenes.filter((s) => s.cast.includes(cardMember.id)).length : 0}
                total={scenes.length}
              />
            )}
          </div>
        )}
      </div>
      <audio ref={audio} hidden />

      <div className={`drawer${behind ? " open" : ""}`} id="behind">
        <div>{behind && <Behind job={job} scenes={scenes} onScene={showScene} />}</div>
      </div>
    </section>
  );
}

function sameAs(a: Pick, b: Pick): boolean {
  return a.kind === "scene" ? b.kind === "scene" && a.n === b.n : b.kind === "cast" && a.id === b.id;
}

// A slide is lit once the mix has passed it: the film is being laid down from scene 1 on.
function lit(scenes: SceneState[], n: number, at: number): boolean {
  return scenes[n - 1]?.cut === "done" && at >= (n - 0.5) / scenes.length;
}

interface CastSlideProps {
  label: string;
  image: string | null;
  drawing: boolean;
  open: boolean;
  onOpen: (el: HTMLButtonElement, pin: boolean) => void;
  onHover: (el: HTMLButtonElement | null) => void;
}

/** A portrait, or the cast sheet, above the reel. */
function CastSlide({ label, image, drawing, open, onOpen, onHover }: CastSlideProps) {
  const visible = useVisible();
  const [first, setFirst] = useState(image);
  if (!visible && first !== image) setFirst(image);
  return (
    <div role="listitem">
      <button
        type="button"
        className={`cnode${label === "Cast sheet" ? " sheet" : ""}${open ? " on" : ""}${image && !first ? " a-pic" : ""}`}
        data-drawing={drawing || undefined}
        aria-label={`${label}: ${image ? "drawn" : drawing ? "being drawn" : "not drawn yet"}`}
        {...slideEvents(onOpen, onHover)}
      >
        <span className="glass">
          <span className="hatch" />
          {image && <img key={image} className="cur" src={thumb(image, 384)} alt="" />}
          <span className="beam" />
        </span>
        <span className="tag">{label}</span>
      </button>
    </div>
  );
}

const Arrow = () => (
  <svg className="arrow" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M4 12h15m-5-5 5 5-5 5" />
  </svg>
);

const Chevron = () => (
  <svg className="chev" viewBox="0 0 24 24" aria-hidden="true">
    <path d="m6 9 6 6 6-6" />
  </svg>
);
