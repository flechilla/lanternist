/* The lighthouse, built as a model is: a tower of card and clay on a rock of clay, a sea of layered
 * cellophane, a painted sky with paper stars on threads. It is cut down the middle like a doll's
 * house. Its front half is there for the opening shots, and then a hand swings it open: behind it, one
 * floor for each job in the studio, the lamp room at the top and the cinema at the bottom. */

import * as THREE from "three";
import { card, cellophane, clay, felt, glow, metal } from "./clay.js";
import { blob, block, bricks, cutout, lathe, painted, part, pivot, planks, star, TAU } from "./shapes.js";
import { noise } from "./engine.js";

const FLOOR_H = 26;
/** The floors from the ground up, each a room of the studio. */
export const FLOORS = ["cinema", "mix", "motion", "paint", "voice", "writer"];
export const LAMP_Y = FLOORS.length * FLOOR_H;
export const SEA_Y = -16;
export const radius = (y) => 34 - y * 0.06;
const WALL = 2.6;
const BACK = [Math.PI / 2, Math.PI];
const FRONT = [-Math.PI / 2, Math.PI];

/** Where a floor's room starts, by name. */
export const floorY = (name) => FLOORS.indexOf(name) * FLOOR_H;

const CREAM = "#ece3d0";
const MADDER = "#b8473a";
const IRON = "#2a2f3a";

/** A slice of the tower's wall between two heights, tapering from r0 to r1: half of it, or all. */
function shell(y0, y1, r0, r1, [start, len], mat) {
  const n = Math.ceil((y1 - y0) / 2);
  const pts = Array.from(
    { length: n + 1 },
    (_, k) => new THREE.Vector2(r0 + ((r1 - r0) * k) / n, y0 + ((y1 - y0) * k) / n),
  );
  return part(new THREE.LatheGeometry(pts, 96, start, len), mat);
}

/** The outside of the tower, one half: cream card with red bands. */
function outside(half) {
  const g = new THREE.Group();
  const cream = clay(CREAM, { lump: 0.3, boil: 0, print: 0.5, freq: 0.2, mottle: 0.04 });
  const red = clay(MADDER, { lump: 0.1, boil: 0, print: 0.5, freq: 0.2, mottle: 0.05 });
  g.add(shell(-2, LAMP_Y + 2, radius(-2), radius(LAMP_Y + 2), half, cream));
  for (const [a, b] of [
    [22, 40],
    [78, 96],
    [128, 146],
  ]) {
    g.add(shell(a, b, radius(a) + 0.7, radius(b) + 0.7, half, red));
  }
  return g;
}

/** Windows on the outside, one per floor, climbing round the tower as a spiral stair would. Each pane
 * has its own glass, so a floor's windows light up when its crew wakes (`panes[floor]`). */
function windows(half, panes) {
  const g = new THREE.Group();
  const frame = clay(IRON, { lump: 0, boil: 0 });
  FLOORS.forEach((_, i) => {
    const y = i * FLOOR_H + 12;
    const a = half === FRONT ? (i % 2 ? -0.35 : 0.3) : Math.PI + (i % 2 ? -0.5 : 0.45);
    const r = radius(y) + 0.3;
    const w = pivot([Math.sin(a) * r, y, Math.cos(a) * r]);
    w.rotation.y = a;
    w.add(part(block(5.4, 8.4, 0.6, 0.3), frame));
    const lit = new THREE.MeshBasicMaterial({ color: new THREE.Color(LIT).multiplyScalar(1.6) });
    (panes[i] ??= []).push(lit);
    const pane = part(new THREE.PlaneGeometry(4.2, 7.2), lit, [0, 0, 0.35]);
    pane.castShadow = false;
    w.add(pane);
    g.add(w);
  });
  return g;
}

/** Where each room's window sits, as an angle round the back wall; the cinema and the animator's black
 * stage have none. */
const WINDOWS = { cinema: null, mix: 0.95, motion: null, paint: -0.5, voice: -0.62, writer: 0.52 };

/** Inside one floor: brick or panelled wall, a plank floor, and a window onto the night. */
function room(i, wallMat) {
  const y = i * FLOOR_H;
  const g = new THREE.Group();
  const r0 = radius(y) - WALL;
  const r1 = radius(y + FLOOR_H) - WALL;
  const wall = shell(y, y + FLOOR_H, r0, r1, BACK, wallMat);
  wall.material.side = THREE.BackSide;
  wall.castShadow = false;
  g.add(wall);

  const boards = planks(i % 2 ? "#6e4b30" : "#7b5536", 9);
  boards.repeat.set(1.5, 1.5);
  const floor = part(
    new THREE.CylinderGeometry(r0 + 0.2, r0 + 0.2, 2, 64, 1, false, ...BACK),
    card("#ffffff", boards, 0.75),
    [0, y - 1, 0],
  );
  g.add(floor);
  g.add(part(block(2 * r0, 2, 1.2, 0.3), clay("#5f3d22", { lump: 0, boil: 0 }), [0, y - 1, -0.2]));

  const angle = WINDOWS[FLOORS[i]];
  if (angle === null) return g;
  const view = painted(256, 384, (c, w, h) => {
    const wash = c.createLinearGradient(0, 0, 0, h);
    wash.addColorStop(0, "#0b1628");
    wash.addColorStop(0.62, "#1b2c4a");
    wash.addColorStop(0.64, "#1f3c5e");
    wash.addColorStop(1, "#122a45");
    c.fillStyle = wash;
    c.fillRect(0, 0, w, h);
    c.fillStyle = "#f3dcb4";
    for (let k = 0; k < 14; k++) c.fillRect(noise(i, k) * w, noise(i + 9, k) * h * 0.55, 3, 3);
    c.beginPath();
    c.arc(w * (0.3 + 0.4 * noise(i, 99)), h * 0.22, 26, 0, TAU);
    c.fill();
    c.fillStyle = "rgba(236,230,217,.35)";
    for (let k = 0; k < 6; k++) c.fillRect(0, h * 0.66 + k * 18, w, 2);
  });
  const rw = radius(y + 13) - WALL - 0.3;
  const win = pivot([Math.sin(angle) * rw, y + 13, -Math.cos(angle) * rw]);
  win.rotation.y = -angle;
  win.add(part(new THREE.PlaneGeometry(9, 13), new THREE.MeshBasicMaterial({ map: view })));
  const frameMat = clay("#3b2b22", { lump: 0.02, boil: 0 });
  win.add(part(block(10.4, 1.2, 1.2, 0.3), frameMat, [0, 7, 0.4]));
  win.add(part(block(10.4, 1.4, 2.6, 0.3), frameMat, [0, -7, 0.8]));
  for (const x of [-5, 5]) win.add(part(block(1.2, 14, 1.2, 0.3), frameMat, [x, 0, 0.4]));
  win.add(part(block(0.5, 13, 0.5, 0.2), frameMat, [0, 0, 0.4]));
  win.add(part(block(9, 0.5, 0.5, 0.2), frameMat, [0, 1.5, 0.4]));
  g.add(win);
  return g;
}

/** Wall treatments, one per room: what each job pins up or pads its walls with. */
function walls() {
  const b = bricks();
  b.repeat.set(5, 1.6);
  const brick = card("#ffffff", b, 0.95);
  const pan = planks("#8a6040", 12);
  pan.rotation = Math.PI / 2;
  pan.repeat.set(3, 1);
  const panel = card("#ffffff", pan, 0.8);
  const quilt = felt("#3f4f6b", { fuzz: 0.8 });
  const cork = card(
    "#ffffff",
    painted(256, 256, (c, w, h) => {
      c.fillStyle = "#b98e5e";
      c.fillRect(0, 0, w, h);
      for (let k = 0; k < 2600; k++) {
        c.fillStyle = noise(k, 1) > 0.5 ? "rgba(90,60,30,.35)" : "rgba(240,210,160,.3)";
        c.fillRect(noise(k, 2) * w, noise(k, 3) * h, 2, 2);
      }
    }),
    1,
  );
  cork.map.wrapS = cork.map.wrapT = THREE.RepeatWrapping;
  cork.map.repeat.set(6, 2);
  const velvet = felt("#5e1f1c", { fuzz: 0.6 });
  const black = felt("#15171c", { fuzz: 0.4 });
  return { cinema: velvet, mix: cork, motion: black, paint: brick, voice: quilt, writer: panel };
}

/* ---------- the lamp room and its gallery ---------- */

/** The great lamp: a beehive of glass rings round a flame, on a brass stand. */
function greatLamp() {
  const g = new THREE.Group();
  const brass = metal("#b98a3a", 0.3);
  g.add(part(new THREE.CylinderGeometry(3.4, 4.4, 5, 24), brass, [0, 2.5, 0]));
  g.add(part(new THREE.CylinderGeometry(5.8, 5.8, 0.8, 32), brass, [0, 5.4, 0]));
  const lens = new THREE.MeshPhysicalMaterial({
    color: "#fff1d6",
    roughness: 0.05,
    transparent: true,
    opacity: 0.55,
    clearcoat: 1,
    iridescence: 0.3,
    depthWrite: false,
  });
  for (let k = 0; k < 9; k++) {
    const y = 6.4 + k * 1.35;
    const r = 5.6 * Math.sin(0.35 + (k / 8) * 2.4);
    g.add(part(new THREE.TorusGeometry(r, 0.62, 10, 40), lens, [0, y, 0], [Math.PI / 2, 0, 0]));
  }
  g.add(part(new THREE.CylinderGeometry(4.4, 4.4, 0.6, 32), brass, [0, 18.8, 0]));
  const heart = part(blob(2.1, 3.2, 2.1, 20), glow("#ffd48a", 1), [0, 12, 0]);
  heart.castShadow = false;
  g.add(heart);
  // It lights the lamp room and the gallery, and falls away before the floors below.
  const light = new THREE.PointLight("#ffc56b", 0, 120, 2);
  light.position.y = 12;
  g.add(light);
  g.userData = { heart, light };
  return g;
}

function lampRoom() {
  const y = LAMP_Y;
  const g = new THREE.Group();
  const iron = clay(IRON, { lump: 0.03, boil: 0, print: 0.4 });
  const walk = planks("#5b5f66", 10);
  walk.repeat.set(2, 2);
  const gallery = part(new THREE.CylinderGeometry(33, 31, 2.2, 72), card("#ffffff", walk, 0.8), [
    0,
    y + 1,
    0,
  ]);
  g.add(gallery);
  for (let k = 0; k < 36; k++) {
    const a = (k / 36) * TAU;
    g.add(
      part(new THREE.CylinderGeometry(0.3, 0.3, 8, 6), iron, [Math.sin(a) * 31.8, y + 6, Math.cos(a) * 31.8]),
    );
  }
  g.add(part(new THREE.TorusGeometry(31.8, 0.5, 8, 96), iron, [0, y + 10, 0], [Math.PI / 2, 0, 0]));
  g.add(part(new THREE.TorusGeometry(31.8, 0.3, 6, 96), iron, [0, y + 5.5, 0], [Math.PI / 2, 0, 0]));
  g.add(
    part(new THREE.CylinderGeometry(18, 18, 4, 48), clay(MADDER, { lump: 0.05, boil: 0 }), [0, y + 4, 0]),
  );

  const glass = new THREE.MeshPhysicalMaterial({
    color: "#cfe0ea",
    transparent: true,
    opacity: 0.07,
    roughness: 0.05,
    clearcoat: 1,
    depthWrite: false,
  });
  const pane = new THREE.Mesh(new THREE.CylinderGeometry(17.5, 17.5, 20, 48, 1, true), glass);
  pane.position.y = y + 16;
  g.add(pane);
  for (let k = 0; k < 12; k++) {
    const a = (k / 12) * TAU;
    g.add(
      part(new THREE.CylinderGeometry(0.35, 0.35, 20, 6), iron, [
        Math.sin(a) * 17.6,
        y + 16,
        Math.cos(a) * 17.6,
      ]),
    );
  }
  g.add(part(new THREE.TorusGeometry(17.6, 0.5, 8, 64), iron, [0, y + 26, 0], [Math.PI / 2, 0, 0]));
  const dome = lathe(
    [
      [19.5, 0],
      [18.5, 1.5],
      [15, 5],
      [9, 9.5],
      [3, 12.5],
      [0, 13],
    ],
    48,
  );
  g.add(part(dome, clay("#3a2a2a", { lump: 0.1, boil: 0, freq: 0.3 }), [0, y + 26, 0]));
  g.add(part(new THREE.CylinderGeometry(1.2, 1.6, 4, 16), iron, [0, y + 40, 0]));
  g.add(part(blob(2.4), iron, [0, y + 43.5, 0]));
  g.add(part(new THREE.CylinderGeometry(0.18, 0.18, 12, 6), iron, [0, y + 51, 0]));

  const lamp = greatLamp();
  lamp.position.y = y + 5.8;
  g.add(lamp);
  g.userData.lamp = lamp.userData;
  return g;
}

/** The lamp's beam, seen side on: two long cones of light that sweep as the lamp turns. */
export function beams() {
  const mat = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide,
    uniforms: { strength: { value: 0 } },
    vertexShader: /* glsl */ `
      varying float vAlong; varying vec3 vN; varying vec3 vV;
      void main() {
        vAlong = uv.y;
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        vN = normalize(normalMatrix * normal); vV = normalize(-mv.xyz);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */ `
      uniform float strength; varying float vAlong; varying vec3 vN; varying vec3 vV;
      void main() {
        float edge = pow(abs(dot(vN, vV)), 1.6);
        float a = strength * edge * pow(vAlong, 1.8) * 0.45;
        gl_FragColor = vec4(vec3(1.0, 0.86, 0.6) * a, a);
      }`,
  });
  const g = new THREE.Group();
  for (const s of [1, -1]) {
    const cone = new THREE.CylinderGeometry(2.5, 70, 420, 32, 1, true);
    cone.translate(0, -210, 0);
    cone.rotateZ(s * (Math.PI / 2));
    const m = new THREE.Mesh(cone, mat);
    m.renderOrder = 5;
    g.add(m);
  }
  g.userData.mat = mat;
  return g;
}

/* ---------- rock, sea and sky ---------- */

function rock() {
  const g = new THREE.Group();
  const dark = clay("#343a45", { lump: 1.4, boil: 0, print: 0.5, freq: 0.12, mottle: 0.1 });
  const mid = clay("#454c59", { lump: 1.2, boil: 0, print: 0.5, freq: 0.14, mottle: 0.1 });
  // The tower stands on the rock's crown, at y = 0; nothing of the rock rises into the ground floor.
  const stones = [
    [0, -18, -6, 46, 16, 42, dark],
    [-32, -22, 10, 20, 14, 18, mid],
    [34, -21, 6, 18, 13, 20, mid],
    [-8, -24, 30, 22, 10, 14, dark],
    [18, -25, 28, 16, 9, 12, mid],
    [-38, -26, -18, 16, 12, 16, dark],
    [40, -26, -20, 18, 11, 16, dark],
  ];
  for (const [x, y, z, rx, ry, rz, m] of stones) g.add(part(blob(rx, ry, rz, 40), m, [x, y, z]));
  return g;
}

/** A strip of cellophane sea: a band with a scalloped top, wider than the view. */
function wave(y, z, amp, len, color) {
  const s = new THREE.Shape();
  s.moveTo(-700, y - 40);
  s.lineTo(-700, y);
  for (let x = -700; x < 700; x += len) s.quadraticCurveTo(x + len / 2, y + amp * 2, x + len, y);
  s.lineTo(700, y - 40);
  const m = part(cutout(s, 1.2, 0.4), cellophane(color, 0.7), [0, 0, z]);
  m.receiveShadow = false;
  return m;
}

export function sea() {
  const g = new THREE.Group();
  const rows = [
    [SEA_Y - 2, -240, 5, 60, "#1c3a5c"],
    [SEA_Y - 1, -120, 6, 70, "#21466b"],
    [SEA_Y, 0, 7, 80, "#28547c"],
    [SEA_Y - 1, 60, 8, 90, "#2e5f8a"],
    [SEA_Y - 3, 110, 9, 110, "#356a96"],
  ];
  const strips = rows.map(([y, z, amp, len, c], k) => {
    const w = wave(y, z, amp, len, c);
    w.userData.k = k;
    g.add(w);
    return w;
  });
  g.userData.strips = strips;
  return g;
}

/** Rocks the sea on twos: each strip slides and bobs a little, out of step with the next. */
export function swell(g, f) {
  for (const w of g.userData.strips) {
    const k = w.userData.k;
    w.position.x = Math.round(Math.sin((f / (30 + k * 6)) * TAU + k) * 10);
    w.position.y = Math.round(Math.sin((f / (20 + k * 4)) * TAU + k * 2) * 1.5 * 10) / 10;
  }
}

/** A cotton-wool cloud: a heap of fluffy balls. */
function cloud(x, y, z, s, seed) {
  const g = new THREE.Group();
  const wool = felt("#8d9bb8", { fuzz: 2.4, lump: 0.6, boil: 0.1, freq: 0.5 });
  for (let k = 0; k < 7; k++) {
    const r = s * (0.5 + 0.5 * noise(seed, k));
    g.add(
      part(blob(r * 1.2, r, r), wool, [
        (k - 3) * s * 0.7,
        noise(seed + 3, k) * s * 0.4,
        noise(seed + 5, k) * s * 0.3,
      ]),
    );
  }
  g.position.set(x, y, z);
  return g;
}

/** A paper star on a thread from above the frame. */
function hangingStar(x, y, z, r, len, color = "#f3dcb4") {
  const g = pivot([x, y + len, z]);
  const thread = new THREE.Mesh(
    new THREE.CylinderGeometry(0.08, 0.08, len, 4),
    new THREE.MeshBasicMaterial({ color: "#c8c2b4", transparent: true, opacity: 0.5 }),
  );
  thread.position.y = -len / 2;
  g.add(thread);
  g.add(part(cutout(star(r), 0.4, 0.2), card(color, null, 0.9), [0, -len - r * 0.9, 0]));
  return g;
}

export function sky() {
  const g = new THREE.Group();
  const backdrop = painted(2048, 1024, (c, w, h) => {
    const grad = c.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, "#050a16");
    grad.addColorStop(0.45, "#0f1d36");
    grad.addColorStop(0.7, "#1b2d4d");
    grad.addColorStop(1, "#23385c");
    c.fillStyle = grad;
    c.fillRect(0, 0, w, h);
    for (let k = 0; k < 500; k++) {
      c.fillStyle = `rgba(243,220,180,${0.25 + 0.6 * noise(k, 4)})`;
      const s = 1 + Math.floor(noise(k, 5) * 3);
      c.fillRect(noise(k, 6) * w, noise(k, 7) * h * 0.7, s, s);
    }
    // Brush strokes, as a scene painter leaves them on a cyclorama.
    c.globalAlpha = 0.05;
    for (let k = 0; k < 90; k++) {
      c.strokeStyle = noise(k, 8) > 0.5 ? "#3a5680" : "#050a16";
      c.lineWidth = 20 + noise(k, 9) * 60;
      c.beginPath();
      const yy = noise(k, 10) * h;
      c.moveTo(0, yy);
      c.bezierCurveTo(w * 0.3, yy - 40, w * 0.6, yy + 40, w, yy);
      c.stroke();
    }
  });
  const cyc = new THREE.Mesh(
    new THREE.CylinderGeometry(1400, 1400, 1600, 64, 1, true, Math.PI * 0.55, Math.PI * 0.9),
    new THREE.MeshBasicMaterial({ map: backdrop, side: THREE.BackSide, fog: false }),
  );
  cyc.position.set(0, 300, 0);
  g.add(cyc);

  const moon = pivot([-230, 330, -520]);
  moon.add(
    part(cutout(new THREE.Shape().absarc(0, 0, 38, 0, TAU), 3, 1), card("#f3dcb4", null, 0.9)),
    part(new THREE.CylinderGeometry(0.2, 0.2, 400, 4), card("#c8c2b4"), [0, 220, -2]),
  );
  for (const [x, y, r] of [
    [-12, 9, 7],
    [14, -12, 5],
    [8, 16, 4],
  ]) {
    moon.add(
      part(new THREE.CylinderGeometry(r, r, 0.8, 20), card("#dcc394"), [x, y, 2.8], [Math.PI / 2, 0, 0]),
    );
  }
  g.add(moon);

  const stars = [
    [-160, 250, -300, 8, 90],
    [-60, 300, -360, 6, 60],
    [90, 270, -320, 9, 110],
    [190, 310, -380, 7, 70],
    [-300, 210, -420, 10, 140],
    [300, 230, -440, 8, 120],
    [20, 330, -460, 6, 50],
  ].map(([x, y, z, r, len]) => hangingStar(x, y, z, r, len));
  for (const s of stars) g.add(s);
  const clouds = [
    cloud(-140, 190, -260, 22, 1),
    cloud(160, 215, -300, 26, 2),
    cloud(-10, 260, -420, 30, 3),
    cloud(320, 170, -380, 24, 4),
  ];
  for (const c of clouds) g.add(c);
  g.userData = { stars, clouds };
  return g;
}

/** Swings the paper stars on their threads and lets the clouds drift, on twos. */
export function breeze(g, f) {
  g.userData.stars.forEach((s, k) => {
    s.rotation.z = Math.round(Math.sin((f / (40 + k * 5)) * TAU + k) * 60) / 1000;
  });
  g.userData.clouds.forEach((c, k) => {
    c.position.x += Math.sin((f / 400) * TAU + k) * 0.08;
  });
}

/* ---------- the whole model ---------- */

const LIT = "#ffc56b";
const DARK = "#1a2230";

export function lighthouse() {
  const g = new THREE.Group();
  const panes = [];
  const front = new THREE.Group();
  front.add(outside(FRONT), windows(FRONT, panes));
  const back = new THREE.Group();
  back.add(outside(BACK), windows(BACK, panes));
  const finish = walls();
  const top = lampRoom();
  g.add(front, back, ...FLOORS.map((name, i) => room(i, finish[name])), top, rock());
  /** Lights or darkens one floor's windows. */
  const wake = (i, on) => {
    for (const m of panes[i]) m.color.set(on ? LIT : DARK).multiplyScalar(on ? 1.6 : 1);
  };
  g.userData = { front, top, wake };
  return g;
}
