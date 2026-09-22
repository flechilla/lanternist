// What the reel shows: each scene's slide and each portrait, from what a job reports over what the
// story has already made, and one plain sentence of what's happening now. The stage names here are
// the backend's (`pipeline.LABELS`), as `jobs.Progress` reports them.

import type { FocusEvent, MouseEvent, PointerEvent } from "react";
import type { BoardPeek, Job, StageState, Step, Storyboard } from "./api";

/** Where one thing a scene needs has got to. */
export type Phase = "planned" | "waiting" | "working" | "done";

export interface SceneState {
  n: number;
  /** Its narration's first sentence, as the backend splits sentences: enough to tell which scene it is. */
  line: string;
  voice: Phase;
  audio: string | null;
  picture: Phase;
  /** The picture on show: the last one drawn, kept up while it's drawn again. */
  image: string | null;
  /** Why the picture check failed the picture, while it's drawn again. */
  again: string | null;
  /** Why the picture still fails the check, now that nothing will draw it again. */
  failing: string | null;
  /** A still has no motion: its clip is the picture with a camera move. */
  motion: Phase | "still";
  /** Requests ahead of it in a provider's queue. */
  ahead: number | null;
  video: string | null;
  cut: Phase;
  steps: Record<string, Step>;
}

function phase(step: Step | undefined, made: boolean): Phase {
  switch (step?.state) {
    case "queued":
      return "planned";
    case "waiting":
    case "working":
      return step.state;
    case undefined:
      return made ? "done" : "planned";
    default:
      return "done";
  }
}

const pending = (step: Step | undefined) =>
  step?.state === "queued" || step?.state === "waiting" || step?.state === "working";

/** Every scene's state: what the job says of it, over what the story had made before it ran. */
export function sceneStates(sb: Storyboard, board: BoardPeek | null, job: Job | undefined): SceneState[] {
  const flagged = job?.status === "done" ? (job.result?.flagged ?? {}) : {};
  // While the check runs, a picture it fails is drawn again, unless it's the last try; once it's done,
  // a fail stands.
  const checking = job?.progress?.stages?.check?.status === "running";
  return sb.scenes.map((sc) => {
    const steps = job?.progress?.scenes?.[String(sc.n)] ?? {};
    const peek = board?.scenes.find((b) => b.n === sc.n);
    // A verdict with fewer tries than its picture judged an older picture: this one waits for its own.
    const current = (steps.check?.tries ?? 0) >= (steps.keyframes?.tries ?? 0);
    const failed = steps.check?.state === "failed" && current ? (steps.check.note ?? "") : null;
    const redrawing = pending(steps.keyframes) || checking;
    const image = steps.keyframes?.asset ?? peek?.keyframe ?? null;
    return {
      n: sc.n,
      line: peek?.line ?? "",
      voice: phase(steps.narration, !!peek?.audio),
      audio: steps.narration?.asset ?? peek?.audio ?? null,
      picture: phase(steps.keyframes, !!image),
      image,
      again: failed !== null && redrawing ? failed : null,
      failing: flagged[String(sc.n)] ?? (failed !== null && !redrawing ? failed : null),
      motion: sc.mode === "still" ? "still" : phase(steps.motion, !!peek?.motion),
      ahead: steps.motion?.ahead ?? steps.keyframes?.ahead ?? null,
      video: steps.motion?.asset ?? peek?.motion ?? null,
      cut: phase(steps.clips, false),
      steps,
    };
  });
}

/** A scene's state in a few words: its slide's label for a screen reader, and its card's chip. */
export function sceneWords(s: SceneState): string {
  if (s.failing !== null) return "still fails the picture check";
  if (s.cut === "done") return "cut into the film";
  if (s.motion === "done") return "animated";
  if (s.motion === "working") return "being animated";
  if (s.motion === "waiting")
    return s.ahead ? `waiting to be animated, ${s.ahead} ahead` : "waiting to be animated";
  if (s.again !== null) return "to be drawn again";
  if (s.picture === "working" || s.picture === "waiting")
    return s.image ? "being drawn again" : "being painted";
  if (s.picture === "done") return "drawn";
  if (s.voice === "done") return "narrated";
  if (s.voice === "working") return "being recorded";
  return "planned";
}

/** Where each slide sits: rows that turn back at each end, like film threaded through a projector, so
 * the thread from one scene to the next is one line. */
export interface Layout {
  points: { x: number; y: number; row: number }[];
  width: number; // of a slide
  height: number; // of a slide, with its frame
  total: number; // the reel's height
  path: string; // the thread through every slide
  segments: string[]; // the thread from each slide to the next
}

export function layout(scenes: number, reelWidth: number): Layout {
  const narrow = reelWidth < 560;
  const pad = 22;
  const gap = narrow ? 10 : 16;
  const rowGap = narrow ? 18 : 24;
  const smallest = narrow ? 84 : 104;
  const cols = Math.max(3, Math.floor((reelWidth - 2 * pad + gap) / (smallest + gap)));
  const width = Math.max((reelWidth - 2 * pad - (cols - 1) * gap) / cols, 0);
  const height = 4 + ((width - 8) * 9) / 16 + 15; // the frame's top, a 16:9 glass, and its label
  const points = Array.from({ length: scenes }, (_, i) => {
    const row = Math.floor(i / cols);
    const col = row % 2 ? cols - 1 - (i % cols) : i % cols;
    return { x: pad + col * (width + gap) + width / 2, y: row * (height + rowGap) + height / 2, row };
  });
  const bulge = width / 2 + 14;
  const segments = points.slice(1).map((b, i) => {
    const a = points[i];
    if (a.row === b.row) return `M${a.x},${a.y} L${b.x},${b.y}`;
    const dir = a.row % 2 ? -1 : 1;
    return `M${a.x},${a.y} C${a.x + dir * bulge},${a.y} ${b.x + dir * bulge},${b.y} ${b.x},${b.y}`;
  });
  const path = points.length
    ? `M${points[0].x},${points[0].y} ${segments.map((s) => s.replace(/^M[^LC]+/, "")).join(" ")}`
    : "";
  const rows = Math.ceil(scenes / cols);
  return { points, width, height, total: rows * height + Math.max(rows - 1, 0) * rowGap, path, segments };
}

const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** What's happening now, in two lines: the stage in plain words, and the scene or character it's on. */
export function headline(
  job: Job,
  scenes: SceneState[],
  names: Record<string, string>,
): { doing: string; detail: string } {
  if (job.status === "queued") return { doing: "Waiting its turn", detail: "Another job is running first." };
  const stages = Object.entries(job.progress?.stages ?? {});
  if (!stages.length) return { doing: "Getting ready", detail: "" };
  const [key, st] = stages.find(([, s]) => s.status === "running") ?? stages[stages.length - 1];
  const doing = st.doing || st.label || key;
  if (key === "cast" || key === "portraits") {
    const who = Object.entries(job.progress?.cast ?? {}).find(
      ([, s]) => s.state === "working" || s.state === "waiting",
    )?.[0];
    if (who) return { doing, detail: `Now ${names[who] ?? who}, drawn from the cast sheet.` };
    return { doing, detail: "First the cast sheet, with everyone together: every picture is drawn from it." };
  }
  const again = scenes.filter((s) => s.again !== null);
  if (key === "check" || (key === "keyframes" && again.length)) {
    if (again.length)
      return {
        doing: `Drawing ${count(again.length, "scene", "scenes")} again`,
        detail: `Scene ${again[0].n}: ${again[0].again}`,
      };
    return {
      doing,
      detail: `Does each picture show who its scene says, once each? ${st.done} of ${st.total}`,
    };
  }
  if (key === "mix") return { doing, detail: "Narration, sound and pictures, laid on one reel." };
  const working = scenes.filter((s) => s.steps[key]?.state === "working");
  const waiting = scenes.filter((s) => s.steps[key]?.state === "waiting");
  if (working.length === 1 && !waiting.length)
    return {
      doing,
      detail: `Scene ${working[0].n} of ${scenes.length}${working[0].line ? ` · “${working[0].line}”` : ""}`,
    };
  if (!working.length && !waiting.length && st.local && st.model && st.done < st.total)
    return { doing, detail: `Loading ${st.model} on this machine.` };
  const parts = [
    working.length > 1 && `${working.length} being made`,
    waiting.length > 0 && `${waiting.length} waiting their turn`,
    st.total > 0 && `${st.done} of ${st.total} done`,
  ];
  return { doing, detail: parts.filter(Boolean).join(" · ") };
}

/** Time left in words, from the snapshot's range: never a countdown. */
export function timeLeft(eta: [number, number] | undefined): string {
  if (!eta) return "";
  const [lo, hi] = eta.map((s) => Math.round(s / 60));
  if (hi < 1) return "less than a minute left";
  if (hi === 1) return "about a minute left";
  return lo === hi || lo < 1 ? `about ${hi} min left` : `${lo}–${hi} min left`;
}

/** A length of time as people say it: "40 s", "8 min", "1 h 5 min". */
export function duration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const m = Math.round(seconds / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

/** What a slide on the reel does when it's clicked (its card stays), focused from the keyboard, or
 * pointed at (its card opens after a moment). */
export function slideEvents(
  onOpen: (el: HTMLButtonElement, pin: boolean) => void,
  onHover: (el: HTMLButtonElement | null) => void,
) {
  return {
    onClick: (e: MouseEvent<HTMLButtonElement>) => onOpen(e.currentTarget, true),
    onFocus: (e: FocusEvent<HTMLButtonElement>) =>
      e.currentTarget.matches(":focus-visible") && onOpen(e.currentTarget, false),
    onPointerEnter: (e: PointerEvent<HTMLButtonElement>) =>
      e.pointerType !== "touch" && onHover(e.currentTarget),
    onPointerLeave: () => onHover(null),
  };
}

/** How far a stage row has got, 0 to 1: its items made, or all of it once it's done. */
export function stageShare(st: StageState): number {
  return st.total ? st.done / st.total : st.status === "done" ? 1 : 0;
}

/** A stage row's count as the progress shows it: "12/37", "done" or "working". */
export function stageCount(st: StageState): string {
  return st.total ? `${st.done}/${st.total}` : st.status === "done" ? "done" : "working";
}

/** Bring an element into view, smoothly unless the viewer asked for less motion. */
export function reveal(el: Element, block: ScrollLogicalPosition = "nearest") {
  el.scrollIntoView({
    block,
    behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
  });
}

/** What "Tell me when it's ready" says once pressed: the page does the telling, so only while it's open. */
export const TELLING = "We'll tell you while this page is open";
