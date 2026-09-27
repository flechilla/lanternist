/* The front of house. The hero lantern projects Luna's first shot, or the visitor's own idea; five
 * reels show how Luna's film was made, each from the same storyboard (story.js); then the film plays,
 * with the visitor's choices from the reels; then the invitation. Everything moves on stage.js's
 * clock. */

import { boat, critter, hand, magicLantern, scissors, tomas } from "./art.js";
import { HOLD, LOOP, SCENES } from "./scenes.js";
import { describe, slide, title } from "./sketch.js";
import { SHOT_MOODS, sound } from "./sound.js";
import { calm, drop, FPS, noise, onFrame, seek, stage, watch } from "./stage.js";
import { CAST, cues, LANGUAGES, nextSeed, SEED, seconds, SHOTS, TITLE } from "./story.js";

const $ = (sel, root = document) => root.querySelector(sel);
const el = (tag, props = {}, html = "") =>
  Object.assign(document.createElement(tag), props, html ? { innerHTML: html } : {});
const secs = (n) => `${n.toFixed(1)}\u00a0s`;

/** What the visitor has chosen, shared by the reels and the show. */
const state = {
  lang: "en",
  modes: SHOTS.map((s) => s.mode),
  seeds: SHOTS.map((s) => SEED + s.n),
  takes: SHOTS.map(() => 0),
};
/** The film's language: the subtitles picked under the screen. */
const showLang = () => $("#subs-lang").value;

/* ---------- the room: grain, boil, the frame counter ---------- */

function grain() {
  const c = el("canvas", { width: 160, height: 160 });
  const g = c.getContext("2d");
  const img = g.createImageData(160, 160);
  for (let i = 0; i < img.data.length; i += 4) {
    const v = 150 + Math.random() * 105;
    img.data.set([v, v, v, Math.random() * 90], i);
  }
  g.putImageData(img, 0, 0);
  document.documentElement.style.setProperty("--noise", `url(${c.toDataURL()})`);
}
grain();

const boil = $("#boil");
const grainEl = $(".grain");
const counter = $("#frame");
let lastFrame = 0;
let skipped = 0;
onFrame((f) => {
  counter.textContent = String(f % 1e6).padStart(6, "0");
  // A machine that can't keep 12 frames a second gets still card edges instead of a stutter.
  skipped = Math.max(0, skipped + (f - lastFrame > 2 ? 4 : -0.25));
  lastFrame = f;
  if (skipped > 24) document.documentElement.classList.add("lite");
  if (calm.matches) return;
  if (f % 2 === 0) boil.setAttribute("seed", String(1 + ((f / 2) % 4)));
  grainEl.style.transform = `translate(${Math.round(noise(1, f) * 120 - 60)}px,${Math.round(noise(2, f) * 120 - 60)}px)`;
});

/** A scene drawn once, without motion, for a thumbnail; `take` is the re-rolled framing. */
function still(i, cls = "thumb") {
  const box = el("div", { className: `${cls} still` }, SCENES[i]().svg);
  frameTake(box, i);
  return box;
}

/** A re-roll draws the same scene again, framed differently: nearer, from another side. */
const TAKES = [
  { s: 1, o: "50% 50%", flip: false },
  { s: 1.18, o: "32% 62%", flip: true },
  { s: 1.24, o: "70% 42%", flip: false },
  { s: 1.12, o: "50% 78%", flip: true },
];
function frameTake(root, i) {
  const take = TAKES[state.takes[i] % TAKES.length];
  // The Marisol's name would read backwards in a mirrored take.
  const flip = take.flip && !SHOTS[i].cast.includes("marisol");
  const g = $(".take", root);
  if (!g) return;
  g.style.transformOrigin = take.o;
  g.style.transform = `scale(${flip ? -take.s : take.s},${take.s})`;
}

/* ---------- the hero: the lantern and its slide ---------- */

const theatre = $("#theatre");
const projection = $("#hero-projection");
const ribbon = $("#hero-title");
const caption = $("#hero-caption");
const lantern = $("#lantern");
lantern.innerHTML = magicLantern();
const lanternStage = stage(lantern);
watch(theatre, lanternStage);

let heroSlide = $("#hero-slide");
const night = SCENES[0]();
heroSlide.innerHTML = night.svg;
let heroStage = stage(heroSlide, { fns: night.fns });
let heroVisible = false;
watch(theatre, heroStage, (v) => {
  heroVisible = v;
  heroStage.on = v && !calm.matches;
});

const beamSvg = $("#beam");
const beamPoly = $("polygon", beamSvg);
function aimBeam() {
  const box = theatre.getBoundingClientRect();
  const lens = lantern.getBoundingClientRect();
  const circle = projection.getBoundingClientRect();
  const px = lens.left - box.left + (lens.width * 364) / 380;
  const py = lens.top - box.top + (lens.height * 186) / 300;
  const cx = circle.left - box.left + circle.width / 2;
  const cy = circle.top - box.top + circle.height / 2;
  const r = circle.width / 2;
  const d = Math.hypot(px - cx, py - cy);
  if (d <= r) return;
  // The beam's edges are the two tangents from the lens to the round slide.
  const base = Math.atan2(py - cy, px - cx);
  const a = Math.acos(r / d);
  const t1 = [cx + r * Math.cos(base + a), cy + r * Math.sin(base + a)];
  const t2 = [cx + r * Math.cos(base - a), cy + r * Math.sin(base - a)];
  beamPoly.setAttribute("points", `${px},${py - 6} ${t1} ${t2} ${px},${py + 6}`);
}
new ResizeObserver(aimBeam).observe(theatre);
const heroFlicker = $(".flicker", projection);
onFrame((f) => {
  if (!heroVisible || calm.matches) return;
  beamPoly.style.opacity = String(0.4 + 0.16 * noise(3, f));
  heroFlicker.style.opacity = String(0.72 + 0.28 * noise(3, f));
});

/** Lights the lantern: the lamp catches, the beam comes on, the slide irises open. */
function lightUp() {
  if (calm.matches) return theatre.classList.remove("dark");
  const steps = [
    [350, () => theatre.classList.add("catching")],
    [800, () => theatre.classList.remove("dark")],
    [1500, () => theatre.classList.remove("catching")],
  ];
  for (const [ms, fn] of steps) setTimeout(fn, ms);
}
lightUp();

const ideaForm = $("#idea-form");
const ideaInput = $("#idea");
const joinIdea = $("#join-idea");

function project(idea) {
  const text = title(idea);
  if (!text) return;
  const { svg, read } = slide(text);
  const next = el("div", { className: "slide in" }, svg);
  projection.insertBefore(next, $(".flicker", projection));
  const nextStage = stage(next);
  nextStage.on = heroVisible && !calm.matches;
  const old = heroSlide;
  const oldStage = heroStage;
  heroSlide = next;
  heroStage = nextStage;
  old.classList.add("out");
  ribbon.classList.add("away");
  sound.tick();
  requestAnimationFrame(() => requestAnimationFrame(() => next.classList.remove("in")));
  setTimeout(() => {
    drop(oldStage);
    old.remove();
    ribbon.textContent = text;
    ribbon.classList.remove("away");
  }, 540);
  caption.replaceChildren(
    "Your slide: ",
    el("b", { textContent: describe(read) }),
    ". A paper sketch, cut in your browser from the words it knows. In the app, the writer turns your line into a whole story, and the image models draw every scene.",
  );
  joinIdea.value = text;
  if (matchMedia("(max-width: 1000px)").matches) theatre.scrollIntoView({ block: "center" });
}

ideaForm.addEventListener("submit", (e) => {
  e.preventDefault();
  project(ideaInput.value || IDEAS[typing.i]);
});
for (const chip of document.querySelectorAll(".chip")) {
  chip.addEventListener("click", () => {
    ideaInput.value = chip.textContent;
    project(chip.textContent);
  });
}

/** The placeholder types itself out, one idea after another, while the field is empty. */
const IDEAS = [
  "A lighthouse cat afraid of the dark",
  "A bear who can't fall asleep",
  "Una niña que guarda estrellas en un frasco",
  "An owl who runs the night library",
  "Um robô que aprende a assobiar",
];
let typing = { i: 0, n: 0, hold: 0, back: false };
onFrame(() => {
  if (calm.matches || ideaInput.value || document.activeElement === ideaInput || !heroVisible) return;
  const idea = IDEAS[typing.i];
  if (typing.hold > 0) typing.hold--;
  else if (!typing.back) {
    typing.n = Math.min(idea.length, typing.n + 1);
    if (typing.n === idea.length) typing = { ...typing, hold: 30, back: true };
  } else {
    typing.n = Math.max(0, typing.n - 3);
    if (typing.n === 0) typing = { i: (typing.i + 1) % IDEAS.length, n: 0, hold: 4, back: false };
  }
  ideaInput.placeholder = idea.slice(0, typing.n) || " ";
});

/* ---------- Reel I: the writer ---------- */

const langs = $("#langs");
const shotsEl = $("#shots");
const script = $("#script");
let typer = null;

function renderScript() {
  const [a, b] = SHOTS;
  const block = (s) =>
    `<div class="shot"><p class="tag">Shot ${s.n} · ${s.shot} · ${secs(seconds(s.narration[state.lang], state.lang))}</p>` +
    `<p class="narr" lang="${state.lang}"></p><p class="prompt" lang="en"><b>Picture</b>${s.visual}</p></div>`;
  shotsEl.innerHTML =
    block(a) +
    `<div class="cutline"><svg viewBox="-60 -30 200 60" aria-hidden="true"></svg><span>cut</span></div>` +
    block(b);
  const lines = [...shotsEl.querySelectorAll(".narr")];
  const texts = [a, b].map((s) => s.narration[state.lang]);
  if (calm.matches) {
    lines.forEach((p, i) => (p.textContent = texts[i]));
    return;
  }
  // Typed out a few characters a frame, the way the writer streams it.
  let k = 0;
  typer?.();
  typer = onFrame(() => {
    k += state.lang === "zh" || state.lang === "ja" ? 1 : 3;
    let left = k;
    lines.forEach((p, i) => {
      const shown = texts[i].slice(0, Math.max(0, left));
      left -= texts[i].length;
      p.innerHTML = "";
      p.append(shown);
      if (shown.length < texts[i].length && left < 0 && left + texts[i].length > 0)
        p.append(el("span", { className: "caret" }));
    });
    if (left > 0) typer();
  });
  snip($(".cutline svg", shotsEl));
}

/** Once, as the script comes into view, the scissors cut the paragraph into its two shots. */
let snipped = calm.matches;
function snip(svg) {
  svg.innerHTML = scissors(10);
  if (snipped) svg.parentElement.classList.add("snipped");
}
new IntersectionObserver(
  ([e], io) => {
    if (!e.isIntersecting || snipped) return;
    io.disconnect();
    let f = 0;
    const stop = onFrame(() => {
      const svg = $(".cutline svg", shotsEl);
      const line = svg.parentElement;
      f++;
      svg.style.translate = `${Math.round(Math.min(1, f / 24) * (line.clientWidth - 70))}px 0`;
      svg.innerHTML = scissors(f % 4 < 2 ? 16 : 3);
      if (f >= 24) {
        stop();
        snipped = true;
        snip(svg);
      }
    });
  },
  { threshold: 0.6 },
).observe(script);

function setLang(code) {
  state.lang = code;
  for (const b of langs.children) b.setAttribute("aria-pressed", String(b.dataset.lang === code));
  renderScript();
  renderTimeline();
  if (TITLE[code] && subsLang.value !== code) {
    subsLang.value = code;
    subsLang.dispatchEvent(new Event("change"));
  }
}

for (const [code, name] of Object.entries(LANGUAGES)) {
  const b = el("button", { type: "button", textContent: name, lang: code });
  b.dataset.lang = code;
  b.setAttribute("aria-pressed", String(code === state.lang));
  b.addEventListener("click", () => setLang(code));
  langs.append(b);
}

/* ---------- Reel II: the narrator ---------- */

const timeline = $("#timeline");
const tlPics = $("#tl-pics");
const tlWave = $("#tl-wave");
const tlWords = $("#tl-words");
const playhead = $("#playhead");
const tlTrack = $("#tl-track");
const legend = $("#tl-legend");
let tl = null;

const tokens = (text, lang) => (lang === "zh" || lang === "ja" ? text.match(/.{1,2}/gu) : text.split(/\s+/));

function renderTimeline() {
  const shots = SHOTS.slice(0, 2).map((s) => {
    const text = s.narration[state.lang];
    return { s, text, d: seconds(text, state.lang), words: tokens(text, state.lang) };
  });
  const total = shots.reduce((a, x) => a + x.d, 0);
  tlPics.replaceChildren(
    ...shots.map((x, i) => {
      const pic = el("div", { className: "tl-pic" });
      pic.style.flex = `${x.d} 1 0`;
      pic.append(still(i), el("span", { textContent: `Shot ${x.s.n} · ${secs(x.d)}` }));
      return pic;
    }),
  );
  // Each word gets its share of its shot, by length; the bars are its syllables.
  const spans = [];
  let at = 0;
  let bars = "";
  shots.forEach((x, si) => {
    const chars = x.words.reduce((a, w) => a + w.length + 1, 0);
    for (const [wi, w] of x.words.entries()) {
      const len = (x.d * (w.length + 1)) / chars;
      spans.push({ w, from: at, to: at + len, si });
      const n = Math.max(1, Math.round(w.length / 1.5));
      for (let k = 0; k < n; k++) {
        const bx = ((at + (len * (k + 0.2)) / n) / total) * 1000;
        const h = 10 + 44 * noise(si * 97 + wi, k);
        bars += `<rect x="${bx.toFixed(1)}" y="${(32 - h / 2).toFixed(1)}" width="${((len / n / total) * 1000 * 0.6).toFixed(1)}" height="${h.toFixed(1)}" rx="1.5"/>`;
      }
      at += len;
    }
  });
  tlWave.setAttribute("viewBox", "0 0 1000 64");
  tlWave.innerHTML = `<g fill="#f0b14a" opacity=".85">${bars}</g>`;
  const sep = state.lang === "zh" || state.lang === "ja" ? "" : " ";
  tlWords.replaceChildren(
    ...spans.flatMap((x, i) => [el("span", { textContent: x.w }), i < spans.length - 1 ? sep : ""]),
  );
  tlWords.lang = state.lang;
  legend.textContent = `${LANGUAGES[state.lang]}, read at ${Math.round((60 * spans.length) / total)} words a minute. Shot 1 holds ${secs(shots[0].d)}, shot 2 holds ${secs(shots[1].d)}.`;
  tl = { total, spans, split: shots[0].d, t: 0 };
}

let tlVisible = false;
new IntersectionObserver(([e]) => (tlVisible = e.isIntersecting)).observe(timeline);
onFrame(() => {
  if (!tl || !tlVisible || calm.matches) return;
  tl.t = (tl.t + 1 / FPS) % (tl.total + 1.5);
  const t = Math.min(tl.t, tl.total);
  playhead.style.translate = `${Math.round((t / tl.total) * tlTrack.clientWidth)}px 0`;
  const words = tlWords.querySelectorAll("span");
  tl.spans.forEach((x, i) => (words[i].className = t >= x.to ? "said" : t >= x.from ? "on" : ""));
  const [p1, p2] = tlPics.children;
  p1.classList.toggle("dim", t >= tl.split);
  p2.classList.toggle("dim", t < tl.split);
});

/* ---------- Reel III: the cast ---------- */

const castboard = $("#castboard");
const portraitsEl = $("#portraits");
const thumbsEl = $("#thumbs");
const threads = $("#threads");

const cameo = (vb, body, bg) =>
  `<svg viewBox="${vb}" aria-hidden="true"><rect x="-500" y="-500" width="1000" height="1000" fill="${bg}"/>${body}</svg>`;
const PORTRAITS = {
  luna: cameo("-78 -178 180 180", critter({ x: 0, y: 0 }), "#1a2b47"),
  tomas: cameo("-86 -262 180 180", tomas({ x: 0, y: 0 }), "#2a1f1c"),
  marisol: cameo(
    "-130 -200 260 260",
    `<rect x="-200" y="0" width="400" height="80" fill="#1e3c60"/>${boat({ x: 0, y: 0, m: "rock 3 3 40" })}`,
    "#13213a",
  ),
};
portraitsEl.innerHTML = `<h3>Cast sheet</h3><div class="cast-row"></div>`;
for (const c of CAST) {
  const card = el("div", { className: `portrait ${c.kind}` });
  card.dataset.id = c.id;
  card.innerHTML = `<div class="cameo">${PORTRAITS[c.id]}</div><b>${c.name}</b><small lang="en">${c.look}</small>`;
  $(".cast-row", portraitsEl).append(card);
  watch(card, stage($(".cameo", card)));
}

function renderThumbs() {
  thumbsEl.replaceChildren(
    ...SHOTS.map((s, i) => {
      const li = el("li");
      const btn = el("button", { type: "button", className: "thumb-btn" });
      btn.setAttribute(
        "aria-label",
        `Shot ${s.n}, ${s.shot}: ${s.cast.length ? s.cast.join(", ") : "no one"}`,
      );
      btn.append(
        still(i),
        el("span", { textContent: `${s.n} · seed ${state.seeds[i].toLocaleString("en")}` }),
      );
      const roll = el("button", { type: "button", className: "reroll", textContent: "↻" });
      roll.setAttribute("aria-label", `Draw shot ${s.n} again`);
      roll.addEventListener("click", () => reroll(i, li));
      for (const ev of ["pointerenter", "focus"]) btn.addEventListener(ev, () => point(i, li));
      for (const ev of ["pointerleave", "blur"]) btn.addEventListener(ev, () => point(-1));
      li.append(btn, roll);
      return li;
    }),
  );
}

let pointing = -1;
function point(i, li) {
  pointing = i;
  castboard.classList.toggle("pointing", i >= 0);
  for (const t of thumbsEl.children) t.classList.toggle("on", t === li);
  for (const p of portraitsEl.querySelectorAll(".portrait"))
    p.classList.toggle("lit", i >= 0 && SHOTS[i].cast.includes(p.dataset.id));
  drawThreads(0);
}

function drawThreads(f) {
  if (pointing < 0) {
    threads.innerHTML = "";
    return;
  }
  const box = castboard.getBoundingClientRect();
  const to = thumbsEl.children[pointing].getBoundingClientRect();
  const tx = to.left - box.left + to.width / 2;
  const ty = to.top - box.top;
  threads.innerHTML = [...portraitsEl.querySelectorAll(".portrait.lit")]
    .map((c, k) => {
      const r = c.getBoundingClientRect();
      const x = r.left - box.left + r.width / 2;
      const y = r.bottom - box.top;
      const sag = 30 + 8 * noise(k, Math.floor(f / 2));
      return `<path d="M${x} ${y}Q${(x + tx) / 2} ${(y + ty) / 2 + sag} ${tx} ${ty}"/>`;
    })
    .join("");
}
onFrame((f) => pointing >= 0 && !calm.matches && drawThreads(f));

function reroll(i, li) {
  li.classList.add("rolling");
  sound.tick();
  setTimeout(
    () => {
      state.takes[i]++;
      state.seeds[i] = nextSeed(state.seeds[i]);
      renderThumbs();
      renderStrip();
      renderMix();
      if (picked === i) renderPreview();
      thumbsEl.children[i].classList.add("rolling");
      requestAnimationFrame(() =>
        requestAnimationFrame(() => thumbsEl.children[i].classList.remove("rolling")),
      );
    },
    calm.matches ? 0 : 300,
  );
}

/** Once, as the board comes into view, the animator's hand reaches in and sets Luna's portrait down. */
const handEl = $("#hand");
handEl.innerHTML = hand();
new IntersectionObserver(
  ([e], io) => {
    if (!e.isIntersecting || calm.matches) return;
    io.disconnect();
    const luna = $(".portrait .cameo", portraitsEl);
    const box = castboard.getBoundingClientRect();
    const r = luna.getBoundingClientRect();
    handEl.style.left = `${r.left - box.left + r.width / 2 - 20}px`;
    handEl.style.top = `${r.top - box.top - handEl.getBoundingClientRect().height + r.height * 0.55}px`;
    let f = 0;
    const path = [-100, -70, -45, -25, -10, 0, 0, 0, 0, 0, 0, -8, -25, -50, -80, -110];
    const stop = onFrame(() => {
      handEl.style.opacity = f < path.length - 1 ? "1" : "0";
      handEl.style.translate = `0 ${path[Math.min(f, path.length - 1)]}%`;
      luna.style.translate = f >= 5 && f <= 10 ? `0 ${f % 2 ? 2 : 0}px` : "";
      if (++f > path.length) stop();
    });
  },
  { threshold: 0.5 },
).observe(castboard);

/* ---------- Reel IV: the motion ---------- */

const strip = $("#strip");
const preview = $("#motion-preview");
const tally = $("#tally");
let picked = 4;
let previewStage = null;
let previewVisible = false;

function renderPreview() {
  drop(previewStage);
  const scene = SCENES[picked]();
  preview.innerHTML = scene.svg;
  frameTake(preview, picked);
  const shot = SHOTS[picked];
  const isStill = state.modes[picked] === "still";
  previewStage = stage(preview, {
    fns: scene.fns,
    still: isStill,
    hold: HOLD[picked],
    camera: shot.camera === "static" ? "push_in" : shot.camera,
    loop: LOOP[picked],
    dur: LOOP[picked],
  });
  previewStage.on = previewVisible && !calm.matches;
}
new IntersectionObserver(([e]) => {
  previewVisible = e.isIntersecting;
  if (previewStage) previewStage.on = previewVisible && !calm.matches;
}).observe(preview);

function renderStrip() {
  strip.replaceChildren(
    ...SHOTS.map((s, i) => {
      const li = el("li");
      const pick = el("button", { type: "button", className: `thumb-btn${i === picked ? " on" : ""}` });
      pick.setAttribute("aria-label", `Preview shot ${s.n}`);
      pick.append(still(i));
      pick.addEventListener("click", () => {
        picked = i;
        renderStrip();
        renderPreview();
      });
      const mode = el("div", { className: "mode", role: "group" });
      mode.setAttribute("aria-label", `Shot ${s.n}`);
      for (const m of ["still", "video"]) {
        const b = el("button", {
          type: "button",
          className: m,
          textContent: m === "still" ? "Still" : "Video",
        });
        b.setAttribute("aria-pressed", String(state.modes[i] === m));
        b.addEventListener("click", () => {
          state.modes[i] = m;
          picked = i;
          sound.tick();
          renderStrip();
          renderPreview();
          renderTally();
        });
        mode.append(b);
      }
      li.append(pick, mode);
      return li;
    }),
  );
}

function renderTally() {
  const lang = showLang();
  const moving = SHOTS.filter((_, i) => state.modes[i] === "video");
  const videoSecs = moving.reduce((a, s) => a + seconds(s.narration[lang], lang), 0);
  const stills = SHOTS.length - moving.length;
  tally.textContent =
    moving.length === 0
      ? "All seven shots are stills, each with a slow camera move."
      : `${moving.length} of 7 shots move: ${Math.round(videoSecs)} seconds of video.` +
        (stills
          ? ` The other ${stills === 1 ? "one is a still" : `${stills} are stills`} with a slow camera move.`
          : "");
}

/* ---------- Reel V: the mix ---------- */

const mixer = $("#mixer");
const meter = $("#meter");
const mixHead = el("div", { className: "playhead" });
mixer.append(mixHead);

function renderMix() {
  const lang = showLang();
  const d = SHOTS.map((s) => seconds(s.narration[lang], lang));
  const total = d.reduce((a, b) => a + b, 0);
  $("#lane-pics").replaceChildren(
    ...SHOTS.map((_, i) => {
      const t = still(i);
      t.style.flex = `${d[i]} 1 0`;
      return t;
    }),
  );
  let x = 0;
  let voice = "";
  let amb = "M0 22";
  SHOTS.forEach((s, i) => {
    const w = (d[i] / total) * 1000;
    const n = Math.round(w / 7);
    for (let k = 0; k < n; k++) {
      const h = 6 + 30 * noise(i * 31 + k, 2);
      voice += `<rect x="${(x + k * 7).toFixed(1)}" y="${(22 - h / 2).toFixed(1)}" width="4" height="${h.toFixed(1)}"/>`;
    }
    const rough = SHOT_MOODS[i] === "storm" || SHOT_MOODS[i] === "inside";
    for (let k = 1; k <= 8; k++)
      amb += `L${(x + (w * k) / 8).toFixed(1)} ${(22 + (rough ? 14 : 5) * (k % 2 ? -1 : 1) * noise(i, k)).toFixed(1)}`;
    x += w;
  });
  $("#lane-voice").setAttribute("viewBox", "0 0 1000 44");
  $("#lane-voice").innerHTML = `<g fill="#f0b14a" opacity=".8">${voice}</g>`;
  $("#lane-amb").setAttribute("viewBox", "0 0 1000 44");
  $("#lane-amb").innerHTML =
    `<path d="${amb}" fill="none" stroke="#6fc4a6" stroke-width="2.5" vector-effect="non-scaling-stroke"/>`;
  $("#lane-subs").replaceChildren(
    ...SHOTS.flatMap((s, i) => {
      const cs = cues(s.narration[lang]);
      const chars = cs.reduce((a, c) => a + c.length, 0);
      return cs.map((c) => {
        const span = el("span", { textContent: c });
        span.style.flex = `${(d[i] * c.length) / chars} 1 0`;
        return span;
      });
    }),
  );
  const m = Math.floor(total / 60);
  $("#can-meta").textContent =
    `${m} min ${Math.round(total - m * 60)} s · 7 shots in 4 paragraphs · ${LANGUAGES[lang]} narration`;
  mix.total = total;
}

const TICKS = [-30, -24, -16, -12, -6, 0];
const angle = (v) => Math.PI * (1 - (v + 30) / 30);
function drawMeter(v) {
  const tick = (t) => {
    const a = angle(t);
    const [c, s] = [Math.cos(a), -Math.sin(a)];
    const lit = t === -16;
    return (
      `<path d="M${100 + 70 * c} ${100 + 70 * s}L${100 + 82 * c} ${100 + 82 * s}" stroke="${lit ? "#f0b14a" : "#8e98a8"}" stroke-width="${lit ? 3 : 1.5}"/>` +
      `<text x="${100 + 96 * c}" y="${104 + 96 * s}" text-anchor="middle" font-family="Courier Prime, monospace" font-size="10" fill="${lit ? "#f5c572" : "#8e98a8"}">${t}</text>`
    );
  };
  const a = angle(v);
  meter.innerHTML =
    `<path d="M22 100A78 78 0 0 1 178 100" fill="none" stroke="rgba(255,255,255,.12)" stroke-width="10"/>` +
    TICKS.map(tick).join("") +
    `<path d="M100 100L${100 + 66 * Math.cos(a)} ${100 - 66 * Math.sin(a)}" stroke="#ece6d9" stroke-width="3" stroke-linecap="round"/>` +
    `<circle cx="100" cy="100" r="6" fill="#ece6d9"/><text x="100" y="118" text-anchor="middle" font-family="Courier Prime, monospace" font-size="10" fill="#8e98a8">LUFS</text>`;
}

const mix = { t: 0, total: 60, visible: false };
new IntersectionObserver(([e]) => (mix.visible = e.isIntersecting)).observe(mixer);
onFrame((f) => {
  if (!mix.visible || calm.matches) return;
  // The playhead runs the whole film in eight seconds, then the loudness settles.
  mix.t = (mix.t + 1) % (8 * FPS + 30);
  const p = Math.min(1, mix.t / (8 * FPS));
  const lane = $("#lane-voice").getBoundingClientRect();
  const box = mixer.getBoundingClientRect();
  mixHead.style.left = `${lane.left - box.left}px`;
  mixHead.style.translate = `${Math.round(p * lane.width)}px 0`;
  drawMeter(p < 1 ? -16 + 7 * (noise(4, f) - 0.5) - 6 * (1 - p) * noise(5, f) : -16);
});

/* ---------- the show ---------- */

const screen = $("#screen");
const layers = [$("#layer-a"), $("#layer-b")];
const subs = $("#subs");
const slate = $("#slate");
const ticks = $("#ticks");
const playBtn = $("#play");
const house = $("#house");
const endCard = $("#end");
const subsLang = $("#subs-lang");
const voiceBox = $("#voice");
const behindBox = $("#behind");

const show = {
  playing: false,
  started: false,
  i: -1,
  t: 0,
  frames: 0,
  stage: null,
  front: 0,
  old: null,
  fade: 0,
  cues: [],
  spoken: true,
};

/** The silence after a shot's words: short before a cut, longer before a dissolve, longest at the end. */
const pause = (i) => (i === SHOTS.length - 1 ? 1.6 : SHOTS[i + 1].continues ? 0.4 : 1);
const shotFrames = (i) => {
  const lang = subsLang.value;
  return Math.round((seconds(SHOTS[i].narration[lang], lang) + pause(i)) * FPS);
};

function renderTicks() {
  ticks.replaceChildren(
    ...SHOTS.map((s, i) => {
      const li = el("li", { className: s.continues ? "cut" : "" });
      li.style.flex = `${shotFrames(i)} 1 0`;
      const b = el("button", { type: "button" });
      b.setAttribute("aria-label", `Go to shot ${s.n}`);
      b.append(el("i"));
      b.addEventListener("click", () => {
        if (!show.started) begin();
        enter(i, true);
      });
      li.append(b);
      return li;
    }),
  );
}

function speak(i) {
  speechSynthesis.cancel();
  show.spoken = true;
  if (!voiceBox.checked) return;
  const lang = subsLang.value;
  const u = new SpeechSynthesisUtterance(SHOTS[i].narration[lang]);
  u.lang = { en: "en-US", es: "es-ES", pt: "pt-BR" }[lang];
  const voices = speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith(lang));
  u.voice = voices.find((v) => /natural|premium|enhanced|google/i.test(v.name)) ?? voices[0] ?? null;
  u.rate = 0.92;
  show.spoken = false;
  u.onend = u.onerror = () => (show.spoken = true);
  speechSynthesis.speak(u);
}

/** Puts shot `i` on the screen: a cut inside a paragraph, a dissolve between paragraphs. */
function enter(i, jump = false) {
  const shot = SHOTS[i];
  const scene = SCENES[i]();
  const back = 1 - show.front;
  const layer = layers[back];
  if (show.old) drop(show.old.stage);
  layer.innerHTML = scene.svg;
  frameTake(layer, i);
  show.frames = shotFrames(i);
  const s = stage(layer, {
    fns: scene.fns,
    still: state.modes[i] === "still",
    hold: HOLD[i],
    camera: shot.camera === "static" ? "push_in" : shot.camera,
    dur: show.frames,
  });
  const dissolve = !jump && !shot.continues && show.stage && !calm.matches;
  show.old = dissolve ? { stage: show.stage, layer: layers[show.front], t: show.t } : null;
  if (!dissolve) {
    drop(show.stage);
    layers[show.front].classList.remove("shown");
    layers[show.front].style.opacity = "";
  }
  layer.classList.add("shown");
  layer.style.opacity = dissolve ? "0" : "";
  show.fade = dissolve ? 12 : 0;
  show.front = back;
  show.stage = s;
  show.i = i;
  show.t = 0;
  show.cues = cues(shot.narration[subsLang.value]);
  sound.mood(SHOT_MOODS[i]);
  slate.innerHTML =
    `<b>Scene ${i + 1} · ${shot.shot} · ${state.modes[i]} · ${secs(show.frames / FPS)}</b>` +
    `${shot.continues ? "Cuts from the shot before." : i ? "Dissolves from the paragraph before." : "Opens the film."} ` +
    `Cast: ${shot.cast.length ? shot.cast.map((id) => CAST.find((c) => c.id === id).name).join(", ") : "no one"}. ` +
    `<i>${shot.visual}</i>`;
  speak(i);
  paintTicks();
}

function paintTicks() {
  [...ticks.querySelectorAll("i")].forEach((bar, k) => {
    bar.style.scale = `${k < show.i ? 1 : k > show.i ? 0 : Math.min(1, show.t / show.frames)} 1`;
  });
}

function begin() {
  show.started = true;
  house.hidden = true;
  endCard.hidden = true;
  screen.classList.add("open");
  play(true);
}

function play(on) {
  show.playing = on;
  playBtn.textContent = on ? "❚❚" : "▸";
  playBtn.setAttribute("aria-label", on ? "Pause" : "Play");
  if (on && show.i < 0) setTimeout(() => show.i < 0 && enter(0), calm.matches ? 0 : 900);
  if (on) speechSynthesis.resume();
  else speechSynthesis.pause();
}

function finish() {
  play(false);
  speechSynthesis.cancel();
  subs.textContent = "";
  screen.classList.remove("open");
  endCard.hidden = false;
  drop(show.stage);
  show.stage = null;
  show.i = -1;
  show.started = false;
  sound.mood("hall");
}

onFrame(() => {
  if (!show.playing || !show.stage) return;
  show.t++;
  seek(show.stage, show.t);
  if (show.old) {
    show.old.t++;
    seek(show.old.stage, show.old.t);
    show.fade--;
    layers[show.front].style.opacity = String(1 - show.fade / 12);
    if (show.fade <= 0) {
      drop(show.old.stage);
      show.old.layer.classList.remove("shown");
      show.old.layer.style.opacity = "";
      show.old = null;
    }
  }
  const speaking = show.frames - pause(show.i) * FPS;
  const k = Math.min(show.cues.length - 1, Math.floor((show.t / Math.max(1, speaking)) * show.cues.length));
  subs.textContent = show.t < speaking || !show.spoken ? show.cues[Math.max(0, k)] : "";
  subs.lang = subsLang.value;
  // Thunder follows the lightning in the storm shots (`STRIKE` in scenes.js).
  if (
    ["storm", "inside"].includes(SHOT_MOODS[show.i]) &&
    show.t % 43 === 41 &&
    state.modes[show.i] === "video"
  )
    sound.thunder();
  paintTicks();
  if (show.t >= show.frames && show.spoken) {
    if (show.i + 1 < SHOTS.length) enter(show.i + 1);
    else finish();
  }
});

$("#play-big").addEventListener("click", begin);
$("#again").addEventListener("click", begin);
playBtn.addEventListener("click", () => (show.started ? play(!show.playing) : begin()));
subsLang.addEventListener("change", () => {
  renderTicks();
  renderTally();
  renderMix();
  if (show.i >= 0) show.cues = cues(SHOTS[show.i].narration[subsLang.value]);
});
behindBox.addEventListener("change", () => (slate.hidden = !behindBox.checked));
voiceBox.addEventListener("change", () => {
  if (!voiceBox.checked) {
    speechSynthesis.cancel();
    show.spoken = true;
  }
});
if (!("speechSynthesis" in window)) voiceBox.closest("label").hidden = true;
new IntersectionObserver(([e]) => {
  if (!e.isIntersecting && show.playing) play(false);
}).observe(screen);

/* ---------- sound ---------- */

const soundBtn = $("#sound");
soundBtn.addEventListener("click", async () => {
  const on = await sound.toggle();
  soundBtn.textContent = on ? "Sound on" : "Sound off";
  soundBtn.setAttribute("aria-pressed", String(on));
});
for (const section of document.querySelectorAll("[data-mood]")) {
  new IntersectionObserver(([e]) => e.isIntersecting && !show.playing && sound.mood(section.dataset.mood), {
    threshold: 0.4,
  }).observe(section);
}

/* ---------- the invitation ---------- */

const join = $("#join");
const status = $("#join-status");
join.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(join));
  status.className = "status";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(data.email)) {
    status.classList.add("err");
    status.textContent = "That email address looks incomplete. Check it and try again.";
    return;
  }
  status.textContent = "Sending…";
  try {
    const res = await fetch("/api/waitlist", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ...data, lang: navigator.language }),
    });
    if (!res.ok) throw new Error(String(res.status));
    status.classList.add("ok");
    status.textContent = `You're on the list. We'll write to ${data.email} when there's a seat for you.`;
    join.reset();
  } catch {
    status.classList.add("err");
    status.textContent = "That didn't reach us. Try again in a minute.";
  }
});

/* ---------- first paint ---------- */

setLang("en");
renderThumbs();
renderStrip();
renderPreview();
renderTally();
renderMix();
renderTicks();
drawMeter(-16);
