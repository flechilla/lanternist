/* Sound, off until the visitor turns it on. Nothing is recorded: a brick's click is a tick of filtered
 * noise and a plastic knock, a whoosh is noise swept through a filter, a chime is three soft bells.
 * Every sound comes out a little different each time, the way no two clicks of real bricks are alike. */

let ctx = null;
let out = null;
let hiss = null;
let on = false;
let last = 0;

function start() {
  ctx = new AudioContext();
  const squash = ctx.createDynamicsCompressor();
  out = ctx.createGain();
  out.gain.value = 0.7;
  out.connect(squash).connect(ctx.destination);
  hiss = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
  const d = hiss.getChannelData(0);
  for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
}

const vary = (v, k = 0.12) => v * (1 + (Math.random() * 2 - 1) * k);

/** A burst of noise through a filter: the body of a click, a rustle, a rush of air. */
function burst({
  at = 0,
  dur = 0.03,
  freq = 3000,
  to = freq,
  q = 1.2,
  gain = 0.5,
  type = "bandpass",
  attack = 0,
}) {
  const t = ctx.currentTime + at;
  const src = ctx.createBufferSource();
  src.buffer = hiss;
  const f = ctx.createBiquadFilter();
  f.type = type;
  f.Q.value = q;
  f.frequency.setValueAtTime(freq, t);
  f.frequency.exponentialRampToValueAtTime(to, t + dur);
  const g = ctx.createGain();
  g.gain.setValueAtTime(attack ? 0.0001 : gain, t);
  if (attack) g.gain.exponentialRampToValueAtTime(gain, t + attack);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  src.connect(f).connect(g).connect(out);
  src.start(t, Math.random() * 0.4);
  src.stop(t + dur + 0.05);
}

/** A tone that slides from one pitch to another and dies away. */
function tone({ at = 0, from = 800, to = from, dur = 0.06, gain = 0.25, type = "triangle", attack = 0.004 }) {
  const t = ctx.currentTime + at;
  const o = ctx.createOscillator();
  o.type = type;
  o.frequency.setValueAtTime(from, t);
  o.frequency.exponentialRampToValueAtTime(to, t + dur);
  const g = ctx.createGain();
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(gain, t + attack);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  o.connect(g).connect(out);
  o.start(t);
  o.stop(t + dur + 0.05);
}

const bell = (at, f, gain = 0.16) => {
  tone({ at, from: f, dur: 0.9, gain, type: "sine" });
  tone({ at, from: f * 2.01, dur: 0.4, gain: gain * 0.35, type: "sine" });
};

const SOUNDS = {
  // A brick pressed onto another: a light tick as it meets the studs, then the snap.
  click() {
    burst({ freq: vary(5200), q: 2.4, dur: 0.012, gain: 0.22 });
    burst({ at: 0.016, freq: vary(2800), q: 1.6, dur: 0.035, gain: 0.5 });
    tone({ at: 0.016, from: vary(1500), to: 700, dur: 0.04, gain: 0.14 });
  },
  snap() {
    burst({ freq: vary(4200), q: 2, dur: 0.015, gain: 0.35 });
    burst({ at: 0.02, freq: vary(2200), q: 1.2, dur: 0.06, gain: 0.8 });
    tone({ at: 0.02, from: 1100, to: 420, dur: 0.07, gain: 0.25 });
  },
  tap() {
    burst({ freq: vary(1900, 0.2), q: 1.4, dur: 0.02, gain: 0.22 });
    tone({ from: vary(620), to: 300, dur: 0.035, gain: 0.1 });
  },
  pop() {
    tone({ from: vary(420), to: 1300, dur: 0.08, gain: 0.22, type: "sine" });
    burst({ freq: 3600, dur: 0.012, gain: 0.18 });
  },
  rattle() {
    for (let i = 0; i < 9; i++)
      burst({ at: Math.random() * 0.4, freq: vary(3000, 0.35), q: 1.6, dur: 0.02, gain: 0.3 });
  },
  camera() {
    burst({ freq: 2400, q: 0.9, dur: 0.025, gain: 0.5 });
    burst({ at: 0.07, freq: 1600, q: 0.9, dur: 0.04, gain: 0.45 });
  },
  whoosh() {
    burst({ freq: 350, to: 3200, q: 0.8, dur: 0.7, gain: 0.5, attack: 0.25 });
  },
  slip() {
    tone({ from: 880, to: 260, dur: 0.45, gain: 0.16, type: "sine" });
  },
  clatter() {
    for (let i = 0; i < 6; i++) {
      const at = i * 0.07 + Math.random() * 0.03;
      burst({ at, freq: vary(2400, 0.3), q: 1.4, dur: 0.03, gain: 0.35 - i * 0.04 });
      tone({ at, from: vary(900, 0.3), to: 400, dur: 0.03, gain: 0.08 });
    }
  },
  boing() {
    tone({ from: 180, to: 560, dur: 0.2, gain: 0.2, type: "sine" });
    tone({ at: 0.12, from: 560, to: 380, dur: 0.18, gain: 0.12, type: "sine" });
  },
  sparkle() {
    for (let i = 0; i < 6; i++)
      tone({ at: i * 0.05, from: vary(2400 + i * 300, 0.1), dur: 0.14, gain: 0.07, type: "sine" });
  },
  tick() {
    tone({ from: 1320, dur: 0.07, gain: 0.14, type: "square" });
    tone({ from: 660, dur: 0.12, gain: 0.1, type: "sine" });
  },
  rumble() {
    burst({ freq: 90, to: 140, q: 0.7, type: "lowpass", dur: 1.6, gain: 0.9, attack: 0.3 });
  },
  whirr() {
    const t = ctx.currentTime;
    const o = ctx.createOscillator();
    o.type = "sawtooth";
    o.frequency.value = 96;
    const wob = ctx.createOscillator();
    wob.frequency.value = 7;
    const depth = ctx.createGain();
    depth.gain.value = 6;
    wob.connect(depth).connect(o.frequency);
    const f = ctx.createBiquadFilter();
    f.type = "lowpass";
    f.frequency.value = 700;
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.1, t + 0.8);
    g.gain.setValueAtTime(0.1, t + 2.6);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 3.6);
    o.connect(f).connect(g).connect(out);
    for (const n of [o, wob]) {
      n.start(t);
      n.stop(t + 3.7);
    }
  },
  snore() {
    burst({ freq: 260, to: 420, q: 0.8, type: "lowpass", dur: 1.1, gain: 0.35, attack: 0.5 });
  },
  yawn() {
    tone({ from: 320, to: 190, dur: 0.9, gain: 0.12, type: "sine", attack: 0.2 });
    burst({ freq: 700, to: 300, q: 0.7, dur: 0.9, gain: 0.12, attack: 0.3 });
  },
  step() {
    tone({ from: 140, to: 80, dur: 0.07, gain: 0.14, type: "sine" });
  },
  chime() {
    [784, 988, 1175].forEach((f, i) => bell(i * 0.09, f));
  },
  fanfare() {
    [523, 659, 784, 1047, 784, 1047].forEach((f, i) => bell(i * 0.11, f, 0.14));
  },
};

export const sound = {
  get on() {
    return on;
  },
  /** Turns sound on or off; the first time on starts the audio, which a browser allows only after a tap. */
  set(value) {
    on = value;
    if (on && !ctx) start();
    if (ctx) on ? ctx.resume() : ctx.suspend();
  },
  play(name) {
    if (!on || !ctx || !SOUNDS[name]) return;
    // Clicks come thick and fast when a model goes together; a few are enough to hear it.
    const now = ctx.currentTime;
    if ((name === "click" || name === "tap") && now - last < 0.045) return;
    if (name === "click" || name === "tap") last = now;
    SOUNDS[name]();
  },
};
