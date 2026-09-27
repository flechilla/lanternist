/* Sound, off until the visitor asks for it; striking the opening's match counts as asking. Every
 * effect, loop and voice was made for this page by sound and voice models, once. Each time an effect
 * plays it is pitched and levelled a little differently, the way a foley artist never knocks the same
 * prop the same way twice. Voices go through a meter, so a puppet's mouth can follow the words. */

const DIR = new URL("audio/", import.meta.url);

let ctx = null;
let master = null;
let bed = null;
let fx = null;
let voiceBus = null;
let meter = null;
let wanted = false;
const buffers = new Map();
const loops = new Map();
let song = null;
const levels = new Float32Array(1024);

function wire() {
  ctx = new AudioContext();
  master = ctx.createGain();
  master.connect(ctx.destination);
  bed = ctx.createGain();
  fx = ctx.createGain();
  voiceBus = ctx.createGain();
  meter = ctx.createAnalyser();
  meter.fftSize = 1024;
  bed.connect(master);
  fx.connect(master);
  voiceBus.connect(meter).connect(master);
}

/** Decodes a file once; later calls share it. MP3's padding is trimmed so loops close cleanly. */
function load(name) {
  if (!buffers.has(name)) {
    buffers.set(
      name,
      fetch(new URL(`${name}.mp3`, DIR))
        .then((r) => {
          if (!r.ok) throw new Error(`no sound called ${name}`);
          return r.arrayBuffer();
        })
        .then((b) => ctx.decodeAudioData(b))
        .then((buf) => {
          const d = buf.getChannelData(0);
          let a = 0;
          let z = d.length - 1;
          while (a < z && Math.abs(d[a]) < 1e-4) a++;
          while (z > a && Math.abs(d[z]) < 1e-4) z--;
          buf.trim = [a / buf.sampleRate, (z + 1) / buf.sampleRate];
          return buf;
        }),
    );
  }
  return buffers.get(name);
}

export const foley = {
  get on() {
    return !!ctx && wanted && ctx.state === "running";
  },

  /** Turns sound on or off; the first call must come from a click or a key. */
  async set(on) {
    wanted = on;
    if (on && !ctx) wire();
    if (!ctx) return false;
    if (on) await ctx.resume();
    else await ctx.suspend();
    return this.on;
  },

  /** Plays an effect once. `pan` is -1 (left) to 1 (right); `vary` is how much it may differ. */
  async play(name, { gain = 1, pan = 0, vary = 0.08, rate = 1, delay = 0 } = {}) {
    if (!this.on) return null;
    const buf = await load(name).catch(() => null);
    if (!buf) return null;
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.playbackRate.value = rate * (1 + (Math.random() - 0.5) * vary);
    const g = ctx.createGain();
    g.gain.value = gain * (1 + (Math.random() - 0.5) * vary);
    const p = ctx.createStereoPanner();
    p.pan.value = Math.max(-1, Math.min(1, pan));
    src.connect(g).connect(p).connect(fx);
    src.start(ctx.currentTime + delay, buf.trim[0]);
    return src;
  },

  /** Keeps a looping bed at `gain` (0 fades it out); beds cross-fade as the camera moves. */
  async loop(name, gain, fade = 1.2) {
    if (!ctx) return;
    let l = loops.get(name);
    if (!l) {
      if (gain <= 0) return;
      l = { gain: ctx.createGain(), src: null };
      l.gain.gain.value = 0;
      l.gain.connect(bed);
      loops.set(name, l);
      const buf = await load(name).catch(() => null);
      if (!buf) return;
      l.src = ctx.createBufferSource();
      l.src.buffer = buf;
      l.src.loop = true;
      [l.src.loopStart, l.src.loopEnd] = buf.trim;
      l.src.connect(l.gain);
      l.src.start(0, buf.trim[0]);
    }
    l.gain.gain.cancelScheduledValues(ctx.currentTime);
    l.gain.gain.setTargetAtTime(gain, ctx.currentTime, fade / 3);
  },

  /** Plays one piece of music at a time, faded in over the beds; `null` fades the current one out. */
  async music(name, gain = 0.6, { loop = false, fade = 1.5 } = {}) {
    if (!ctx || song?.name === name) return;
    if (song) {
      const old = song;
      old.gain.gain.setTargetAtTime(0, ctx.currentTime, fade / 3);
      old.src?.stop(ctx.currentTime + fade * 2);
      song = null;
    }
    if (!name) return;
    const g = ctx.createGain();
    g.gain.value = 0;
    g.connect(bed);
    song = { name, gain: g, src: null };
    const mine = song;
    const buf = await load(name).catch(() => null);
    if (!buf || song !== mine) return;
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.loop = loop;
    if (loop) [src.loopStart, src.loopEnd] = buf.trim;
    src.connect(g);
    src.start(0, buf.trim[0]);
    g.gain.setTargetAtTime(gain, ctx.currentTime, 0.3);
    mine.src = src;
  },

  /** Sets every bed at once: the ones not named fade out. */
  beds(mix, fade) {
    for (const name of new Set([...loops.keys(), ...Object.keys(mix)])) this.loop(name, mix[name] ?? 0, fade);
  },

  /** Plays a voice through the meter; resolves when it ends. Beds dip under it. */
  async say(name, { gain = 1 } = {}) {
    if (!this.on) return null;
    const buf = await load(name).catch(() => null);
    if (!buf) return null;
    const src = ctx.createBufferSource();
    src.buffer = buf;
    const g = ctx.createGain();
    g.gain.value = gain;
    src.connect(g).connect(voiceBus);
    bed.gain.setTargetAtTime(0.45, ctx.currentTime, 0.2);
    src.start(ctx.currentTime, buf.trim[0]);
    src.onended = () => bed.gain.setTargetAtTime(1, ctx.currentTime, 0.4);
    return src;
  },

  /** How loud the voices are right now, 0 to 1: a mouth opens with it, a needle swings with it. */
  level() {
    if (!meter) return 0;
    meter.getFloatTimeDomainData(levels);
    let s = 0;
    for (const v of levels) s += v * v;
    return Math.min(1, Math.sqrt(s / levels.length) * 5);
  },

  /** The context's clock, for sounds that must line up with words. */
  get time() {
    return ctx ? ctx.currentTime : 0;
  },
};
