/* Brick by brick: the page. The box at the top rebuilds itself around the idea a visitor snaps
 * together from word bricks. Below it, five bags build "The Little Red Brick" a step at a time, the
 * way Lanternist builds a film: the story, the voice, the pictures, the motion, and the film itself.
 * Every picture here is drawn in bricks (models.js), the film's shots by film.js. Whatever can be
 * done by tapping a canvas can also be done with the buttons beside it. */

import { COLORS, PLATE, Stage, calm, join, model, noise, onTick, whileSeen } from "./brick.js";
import { BRICK, HEROES, PICKLE_ASLEEP, PLACES, ROCKET, WISHES, face, ground } from "./models.js";
import { Film, picture } from "./film.js";
import { CAST, FIRST_LINE, PARAGRAPHS, PLACE, SHOTS, TITLE, seconds } from "./tale.js";
import { LANGUAGES } from "../story.js";
import { sound } from "./sound.js";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const el = (tag, props = {}, ...kids) => {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...kids);
  return node;
};
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

/** Remembered in this browser only: which lost bricks were found. Storage can be off; then nothing is. */
const store = {
  get(key) {
    try {
      return JSON.parse(localStorage.getItem(`lanternist-bricks-${key}`));
    } catch {
      return null;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(`lanternist-bricks-${key}`, JSON.stringify(value));
    } catch {
      // A private window may refuse; the page works the same without it.
    }
  },
};

let toastTimer = 0;
function toast(text) {
  const t = $("#toast");
  t.textContent = text;
  t.classList.add("on");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("on"), 3400);
}

/** A model painted small, for a button or a label. */
function icon(m, { w = 96, h = 80, prints = null } = {}) {
  const c = el("canvas", { width: w, height: h });
  const s = new Stage(c, {
    fixed: true,
    view: Math.max(m.w, (m.h * PLATE * w) / h) * 1.12,
    x: m.w / 2,
    y: m.h / 2,
  });
  s.put(m, 0, 0, { prints });
  return c.toDataURL();
}

/* ---------- sound ---------- */

const soundButton = $("#sound");
soundButton.addEventListener("click", () => {
  sound.set(!sound.on);
  soundButton.setAttribute("aria-pressed", String(sound.on));
  $("#sound-label").textContent = sound.on ? "Sound on" : "Sound off";
  sound.play("snap");
});
// Every brick on the page clicks when it's pressed.
addEventListener("pointerdown", (e) => e.target.closest(".brick") && sound.play("click"));

/* ---------- the box ---------- */

/** The word bricks: the short label on the brick, and the words it puts in the idea. */
const WORDS = {
  hero: {
    dragon: ["Dragon", "a little dragon"],
    dinosaur: ["Dinosaur", "a dinosaur"],
    bunny: ["Bunny", "a brave bunny"],
    robot: ["Robot", "a tiny robot"],
    penguin: ["Penguin", "a penguin"],
    shark: ["Shark", "a shark"],
  },
  place: {
    castle: ["Castle", "in a castle"],
    sea: ["Under the sea", "under the sea"],
    moon: ["The moon", "on the moon"],
    jungle: ["Jungle", "in the jungle"],
    snow: ["Snow", "in the snow"],
  },
  wish: {
    fly: ["Wants to fly", "who wants to fly"],
    sneeze: ["Can't stop sneezing", "who can't stop sneezing"],
    birthday: ["Birthday!", "who is having a birthday"],
    treasure: ["Treasure map", "who finds a treasure map"],
    dance: ["Loves to dance", "who loves to dance"],
    friend: ["New friend", "who makes a new friend"],
  },
};

/**
 * Words in a typed idea that pick a brick, in English, Spanish and Portuguese. A word matches whole
 * (or with an s), so "baking" doesn't call up a king; a stem ending in * matches any ending.
 */
const KEYS = {
  dragon: ["dragon", "dragón", "dragão"],
  dinosaur: ["dinosaur", "dino", "rex", "dinosaurio", "dinossauro"],
  bunny: ["bunny", "bunnies", "rabbit", "hare", "conejo", "coelho"],
  robot: ["robot", "robô"],
  penguin: ["penguin", "pingüino", "pinguim"],
  shark: ["shark", "tiburón", "tubarão"],
  castle: ["castle", "king", "queen", "princess", "prince", "knight", "castillo", "castelo", "princesa"],
  sea: ["sea", "ocean", "underwater", "fish", "mar", "océano", "oceano", "peixe", "pez"],
  moon: ["moon", "space", "star", "planet", "rocket", "luna", "espacio", "lua", "espaço", "estrela"],
  jungle: ["jungle", "forest", "tree", "monkey", "selva", "bosque", "floresta", "macaco", "mono"],
  snow: ["snow", "ice", "winter", "cold", "nieve", "hielo", "neve", "gelo", "inverno", "invierno"],
  fly: ["fly", "flies", "flying", "sky", "balloon", "wing", "volar", "voar", "globo", "balão"],
  sneeze: ["sneez*", "achoo", "cold", "estornud*", "espirr*"],
  birthday: ["birthday", "cake", "party", "cumpleaños", "pastel", "tarta", "aniversário", "bolo", "festa"],
  treasure: ["treasure", "map", "pirate", "tesoro", "mapa", "tesouro", "pirata"],
  dance: ["danc*", "music", "sing", "singing", "song", "bail*", "danç*", "música", "cant*"],
  friend: ["friend*", "amig*"],
};
const MATCH = Object.fromEntries(
  Object.entries(KEYS).map(([key, words]) => {
    const any = words.map((w) => (w.endsWith("*") ? `${w.slice(0, -1)}\\p{L}*` : `${w}(?:e?s)?`));
    return [key, new RegExp(`(?<!\\p{L})(?:${any.join("|")})(?!\\p{L})`, "iu")];
  }),
);

const pick = { hero: "dragon", place: "castle", wish: "fly" };
let typed = "";
const idea = () =>
  typed || `${cap(WORDS.hero[pick.hero][1])} ${WORDS.place[pick.place][1]} ${WORDS.wish[pick.wish][1]}`;

/** A model going together a few pieces a frame, each dropping into place over two frames. */
class Build {
  constructor(m, { rate = 5, delay = 0 } = {}) {
    Object.assign(this, { m, rate, f: -delay });
  }
  get done() {
    return calm.matches || this.f > this.m.pieces.length / this.rate + 2;
  }
  /** How many pieces have landed by frame `f`. */
  landed(f) {
    return Math.max(0, Math.min(this.m.pieces.length, Math.floor((f - 2) * this.rate) + 1));
  }
  /** Moves on a frame; says how many pieces landed on it. */
  tick() {
    if (this.done) return 0;
    this.f++;
    return this.landed(this.f) - this.landed(this.f - 1);
  }
  draw(s, x, y, opts = {}) {
    if (this.done) return s.put(this.m, x, y, opts);
    if (this.f <= 0) return;
    s.build(this.m, x, y, {
      n: Math.min(this.m.pieces.length, Math.ceil(this.f * this.rate)),
      lift: (i) => Math.max(0, 2 - (this.f - i / this.rate)) * 7,
      prints: false,
    });
  }
}

/** What's in the box's picture, and each part's build. */
const scene = { builds: {}, t: 0 };

const placed = {};
/** A place's back models joined into one, and its ground; made once for each place. */
function placeModels(key) {
  const place = PLACES[key];
  // The back models are shifted right so the joined model starts at its own corner.
  return (placed[key] ??= {
    back: join(place.back.map(([m, x, y]) => [m, x + 4, y])),
    ground: ground(place.ground),
  });
}

function layout() {
  const hero = HEROES[pick.hero];
  const wish = WISHES[pick.wish];
  const beside = ["birthday", "treasure", "friend"].includes(pick.wish);
  const width = hero.m.w + (beside ? wish.m.w + 2 : 0);
  const hx = Math.round(20 - width / 2);
  return { hero, wish, beside, hx, wx: hx + hero.m.w + 2 };
}

/** Starts building one part of the box (or all of it, the first time). */
function rebuild(part) {
  const b = scene.builds;
  const models = placeModels(pick.place);
  if (part === "place" || part === "all") {
    b.ground = new Build(models.ground, { rate: 12 });
    b.back = new Build(models.back, { rate: 9, delay: part === "all" ? 4 : 1 });
  }
  if (part === "hero" || part === "all")
    b.hero = new Build(HEROES[pick.hero].m, { rate: 5, delay: part === "all" ? 18 : 0 });
  if (part === "wish" || part === "all" || part === "hero")
    b.wish = new Build(WISHES[pick.wish].m, {
      rate: 4,
      delay: part === "all" ? 34 : part === "hero" ? 10 : 0,
    });
  const pieces = [models.back, models.ground, HEROES[pick.hero].m, WISHES[pick.wish].m].reduce(
    (n, m) => n + m.pieces.length,
    0,
  );
  $("#set-pieces").textContent = pieces;
}

/** Draws the box's picture at frame `t`; with `done`, the finished model with nothing building. */
function drawBox(s, t, { done = false } = {}) {
  const place = PLACES[pick.place];
  const b = scene.builds;
  const still = calm.matches;
  s.wash([
    [0, place.sky[0]],
    [1, place.sky[1]],
  ]);
  if (place.fx === "stars")
    s.print(
      Array.from({ length: 16 }, (_, i) => ({
        k: "star",
        x: noise(i, 1) * 40,
        y: 30 + noise(i, 2) * 40,
        r: 0.35 + noise(i, 3) * 0.35,
        c: "white",
        a: still ? 0.8 : 0.35 + 0.65 * noise(i, Math.floor(t / 4)),
      })),
      0,
      0,
    );
  const models = placeModels(pick.place);
  if (done) s.put(models.back, -4, 0);
  else b.back.draw(s, -4, 0);
  // What's further back sits in a little haze.
  s.rect(-10, 0, 60, 90, "rgba(255,255,255,.12)");
  if (done) s.put(models.ground, -4, -models.ground.h);
  else b.ground.draw(s, -4, -models.ground.h);

  const { hero, wish, beside, hx, wx } = layout();
  const heroDone = done || b.hero.done;
  const floats = pick.wish === "fly";
  let hy = 0;
  let rot = 0;
  let sy = 1;
  if (heroDone && !still) {
    if (floats) hy = 7 + (Math.floor(t / 8) % 2) * 2;
    else if (pick.wish === "dance") {
      hy = [0, 3, 4, 3][Math.floor(t / 3) % 4];
      rot = Math.floor(t / 6) % 2 ? 0.07 : -0.07;
    } else hy = Math.floor(t / 10) % 2;
    if (pick.wish === "sneeze" && t % 44 >= 30 && t % 44 < 36) sy = 0.9;
  } else if (heroDone && floats) hy = 8;
  s.shadow(hx, 0, hero.m.w, floats ? 0.14 : 0.28);
  if (heroDone) s.put(hero.m, hx, hy, { rot, sy });
  else b.hero.draw(s, hx, 0);

  const wishDone = done || b.wish.done;
  if (wishDone || b.wish.f > 0) {
    const [handX, handY] = [hx + hero.hand[0], hy + hero.hand[1] / PLATE];
    const [noseX, noseY] = [hx + hero.nose[0], hy + hero.nose[1] / PLATE];
    const put = (m, x, y, opts) => (wishDone ? s.put(m, x, y, opts) : b.wish.draw(s, x, y));
    if (pick.wish === "fly") put(wish.m, handX - 4.6, handY);
    else if (beside) {
      s.shadow(wx, 0, wish.m.w, 0.25);
      put(wish.m, wx, 0, pick.wish === "friend" && !still ? { sy: t % 12 < 6 ? 1 : 1.02 } : {});
      if (pick.wish === "birthday" && wishDone)
        for (const [fx, fy] of wish.lights)
          s.glow(wx + fx, fy / PLATE, 2.2, "flame", still ? 0.5 : 0.35 + 0.3 * noise(fx, t));
    } else if (pick.wish === "dance") {
      const drift = still ? 0 : (t % 36) / 36;
      put(wish.m, hx + hero.m.w - 2 + drift * 3, 26 + drift * 14, { alpha: 1 - drift * 0.6 });
    } else if (pick.wish === "sneeze" && wishDone) {
      const phase = t % 44;
      if (still || phase >= 34) {
        const f = still ? 0.4 : (phase - 34) / 10;
        s.put(wish.m, noseX + f * 5, noseY - 5 + f * 3, {
          alpha: 1 - f * 0.8,
          sx: 0.6 + f * 0.6,
          sy: 0.6 + f * 0.6,
        });
        s.print(
          [{ k: "text", x: noseX + 5, y: noseY + 14, s: 2.2, t: "ACHOO!", c: "red", a: 1 - f * 0.5 }],
          0,
          0,
        );
      }
    }
  }

  if (!still && place.fx === "bubbles")
    s.print(
      Array.from({ length: 9 }, (_, i) => ({
        k: "ring",
        x: (i * 4.7 + 2) % 40,
        y: (t * 0.8 + i * 11) % 75,
        r: 0.35 + noise(i, 5) * 0.4,
        c: "sky",
        rim: "white",
        a: 0.5,
      })),
      0,
      0,
    );
  if (!still && place.fx === "snow")
    s.print(
      Array.from({ length: 26 }, (_, i) => ({
        k: "dot",
        x: (i * 1.6 + Math.sin((t + i * 7) / 9) * 1.2 + 40) % 40,
        y: 70 - ((t * 0.7 + i * 9) % 80),
        r: 0.22 + noise(i, 6) * 0.2,
        c: "white",
      })),
      0,
      0,
    );
}

/** One word brick in a tray: a radio button dressed as a brick with a little model on it. */
function wordBrick(part, key, [label]) {
  const input = el("input", { type: "radio", name: part, value: key, checked: pick[part] === key });
  const m =
    part === "hero" ? HEROES[key].m : part === "wish" ? WISHES[key].m : PLACES[key].back[PLACES[key].icon][0];
  input.addEventListener("change", () => choose(part, key));
  return el(
    "label",
    { className: "word" },
    input,
    el("span", { className: "brick" }, el("img", { src: icon(m, { w: 72, h: 64 }), alt: "" }), label),
  );
}

function choose(part, key) {
  pick[part] = key;
  typed = "";
  rebuild(part);
  showIdea();
}

function showIdea() {
  $("#set-title").textContent = idea();
  $("#turn-idea").textContent = idea();
  $("#join-idea").value = idea();
}

for (const tray of $$(".tray")) {
  const part = tray.dataset.part;
  $(".words", tray).append(...Object.entries(WORDS[part]).map(([key, words]) => wordBrick(part, key, words)));
}

$("#shuffle").addEventListener("click", () => {
  const any = (o) => {
    const keys = Object.keys(o);
    return keys[Math.floor(Math.random() * keys.length)];
  };
  for (const part of ["hero", "place", "wish"]) {
    pick[part] = any(WORDS[part]);
    $(`input[name="${part}"][value="${pick[part]}"]`).checked = true;
  }
  typed = "";
  rebuild("all");
  showIdea();
  sound.play("rattle");
});

$("#type-own").addEventListener("click", (e) => {
  const form = $("#own");
  form.hidden = !form.hidden;
  e.currentTarget.setAttribute("aria-expanded", String(!form.hidden));
  if (!form.hidden) $("#own-idea").focus();
});

$("#own").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("#own-idea").value.trim();
  if (!text) return;
  // The idea keeps its own words; any brick it names is picked, so the picture follows along.
  for (const part of ["hero", "place", "wish"]) {
    const hit = Object.keys(WORDS[part]).find((key) => MATCH[key].test(text));
    if (hit && hit !== pick[part]) {
      pick[part] = hit;
      $(`input[name="${part}"][value="${hit}"]`).checked = true;
      rebuild(part);
    }
  }
  typed = cap(text);
  showIdea();
  sound.play("pop");
});

const box = new Stage($("#box-art"), { view: 40, x: 20, y: 28 });
box.onfit = () => drawBox(box, scene.t);
rebuild("all");
showIdea();
drawBox(box, 0);
whileSeen($("#box-art"), () => {
  scene.t++;
  let landed = 0;
  for (const b of Object.values(scene.builds)) landed += b.tick();
  if (landed) sound.play("click");
  drawBox(box, scene.t);
});

/* ---------- everything below the box, built once the box is up ---------- */

requestAnimationFrame(() => setTimeout(below, 30));

function below() {
  const thumbs = SHOTS.map((_, i) =>
    picture(el("canvas", { width: 480, height: 270 }), i).toDataURL("image/jpeg", 0.86),
  );
  const castIcons = {
    brick: icon(join([[BRICK, 0, 0]], face("happy", [0.2, 0])), { w: 90, h: 60 }),
    pickle: icon(PICKLE_ASLEEP, { w: 120, h: 60 }),
    rocket: icon(ROCKET, { w: 60, h: 80 }),
  };
  bags();
  booklet(thumbs, castIcons);
  voice(thumbs);
  pictures(thumbs, castIcons);
  const film = theFilm(thumbs);
  motion(thumbs, film);
  backOfTheBox();
  lostBricks();
  fitStuds();
  document.fonts.ready.then(fitStuds);
  let fitting = 0;
  addEventListener("resize", () => {
    cancelAnimationFrame(fitting);
    fitting = requestAnimationFrame(fitStuds);
  });
}

/** Bricks come in whole studs: widen each brick button to a whole number of them. */
function fitStuds() {
  for (const b of $$(".brick")) {
    b.style.width = "";
    const pitch = parseFloat(getComputedStyle(b).getPropertyValue("--pitch")) || 22;
    const w = b.getBoundingClientRect().width;
    if (w) b.style.width = `${Math.ceil(w / pitch - 0.02) * pitch}px`;
  }
}

/* ---------- the bags ---------- */

function bagArt(n) {
  const teeth = Array.from({ length: 11 }, (_, i) => `l4 ${i % 2 ? -4 : 4}`).join("");
  const spill = [
    ["#e0261d", -34, -28, -30],
    ["#ffc40c", 30, -44, 20],
    ["#1b5fd0", 46, 4, 40],
  ]
    .map(
      ([c, x, y, r]) =>
        `<g class="spill" style="--to: translate(${x}px, ${y}px) rotate(${r}deg)"><rect x="38" y="34" width="24" height="12" rx="2" fill="${c}"/><rect x="41" y="31" width="6" height="3" rx="1" fill="${c}"/><rect x="53" y="31" width="6" height="3" rx="1" fill="${c}"/></g>`,
    )
    .join("");
  return `<svg viewBox="0 0 100 124">${spill}
    <path d="M10 18h80l-3 92q-.5 8-8.5 8h-57q-8 0-8.5-8z" fill="#f1f7fd" fill-opacity=".94" stroke="#b7cde2" stroke-width="2"/>
    <rect x="21" y="80" width="22" height="12" rx="2" fill="#e0261d" opacity=".5"/>
    <rect x="50" y="88" width="26" height="12" rx="2" fill="#1b5fd0" opacity=".45"/>
    <rect x="33" y="98" width="16" height="10" rx="2" fill="#ffc40c" opacity=".6"/>
    <path d="M20 28q-3 36 1 78" stroke="#fff" stroke-width="5" stroke-linecap="round" fill="none"/>
    <circle cx="50" cy="55" r="19" fill="#fff" stroke="#1d2233" stroke-width="3"/>
    <text x="50" y="64" text-anchor="middle" font-family="Fredoka, sans-serif" font-weight="700" font-size="26" fill="#1d2233">${n}</text>
    <path class="seal" d="M6 6h88v11${teeth}v-11z" fill="#d7e7f5" stroke="#b7cde2" stroke-width="2" stroke-linejoin="round"/>
  </svg>`;
}

function bags() {
  for (const art of $$(".bag-art")) art.innerHTML = bagArt(art.dataset.n);
  for (const [i, span] of $$(".bag-links span").entries()) span.innerHTML = bagArt(i + 1);
  const seen = new IntersectionObserver(
    (entries) => {
      for (const e of entries)
        if (e.isIntersecting) {
          e.target.classList.add("open");
          seen.unobserve(e.target);
          sound.play("pop");
        }
    },
    { threshold: 0.25 },
  );
  $$(".bag").forEach((b) => seen.observe(b));
  const mix = $("#mix");
  new IntersectionObserver(([e]) => e.isIntersecting && mix.classList.add("on"), { threshold: 0.6 }).observe(
    mix,
  );
}

/** Language buttons for `langs`, calling `onPick(code)`; the first is pressed. */
function tabs(root, langs, onPick) {
  const buttons = langs.map((code, i) => {
    const b = el("button", { type: "button", textContent: LANGUAGES[code], lang: code });
    b.setAttribute("aria-pressed", String(i === 0));
    b.addEventListener("click", () => {
      buttons.forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      onPick(code);
    });
    return b;
  });
  root.append(...buttons);
}

const STORY_LANGS = ["en", "es", "pt"];

/* ---------- bag 1: the story, as a building booklet ---------- */

/** A cast member's name as a building booklet would list the part: "little red brick". */
const partName = (id) => CAST.find((c) => c.id === id).name.replace(/^the /, "");

function booklet(thumbs, castIcons) {
  const pages = $("#pages");
  const names = CAST.map((c) => c.name);
  pages.before(
    el("p", {
      className: "booklet-cast",
      textContent: `In ${PLACE.name}, with ${names.slice(0, -1).join(", ")} and ${names.at(-1)}.`,
    }),
  );
  let lang = "en";
  const says = [];
  PARAGRAPHS.forEach((shots, p) => {
    const page = el("div", { className: "page", ariaLabel: `Page ${p + 1}: paragraph ${p + 1}` });
    for (const shot of shots) {
      const say = el("p", { className: "say" });
      says.push([say, shot]);
      page.append(
        el(
          "article",
          { className: "step" },
          el(
            "div",
            { className: "step-top" },
            el("span", { className: "step-n", textContent: shot.n }),
            el(
              "ul",
              { className: "parts", ariaLabel: "Who is in this picture" },
              ...shot.cast.map((id) =>
                el("li", {}, el("img", { src: castIcons[id], alt: "" }), `1× ${partName(id)}`),
              ),
            ),
          ),
          el("img", { className: "step-pic", src: thumbs[shot.n - 1], alt: shot.visual, loading: "lazy" }),
          say,
          el(
            "p",
            { className: "prompt" },
            el("b", {
              textContent: `${cap(shot.shot)} shot · ${shot.mode === "video" ? "moving" : "still"}. `,
            }),
            shot.visual,
          ),
        ),
      );
    }
    pages.append(page);
  });
  const show = () => {
    for (const [say, shot] of says) {
      say.textContent = shot.narration[lang];
      say.lang = lang;
    }
  };
  tabs($("#story-langs"), STORY_LANGS, (code) => {
    lang = code;
    show();
  });
  show();
  const count = PARAGRAPHS.length;
  const at = () => Math.round(pages.scrollLeft / pages.clientWidth);
  const label = () => {
    const i = at();
    $("#booklet-page").textContent = `Page ${i + 1} of ${count}`;
    $("#page-prev").disabled = i === 0;
    $("#page-next").disabled = i === count - 1;
  };
  const go = (d) => {
    pages.scrollTo({ left: (at() + d) * pages.clientWidth, behavior: calm.matches ? "auto" : "smooth" });
    sound.play("tap");
  };
  $("#page-prev").addEventListener("click", () => go(-1));
  $("#page-next").addEventListener("click", () => go(1));
  pages.addEventListener("scroll", () => requestAnimationFrame(label), { passive: true });
  label();
}

/* ---------- reading aloud, with the browser's own voice ---------- */

const synth = window.speechSynthesis;
const BCP = {
  en: "en-US",
  es: "es-ES",
  pt: "pt-BR",
  fr: "fr-FR",
  de: "de-DE",
  it: "it-IT",
  ru: "ru-RU",
  zh: "zh-CN",
  ja: "ja-JP",
  ko: "ko-KR",
};
const voiceFor = (lang) => synth?.getVoices().find((v) => v.lang.toLowerCase().startsWith(lang));

/** Reads `text` aloud in `lang`; `onWord(i)` hears where each word starts, `onEnd` when it's done. */
function say(text, lang, { onWord, onEnd } = {}) {
  if (!synth) return false;
  synth.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = BCP[lang];
  const v = voiceFor(lang);
  if (v) u.voice = v;
  u.rate = 0.95;
  u.onboundary = (e) => e.name === "word" && onWord?.(e.charIndex);
  u.onend = u.onerror = () => onEnd?.();
  synth.speak(u);
  return true;
}

/** Writes `text` into `line` a word to a span, and returns how to light the word at a character. */
function wordsInto(line, text, lang) {
  line.lang = lang;
  const spans = [...text.matchAll(/\S+/g)].map((m) => [m.index, el("span", { textContent: m[0] })]);
  line.replaceChildren(...spans.flatMap(([, span], i) => (i ? [" ", span] : [span])));
  return (at) => {
    const hit = spans.findLast(([start]) => start <= at)?.[1];
    for (const [, span] of spans) span.classList.toggle("said", span === hit);
  };
}

/* ---------- bag 2: the voice ---------- */

function voice(thumbs) {
  const strip = $("#strip");
  const items = SHOTS.map((shot, i) => {
    const li = el("li", {}, el("img", { src: thumbs[i], alt: `Picture ${i + 1}` }), el("span"));
    strip.append(li);
    return li;
  });
  const line = $("#words-line");
  let lang = "en";
  let reading = false;
  const stretch = () => {
    let total = 0;
    items.forEach((li, i) => {
      const sec = seconds(SHOTS[i].narration[lang], lang);
      total += sec;
      li.style.setProperty("--sec", sec.toFixed(2));
      $("span", li).textContent = `${sec.toFixed(1)} s`;
    });
    $("#reel-total").textContent = `${LANGUAGES[lang]}: the film runs ${Math.round(total)} seconds.`;
  };
  const stop = () => {
    reading = false;
    synth?.cancel();
    items.forEach((li) => li.classList.remove("on"));
    $("#voice-play").setAttribute("aria-pressed", "false");
    $("#voice-play span").textContent = "Read it to me";
  };
  const readFrom = (i) => {
    if (!reading || i >= SHOTS.length) return stop();
    items.forEach((li, k) => li.classList.toggle("on", k === i));
    const text = SHOTS[i].narration[lang];
    const mark = wordsInto(line, text, lang);
    const next = () => reading && readFrom(i + 1);
    // Without a voice, the words still go by at the pace the narration would take.
    if (!say(text, lang, { onWord: mark, onEnd: next })) setTimeout(next, seconds(text, lang) * 1000);
  };
  tabs($("#voice-langs"), STORY_LANGS, (code) => {
    lang = code;
    stop();
    stretch();
    wordsInto(line, SHOTS[0].narration[lang], lang);
    sound.play("rattle");
  });
  $("#voice-play").addEventListener("click", () => {
    if (reading) return stop();
    reading = true;
    $("#voice-play").setAttribute("aria-pressed", "true");
    $("#voice-play span").textContent = "Stop";
    readFrom(0);
  });
  stretch();
  wordsInto(line, SHOTS[0].narration.en, "en");

  const hello = $("#hello-langs");
  const buttons = Object.entries(LANGUAGES).map(([code, name]) => {
    const b = el("button", { type: "button", textContent: name, lang: code });
    b.addEventListener("click", () => {
      stop();
      buttons.forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      const mark = wordsInto(line, FIRST_LINE[code], code);
      const spoke = say(FIRST_LINE[code], code, { onWord: mark });
      if (!spoke || !voiceFor(code))
        toast(`This browser has no ${name} voice. In the app, a voice model reads all ten languages.`);
    });
    return b;
  });
  hello.append(...buttons);
}

/* ---------- bag 3: the pictures, found in a jumble of studs ---------- */

function pictures(thumbs, castIcons) {
  const cast = $("#cast");
  cast.append(el("p", { className: "cast-title", textContent: "Cast sheet" }));
  for (const { id, name } of CAST)
    cast.append(
      el(
        "figure",
        {},
        el("img", { src: castIcons[id], alt: "" }),
        el("figcaption", { textContent: cap(name) }),
      ),
    );

  const SHOT = 2; // picture 3: the brick hopping past Pickle
  const cols = 64;
  const rows = 36;
  const solid = Object.values(COLORS).filter((c) => c.a === 1);
  const nearest = (r, g, b) => {
    let best = solid[0];
    let d = Infinity;
    for (const c of solid) {
      const [cr, cg, cb] = c.rgb;
      const e = 2 * (r - cr) ** 2 + 4 * (g - cg) ** 2 + 3 * (b - cb) ** 2;
      if (e < d) [best, d] = [c, e];
    }
    return best;
  };
  /** The picture as a grid of stud colours, `at` of the way through its shot. */
  const target = (at) => {
    const big = picture(el("canvas", { width: 640, height: 360 }), SHOT, { at });
    const small = el("canvas", { width: cols, height: rows });
    const g = small.getContext("2d", { willReadFrequently: true });
    // Closer in than the film's wide shot, so Pickle and the brick fill the picture.
    g.drawImage(big, 200, 60, 420, 236, 0, 0, cols, rows);
    const px = g.getImageData(0, 0, cols, rows).data;
    return Array.from({ length: cols * rows }, (_, i) => [px[i * 4], px[i * 4 + 1], px[i * 4 + 2]]);
  };
  /** The same grid seen through blocks `n` studs square: how the picture looks early on. */
  const blocks = (rgb, n) =>
    rgb.map((_, i) => {
      const x0 = Math.floor((i % cols) / n) * n;
      const y0 = Math.floor(Math.floor(i / cols) / n) * n;
      let r = 0;
      let g = 0;
      let b = 0;
      let k = 0;
      for (let y = y0; y < Math.min(rows, y0 + n); y++)
        for (let x = x0; x < Math.min(cols, x0 + n); x++) {
          const [pr, pg, pb] = rgb[y * cols + x];
          r += pr;
          g += pg;
          b += pb;
          k++;
        }
      return nearest(r / k, g / k, b / k);
    });

  const canvas = $("#mosaic");
  const g = canvas.getContext("2d");
  const studs = new Map();
  const stud = (c, size) => {
    const key = `${c.name}@${size}`;
    if (!studs.has(key)) {
      const img = el("canvas", { width: size, height: size });
      const s = img.getContext("2d");
      const r = size / 2;
      s.fillStyle = `rgb(${c.rgb.map((v) => v * 0.8).join(",")})`;
      s.fillRect(0.5, 0.5, size - 1, size - 1);
      const grad = s.createRadialGradient(r * 0.7, r * 0.6, r * 0.1, r, r, r * 0.8);
      grad.addColorStop(0, `rgb(${c.rgb.map((v) => Math.min(255, v + 70)).join(",")})`);
      grad.addColorStop(0.6, c.hex);
      grad.addColorStop(1, `rgb(${c.rgb.map((v) => v * 0.78).join(",")})`);
      s.fillStyle = grad;
      s.beginPath();
      s.arc(r, r, r * 0.74, 0, Math.PI * 2);
      s.fill();
      studs.set(key, img);
    }
    return studs.get(key);
  };
  const paint = (cells) => {
    const dpr = Math.min(2, devicePixelRatio || 1);
    const w = Math.round(canvas.clientWidth * dpr);
    const h = Math.round((w * rows) / cols);
    if (canvas.width !== w) [canvas.width, canvas.height] = [w, h];
    const size = w / cols;
    g.fillStyle = "#34373e";
    g.fillRect(0, 0, w, h);
    const q = Math.floor(size);
    cells.forEach((c, i) =>
      g.drawImage(stud(c, q), (i % cols) * size, Math.floor(i / cols) * size, size, size),
    );
  };

  // Coarse to fine, the jumble thinning out: the order a picture comes clear in.
  const LEVELS = [
    [0, 1],
    [16, 0.7],
    [12, 0.5],
    [8, 0.34],
    [6, 0.22],
    [4, 0.12],
    [3, 0.06],
    [2, 0.02],
    [1, 0],
  ];
  let job = null;
  let take = 0;
  const TAKES = [0.55, 0.3, 0.72, 0.45];
  const draw = (animate) => {
    job?.();
    const rgb = target(TAKES[take % TAKES.length]);
    const levels = LEVELS.map(([n]) => (n ? blocks(rgb, n) : null));
    const jumble = () => solid[Math.floor(Math.random() * solid.length)];
    const frameOf = (k, t) =>
      rgb.map((_, i) => {
        const [n, left] = LEVELS[k];
        if (!n || noise(i, t) < left) return jumble();
        return levels[k][i];
      });
    const step = $("#easel-step");
    if (!animate || calm.matches) {
      paint(levels.at(-1));
      step.textContent = "Picture 3 of 8, drawn from the cast sheet.";
      return;
    }
    let t = 0;
    const per = 3;
    job = onTick(() => {
      const k = Math.min(LEVELS.length - 1, Math.floor(t / per));
      paint(frameOf(k, t));
      step.textContent =
        k < LEVELS.length - 1
          ? `Finding the picture: step ${k + 1} of ${LEVELS.length}…`
          : "Picture 3 of 8, done.";
      if (t % per === 0) sound.play(k < LEVELS.length - 1 ? "tap" : "sparkle");
      if (k === LEVELS.length - 1) {
        job();
        job = null;
      }
      t++;
    });
  };
  let drawn = false;
  new IntersectionObserver(
    ([e], seen) => {
      if (!e.isIntersecting) return;
      seen.disconnect();
      drawn = true;
      draw(true);
    },
    { threshold: 0.3 },
  ).observe(canvas);
  new ResizeObserver(() => drawn && !job && draw(false)).observe(canvas);

  const locks = $("#locks");
  SHOTS.forEach((_, i) =>
    locks.append(
      el(
        "li",
        { className: i === SHOT ? "new" : "" },
        el("img", { src: thumbs[i], alt: `Picture ${i + 1}` }),
      ),
    ),
  );
  $("#redraw").addEventListener("click", () => {
    take++;
    draw(true);
  });
}

/* ---------- bag 4: the motion ---------- */

const RUG = model(
  { r: "red", y: "yellow", b: "blue" },
  ["r", "y", "b"].map((c) => `p ${c.repeat(60)}`).join("\n"),
);

function motion(thumbs, film) {
  const canvas = $("#set-stage");
  const s = new Stage(canvas, { view: 40, x: 20, y: 20 });
  const shots = [];
  const PATH = [0, 3, 5, 3];
  let playing = null;
  const pose = (k) => ({ x: 3 + k * 2.4, y: PATH[k % PATH.length], rot: k % 2 ? -0.06 : 0.04 });
  const hero = () => HEROES[pick.hero];
  const room = () => {
    s.bond("paleBlue", -10, 0, 60, 80);
    s.rect(-10, -40, 70, 36, "#6d3a1d");
    s.put(RUG, -8, -3);
  };
  const draw = (k, ghost = true) => {
    room();
    const h = hero();
    // The last picture shows through faintly, as an animator's onion skin does.
    if (ghost && k > 0) s.put(h.m, pose(k - 1).x, pose(k - 1).y, { alpha: 0.28, rot: pose(k - 1).rot });
    const p = pose(k);
    s.shadow(p.x, 0, h.m.w, 0.3 - p.y * 0.03);
    s.put(h.m, p.x, p.y, { rot: p.rot });
  };
  const label = () => {
    $("#frames").textContent =
      shots.length === 12 ? "12 of 12: that's one second of film!" : `${shots.length} of 12 pictures`;
    $("#replay").disabled = shots.length < 2;
  };
  s.onfit = () => draw(Math.max(0, shots.length - 1));
  draw(0, false);
  label();

  $("#snap").addEventListener("click", () => {
    playing?.();
    playing = null;
    if (shots.length === 12) {
      shots.length = 0;
      $("#filmstrip").replaceChildren();
    }
    const k = shots.length;
    draw(k, false);
    const small = el("canvas", { width: 160, height: 80 });
    small.getContext("2d").drawImage(canvas, 0, 0, 160, 80);
    shots.push(small.toDataURL("image/jpeg", 0.8));
    $("#filmstrip").append(el("li", {}, el("img", { src: shots[k], alt: `Picture ${k + 1}` })));
    draw(k);
    label();
    sound.play("camera");
  });

  $("#replay").addEventListener("click", () => {
    playing?.();
    let t = 0;
    const strip = $$("#filmstrip li");
    playing = onTick(() => {
      const k = t % shots.length;
      draw(k, false);
      strip.forEach((li, i) => li.classList.toggle("on", i === k));
      t++;
      if (t >= shots.length * 3) {
        playing();
        playing = null;
        strip.forEach((li) => li.classList.remove("on"));
      }
    });
  });

  const toggles = $("#toggles");
  const tally = () => {
    const moving = film.modes.filter((m) => m === "video").length;
    $("#tally").textContent =
      `${moving} moving, ${8 - moving} still. Moving pictures take more to make, so they cost more.`;
  };
  SHOTS.forEach((shot, i) => {
    const b = el(
      "button",
      { type: "button", ariaLabel: `Picture ${i + 1}` },
      el("img", { src: thumbs[i], alt: "" }),
      el("b"),
    );
    const show = () => {
      const moving = film.modes[i] === "video";
      b.setAttribute("aria-pressed", String(moving));
      $("b", b).textContent = moving ? "Moving" : "Still";
    };
    b.addEventListener("click", () => {
      film.modes[i] = film.modes[i] === "video" ? "still" : "video";
      show();
      tally();
      film.draw();
    });
    show();
    toggles.append(el("li", {}, b));
  });
  tally();
}

/* ---------- bag 5: the film ---------- */

function theFilm(thumbs) {
  const subs = $("#subs");
  const ticks = SHOTS.map((_, i) => {
    const b = el("button", { type: "button", ariaLabel: `Picture ${i + 1}` });
    b.addEventListener("click", () => {
      film.seek(i);
      mark(i);
      if (!film.playing) start();
    });
    $("#ticks").append(el("li", {}, b));
    return b;
  });
  const mark = (i) =>
    ticks.forEach((b, k) => {
      b.classList.toggle("on", k === i);
      b.classList.toggle("done", k < i);
    });
  const cues = (text) => text.split(/(?<=[.!?…])\s+/).filter(Boolean);
  let spoken = 0;

  const film = new Film($("#film"), {
    onShot(i) {
      mark(i);
      const text = SHOTS[i].narration[film.lang];
      if ($("#voice-on").checked && synth) {
        film.waiting = true;
        const id = ++spoken;
        const release = () => id === spoken && (film.waiting = false);
        say(text, film.lang, { onEnd: release });
        // If the voice never says it's done, don't hold the picture forever.
        setTimeout(release, seconds(text, film.lang) * 1600 + 3000);
      }
    },
    onFrame(i, t, d) {
      const parts = cues(SHOTS[i].narration[film.lang]);
      const total = parts.reduce((n, p) => n + p.length, 0);
      let at = (t / d) * total;
      const cue = parts.find((p) => (at -= p.length) < 0) ?? parts.at(-1);
      if (subs.textContent !== cue) {
        subs.textContent = cue;
        subs.lang = film.lang;
      }
    },
    onCue: (name) => sound.play(name),
    onEnd() {
      subs.textContent = "The End";
      ticks.forEach((b) => b.classList.add("done"));
      $("#tv-end").hidden = false;
      setPlay(false);
    },
  });
  film.draw();

  const setPlay = (on) => {
    $("#play").setAttribute("aria-label", on ? "Pause" : "Play");
    $("#play").innerHTML = on
      ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4h4v16H6zM14 4h4v16h-4z" fill="currentColor"/></svg>'
      : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4l13 8-13 8z" fill="currentColor"/></svg>';
  };
  const start = () => {
    $("#tv-start").hidden = true;
    $("#tv-end").hidden = true;
    film.play();
    setPlay(true);
  };
  const pause = () => {
    film.pause();
    synth?.cancel();
    film.waiting = false;
    setPlay(false);
  };
  $("#play-big").addEventListener("click", start);
  $("#play").addEventListener("click", () => (film.playing ? pause() : start()));
  $("#again").addEventListener("click", () => {
    film.seek(0);
    mark(0);
    ticks.forEach((b) => b.classList.remove("done"));
    start();
  });
  // Each tick is as long as its picture, in the film's language.
  const sizeTicks = () =>
    SHOTS.forEach((shot, i) =>
      ticks[i].parentElement.style.setProperty("--sec", seconds(shot.narration[film.lang], film.lang)),
    );
  $("#film-lang").addEventListener("change", (e) => {
    film.lang = e.target.value;
    $("#tv-title").textContent = TITLE[film.lang];
    sizeTicks();
    film.seek(film.i);
  });
  $("#subs-on").addEventListener("change", (e) => (subs.hidden = !e.target.checked));
  $("#voice-on").addEventListener("change", (e) => {
    if (!e.target.checked) {
      synth?.cancel();
      film.waiting = false;
    }
  });
  $("#full").addEventListener("click", () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else $("#tv-picture").requestFullscreen?.();
  });
  // A film that scrolls out of sight stops, and so does its voice.
  new IntersectionObserver(([e]) => !e.isIntersecting && film.playing && pause()).observe($("#film"));
  sizeTicks();
  return film;
}

/* ---------- the back of the box ---------- */

function backOfTheBox() {
  const s = new Stage($("#turn-art"), { view: 40, x: 20, y: 28 });
  let t = 0;
  s.onfit = () => drawBox(s, t, { done: true });
  drawBox(s, 0, { done: true });
  whileSeen($("#turn-art"), () => drawBox(s, ++t, { done: true }));

  const form = $("#join");
  const status = $("#join-status");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(form));
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
      status.textContent = `Sent! We'll write to ${data.email} when there's a place for you.`;
      $("#join-email").value = "";
      confetti();
      sound.play("fanfare");
    } catch {
      status.classList.add("err");
      status.textContent = "That didn't reach us. Try again in a minute.";
    }
  });
}

/* ---------- five lost bricks ---------- */

function lostBricks() {
  const found = new Set(store.get("found") ?? []);
  const count = () => {
    $("#found-n").textContent = found.size;
    $("#found").classList.toggle("all", found.size === 5);
  };
  for (const b of $$(".lost")) {
    if (found.has(b.dataset.lost)) {
      b.remove();
      continue;
    }
    b.addEventListener("click", () => {
      found.add(b.dataset.lost);
      store.set("found", [...found]);
      b.classList.add("found");
      setTimeout(() => b.remove(), 700);
      count();
      const badge = $("#found");
      badge.classList.remove("bump");
      void badge.offsetWidth; // reading the layout restarts the bump
      badge.classList.add("bump");
      if (found.size === 5) {
        toast("You found all five lost bricks. You're a real builder!");
        confetti();
        sound.play("fanfare");
      } else {
        toast(`You found a lost brick! ${5 - found.size} more hiding on this page.`);
        sound.play("chime");
      }
    });
  }
  count();
}

/* ---------- confetti, in bricks ---------- */

const CONFETTI = ["red", "yellow", "blue", "green", "orange", "white", "azure", "pink", "lime"].map((c) =>
  model({ x: c }, "b xx"),
);

function confetti() {
  if (calm.matches) return;
  const canvas = el("canvas", { className: "confetti" });
  document.body.append(canvas);
  const s = new Stage(canvas, { view: 60, x: 30 });
  const [, tall] = s.span;
  s.cam.y = tall / 2;
  const bits = Array.from({ length: 80 }, (_, i) => ({
    m: CONFETTI[i % CONFETTI.length],
    x: Math.random() * 60,
    y: tall + 4 + Math.random() * tall * 0.6,
    vx: (Math.random() - 0.5) * 0.6,
    vy: -(2 + Math.random() * 3),
    rot: Math.random() * 6,
    spin: (Math.random() - 0.5) * 0.9,
  }));
  let t = 0;
  const stop = onTick(() => {
    s.g.clearRect(0, 0, s.W, s.H);
    for (const b of bits) {
      b.x += b.vx;
      b.y += b.vy;
      b.vy -= 0.35;
      b.rot += b.spin;
      s.put(b.m, b.x, b.y, { rot: b.rot });
    }
    if (++t > 48) {
      stop();
      canvas.remove();
    }
  });
}
