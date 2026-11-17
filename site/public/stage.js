/* The stop-motion clock. Everything on the page moves on one 12 fps clock, "on twos", the way a
 * paper cut-out film is shot: a part is set down, the frame is taken, the part is nudged. Nothing
 * tweens between frames, and the edges of the card boil a little from frame to frame because each
 * frame was cut again. With reduced motion asked for, the clock still runs what a visitor starts
 * (the film), but nothing moves on its own. */

export const FPS = 12;
export const calm = matchMedia("(prefers-reduced-motion: reduce)");

const TAU = Math.PI * 2;
const r1 = (n) => Math.round(n * 10) / 10;
const sine = (t, per, ph = 0) => Math.sin(TAU * (t / per + ph));

/** The same number for the same part on the same frame: the hand that placed it, not a tween. */
export const noise = (i, t) => {
  const x = Math.sin(i * 12.9898 + t * 78.233) * 43758.5453;
  return x - Math.floor(x);
};

/** Blinks and flashes fall at the end of their period, so frame 0 (a still) never catches one. */
const beat = (t, per, ph, len = 2) => (t + ph * per) % per >= per - len;

/** The motions a part may name in `data-m`: a transform, or a transform and an opacity. */
const MOTIONS = {
  bob: (t, [a = 4, per = 24, ph = 0]) => `translate(0px,${r1(a * sine(t, per, ph))}px)`,
  sway: (t, [deg = 4, per = 24, ph = 0]) => `rotate(${r1(deg * sine(t, per, ph))}deg)`,
  drift: (t, [dx = 20, per = 96, ph = 0]) => `translate(${r1(dx * sine(t, per, ph))}px,0px)`,
  wave: (t, [dx = 30, dy = 6, per = 36, ph = 0]) =>
    `translate(${r1(dx * sine(t, per, ph))}px,${r1(dy * sine(t, per, ph + 0.25))}px)`,
  rock: (t, [deg = 5, dy = 5, per = 30, ph = 0]) =>
    `translate(0px,${r1(dy * sine(t, per, ph + 0.25))}px) rotate(${r1(deg * sine(t, per, ph))}deg)`,
  breathe: (t, [a = 0.04, per = 40]) => `scale(1,${r1(1000 + 1000 * a * (0.5 + 0.5 * sine(t, per))) / 1000})`,
  blink: (t, [per = 60, ph = 0]) => (beat(t, per, ph / per) ? "scale(1,0.1)" : "none"),
  flick: (t, [lo = 0.8], i) => ({ opacity: r1(lo + (1 - lo) * noise(i, t)) }),
  flash: (t, [per = 43, ph = 0, peak = 1]) => ({ opacity: beat(t, per, ph / per) ? peak : 0 }),
  rain: (t, _, i) => `translate(${Math.floor(noise(i, t) * 48)}px,${Math.floor(noise(i + 5, t) * 120)}px)`,
  jit: (t, [a = 1.5], i) =>
    `translate(${r1((noise(i, t) - 0.5) * a)}px,${r1((noise(i + 3, t) - 0.5) * a)}px)`,
  spin: (t, [deg = 1]) => `rotate(${r1(t * deg) % 360}deg)`,
  flap: (t, [per = 6]) => (t % per < per / 2 ? "none" : "scale(1,-0.55)"),
  smoke: (t, [per = 30, ph = 0]) => {
    const p = (t / per + ph) % 1;
    return {
      transform: `translate(${r1(14 * p)}px,${r1(-70 * p)}px) scale(${r1(0.6 + p)})`,
      opacity: r1(0.6 * (1 - p)),
    };
  },
  mote: (t, [per = 90, ph = 0], i) => ({
    transform: `translate(${r1(30 * sine(t, per, ph))}px,${r1(-20 * sine(t, per * 1.7, ph + 0.3))}px)`,
    opacity: r1(0.25 + 0.6 * noise(i, Math.floor(t / 3))),
  }),
};

/** How a still's camera moves across its shot, as the app's `camera` field names it. */
const CAMERA = {
  push_in: (p) => `scale(${r1(1000 + 90 * p) / 1000})`,
  pull_out: (p) => `scale(${r1(1090 - 90 * p) / 1000})`,
  pan_left: (p) => `scale(1.08) translate(${r1(40 - 80 * p)}px,0px)`,
  pan_right: (p) => `scale(1.08) translate(${r1(-40 + 80 * p)}px,0px)`,
  static: () => "none",
};

const stages = new Set();

/**
 * Brings the cut-outs under `root` to life. `fns` are the scene's own motions (`data-m="@name"`),
 * `still` freezes every part on frame `hold` so only the camera moves, and `loop` (frames) restarts
 * the shot, as a preview does.
 */
export function stage(
  root,
  { fns = {}, still = false, hold = 0, camera = "static", loop = 0, dur = 96 } = {},
) {
  const parts = [...root.querySelectorAll("[data-m]")].map((el, i) => {
    const [name, ...args] = el.dataset.m.split(" ");
    if (el.dataset.o) el.style.transformOrigin = el.dataset.o;
    const fn = name.startsWith("@") ? fns[name.slice(1)] : MOTIONS[name];
    return { el, i, fn, args: args.map(Number), last: "" };
  });
  const s = {
    root,
    parts,
    fns,
    still,
    hold,
    camera,
    loop,
    dur,
    t: 0,
    on: false,
    cam: root.querySelector(".cam"),
  };
  root.classList.toggle("still", still);
  paint(s);
  stages.add(s);
  return s;
}

export const drop = (s) => s && stages.delete(s);

function paint(s) {
  const t = s.still ? s.hold : s.t;
  for (const p of s.parts) {
    if (!p.fn) continue;
    const out = p.fn(t, p.args, p.i, s);
    const key = typeof out === "string" ? out : `${out.transform}|${out.opacity}`;
    if (key === p.last) continue;
    p.last = key;
    if (typeof out === "string") p.el.style.transform = out;
    else {
      if (out.transform !== undefined) p.el.style.transform = out.transform;
      if (out.opacity !== undefined) p.el.style.opacity = out.opacity;
    }
  }
  if (s.cam) {
    const p = Math.min(1, (s.t % (s.loop || Infinity)) / s.dur);
    s.cam.style.transform = s.still ? (CAMERA[s.camera]?.(p) ?? "none") : "none";
  }
}

/** Runs a stage while it's on screen, and stops it when it scrolls away. */
export function watch(el, s, onChange) {
  new IntersectionObserver(([e]) => {
    s.on = e.isIntersecting && !calm.matches;
    onChange?.(e.isIntersecting);
  }).observe(el);
}

/* ---------- the clock ---------- */

const listeners = new Set();
/** Calls `fn(frame)` on every frame of the clock; returns the way to stop. */
export const onFrame = (fn) => (listeners.add(fn), () => listeners.delete(fn));

let frame = 0;
function tick(now) {
  const f = Math.floor((now / 1000) * FPS);
  if (f !== frame) {
    frame = f;
    for (const s of stages) {
      if (!s.on) continue;
      s.t = s.loop ? (s.t + 1) % s.loop : s.t + 1;
      paint(s);
    }
    for (const fn of listeners) fn(f);
  }
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

/** Moves a stage to frame `t` and paints it, for a film that keeps its own time. */
export function seek(s, t) {
  s.t = t;
  paint(s);
}
