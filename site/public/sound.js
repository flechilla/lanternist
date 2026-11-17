/* Sound, off until the visitor turns it on. Each scene gets the ambience its `sound` prompt asks for,
 * made here from filtered noise: the sea, wind, rain, a lamp's hum, thunder, gulls. There is no music,
 * because the app's films have none. */

let ctx = null;
let out = null;
const beds = {};

/** How loud each bed is in each mood; a mood is a scene's sound, or the hall between reels. */
const MOODS = {
  hall: { hum: 0.1 },
  calm: { sea: 0.5, wind: 0.1 },
  room: { sea: 0.12, hum: 0.22 },
  storm: { sea: 0.85, wind: 0.5, rain: 0.45 },
  inside: { rain: 0.25, wind: 0.28, sea: 0.15 },
  dawn: { sea: 0.32, wind: 0.06, gulls: 1 },
};

const buffers = {};

/** A looping source of white or brown noise; each kind is made once and shared. */
function noise(kind) {
  if (!buffers[kind]) {
    const len = ctx.sampleRate * 4;
    buffers[kind] = ctx.createBuffer(1, len, ctx.sampleRate);
    const d = buffers[kind].getChannelData(0);
    let last = 0;
    for (let i = 0; i < len; i++) {
      const w = Math.random() * 2 - 1;
      last = (last + 0.02 * w) / 1.02;
      d[i] = kind === "brown" ? last * 3.5 : w;
    }
  }
  const src = ctx.createBufferSource();
  src.buffer = buffers[kind];
  src.loop = true;
  src.start();
  return src;
}

function bed(src, type, freq, lfo) {
  const filter = ctx.createBiquadFilter();
  filter.type = type;
  filter.frequency.value = freq;
  const gain = ctx.createGain();
  gain.gain.value = 0;
  src.connect(filter).connect(gain).connect(out);
  if (lfo) {
    const osc = ctx.createOscillator();
    osc.frequency.value = lfo.rate;
    const depth = ctx.createGain();
    depth.gain.value = lfo.depth;
    osc.connect(depth).connect(lfo.param === "freq" ? filter.frequency : gain.gain);
    osc.start();
  }
  return gain;
}

function start() {
  ctx = new AudioContext();
  out = ctx.createGain();
  out.gain.value = 0.5;
  out.connect(ctx.destination);
  beds.sea = bed(noise("brown"), "lowpass", 520, { rate: 0.11, depth: 0.25 });
  beds.wind = bed(noise("white"), "bandpass", 480, { rate: 0.07, depth: 260, param: "freq" });
  beds.rain = bed(noise("white"), "highpass", 2600);
  const hum = ctx.createOscillator();
  hum.frequency.value = 55;
  hum.start();
  beds.hum = bed(hum, "lowpass", 200);
  beds.gulls = ctx.createGain();
  beds.gulls.gain.value = 0;
  beds.gulls.connect(out);
  setInterval(gull, 4200);
}

function gull() {
  if (!ctx || beds.gulls.gain.value < 0.5) return;
  const t = ctx.currentTime + Math.random();
  for (let i = 0; i < 3; i++) {
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    const at = t + i * 0.32;
    osc.frequency.setValueAtTime(1500, at);
    osc.frequency.exponentialRampToValueAtTime(820, at + 0.24);
    g.gain.setValueAtTime(0, at);
    g.gain.linearRampToValueAtTime(0.05, at + 0.03);
    g.gain.exponentialRampToValueAtTime(0.001, at + 0.26);
    osc.connect(g).connect(beds.gulls);
    osc.start(at);
    osc.stop(at + 0.3);
  }
}

let mood = "hall";

export const sound = {
  get on() {
    return !!ctx && ctx.state === "running";
  },
  async toggle() {
    if (!ctx) start();
    else if (ctx.state === "running") await ctx.suspend();
    else await ctx.resume();
    this.mood(mood);
    return this.on;
  },
  mood(name) {
    mood = name;
    if (!ctx) return;
    const levels = MOODS[name] ?? MOODS.hall;
    for (const [key, g] of Object.entries(beds))
      g.gain.setTargetAtTime(levels[key] ?? 0, ctx.currentTime, 0.6);
  },
  thunder() {
    if (!this.on) return;
    const src = noise("brown");
    const filter = ctx.createBiquadFilter();
    filter.type = "lowpass";
    filter.frequency.value = 140;
    const g = ctx.createGain();
    const t = ctx.currentTime + 0.25;
    g.gain.setValueAtTime(0, ctx.currentTime);
    g.gain.linearRampToValueAtTime(1.6, t + 0.08);
    g.gain.exponentialRampToValueAtTime(0.001, t + 2.6);
    src.connect(filter).connect(g).connect(out);
    src.stop(t + 2.8);
  },
  /** A paper click, for a slide going into the lantern. */
  tick() {
    if (!this.on) return;
    const src = noise("white");
    const filter = ctx.createBiquadFilter();
    filter.type = "bandpass";
    filter.frequency.value = 2400;
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.5, ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.05);
    src.connect(filter).connect(g).connect(out);
    src.stop(ctx.currentTime + 0.06);
  },
};

/** Which mood each shot's sound prompt calls for. */
export const SHOT_MOODS = ["calm", "room", "storm", "storm", "inside", "inside", "dawn"];
