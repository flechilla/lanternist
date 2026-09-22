import { useState, type CSSProperties, type Ref } from "react";
import { thumb } from "../api";
import { useVisible } from "../hooks";
import { sceneWords, slideEvents, type Phase, type SceneState } from "../reel";

// A waveform's bars, drawn from the scene's number so a slide's voice keeps its look between visits.
// It's a picture of the narration, not a measure of it: a length the page doesn't know yet draws 12 bars.
function bars(n: number, seconds: number | null): number[] {
  let x = n * 9301 + 49297;
  const next = () => (x = (x * 9301 + 49297) % 233280) / 233280;
  const count = seconds == null ? 12 : Math.round(Math.min(22, 7 + seconds * 1.5));
  return Array.from({ length: count }, (_, i) => {
    const envelope = Math.sin((Math.PI * (i + 0.5)) / count) ** 0.6;
    return Math.round(18 + 82 * envelope * (0.35 + 0.65 * next()));
  });
}

/** A scene's narration, drawn as a waveform on its glass once it's recorded. */
export function Wave({ n, seconds, arrived }: { n: number; seconds: number | null; arrived?: boolean }) {
  return (
    <span className={`wave${arrived ? " a-voice" : ""}`} aria-hidden="true">
      {bars(n, seconds).map((h, i) => (
        <i key={i} style={{ "--h": `${h}%`, "--i": i } as CSSProperties} />
      ))}
    </span>
  );
}

const pip = (p: Phase | "still", bad = false) =>
  bad
    ? "bad"
    : p === "done"
      ? "on"
      : p === "working" || p === "waiting"
        ? "work"
        : p === "still"
          ? "none"
          : undefined;

interface Props {
  s: SceneState;
  seconds: number | null; // of narration: how wide its waveform is
  tabbable: boolean; // the one slide Tab stops at
  style: CSSProperties;
  lit: boolean; // the mix has passed it
  run: boolean; // finished while someone watched: the slides light up in turn
  open: boolean; // its card is open
  dim: boolean; // another character's scenes are picked out
  ref?: Ref<HTMLButtonElement>;
  onOpen: (el: HTMLButtonElement, pin: boolean) => void;
  onHover: (el: HTMLButtonElement | null) => void;
}

/** One scene on the reel: a small lantern slide whose glass shows what's made of it so far, and four
 * pips for its voice, picture, motion and cut. Only what changes while someone watches animates. */
export default function ReelSlide(props: Props) {
  const { s, seconds, style, tabbable, lit, run, open, dim, ref, onOpen, onHover } = props;
  // What the viewer last saw: it keeps up while the page is hidden, so a return doesn't replay it all.
  const visible = useVisible();
  const now = { voice: s.voice, image: s.image, again: s.again, cut: s.cut };
  const [first, setFirst] = useState(now);
  if (!visible && JSON.stringify(first) !== JSON.stringify(now)) setFirst(now);
  // The picture on show, and the one it replaces while the new one slides in over it.
  const [shown, setShown] = useState<{ image: string | null; old: string | null }>({
    image: s.image,
    old: null,
  });
  if (s.image !== shown.image) setShown({ image: s.image, old: visible ? shown.image : null });

  const classes = [
    "node",
    lit && "lit",
    run && "a-run",
    open && "on",
    dim && "dim",
    shown.image && !first.image && !shown.old && "a-pic",
    s.cut === "done" && first.cut !== "done" && "a-done",
  ];
  return (
    <button
      ref={ref}
      type="button"
      className={classes.filter(Boolean).join(" ")}
      style={style}
      data-n={s.n}
      data-voice={s.voice}
      data-picture={s.picture}
      data-motion={s.motion}
      data-again={s.again !== null || undefined}
      aria-label={`Scene ${s.n}: ${sceneWords(s)}`}
      aria-haspopup="dialog"
      aria-expanded={open}
      tabIndex={tabbable ? 0 : -1}
      {...slideEvents(onOpen, onHover)}
    >
      <span className="glass">
        <span className="hatch" />
        {s.voice === "done" && <Wave n={s.n} seconds={seconds} arrived={first.voice !== "done"} />}
        {s.voice === "working" && (
          <span className="rec" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
        )}
        {shown.old && (
          <img
            className="old"
            src={thumb(shown.old, 384)}
            alt=""
            onAnimationEnd={() => setShown((v) => ({ ...v, old: null }))}
          />
        )}
        {shown.image && (
          <img
            key={shown.image}
            className={`cur${shown.old ? " swap" : ""}`}
            src={thumb(shown.image, 384)}
            alt=""
            decoding="async"
          />
        )}
        <span className="beam" />
        {s.again !== null && <span className={`stamp${first.again === null ? " a-stamp" : ""}`}>again</span>}
        {s.failing !== null && (
          <span className="flag" aria-hidden="true">
            !
          </span>
        )}
      </span>
      <span className="tag">{s.n}</span>
      <span className="pips" aria-hidden="true">
        <i className={pip(s.voice)} />
        <i className={pip(s.picture, s.again !== null || s.failing !== null)} />
        <i className={pip(s.motion)} />
        <i className={pip(s.cut)} />
      </span>
    </button>
  );
}
