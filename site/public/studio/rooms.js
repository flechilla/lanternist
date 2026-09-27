/* The floors of the studio, each dressed for one job and lit by its own lamps: what is on the set,
 * where the camera stands for it, which ambience plays there, what can be pointed at, and what the
 * crew member does when asked. The page's chapters drive these; the rooms know nothing of the page. */

import * as THREE from "three";
import { cat, lantern, mouse } from "./crew.js";
import { card, clay, felt } from "./clay.js";
import {
  books,
  boat,
  brush,
  crumple,
  deskLamp,
  easel,
  envelope,
  filmCamera,
  gramophone,
  jetty,
  lampPost,
  microphone,
  mixingDesk,
  modelLighthouse,
  paintPot,
  postbox,
  record,
  reel,
  screen,
  spool,
  table,
  typewriter,
  workLight,
} from "./props.js";
import { blob, block, painted, paper, part, pivot, taper, TAU, v3 } from "./shapes.js";
import { floorY, LAMP_Y, radius, SEA_Y } from "./tower.js";
import { noise } from "./engine.js";
import { LANGUAGES, SHOTS, TITLE } from "../story.js";

/** The picture styles, as the app names them (`writer.STYLES`), each with the colour of its pot. */
export const STYLES = [
  ["watercolour", "Watercolour", "#7fb2d9"],
  ["3d_film", "3D film", "#3fa7a0"],
  ["paper_cutout", "Paper cut-out", "#c0503f"],
  ["clay", "Clay", "#e08a3c"],
  ["ink_pencil", "Ink and pencil", "#2b2f38"],
  ["anime", "Anime", "#e98fb0"],
];

/** The colour on each language's record label. */
const LABELS = [
  "#f0b14a",
  "#c0503f",
  "#3d8a5a",
  "#2f5a88",
  "#e98fb0",
  "#7fb2d9",
  "#c9973f",
  "#b8a0d8",
  "#e08a3c",
  "#6fc4a6",
];

const at = (o, x, y, z, ry = 0) => {
  o.position.set(x, y, z);
  o.rotation.y = ry;
  return o;
};

/** Hop, squeak and settle: what any puppet does when it's poked. */
export const HOP = {
  len: 10,
  keys: [
    [0, {}],
    [2, { hips: { sy: -0.18, s: 0.04 } }],
    [
      4,
      {
        hips: { y: 3.2, sy: 0.12 },
        armL: { rz: -1.2 },
        armR: { rz: 1.2 },
        earL: { rz: 0.3 },
        earR: { rz: -0.3 },
      },
    ],
    [6, { hips: { y: 2.4 }, armL: { rz: -0.9 }, armR: { rz: 0.9 } }],
    [8, { hips: { sy: -0.12, s: 0.03 } }],
    [10, {}],
  ],
};

export const WAVE = {
  len: 22,
  keys: [
    [0, {}],
    [3, { armR: { rz: 2.5, rx: -0.3 }, head: { rz: 0.12 } }],
    [6, { armR: { rz: 2.9, rx: -0.3 }, pawR: { rz: 0.5 }, head: { rz: 0.12 } }],
    [9, { armR: { rz: 2.5, rx: -0.3 }, pawR: { rz: -0.4 }, head: { rz: 0.12 } }],
    [12, { armR: { rz: 2.9, rx: -0.3 }, pawR: { rz: 0.5 }, head: { rz: 0.1 } }],
    [15, { armR: { rz: 2.5, rx: -0.3 }, pawR: { rz: -0.4 } }],
    [22, {}],
  ],
};

/** Paws up, bouncing in turn: typing on the keys below, playing the desk, dabbing paint. */
const busy = (len, arm = 0.9) => ({
  len,
  keys: [
    [0, { armL: { rx: -arm }, armR: { rx: -arm - 0.4 }, hips: { sy: -0.03 } }],
    [len / 2, { armL: { rx: -arm - 0.4 }, armR: { rx: -arm }, hips: { sy: 0.02 } }],
    [len, { armL: { rx: -arm }, armR: { rx: -arm - 0.4 }, hips: { sy: -0.03 } }],
  ],
});

/** The typed page for a language: the title and the first shot, as the writer lays it out. */
export function scriptFor(lang) {
  const [shot] = SHOTS;
  return {
    title: TITLE[lang] ?? TITLE.en,
    meta: "Bedtime · ages 5 to 8 · 7 shots",
    tag: `Shot 1 · ${shot.shot}`,
    text: shot.narration[lang],
    picture: shot.visual,
  };
}

/** Breaks text into lines no wider than `max` in the context's font: at spaces, or between any two
 * Chinese, Japanese or Korean characters, which have none. */
function wrap(c, text, max) {
  const lines = [];
  let line = "";
  for (const w of text.split(/(?<=\s)|(?=[\u3000-\u9fff\uac00-\ud7af])/u)) {
    if (c.measureText(line + w).width > max && line) {
      lines.push(line);
      line = w;
    } else line += w;
  }
  return [...lines, line];
}

/** Lays out a page as lines, each with its font, colour, height on the page, and where its first
 * character falls in the text as typed (`at`). */
function layout(c, page, max) {
  const blocks = [
    ["700 30px 'Courier Prime', monospace", "#1a2434", page.title.toUpperCase(), 36, 0],
    ["400 20px 'Courier Prime', monospace", "#6f7a8b", page.meta, 26, 18],
    ["700 20px 'Courier Prime', monospace", "#8f3528", page.tag.toUpperCase(), 26, 4],
    ["400 24px 'Courier Prime', monospace", "#1a2434", page.text, 32, 12],
    ["italic 400 19px 'Courier Prime', monospace", "#465163", `Picture: ${page.picture}`, 25, 0],
  ];
  const lines = [];
  let y = 0;
  let typed = 0;
  for (const [font, color, text, lh, gap] of blocks) {
    c.font = font;
    for (const line of wrap(c, text, max)) {
      lines.push({ font, color, text: line, y, at: typed });
      typed += line.length;
      y += lh;
    }
    y += gap;
  }
  return lines;
}

/** Draws `shown` characters of the page; the line being typed sits just above the roller. */
function typePage(c, w, h, page, shown) {
  c.fillStyle = "#f3ead6";
  c.fillRect(0, 0, w, h);
  const lines = layout(c, page, w - 70);
  const typed = lines.filter((l) => l.at < shown);
  const last = typed.at(-1) ?? lines[0];
  const lift = Math.max(0, last.y + 60 - (h - 40));
  for (const l of typed) {
    c.font = l.font;
    c.fillStyle = l.color;
    c.fillText(l.text.slice(0, shown - l.at).trim(), 34, l.y + 60 - lift);
  }
}

/* ---------- the lamp room: the top of the tower ---------- */

function lampRoom(ctx) {
  const y = LAMP_Y;
  const g = new THREE.Group();
  const luna = cat({ curled: true });
  at(luna.root, -8, y + 6.4, 5, 0.2);
  const rug = part(new THREE.CylinderGeometry(9.5, 9.5, 0.4, 32), felt("#8f3528", { fuzz: 1 }), [
    -7,
    y + 6.2,
    5,
  ]);
  g.add(rug, luna.root);
  // Wick perches on the gallery's top rail, where the whole sea can see his lantern.
  const wick = mouse("wick");
  at(wick.root, Math.sin(0.34) * 31.8, y + 10.4, Math.cos(0.34) * 31.8, 0.34);
  const lamp = lantern();
  lamp.position.set(0.2, -2.2, 0.6);
  wick.joints.pawR.add(lamp);
  wick.joints.armR.rotation.x = -0.9;
  g.add(wick.root);

  // A bank of cotton cloud off to the side, for the lamp to throw the visitor's line onto.
  const bank = new THREE.Group();
  const wool = felt("#8d9bb8", { fuzz: 2.4, lump: 0.6, boil: 0.1, freq: 0.5 });
  for (let k = 0; k < 9; k++) {
    const r = 11 + 7 * noise(k, 21);
    bank.add(
      part(blob(r * 1.3, r * 0.8, r * 0.7), wool, [
        (k - 4) * 12,
        (noise(k, 22) - 0.4) * 10,
        noise(k, 23) * 6,
      ]),
    );
  }
  // The bank hangs where the hero shot sees it: a little left of the lens's axis and well above it.
  const shot = { look: [6, y + 16, 2], yaw: 0.32, pitch: 0.12, dist: 104 };
  const eye = new THREE.Vector3(
    shot.look[0] + Math.sin(shot.yaw) * Math.cos(shot.pitch) * shot.dist,
    shot.look[1] + Math.sin(shot.pitch) * shot.dist,
    shot.look[2] + Math.cos(shot.yaw) * Math.cos(shot.pitch) * shot.dist,
  );
  const axis = new THREE.Vector3(...shot.look).sub(eye).normalize();
  const turn = Math.atan2(axis.x, axis.z) + 0.33;
  const rise = Math.asin(axis.y) + 0.175;
  bank.position
    .copy(eye)
    .add(
      new THREE.Vector3(
        Math.sin(turn) * Math.cos(rise),
        Math.sin(rise),
        Math.cos(turn) * Math.cos(rise),
      ).multiplyScalar(240),
    );
  bank.lookAt(eye);
  const slide = painted(1024, 512, () => {});
  const words = new THREE.Mesh(
    new THREE.PlaneGeometry(92, 46),
    // Light thrown on the cotton, so it lies over the tufts rather than behind them.
    new THREE.MeshBasicMaterial({
      map: slide,
      transparent: true,
      depthWrite: false,
      depthTest: false,
      blending: THREE.AdditiveBlending,
    }),
  );
  words.renderOrder = 6;
  words.position.copy(bank.position).addScaledVector(eye.clone().sub(bank.position).normalize(), 14);
  words.lookAt(eye);
  words.visible = false;
  g.add(bank, words);
  ctx.scene.add(g);
  const aim = bank.position.clone().sub(new THREE.Vector3(0, LAMP_Y + 18, 0));
  let focus = null;

  /** Draws the line as a lantern slide: warm light in a soft round frame, `blur` pixels out of focus. */
  function drawSlide(idea, blur) {
    const c = slide.image.getContext("2d");
    const [w, h] = [slide.image.width, slide.image.height];
    c.clearRect(0, 0, w, h);
    c.filter = `blur(${blur}px)`;
    const glowFill = c.createRadialGradient(w / 2, h / 2, 40, w / 2, h / 2, h * 0.62);
    glowFill.addColorStop(0, "rgba(255,214,150,0.22)");
    glowFill.addColorStop(1, "rgba(255,214,150,0)");
    c.fillStyle = glowFill;
    c.fillRect(0, 0, w, h);
    c.fillStyle = "rgba(255,232,190,0.95)";
    c.textAlign = "center";
    c.textBaseline = "middle";
    const size = idea.length > 42 ? 58 : 72;
    c.font = `italic ${size}px 'IM Fell Double Pica', Georgia, serif`;
    const lines = [];
    let line = "";
    for (const word of idea.split(" ")) {
      if (c.measureText(`${line} ${word}`).width > w * 0.82 && line) {
        lines.push(line);
        line = word;
      } else line = line ? `${line} ${word}` : word;
    }
    lines.push(line);
    lines.forEach((l, i) => c.fillText(l, w / 2, h / 2 + (i - (lines.length - 1) / 2) * size * 1.15));
    c.filter = "none";
    slide.needsUpdate = true;
  }
  let purring = 0;
  return {
    name: "lamp",
    group: g,
    actors: [wick, luna],
    wick,
    luna,
    lantern: lamp,
    shot: { ...shot, fov: 32, span: 70, focus: [10, y + 10, 6] },
    lamps: [{ at: [13, y + 22, 36], color: "#ffc56b", power: 160, reach: 30 }],
    key: { from: [60, 70, 90], color: "#ffe0b0", power: 2400 },
    beds: { sea: 0.55, wind: 0.35 },
    hot: [
      {
        object: luna.root,
        label: "Luna",
        act(f) {
          luna.wake(true);
          ctx.foley.play(purring++ % 3 === 2 ? "meow" : "purr", { gain: 0.8 });
          luna.play(STRETCH, f).then(() => luna.wake(false));
        },
      },
      { object: wick.root, label: "Wick", act: (f) => (ctx.foley.play("squeak-hello"), wick.play(WAVE, f)) },
      { object: bank, label: "the cloud", act: () => ctx.foley.play("whoosh", { gain: 0.4 }) },
    ],
    /** Throws a line onto the cloud: the beam swings round and stops on it, and the slide comes into focus. */
    project(idea, f) {
      ctx.world.beam.userData.hold = [Math.atan2(-aim.z, aim.x), Math.atan2(aim.y, Math.hypot(aim.x, aim.z))];
      words.visible = true;
      focus = { idea, from: f };
      drawSlide(idea, 14);
      ctx.foley.play("click", { gain: 0.5 });
      wick.play(HOP, f);
    },
    update(f) {
      if (focus) {
        const k = f - focus.from;
        if (k <= 6) drawSlide(focus.idea, (6 - k) * 2.4);
        else focus = null;
      }
      wick.pose(f);
      luna.pose(f);
      if (lamp.userData.flame.visible) lamp.userData.light.intensity = 40 + 12 * noise(3, f);
    },
  };
}

const STRETCH = {
  len: 30,
  keys: [
    [0, {}],
    [6, { head: { rx: -0.35, y: 1.2 }, earL: { rz: 0.2 }, earR: { rz: -0.2 } }],
    [18, { head: { rx: -0.3, y: 1.4, rz: 0.1 } }],
    [30, {}],
  ],
};

/* ---------- the writer's floor ---------- */

function writerRoom(ctx) {
  const y = floorY("writer");
  const g = new THREE.Group();
  let page = scriptFor("en");
  let shown = 0;
  const sheet = paper(512, 400, (c, w, h) => typePage(c, w, h, page, 0));
  const tw = typewriter(sheet);
  at(tw, 3, y, -11, -0.12);
  const lamp = deskLamp();
  at(lamp, -17, y, -13, 0.1);
  const pile = books();
  at(pile, 19, y, -8, 0.4);
  g.add(tw, lamp, pile);
  const balls = [
    [-7, 1.3, -1, 1.6],
    [-11, 1.1, 2, 1.3],
    [15, 1.2, 1, 1.5],
    [21, 1.1, -1, 1.2],
  ].map(([x, h, z, r], k) => {
    const b = crumple(r, k);
    b.position.set(x, y + h, z);
    g.add(b);
    return b;
  });
  const quill = mouse("quill");
  const keys = tw.userData.keys;
  for (const k of keys.flat()) k.userData.rest = k.position.y;
  const keyWorld = (r, k) => {
    const v = new THREE.Vector3();
    keys[r][k].getWorldPosition(v);
    return v;
  };
  g.add(quill.root);
  ctx.scene.add(g);
  g.updateMatrixWorld(true);
  const perch = keyWorld(1, 4);
  quill.root.position.set(perch.x, perch.y + 0.4, perch.z);
  quill.root.rotation.y = -0.12;

  let typing = null;
  const hop = { from: perch.clone(), to: perch.clone(), t: 1, key: null };
  function redraw() {
    const c = sheet.image.getContext("2d");
    typePage(c, sheet.image.width, sheet.image.height, page, shown);
    sheet.needsUpdate = true;
  }
  const total = () =>
    layout(sheet.image.getContext("2d"), page, sheet.image.width - 70).reduce((a, l) => a + l.text.length, 0);
  let typed = false;

  const room = {
    name: "writer",
    group: g,
    actors: [quill],
    shot: {
      look: [3, y + 11, -9],
      yaw: -0.1,
      pitch: 0.16,
      dist: 66,
      fov: 30,
      span: 52,
      focus: [2, y + 11, -7],
    },
    lamps: [
      { at: [-8, y + 15, -12], color: "#ffd9a0", power: 480, reach: 45 },
      { at: [14, y + 18, 6], color: "#ffb86b", power: 180, reach: 50 },
    ],
    key: { from: [40, 60, 70], color: "#ffe6c4", power: 2200 },
    beds: { room: 0.6, sea: 0.12 },
    hot: [
      { object: tw, label: "the typewriter", act: () => room.type(ctx.state.lang) },
      {
        object: quill.root,
        label: "Quill",
        act: (f) => (ctx.foley.play("squeak-giggle"), quill.play(HOP, f)),
      },
      ...balls.map((b) => ({
        object: b,
        label: "a crumpled page",
        act: () => ctx.foley.play("squish-3", { gain: 0.6 }),
      })),
    ],
    /** The first time the camera arrives, Quill starts typing. */
    enter() {
      if (!typed) room.type(ctx.state.lang);
    },
    /** Types the page again in `lang`: Quill hops from key to key, a character or three a frame. */
    type(lang) {
      typed = true;
      page = scriptFor(lang);
      shown = 0;
      redraw();
      typing = { lang, n: total(), step: lang === "zh" || lang === "ja" || lang === "ko" ? 1 : 3 };
      quill.hold(busy(4, 0.7));
      ctx.foley.play("page", { gain: 0.5 });
    },
    update(f) {
      if (typing) {
        shown = Math.min(typing.n, shown + typing.step);
        redraw();
        if (f % 2 === 0) {
          const r = Math.floor(noise(f, 1) * 4);
          const k = Math.floor(noise(f, 2) * keys[r].length);
          hop.from.copy(quill.root.position);
          hop.to.copy(keyWorld(r, k));
          hop.t = 0;
          hop.key = keys[r][k];
          ctx.foley.play("key", { gain: 0.55, pan: 0.2, vary: 0.25 });
        }
        if (shown >= typing.n) {
          typing = null;
          quill.hold(null);
          ctx.foley.play("carriage", { gain: 0.6 });
        }
      }
      for (const k of keys.flat()) k.position.y = k.userData.rest;
      if (hop.t < 1) {
        hop.t = Math.min(1, hop.t + 0.5);
        quill.root.position.lerpVectors(hop.from, hop.to, hop.t);
        quill.root.position.y += Math.sin(hop.t * Math.PI) * 2.2 + 0.4;
        if (hop.t >= 1 && hop.key) hop.key.position.y -= 0.6;
      }
      quill.pose(f);
    },
  };
  return room;
}

/* ---------- the voice's floor ---------- */

function voiceRoom(ctx) {
  const y = floorY("voice");
  const g = new THREE.Group();
  const mic = microphone(5.6);
  at(mic, -9, y, -3, 0.2);
  const stage = spool("#3f4f6b");
  at(stage, -4, y, -9);
  const echo = mouse("echo");
  at(echo.root, -4, y + 5, -9, 0.15);
  const gram = gramophone();
  at(gram, 11, y, -13, -0.35);
  // The records hang on a line across the back, pegged like washing, one for each language.
  const line = new THREE.CatmullRomCurve3([v3(-8, y + 22, -18), v3(7, y + 20.6, -19), v3(22, y + 22, -12)]);
  g.add(part(taper(line, 0.08, 0.08, 20, 4), clay("#d9d0bf", { lump: 0, boil: 0 })));
  const records = Object.keys(LANGUAGES).map((code, i) => {
    const r = record(code.toUpperCase(), LABELS[i], 2.2);
    const p = line.getPointAt(0.05 + i * 0.1);
    r.rotation.set(Math.PI / 2, 0, (noise(i, 5) - 0.5) * 0.3);
    r.position.set(p.x, p.y - 2.5, p.z + 0.2);
    r.lookAt(0, p.y - 2.5, 30);
    r.rotateX(Math.PI / 2);
    r.userData.code = code;
    g.add(
      r,
      part(block(0.5, 1.6, 0.6, 0.15), clay("#c9973f", { lump: 0, boil: 0 }), [p.x, p.y - 0.2, p.z + 0.3]),
    );
    return r;
  });
  g.add(mic, stage, echo.root, gram);
  ctx.scene.add(g);
  let playing = null;
  const onPlatter = record("", "#f0b14a");
  gram.userData.record.add(onPlatter);
  onPlatter.visible = false;
  return {
    name: "voice",
    group: g,
    actors: [echo],
    shot: {
      look: [1, y + 12, -9],
      yaw: 0.1,
      pitch: 0.14,
      dist: 66,
      fov: 30,
      span: 52,
      focus: [-4, y + 11, -8],
    },
    lamps: [
      { at: [12, y + 16, -6], color: "#ffcf8a", power: 380, reach: 45 },
      { at: [-9, y + 21, -2], color: "#ff5a3a", power: 0, reach: 30 },
    ],
    key: { from: [-40, 55, 70], color: "#ffe6c4", power: 2100 },
    beds: { room: 0.35 },
    hot: [
      ...records.map((r) => ({
        object: r,
        label: `the ${LANGUAGES[r.userData.code]} record`,
        act: () => ctx.onRecord?.(r.userData.code),
      })),
      { object: echo.root, label: "Echo", act: (f) => (ctx.foley.play("squeak-oh"), echo.play(HOP, f)) },
      { object: mic, label: "the microphone", act: () => ctx.foley.play("click", { gain: 0.7 }) },
    ],
    /** Puts `code`'s record on the gramophone and lights the sign; `null` takes it off. */
    play(code, f) {
      playing = code;
      onPlatter.visible = !!code;
      for (const r of records) r.visible = r.userData.code !== code;
      mic.userData.lit.color.set("#ff6a4a").multiplyScalar(code ? 2.4 : 0.5);
      ctx.foley.loop("crackle", code ? 0.3 : 0, 0.3);
      this.lamps[1].power = code ? 260 : 0;
      ctx.relight?.();
      if (code) echo.play(HOP, f);
    },
    update(f) {
      if (playing) gram.userData.platter.rotation.y -= 0.55;
      echo.talk = playing ? ctx.foley.level() : 0;
      echo.pose(f);
    },
  };
}

/* ---------- the painter's floor ---------- */

function paintRoom(ctx) {
  const y = floorY("paint");
  const g = new THREE.Group();
  const stand = easel();
  at(stand, 7, y, -13, -0.28);
  const box = part(block(7, 4.5, 5, 0.5), clay("#c9973f", { lump: 0.04, boil: 0 }), [-3, y + 2.25, -8]);
  const dab = mouse("dab");
  at(dab.root, -3, y + 4.5, -8, 0.75);
  const tool = brush("#e08a3c");
  tool.position.set(0.2, -0.6, 0.4);
  tool.rotation.set(0.3, 0, -1.4);
  tool.scale.setScalar(0.7);
  dab.joints.pawR.add(tool);
  dab.joints.armR.rotation.x = -1.1;
  const model = cat();
  model.root.scale.setScalar(0.5);
  const turntable = pivot([-16, y, -12]);
  turntable.add(
    part(new THREE.CylinderGeometry(6, 6.4, 1.6, 36), clay("#5f3d22", { lump: 0.03, boil: 0 }), [0, 0.8, 0]),
  );
  model.root.position.y = 1.6;
  turntable.add(model.root);
  const pots = STYLES.map(([key, , color], i) => {
    const p = paintPot(color);
    at(p, -4 + i * 4.6, y, 1.5 - Math.abs(i - 2.5) * 0.8);
    p.userData.style = key;
    g.add(p);
    return p;
  });
  const splats = [
    [2, -3, "#e08a3c", 1.6],
    [-9, 0, "#7fb2d9", 1.2],
    [16, -4, "#c0503f", 1.4],
  ].map(([x, z, c, r]) => part(blob(r, 0.12, r * 0.8), clay(c, { lump: 0.02, boil: 0 }), [x, y + 0.08, z]));
  g.add(stand, box, dab.root, turntable, ...splats);
  ctx.scene.add(g);
  const blank = painted(512, 384, (c, w, h) => {
    c.fillStyle = "#efe6d2";
    c.fillRect(0, 0, w, h);
  });
  const canvas = stand.userData.canvas;
  canvas.material.map = blank;
  const pictures = new Map();
  const loader = new THREE.TextureLoader();
  let reveal = null;
  let drawn = false;
  return {
    name: "paint",
    group: g,
    actors: [dab, model],
    shot: {
      look: [2, y + 12, -9],
      yaw: -0.1,
      pitch: 0.14,
      dist: 66,
      fov: 30,
      span: 54,
      focus: [4, y + 12, -10],
    },
    lamps: [
      { at: [4, y + 22, -4], color: "#fff0d0", power: 440, reach: 50 },
      { at: [-16, y + 12, -2], color: "#ffb86b", power: 170, reach: 35 },
    ],
    key: { from: [35, 60, 75], color: "#fff0d8", power: 2300 },
    beds: { room: 0.5, sea: 0.1 },
    hot: [
      ...pots.map((p) => ({
        object: p,
        label: `the ${STYLES.find((s) => s[0] === p.userData.style)[1]} paint`,
        act: () => ctx.onStyle?.(p.userData.style),
      })),
      { object: dab.root, label: "Dab", act: (f) => (ctx.foley.play("squeak-hello"), dab.play(HOP, f)) },
      {
        object: turntable,
        label: "Luna's model",
        act: () => ctx.foley.play("meow", { gain: 0.4, rate: 1.4 }),
      },
    ],
    /** The first time the camera arrives, Dab paints the style already chosen. */
    enter(f) {
      if (!drawn) this.paint(ctx.state.style, ctx.state.take, f);
    },
    /** Paints the cast in `style` onto the canvas, a band at a time, while Dab dabs. */
    paint(style, take, f) {
      drawn = true;
      const src = `img/cast-${style}-${take}.webp`;
      if (!pictures.has(src)) {
        const t = loader.load(src);
        t.colorSpace = THREE.SRGBColorSpace;
        pictures.set(src, t);
      }
      reveal = { tex: pictures.get(src), from: f, bands: 8 };
      dab.hold(busy(6, 1.2));
      ctx.foley.play("brush", { gain: 0.7 });
    },
    update(f) {
      turntable.rotation.y = Math.round((f / 72) * TAU * 12) / 12;
      if (reveal) {
        const k = Math.floor((f - reveal.from) / 2);
        const mat = canvas.material;
        if (k === 0) {
          mat.map = reveal.tex;
          mat.needsUpdate = true;
        }
        canvas.scale.set(1, Math.min(1, (k + 1) / reveal.bands), 1);
        canvas.position.y = (-(1 - canvas.scale.y) * 14.4) / 2;
        mat.map.repeat.set(1, canvas.scale.y);
        mat.map.offset.set(0, 1 - canvas.scale.y);
        if (k % 2 === 0 && k < reveal.bands) ctx.foley.play("brush", { gain: 0.4, vary: 0.3 });
        if (k >= reveal.bands) {
          reveal = null;
          dab.hold(null);
        }
      }
      dab.pose(f);
      model.pose(f);
    },
  };
}

/* ---------- the animator's floor ---------- */

/** Where the little Luna stands on the model set, frame by frame of the visitor's shoot. */
const WALK = Array.from({ length: 13 }, (_, k) => [-2 + k * 0.95, Math.abs(Math.sin(k * 1.2)) * 0.6]);

function motionRoom(ctx) {
  const y = floorY("motion");
  const g = new THREE.Group();
  const bench = table(30, 16, 8);
  at(bench, -2, y, -12);
  const set = modelLighthouse();
  at(set, -2, y + 8, -12);
  const mini = cat();
  mini.root.scale.setScalar(0.26);
  set.add(mini.root);
  const cam = filmCamera();
  at(cam, 17, y, -1, -2.1);
  const nudge = mouse("nudge");
  at(nudge.root, -17, y + 8, -9, 0.9);
  const work = workLight();
  at(work, 9, y + 8, -18.5, -0.35);
  const board = painted(256, 128, (c, w, h) => {
    c.fillStyle = "#15171c";
    c.fillRect(0, 0, w, h);
  });
  const sign = part(new THREE.PlaneGeometry(12, 6), new THREE.MeshBasicMaterial({ map: board }), [
    -2,
    y + 20,
    -24,
  ]);
  sign.castShadow = false;
  g.add(bench, set, cam, nudge.root, work, sign);
  ctx.scene.add(g);
  let frame = 0;
  let playback = null;
  function place(k) {
    const [x, z] = WALK[Math.min(k, WALK.length - 1)];
    mini.root.position.set(x, 1.1, z + 2.5);
    mini.root.rotation.y = Math.PI / 2 - 0.3;
  }
  function label(text) {
    const c = board.image.getContext("2d");
    c.fillStyle = "#15171c";
    c.fillRect(0, 0, 256, 128);
    c.fillStyle = "#f0b14a";
    c.font = "700 40px 'Courier Prime', monospace";
    c.textAlign = "center";
    c.fillText(text, 128, 78);
    board.needsUpdate = true;
  }
  place(0);
  label("FRAME 00");
  const REACH = {
    len: 10,
    keys: [
      [0, {}],
      [3, { body: { rz: -0.25 }, armR: { rx: -1.5, rz: 0.4 }, head: { rx: 0.3 } }],
      [6, { body: { rz: -0.3 }, armR: { rx: -1.7, rz: 0.5 }, head: { rx: 0.35 } }],
      [10, {}],
    ],
  };
  return {
    name: "motion",
    group: g,
    actors: [nudge, mini],
    shot: {
      look: [-1, y + 12, -10],
      yaw: 0.12,
      pitch: 0.16,
      dist: 66,
      fov: 30,
      span: 54,
      focus: [-3, y + 11, -11],
    },
    lamps: [
      { at: [4, y + 20, -12], color: "#fff4e0", power: 650, reach: 40 },
      { at: [-18, y + 16, 4], color: "#6f8fbf", power: 120, reach: 50 },
    ],
    key: { from: [-30, 50, 60], color: "#d8e4ff", power: 1500 },
    beds: { room: 0.25 },
    hot: [
      { object: cam, label: "the camera", act: (f) => ctx.onShutter?.(f) },
      { object: nudge.root, label: "Nudge", act: (f) => (ctx.foley.play("squeak-oh"), nudge.play(HOP, f)) },
      { object: set, label: "the model lighthouse", act: (f) => ctx.onShutter?.(f) },
    ],
    get frames() {
      return frame;
    },
    /** One press of the shutter: a frame is taken, and Nudge moves Luna on. Returns frames taken. */
    shoot(f) {
      if (playback) return frame;
      ctx.foley.play("shutter", { gain: 0.9 });
      cam.userData.pilot.material.color.set("#ff4a3a").multiplyScalar(4);
      setTimeout(() => cam.userData.pilot.material.color.set("#ff4a3a").multiplyScalar(0.4), 120);
      frame = Math.min(12, frame + 1);
      label(`FRAME ${String(frame).padStart(2, "0")}`);
      nudge.play(REACH, f).then(() => place(frame));
      if (frame === 12) playback = { from: f + 14, loops: 3 };
      return frame;
    },
    reset() {
      frame = 0;
      playback = null;
      place(0);
      label("FRAME 00");
    },
    update(f) {
      if (playback && f >= playback.from) {
        const k = f - playback.from;
        place(k % 13);
        label(`PLAYBACK ${String(k % 13).padStart(2, "0")}`);
        if (k === 0) ctx.foley.play("projector", { gain: 0.35 });
        if (k >= 13 * playback.loops) {
          playback = null;
          ctx.onShot?.();
        }
      }
      nudge.pose(f);
      mini.pose(f);
    },
  };
}

/* ---------- the editor's floor ---------- */

function mixRoom(ctx) {
  const y = floorY("mix");
  const g = new THREE.Group();
  const desk = mixingDesk();
  at(desk, 5, y, -8, -0.05);
  const seat = spool("#3d8a5a");
  at(seat, 6, y, -19);
  const splice = mouse("splice");
  at(splice.root, 6, y + 5.4, -19, 0);
  const deck = new THREE.Group();
  deck.add(part(block(14, 16, 4, 0.8), clay("#3a2a22", { lump: 0.03, boil: 0 }), [0, 8, 0]));
  const reels = [-3.4, 3.4].map((x) => {
    const r = reel(3.2);
    r.position.set(x, 12, 2.4);
    deck.add(r);
    return r;
  });
  at(deck, -14, y, -18, 0.35);
  // The shot list, pinned to the cork: one card a shot.
  SHOTS.forEach((s, i) => {
    const t = paper(256, 160, (c, w) => {
      c.fillStyle = "#8f3528";
      c.font = "700 22px 'Courier Prime', monospace";
      c.fillText(`SHOT ${s.n} · ${s.shot.toUpperCase()}`, 16, 34);
      c.fillStyle = "#1a2434";
      c.font = "400 17px 'Courier Prime', monospace";
      wrap(c, `${s.narration.en.slice(0, 90)}…`, w - 32).forEach((l, k) =>
        c.fillText(l.trim(), 16, 64 + k * 22),
      );
    });
    const a = Math.PI + (i - 3.6) * 0.19;
    const h = y + 14.5 + (i % 2) * 5.5;
    const r = radius(h) - 2.6 - 0.9;
    const m = part(new THREE.PlaneGeometry(7.5, 4.7), card("#ffffff", t, 0.9), [
      Math.sin(a) * r,
      h,
      Math.cos(a) * r,
    ]);
    m.lookAt(0, m.position.y, 0);
    m.rotation.z = (noise(i, 8) - 0.5) * 0.15;
    g.add(m);
  });
  g.add(desk, seat, splice.root, deck);
  ctx.scene.add(g);
  let playing = false;
  return {
    name: "mix",
    group: g,
    actors: [splice],
    shot: {
      look: [2, y + 11, -9],
      yaw: -0.08,
      pitch: 0.18,
      dist: 66,
      fov: 30,
      span: 54,
      focus: [5, y + 10, -12],
    },
    lamps: [
      { at: [0, y + 20, -6], color: "#ffd9a0", power: 440, reach: 45 },
      { at: [-14, y + 14, -10], color: "#6fc4a6", power: 150, reach: 30 },
    ],
    key: { from: [40, 55, 70], color: "#ffe6c4", power: 2100 },
    beds: { room: 0.4 },
    hot: [
      { object: desk, label: "the mixing desk", act: () => ctx.onMix?.() },
      {
        object: splice.root,
        label: "Splice",
        act: (f) => (ctx.foley.play("squeak-giggle"), splice.play(HOP, f)),
      },
      { object: deck, label: "the tape deck", act: () => ctx.foley.play("reel", { gain: 0.7 }) },
    ],
    set playing(on) {
      playing = on;
      splice.hold(on ? busy(6, 0.8) : null);
    },
    /** Moves the desk's first two faders to the page's sliders (0 to 1). */
    faders(voice, sea) {
      desk.userData.faders[0].position.z = 3.4 + 2 - voice * 4;
      desk.userData.faders[1].position.z = 3.4 + 2 - sea * 4;
    },
    update(f) {
      if (playing) for (const r of reels) r.rotation.z -= 0.4;
      const level = ctx.foley.level();
      desk.userData.needle.rotation.z =
        Math.round((0.9 - (playing ? Math.min(1.2, level * 1.8) : 0)) * 20) / 20;
      splice.pose(f);
    },
  };
}

/* ---------- the cinema ---------- */

function cinemaRoom(ctx) {
  const y = floorY("cinema");
  const g = new THREE.Group();
  const r0 = radius(y) - 2.6;
  const scr = screen(30, 17);
  at(scr, 0, y + 14, -r0 + 4.5);
  const colors = ["#c0503f", "#3d8a5a", "#2f5a88", "#c9973f", "#8f3528", "#3f4f6b", "#b8a0d8"];
  const roles = ["quill", "echo", "dab", "nudge", "splice"];
  const audience = [];
  let k = 0;
  for (const [row, z] of [
    [0, -12],
    [1, -5],
  ]) {
    for (let s = 0; s < 5 - row; s++) {
      const x = (s - (4 - row) / 2) * 7.5;
      const seat = spool(colors[k % colors.length]);
      at(seat, x, y, z);
      g.add(seat);
      if (k < roles.length || noise(k, 3) > 0.35) {
        const m = mouse(roles[k % roles.length]);
        at(m.root, x, y + 5.4, z, Math.PI + (noise(k, 4) - 0.5) * 0.4);
        g.add(m.root);
        audience.push(m);
      }
      k++;
    }
  }
  const projector = new THREE.Group();
  projector.add(part(block(7, 5, 7, 0.6), clay("#3a2a22", { lump: 0.04, boil: 0 }), [0, 2.5, 0]));
  const magic = lantern();
  magic.position.set(0, 5, 0);
  magic.userData.light.intensity = 0;
  projector.add(magic);
  at(projector, 18, y, -2, -0.4);
  const beam = new THREE.Mesh(
    new THREE.CylinderGeometry(0.6, 11, 1, 24, 1, true),
    new THREE.MeshBasicMaterial({
      color: "#ffe2a8",
      transparent: true,
      opacity: 0.07,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    }),
  );
  g.add(scr, projector, beam);
  ctx.scene.add(g);
  const from = new THREE.Vector3(18, y + 7, -2);
  const to = new THREE.Vector3(0, y + 14, -r0 + 5);
  beam.position.copy(from).lerp(to, 0.5);
  beam.scale.y = from.distanceTo(to);
  beam.lookAt(to);
  beam.rotateX(Math.PI / 2);
  beam.visible = false;
  const face = scr.userData.face;
  const poster = new THREE.TextureLoader().load("film/poster.jpg");
  poster.colorSpace = THREE.SRGBColorSpace;
  const blank = new THREE.MeshBasicMaterial({
    map: poster,
    color: new THREE.Color("#ffffff").multiplyScalar(0.55),
  });
  face.material = blank;
  const curtains = scr.userData.curtains;
  const shut = curtains.map((c) => c.position.x);
  let open = 0;
  const room = {
    name: "cinema",
    group: g,
    actors: audience,
    shot: {
      look: [0, y + 13, -16],
      yaw: 0,
      pitch: 0.06,
      dist: 70,
      fov: 30,
      span: 50,
      focus: [0, y + 12, -12],
    },
    close: {
      look: [0, y + 13, -r0 + 5],
      yaw: 0,
      pitch: 0.04,
      dist: 50,
      fov: 30,
      span: 34,
      focus: [0, y + 14, -r0 + 5],
    },
    lamps: [
      { at: [0, y + 22, -6], color: "#ffb86b", power: 260, reach: 45 },
      { at: [18, y + 9, -2], color: "#ffe2a8", power: 0, reach: 40 },
    ],
    key: { from: [20, 50, 70], color: "#ffd8b0", power: 1500 },
    beds: { room: 0.3 },
    hot: [
      { object: scr, label: "the screen", act: () => ctx.onPlay?.() },
      ...audience.map((m) => ({
        object: m.root,
        label: "a mouse in the audience",
        act: (f) => (ctx.foley.play("squeak-oh", { rate: 1.1 }), m.play(HOP, f)),
      })),
    ],
    /** Puts a playing video on the screen, the curtains drawn and the lantern lit; `null` ends the show. */
    show(video) {
      if (video) {
        const tex = new THREE.VideoTexture(video);
        tex.colorSpace = THREE.SRGBColorSpace;
        face.material = new THREE.MeshBasicMaterial({ map: tex, toneMapped: false });
      } else {
        if (face.material !== blank) face.material.map?.dispose();
        face.material = blank;
      }
      beam.visible = !!video;
      magic.userData.light.intensity = video ? 30 : 0;
      room.lamps[0].power = video ? 40 : 260;
      room.lamps[1].power = video ? 120 : 0;
      room.beds = video ? { projector: 0.12 } : { room: 0.3 };
      open = video ? 1 : 0;
      ctx.relight?.();
    },
    applaud(f) {
      ctx.foley.play("applause");
      audience.forEach((m, i) => m.play(HOP, f + i * 2));
    },
    update(f) {
      // The curtains are drawn a step at a time.
      curtains.forEach((c, i) => {
        const want = shut[i] + (i ? 1 : -1) * open * 11;
        c.position.x += Math.sign(want - c.position.x) * Math.min(1.2, Math.abs(want - c.position.x));
      });
      for (const m of audience) m.pose(f);
    },
  };
  return room;
}

/* ---------- the jetty, outside at the foot of the tower ---------- */

function jettyRoom(ctx) {
  const y = SEA_Y + 5;
  const g = new THREE.Group();
  const pier = jetty(66, 12);
  at(pier, 26, y, 38);
  const box = postbox();
  at(box, 86, y + 0.4, 34, -0.35);
  const marisol = boat();
  marisol.scale.setScalar(0.62);
  at(marisol, 62, SEA_Y + 6, 18, 1.5);
  const post = lampPost();
  at(post, 42, y + 0.4, 33);
  // A second Wick: stop-motion studios keep a double of the lead for another set.
  const wick = mouse("wick");
  at(wick.root, 76, y + 0.8, 39, -0.25);
  const lamp = lantern();
  lamp.position.set(0.2, -2.2, 0.6);
  wick.joints.pawR.add(lamp);
  wick.joints.armR.rotation.x = -0.9;
  lamp.userData.light.intensity = 40;
  const letter = envelope();
  letter.visible = false;
  g.add(pier, box, marisol, post, wick.root, letter);
  ctx.scene.add(g);
  let posted = null;
  return {
    name: "jetty",
    group: g,
    actors: [wick],
    closed: true,
    shot: {
      look: [66, y + 9, 38],
      yaw: 0.36,
      pitch: 0.17,
      dist: 90,
      fov: 30,
      span: 72,
      focus: [78, y + 8, 38],
    },
    lamps: [
      { at: [42, y + 24, 33], color: "#ffd48a", power: 480, reach: 70 },
      { at: [62, SEA_Y + 26, 20], color: "#ffc56b", power: 260, reach: 45 },
      { at: [77, y + 8, 42], color: "#ffb257", power: 140, reach: 25 },
    ],
    key: { from: [80, 90, 120], color: "#b8c8ff", power: 1600 },
    beds: { sea: 0.8, wind: 0.25 },
    hot: [
      { object: box, label: "the post-box", act: () => ctx.onPost?.() },
      { object: marisol, label: "the Marisol", act: () => ctx.foley.play("bell", { gain: 0.5, rate: 0.7 }) },
      { object: wick.root, label: "Wick", act: (f) => (ctx.foley.play("squeak-hello"), wick.play(WAVE, f)) },
    ],
    enter() {
      ctx.foley.play("gulls", { gain: 0.45, delay: 1.5 });
    },
    /** Posts the letter: it slides into the box, the flag goes up, Wick waves. */
    post(f) {
      letter.visible = true;
      letter.position.set(box.position.x - 3, box.position.y + 16, box.position.z + 4);
      posted = f;
      ctx.foley.play("letterbox");
      wick.play(WAVE, f + 10);
    },
    update(f) {
      marisol.position.y = SEA_Y + 6 + Math.round(Math.sin((f / 30) * TAU) * 6) / 10;
      marisol.rotation.z = Math.round(Math.sin((f / 26) * TAU) * 40) / 1000;
      if (posted !== null) {
        const k = f - posted;
        if (k < 8) letter.position.x += 0.45;
        else letter.visible = false;
        box.userData.flag.rotation.x = k > 8 ? -Math.min(1.4, (k - 8) * 0.35) : 0;
        if (k === 9) ctx.foley.play("stamp", { gain: 0.8 });
      }
      wick.pose(f);
    },
  };
}

/** Builds every floor into the scene, as `ctx.rooms`. */
export function buildRooms(ctx) {
  ctx.rooms = {};
  const makers = {
    lamp: lampRoom,
    writer: writerRoom,
    voice: voiceRoom,
    paint: paintRoom,
    motion: motionRoom,
    mix: mixRoom,
    cinema: cinemaRoom,
    jetty: jettyRoom,
  };
  for (const [name, make] of Object.entries(makers)) ctx.rooms[name] = make(ctx);
  return ctx.rooms;
}
