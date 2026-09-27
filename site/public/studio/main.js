/* The night crew's page. The set is built once, behind the page; each chapter the visitor scrolls to
 * sends the camera down to its floor, lights that floor's lamps and plays its ambience. Whatever can
 * be done on the set can also be done from the chapter's card, so the page works from a keyboard and a
 * screen reader, and still reads as a page where there is no WebGL at all. */

import * as THREE from "three";
import { calm, studio } from "./engine.js";
import { foley } from "./foley.js";
import { opening } from "./intro.js";
import { rig } from "./rig.js";
import { hideStars } from "./stars.js";
import { buildRooms, HOP, scriptFor, STYLES } from "./rooms.js";
import { beams, breeze, lighthouse, LAMP_Y, sea, sky, swell } from "./tower.js";
import { LANGUAGES, nextSeed, SEED } from "../story.js";

const $ = (sel, root = document) => root.querySelector(sel);
const el = (tag, props = {}) => Object.assign(document.createElement(tag), props);

/** What the visitor has chosen so far. `take` is which of the two drawings of the cast is up. */
const state = { lang: "en", style: "clay", take: 0, chapter: "lamp" };
/** The seeds the two drawings were made with: the story's, and the one a redraw gives it. */
const TAKES = [SEED, nextSeed(SEED)];

/** The wide shot of the whole lighthouse at night: the opening's last shot and the notes' backdrop. */
const NIGHT = {
  look: [10, 96, 0],
  yaw: 0.28,
  pitch: 0.06,
  dist: 560,
  fov: 30,
  span: 330,
  focus: [0, 110, 0],
};

const FLOOR_NAMES = {
  lamp: "The lamp room",
  writer: "The writer",
  voice: "The voice",
  paint: "The painter",
  motion: "The animator",
  mix: "The editor",
  cinema: "The cinema",
  jetty: "The jetty",
};

function canDraw() {
  try {
    return !!document.createElement("canvas").getContext("webgl2");
  } catch {
    return false;
  }
}

/* ---------- the set ---------- */

const flat = !canDraw();
const ctx = { state, foley };
let s = null;
let r = null;
let rooms = {};
let world = null;
let stars = null;
let allFound = false;

function build() {
  s = studio($("#set"));
  const { scene } = s;
  scene.background = new THREE.Color("#050a16");
  scene.fog = new THREE.Fog("#0b1628", 700, 2200);
  const house = lighthouse();
  const water = sea();
  const heavens = sky();
  const beam = beams();
  beam.position.y = LAMP_Y + 18;
  scene.add(house, water, heavens, beam);

  const moon = new THREE.DirectionalLight("#8fb0e0", 0.9);
  moon.position.set(-220, 320, 260);
  moon.castShadow = true;
  moon.shadow.mapSize.set(2048, 2048);
  Object.assign(moon.shadow.camera, { left: -140, right: 160, top: 240, bottom: -70, near: 10, far: 1200 });
  moon.shadow.bias = -0.0005;
  const hemi = new THREE.HemisphereLight("#2b3f66", "#140d08", 0.2);
  const key = new THREE.SpotLight("#ffe0b0", 0, 420, 0.55, 0.85, 1.4);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.bias = -0.0003;
  key.shadow.radius = 5;
  const practicals = [0, 1, 2].map(() => new THREE.PointLight("#ffc56b", 0, 50, 1.6));
  scene.add(moon, hemi, key, key.target, ...practicals);

  Object.assign(ctx, { scene, studio: s });
  rooms = buildRooms(ctx);
  stars = hideStars(ctx, found);
  r = rig(s);
  world = { house, water, heavens, beam, moon, hemi, key, practicals };
  ctx.world = world;
  ctx.rig = r;
  ctx.relight = () => relight(current);
  lamp(true);
  house.userData.front.visible = false;
}

/** Lights or darkens the great lamp at the top of the tower, and its beam. */
let lit = true;
function lamp(on) {
  lit = on;
  const top = world.house.userData.top.userData.lamp;
  top.light.intensity = on ? 700 : 0;
  top.heart.material.color.set("#ffd48a").multiplyScalar(on ? 4 : 0.15);
  world.beam.userData.mat.uniforms.strength.value = on ? 1 : 0;
}
ctx.lamp = lamp;

/** Moves the key light and the lamps to a room, and gives it its ambience. */
function relight(room) {
  if (!room) return;
  const { key, practicals } = world;
  const look = new THREE.Vector3(...room.shot.look);
  key.position.copy(look).add(new THREE.Vector3(...room.key.from));
  key.target.position.copy(look);
  key.color.set(room.key.color);
  key.intensity = room.key.power;
  key.angle = 0.55;
  key.distance = 420;
  practicals.forEach((l, i) => {
    const spec = room.lamps[i];
    l.intensity = spec ? spec.power : 0;
    if (!spec) return;
    l.position.set(...spec.at);
    l.color.set(spec.color);
    l.distance = spec.reach;
  });
  // Outside, the moon and the great lamp light the set; inside, they'd shine through the floors.
  const out = ["jetty", "lamp", "night"].includes(room.name);
  world.moon.intensity = out ? 1.1 : 0.22;
  world.house.userData.top.userData.lamp.light.intensity = out && lit ? 700 : 0;
}

/* ---------- chapters ---------- */

let current = null;
const chapters = [...document.querySelectorAll("[data-shot]")];
const floorsNav = $("#floors");

/** The notes have no floor of their own: behind them, the whole lighthouse at night. */
const night = {
  name: "night",
  shot: NIGHT,
  lamps: [],
  key: { from: [0, 0, 0], color: "#000", power: 0 },
  beds: { sea: 0.7, wind: 0.4 },
  hot: [],
};
const roomOf = (name) => (name === "night" ? night : rooms[name]);

/** Sends the camera to a chapter's floor: the farther the floor, the longer the move. */
function go(name, f = s?.frame ?? 0) {
  const section = chapters.find((c) => c.dataset.shot === name);
  state.chapter = name;
  for (const a of floorsNav.querySelectorAll("a"))
    a.setAttribute("aria-current", String(a.dataset.shot === name));
  if (!s) return;
  const room = roomOf(name);
  if (current === room) return;
  if (showing && room !== rooms.cinema) endFilm(false);
  const from = current;
  current = room;
  r.side = section?.dataset.side ?? "center";
  const dy = from
    ? Math.abs(from.shot.look[1] - room.shot.look[1]) + Math.abs(from.shot.look[0] - room.shot.look[0])
    : 0;
  r.to(room.shot, from ? Math.round(10 + Math.min(26, dy / 4)) : 0, f);
  // Outside at the jetty the tower is shut; everywhere else it is open like a doll's house.
  world.house.userData.front.visible = !!room.closed;
  relight(room);
  foley.beds(room.beds);
  room.enter?.(f);
  if (from && from.name !== room.name) foley.play("pulley", { gain: 0.25 });
}

for (const c of chapters) {
  if (c.dataset.shot === "night") continue;
  const li = el("li");
  const a = el("a", { href: `#${c.id}` });
  a.dataset.shot = c.dataset.shot;
  a.append(el("span", { textContent: FLOOR_NAMES[c.dataset.shot] }));
  a.setAttribute("aria-label", FLOOR_NAMES[c.dataset.shot]);
  li.append(a);
  floorsNav.append(li);
}

const seen = new Map();
const watcher = new IntersectionObserver(
  (entries) => {
    for (const e of entries) seen.set(e.target, e.intersectionRatio);
    let best = null;
    for (const [c, ratio] of seen) if (!best || ratio > seen.get(best)) best = c;
    if (best && seen.get(best) > 0.3 && !document.body.classList.contains("opening-on"))
      go(best.dataset.shot);
  },
  { threshold: [0, 0.3, 0.55, 0.8] },
);
for (const c of chapters) watcher.observe(c);

/* ---------- the set's frame: puppets, sea, sky, the beam ---------- */

const counter = $("#frame");
const pointer = { ndc: new THREE.Vector2(9, 9), world: new THREE.Vector3(), moved: false, hot: null };
const ray = new THREE.Raycaster();

function frame(f) {
  counter.textContent = String(f % 1e6).padStart(6, "0");
  swell(world.water, f);
  breeze(world.heavens, f);
  // The beam turns, unless it is holding a slide on the clouds.
  const hold = world.beam.userData.hold;
  if (hold) world.beam.rotation.set(0, hold[0], hold[1]);
  else if (!calm.matches) world.beam.rotation.set(0, (f / 90) * Math.PI * 2, 0);
  r.update(f);
  // Only the floor on camera and its neighbours are posed; the others hold still, unseen.
  const near = current ? current.shot.look[1] : LAMP_Y;
  for (const room of Object.values(rooms)) {
    const y = room.shot.look[1];
    if (Math.abs(y - near) < 60 || room === current) room.update(f);
  }
  aimPointer();
  wiggle(f);
  nod(f);
  stars.update(f, allFound);
  ctx.onFilm?.();
  if (spoken?.words) {
    const t = foley.time - spoken.t0;
    spoken.words.forEach(
      (w, i) => (spoken.spans[i].className = t >= w.end ? "done" : t >= w.start ? "on" : ""),
    );
  }
  ctx.onFrame?.(f);
}

/** What the pointer is over trembles a little on twos, the way a puppet does when a finger nears it. */
let trembling = null;
function wiggle(f) {
  const o = pointer.hot?.object ?? null;
  if (trembling && trembling.o !== o) {
    trembling.o.rotation.z = trembling.z;
    trembling = null;
  }
  if (!o || calm.matches) return;
  trembling ??= { o, z: o.rotation.z };
  o.rotation.z = trembling.z + (f % 2 ? 0.025 : -0.025);
}

function aimPointer() {
  if (!current || !pointer.moved) return;
  pointer.moved = false;
  ray.setFromCamera(pointer.ndc, s.camera);
  const look = new THREE.Vector3(...current.shot.look);
  const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(
    s.camera.getWorldDirection(new THREE.Vector3()).negate(),
    look.clone().add(new THREE.Vector3(0, 0, 18)),
  );
  ray.ray.intersectPlane(plane, pointer.world);
  for (const a of current.actors ?? []) a.look = pointer.world;
  const hits = ray.intersectObjects(
    current.hot.map((h) => h.object),
    true,
  );
  pointer.hot = null;
  if (hits.length) {
    let o = hits[0].object;
    while (o && !pointer.hot) {
      pointer.hot = current.hot.find((h) => h.object === o) ?? null;
      o = o.parent;
    }
  }
  $("#set").classList.toggle("hot", !!pointer.hot);
  $("#set").title = pointer.hot ? pointer.hot.label : "";
}

/* ---------- the seven stars ---------- */

const toast = $("#toast");
let toastTimer = 0;
function found(n) {
  $("#stars-n").textContent = String(n);
  toast.textContent =
    n < 7 ? `A paper star! ${7 - n} still hiding.` : "All seven stars are home. Look up at the lamp.";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toast.textContent = ""), 4000);
  if (n < 7) return;
  allFound = true;
  setTimeout(() => {
    foley.play("applause", { gain: 0.7 });
    rooms.lamp.luna.wake(true);
  }, 1200);
}

/* ---------- idling: leave the crew alone and they nod off ---------- */

const YAWN = {
  len: 20,
  keys: [
    [0, {}],
    [5, { neck: { rx: -0.35 }, armL: { rz: -2.4 }, armR: { rz: 2.4 }, hips: { sy: 0.06 } }],
    [13, { neck: { rx: -0.4 }, armL: { rz: -2.6 }, armR: { rz: 2.6 }, hips: { sy: 0.08 } }],
    [20, {}],
  ],
};
let stirred = performance.now();
let dozing = null;
function stir() {
  stirred = performance.now();
  if (!dozing) return;
  foley.loop("snore", 0, 0.3);
  dozing.asleep = false;
  dozing.play(HOP, s.frame);
  foley.play("squeak-oh", { gain: 0.6 });
  dozing = null;
}
for (const ev of ["pointermove", "keydown", "scroll", "touchstart"])
  addEventListener(ev, stir, { passive: true });
function nod(f) {
  if (dozing || calm.matches || !current?.actors?.length || performance.now() - stirred < 25000) return;
  dozing = current.actors[0];
  dozing.play(YAWN, f).then(() => {
    if (!dozing) return;
    dozing.asleep = true;
    foley.loop("snore", 0.3);
  });
  dozing.talk = 0.8;
  setTimeout(() => dozing && (dozing.talk = 0), 900);
  foley.play("squeak-yawn", { gain: 0.6 });
}

/* ---------- the chapters' controls ---------- */

// The lamp room: an idea goes up on the clouds.
const ideaForm = $("#idea-form");
const ideaInput = $("#idea");
const ideaSaid = $("#idea-said");
const joinIdea = $("#join-idea");
function lightIdea(text) {
  const idea = text.trim().replace(/\s+/g, " ");
  if (!idea) return;
  joinIdea.value = idea;
  ideaSaid.textContent = `“${idea}” is up on the clouds. In the app, the writer turns it into a whole story.`;
  rooms.lamp?.project(idea, s?.frame ?? 0);
  foley.play("lamp-whoomp", { gain: 0.5 });
}
ideaForm.addEventListener("submit", (e) => {
  e.preventDefault();
  lightIdea(ideaInput.value || ideaInput.placeholder);
});
for (const chip of document.querySelectorAll(".chip")) {
  chip.addEventListener("click", () => {
    ideaInput.value = chip.textContent;
    lightIdea(chip.textContent);
  });
}

// The writer: a language, and the page typed out in it.
const langs = $("#langs");
const script = $("#script");
let typer = 0;
function showScript(lang) {
  const page = scriptFor(lang);
  script.lang = lang;
  script.innerHTML = "";
  const h = el("h3", { textContent: page.title });
  const meta = el("p", { textContent: page.meta });
  const tag = el("p", { className: "tag", textContent: page.tag });
  const text = el("p");
  const pic = el("p", { className: "pic", lang: "en", textContent: `Picture: ${page.picture}` });
  script.append(h, meta, tag, text, pic);
  clearInterval(typer);
  if (calm.matches) {
    text.textContent = page.text;
    return;
  }
  let n = 0;
  const step = ["zh", "ja", "ko"].includes(lang) ? 1 : 3;
  typer = setInterval(() => {
    n = Math.min(page.text.length, n + step);
    text.replaceChildren(
      page.text.slice(0, n),
      ...(n < page.text.length ? [el("span", { className: "caret" })] : []),
    );
    if (n >= page.text.length) clearInterval(typer);
  }, 1000 / 12);
}
function setLang(code, type = true) {
  state.lang = code;
  for (const b of langs.children) b.setAttribute("aria-pressed", String(b.dataset.lang === code));
  showScript(code);
  if (type) rooms.writer?.type(code);
}
for (const [code, name] of Object.entries(LANGUAGES)) {
  const b = el("button", { type: "button", textContent: name, lang: code });
  b.dataset.lang = code;
  b.addEventListener("click", () => setLang(code));
  langs.append(b);
}

// The voice: a record per language, and the line lit word by word as it's read.
const recordsEl = $("#records");
const lineEl = $("#line");
let spoken = null;
async function playRecord(code) {
  if (!foley.on) await turnSound(true);
  spoken?.src?.stop();
  for (const b of recordsEl.children) b.setAttribute("aria-pressed", String(b.dataset.lang === code));
  const f = s?.frame ?? 0;
  rooms.voice?.play(code, f);
  foley.play("needle", { gain: 0.5 });
  const words = await fetch(`audio/line-${code}.json`)
    .then((res) => (res.ok ? res.json() : null))
    .catch(() => null);
  const text = scriptFor(code).text;
  lineEl.lang = code;
  const spans = (words ?? [{ text, start: 0, end: 0 }]).map((w) => el("span", { textContent: w.text }));
  lineEl.replaceChildren(...spans.flatMap((sp, i) => (i && !["zh", "ja"].includes(code) ? [" ", sp] : [sp])));
  const src = await foley.say(`line-${code}`, { gain: 1 });
  const t0 = foley.time;
  spoken = { code, src, words, spans, t0 };
  if (src) src.addEventListener("ended", () => spoken?.src === src && stopRecord());
}
function stopRecord() {
  spoken = null;
  rooms.voice?.play(null, s?.frame ?? 0);
  for (const b of recordsEl.children) b.setAttribute("aria-pressed", "false");
  for (const sp of lineEl.children) sp.className = "done";
}
ctx.onRecord = playRecord;
Object.keys(LANGUAGES).forEach((code) => {
  const b = el("button", { type: "button", textContent: LANGUAGES[code], lang: code });
  b.dataset.lang = code;
  b.setAttribute("aria-pressed", "false");
  b.addEventListener("click", () =>
    spoken?.code === code ? (spoken.src?.stop(), stopRecord()) : playRecord(code),
  );
  recordsEl.append(b);
});

// The painter: a style, a picture painted in it, and another drawing of it.
const stylesEl = $("#styles");
function setStyle(style) {
  state.style = style;
  for (const b of stylesEl.children) b.setAttribute("aria-pressed", String(b.dataset.style === style));
  rooms.paint?.paint(style, state.take, s?.frame ?? 0);
  $("#paint-aside").textContent =
    `In the app, Dab is an image model. This cast sheet was drawn by one, in ` +
    `${STYLES.find((x) => x[0] === style)[1].toLowerCase()}, with seed ${TAKES[state.take].toLocaleString("en")}.`;
}
ctx.onStyle = setStyle;
for (const [key, name] of STYLES) {
  const b = el("button", { type: "button", textContent: name });
  b.dataset.style = key;
  b.setAttribute("aria-pressed", String(key === state.style));
  b.addEventListener("click", () => setStyle(key));
  stylesEl.append(b);
}
$("#redraw").addEventListener("click", () => {
  state.take = 1 - state.take;
  foley.play("whoosh", { gain: 0.6 });
  setStyle(state.style);
});

// The animator: the shutter.
const framesEl = $("#frames");
function shutter() {
  const n = rooms.motion?.shoot(s?.frame ?? 0) ?? 0;
  framesEl.textContent = n < 12 ? `${n} of 12 frames` : "12 of 12: that's one second. Watch it play.";
  if (n >= 12) $("#shutter").textContent = "Start again";
}
ctx.onShutter = shutter;
ctx.onShot = () =>
  (framesEl.textContent = "One second of film, twelve frames. A film of a minute takes 720.");
$("#shutter").addEventListener("click", () => {
  if ((rooms.motion?.frames ?? 0) >= 12) {
    rooms.motion?.reset();
    $("#shutter").textContent = "Take a frame";
    framesEl.textContent = "0 of 12 frames";
    return;
  }
  shutter();
});
addEventListener("keydown", (e) => {
  if (e.code === "Space" && state.chapter === "motion" && e.target === document.body) {
    e.preventDefault();
    shutter();
  }
});

// The editor: the mix plays, the faders move, the needle swings.
const mixBtn = $("#mix-play");
const faderVoice = $("#fader-voice");
const faderSea = $("#fader-sea");
let mixing = null;
async function toggleMix() {
  if (mixing) {
    mixing.src?.stop();
    return;
  }
  if (!foley.on) await turnSound(true);
  mixBtn.setAttribute("aria-pressed", "true");
  mixBtn.textContent = "Stop the mix";
  if (rooms.mix) rooms.mix.playing = true;
  foley.loop("sea", Number(faderSea.value) / 100);
  const src = await foley.say("line-en-7", { gain: Number(faderVoice.value) / 100 });
  mixing = { src };
  const end = () => {
    mixing = null;
    if (rooms.mix) rooms.mix.playing = false;
    foley.loop("sea", current?.beds.sea ?? 0);
    mixBtn.setAttribute("aria-pressed", "false");
    mixBtn.textContent = "Play the mix";
  };
  if (src) src.addEventListener("ended", end);
  else end();
}
ctx.onMix = toggleMix;
mixBtn.addEventListener("click", toggleMix);
for (const fader of [faderVoice, faderSea]) {
  fader.addEventListener("input", () => {
    rooms.mix?.faders(Number(faderVoice.value) / 100, Number(faderSea.value) / 100);
    if (mixing) foley.loop("sea", Number(faderSea.value) / 100, 0.2);
    foley.play("fader", { gain: 0.25, vary: 0.3 });
  });
}

// The show: Luna's film, as Lanternist made it, on the cinema's screen.
const film = $("#film");
const filmSubs = $("#film-subs");
const playBtn = $("#play");
const filmLang = $("#film-lang");
const subsOn = $("#subs-on");
// The films are too heavy for git: they live in the site's R2 bucket (site/README.md).
const FILMS = "https://assets.lanternist.dev/studio/film/";
const srt = new Map();
let showing = null;

/** The film's subtitles for a language, from the SRT the app wrote beside it. */
function subtitles(lang) {
  if (!srt.has(lang)) {
    const time = (t) => t.split(/[:,]/).reduce((a, v, i) => a + Number(v) * [3600, 60, 1, 0.001][i], 0);
    srt.set(
      lang,
      fetch(`film/luna-${lang}.srt`)
        .then((res) => (res.ok ? res.text() : ""))
        .then((text) =>
          text
            .trim()
            .split(/\r?\n\r?\n/)
            .map((block) => block.split(/\r?\n/))
            .filter((lines) => lines.length >= 3)
            .map(([, span, ...words]) => {
              const [a, b] = span.split(" --> ");
              return { start: time(a), end: time(b), text: words.join(" ") };
            }),
        )
        .catch(() => []),
    );
  }
  return srt.get(lang);
}

async function playFilm() {
  if (showing) return endFilm(false);
  const lang = filmLang.value;
  film.src = `${FILMS}luna-${lang}.mp4`;
  film.lang = lang;
  // Without the set there is no cinema to play it in: the browser's own player takes the whole screen.
  if (!s) {
    film.controls = true;
    await film.requestFullscreen?.().catch(() => {});
    return film.play().catch(() => {});
  }
  try {
    await film.play();
  } catch {
    $("#film-note").textContent = "The film couldn't start here. Try again, or press Full screen.";
    return;
  }
  showing = { lang, cues: await subtitles(lang) };
  document.body.classList.add("screening");
  rooms.cinema.show(film);
  r.to(rooms.cinema.close, 22, s.frame);
  foley.music(null);
  foley.beds(rooms.cinema.beds);
  playBtn.textContent = "Stop the film";
}

function endFilm(finished) {
  film.pause();
  showing = null;
  filmSubs.textContent = "";
  document.body.classList.remove("screening");
  rooms.cinema.show(null);
  if (current === rooms.cinema) r.to(rooms.cinema.shot, 16, s.frame);
  foley.beds(current?.beds ?? {});
  if (foley.on) foley.music("theme", 0.22, { loop: true, fade: 4 });
  if (finished) rooms.cinema.applaud(s.frame);
  playBtn.textContent = "Play the film";
}
ctx.onPlay = playFilm;
playBtn.addEventListener("click", playFilm);
film.addEventListener("ended", () => showing && endFilm(true));
filmLang.addEventListener("change", () => showing && (endFilm(false), playFilm()));
$("#full").addEventListener("click", async () => {
  if (!showing) await playFilm();
  film.controls = true;
  await film.requestFullscreen?.().catch(() => {});
});
document.addEventListener("fullscreenchange", () => (film.controls = !!document.fullscreenElement));
ctx.onFilm = () => {
  if (!showing) return;
  const t = film.currentTime;
  const cue = showing.cues.find((c) => t >= c.start && t < c.end);
  filmSubs.lang = showing.lang;
  filmSubs.textContent = subsOn.checked && !document.fullscreenElement ? (cue?.text ?? "") : "";
};

// The jetty: the invitation, posted.
const join = $("#join");
const status = $("#join-status");
ctx.onPost = () => $("#join-email").focus();
join.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(join));
  status.className = "status";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(data.email)) {
    status.classList.add("err");
    status.textContent = "That email address looks incomplete. Check it and try again.";
    return;
  }
  status.textContent = "Posting…";
  try {
    const res = await fetch("/api/waitlist", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ...data, lang: navigator.language }),
    });
    if (!res.ok) throw new Error(String(res.status));
    status.classList.add("ok");
    status.textContent = `Posted. We'll write to ${data.email} when there's a seat for you.`;
    rooms.jetty?.post(s?.frame ?? 0);
    join.reset();
  } catch {
    status.classList.add("err");
    status.textContent = "That didn't reach us. Try again in a minute.";
  }
});

/* ---------- sound ---------- */

const soundBtn = $("#sound");
async function turnSound(on) {
  const got = await foley.set(on);
  soundBtn.textContent = got ? "Sound on" : "Sound off";
  soundBtn.setAttribute("aria-pressed", String(got));
  if (got && current) foley.beds(current.beds, 0.4);
  if (got && !document.body.classList.contains("opening-on"))
    foley.music("theme", 0.22, { loop: true, fade: 4 });
  return got;
}
ctx.turnSound = turnSound;
soundBtn.addEventListener("click", () => turnSound(!foley.on));

/* ---------- pointing at the set ---------- */

addEventListener("pointermove", (e) => {
  pointer.ndc.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
  pointer.moved = true;
});
$("#set").addEventListener("click", () => {
  if (!pointer.hot || !s) return;
  pointer.hot.act(s.frame);
  if (!foley.on) return;
  foley.play(`squish-${1 + Math.floor(Math.random() * 3)}`, { gain: 0.25 });
});

/* ---------- start ---------- */

if (flat) {
  document.body.classList.add("flat");
  $("#opening").hidden = true;
  setLang("en", false);
} else {
  build();
  s.acts.add(frame);
  r.cut(NIGHT);
  relight(roomOf("night"));
  setLang("en", false);
  opening(ctx, {
    reveal() {
      document.body.classList.remove("opening-on");
      setTimeout(() => foley.music("theme", 0.22, { loop: true, fade: 4 }), 2500);
      current = null;
      const top = chapters.find((c) => c.getBoundingClientRect().bottom > innerHeight * 0.4);
      go(top?.dataset.shot ?? "lamp");
    },
  });
}
