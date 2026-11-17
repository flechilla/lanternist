/* The props on each floor, built big: a mouse is nine centimetres tall, and the tools of each job are
 * too large for it, so the crew climbs them. A typewriter the mice hop across, a microphone taller than
 * its singer, a camera on a tripod, a desk of bottle caps and matchsticks. Each builder returns a group
 * standing on y = 0, facing +z, with the parts that move named in `userData`. */

import * as THREE from "three";
import { card, cellophane, clay, felt, glow, metal } from "./clay.js";
import { blob, block, cutout, lathe, painted, paper, part, pivot, roll, taper, TAU, v3 } from "./shapes.js";
import { noise } from "./engine.js";

const IRON = "#26292f";
const BRASS = "#b98a3a";
const OAK = "#7b5230";
const OAK_DK = "#5f3d22";
const CREAM = "#ece3d0";

/* ---------- the writer's floor ---------- */

/** A tall manual typewriter with its sheet of paper in. `userData.keys` are the keys, in rows. */
export function typewriter(pageTex) {
  const g = new THREE.Group();
  const enamel = clay("#20352c", { lump: 0.04, boil: 0, print: 0.3, rough: 0.35 });
  const chrome = metal("#c9c6be", 0.25);
  const rubber = clay("#15171a", { lump: 0, boil: 0, rough: 0.7 });
  g.add(part(block(26, 7, 18, 2.4), enamel, [0, 3.5, 0]));
  g.add(part(block(24, 5, 8, 2), enamel, [0, 8.5, -5.5]));
  g.add(part(block(27, 1.2, 19, 0.6), rubber, [0, 0.6, 0]));
  const plate = paper(256, 48, (c, w, h) => {
    c.fillStyle = "#20352c";
    c.fillRect(0, 0, w, h);
    c.fillStyle = "#e9dcc0";
    c.font = "700 21px 'Courier Prime', monospace";
    c.textAlign = "center";
    c.fillText("L A N T E R N I S T", w / 2, 31);
  });
  g.add(part(new THREE.PlaneGeometry(12, 2.2), card("#ffffff", plate, 0.4), [0, 5.2, 9.05]));

  // Keys in four stepped rows, each a little cylinder with a cream cap.
  const keys = [];
  const stem = new THREE.CylinderGeometry(0.28, 0.28, 2.2, 8);
  const cap = new THREE.CylinderGeometry(0.95, 0.95, 0.55, 20);
  const capMat = clay("#eee4cf", { lump: 0, boil: 0.01, print: 0.3, rough: 0.4 });
  const ringMat = metal("#bfbab0", 0.3);
  for (let r = 0; r < 4; r++) {
    const row = [];
    const n = 10 - (r === 3 ? 1 : 0);
    for (let k = 0; k < n; k++) {
      const x = (k - (n - 1) / 2) * 2.3 + (r % 2) * 0.6;
      const z = 6.5 - r * 2.3;
      const y = 7.6 + r * 0.9;
      const key = pivot([x, y, z]);
      key.add(
        part(stem, ringMat, [0, -1, 0]),
        part(cap, capMat),
        part(new THREE.TorusGeometry(0.95, 0.12, 6, 20), ringMat, [0, 0, 0], [Math.PI / 2, 0, 0]),
      );
      g.add(key);
      row.push(key);
    }
    keys.push(row);
  }
  g.add(part(block(12, 1, 1.8, 0.45), capMat, [0, 6.9, 8.6]));

  const carriage = pivot([0, 13.4, -6]);
  carriage.add(part(new THREE.CylinderGeometry(1.9, 1.9, 28, 28), rubber, [0, 0, 0], [0, 0, Math.PI / 2]));
  for (const s of [-1, 1])
    carriage.add(
      part(new THREE.CylinderGeometry(1.4, 1.4, 1.8, 20), chrome, [s * 15, 0, 0], [0, 0, Math.PI / 2]),
    );
  carriage.add(
    part(
      taper(
        new THREE.CatmullRomCurve3([v3(-14, 0.5, 1), v3(-17, 3, 2.5), v3(-19, 4.5, 5.5)]),
        0.35,
        0.3,
        12,
        6,
      ),
      chrome,
    ),
  );
  carriage.add(part(blob(0.8), chrome, [-19, 4.6, 5.8]));
  // The sheet leaves the roller and curls back, typed on the side that faces the room.
  const sheet = new THREE.PlaneGeometry(13, 10, 1, 12);
  const pos = sheet.attributes.position;
  for (let i = 0; i < pos.count; i++) {
    const y = pos.getY(i) + 5;
    pos.setY(i, y);
    pos.setZ(i, -0.02 * y * y);
  }
  sheet.computeVertexNormals();
  const page = part(
    sheet,
    new THREE.MeshStandardMaterial({ map: pageTex, roughness: 0.9, side: THREE.DoubleSide }),
    [0, 1.2, 1.2],
    [-0.12, 0, 0],
  );
  carriage.add(page);
  g.add(carriage);
  g.userData.keys = keys;
  return g;
}

/** A crumpled ball of paper: a sphere pushed in all over. */
export function crumple(r, seed) {
  const g = new THREE.IcosahedronGeometry(r, 3);
  const pos = g.attributes.position;
  const p = new THREE.Vector3();
  for (let i = 0; i < pos.count; i++) {
    p.fromBufferAttribute(pos, i);
    const k =
      0.8 + 0.28 * Math.abs(Math.sin(p.x * 3.1 + seed) * Math.cos(p.y * 2.7 - seed) + Math.sin(p.z * 3.7));
    pos.setXYZ(i, p.x * k, p.y * k, p.z * k);
  }
  g.computeVertexNormals();
  return part(g, clay("#e6dcc6", { lump: 0.05, boil: 0.01, print: 0, rough: 0.9 }));
}

/** An anglepoise desk lamp, its bulb lit. */
export function deskLamp(color = "#3d8a5a") {
  const g = new THREE.Group();
  const paint = clay(color, { lump: 0.02, boil: 0, rough: 0.45 });
  const chrome = metal("#c9c6be", 0.3);
  g.add(part(new THREE.CylinderGeometry(3, 3.4, 1, 24), paint, [0, 0.5, 0]));
  g.add(part(new THREE.CylinderGeometry(0.3, 0.3, 11, 8), chrome, [1.4, 5.7, 0], [0, 0, -0.28]));
  g.add(part(new THREE.CylinderGeometry(0.3, 0.3, 9, 8), chrome, [5.1, 12.6, 0], [0, 0, 1.0]));
  const head = pivot([8.8, 14.4, 0]);
  head.rotation.z = -0.5;
  head.add(
    part(
      lathe(
        [
          [0.8, 1.6],
          [1.4, 1.2],
          [3.2, -1.2],
          [3.4, -1.6],
        ],
        28,
      ),
      paint,
    ),
  );
  const bulb = part(blob(1.2, 1.2, 1.2, 16), glow("#ffe2a8", 3), [0, -1, 0]);
  bulb.castShadow = false;
  head.add(bulb);
  g.add(head);
  return g;
}

/** A stack of books, each a little askew. */
export function books(colors = ["#8f3528", "#2f5a88", "#c9973f", "#3d8a5a"]) {
  const g = new THREE.Group();
  let y = 0;
  colors.forEach((c, k) => {
    const h = 1.6 + noise(k, 3) * 0.8;
    const b = pivot([noise(k, 1) * 1.4 - 0.7, y + h / 2, noise(k, 2) - 0.5]);
    b.rotation.y = (noise(k, 4) - 0.5) * 0.4;
    b.add(part(block(9, h, 6.5, 0.3), clay(c, { lump: 0.02, boil: 0 })));
    b.add(part(block(8.4, h * 0.8, 6.6, 0.1), card("#efe6d2"), [0.4, 0, 0]));
    g.add(b);
    y += h;
  });
  return g;
}

/* ---------- the voice's floor ---------- */

/** A ribbon microphone on a stand, taller than the mouse who sings into it. */
export function microphone(height = 11) {
  const g = new THREE.Group();
  const chrome = metal("#d2d0ca", 0.22);
  const grille = painted(128, 256, (c, w, h) => {
    c.fillStyle = "#8f8d88";
    c.fillRect(0, 0, w, h);
    c.fillStyle = "#3a3936";
    for (let x = 4; x < w; x += 10) c.fillRect(x, 0, 4, h);
  });
  g.add(part(new THREE.CylinderGeometry(3.4, 3.8, 0.8, 32), metal(IRON, 0.35), [0, 0.4, 0]));
  g.add(part(new THREE.CylinderGeometry(0.35, 0.35, height, 10), chrome, [0, height / 2, 0]));
  const head = pivot([0, height + 5.2, 0]);
  head.add(part(roll(2.6, 5.2, 24), card("#ffffff", grille, 0.5), [0, 0, 0]));
  head.add(part(new THREE.TorusGeometry(2.8, 0.35, 10, 32), chrome, [0, 0, 0], [0, Math.PI / 2, 0]));
  head.add(part(new THREE.CylinderGeometry(2.7, 2.7, 0.5, 28), chrome, [0, 0, 0]));
  head.add(part(block(1.6, 2, 1.6, 0.4), chrome, [0, -5.4, 0]));
  g.add(head);
  const sign = pivot([0, height + 12.5, 0]);
  const onAir = painted(256, 96, (c, w, h) => {
    c.fillStyle = "#3a0c0a";
    c.fillRect(0, 0, w, h);
    c.fillStyle = "#ffd6c8";
    c.font = "700 52px 'Courier Prime', monospace";
    c.textAlign = "center";
    c.fillText("ON AIR", w / 2, 66);
  });
  const lit = new THREE.MeshBasicMaterial({
    map: onAir,
    color: new THREE.Color("#ff6a4a").multiplyScalar(0.5),
  });
  sign.add(part(block(8.6, 3.4, 1.4, 0.5), clay("#2b2f38", { lump: 0, boil: 0 })));
  const face = part(new THREE.PlaneGeometry(8, 3), lit, [0, 0, 0.75]);
  face.castShadow = false;
  sign.add(face);
  g.userData.lit = lit;
  return g;
}

/** A gramophone with its horn, and the record on it. */
export function gramophone() {
  const g = new THREE.Group();
  const wood = clay(OAK, { lump: 0.04, boil: 0, print: 0.3 });
  const brass = metal(BRASS, 0.3);
  g.add(part(block(11, 5, 11, 0.6), wood, [0, 2.5, 0]));
  const platter = pivot([0, 5.3, 0]);
  platter.add(part(new THREE.CylinderGeometry(4.6, 4.6, 0.4, 36), clay("#2a1f1c", { lump: 0, boil: 0 })));
  const disc = pivot([0, 0.35, 0]);
  platter.add(disc);
  g.add(platter);
  g.add(part(new THREE.CylinderGeometry(0.5, 0.6, 3, 10), brass, [4.2, 6.5, -4.2]));
  const arm = pivot([4.2, 8, -4.2]);
  arm.add(
    part(
      taper(
        new THREE.CatmullRomCurve3([v3(0, 0, 0), v3(-1.5, 0.5, 2.5), v3(-3.6, -1.2, 4.2)]),
        0.4,
        0.3,
        10,
        6,
      ),
      brass,
    ),
  );
  g.add(arm);
  const horn = lathe(
    [
      [0.5, 0],
      [0.6, 3],
      [1.2, 7],
      [3, 10],
      [6.5, 12],
      [7, 12.2],
    ],
    32,
  );
  horn.scale(0.72, 0.8, 0.72);
  const hornMesh = part(horn, brass, [4.2, 8.4, -4.2], [0.75, 0.9, -0.35]);
  hornMesh.material.side = THREE.DoubleSide;
  g.add(hornMesh);
  g.userData = { platter, record: disc };
  return g;
}

/** A record for one language: black, with a coloured paper label. */
export function record(label, color, r = 4.2) {
  const g = new THREE.Group();
  g.add(part(new THREE.CylinderGeometry(r, r, 0.18, 40), clay("#101114", { lump: 0, boil: 0, rough: 0.3 })));
  const tex = painted(128, 128, (c, w, h) => {
    c.fillStyle = color;
    c.beginPath();
    c.arc(w / 2, h / 2, w / 2, 0, TAU);
    c.fill();
    c.fillStyle = "#1a1407";
    c.font = "700 26px 'Figtree', sans-serif";
    c.textAlign = "center";
    c.fillText(label, w / 2, h / 2 + 9);
  });
  const face = card("#ffffff", tex, 0.8);
  const vinyl = clay("#101114", { lump: 0, boil: 0, rough: 0.3 });
  g.add(part(new THREE.CylinderGeometry(r * 0.42, r * 0.42, 0.22, 28), [vinyl, face, face], [0, 0.02, 0]));
  return g;
}

/* ---------- the painter's floor ---------- */

/** An easel with a canvas on it. `userData.canvas` is the painted face, to swap pictures on. */
export function easel() {
  const g = new THREE.Group();
  const wood = clay("#9c7348", { lump: 0.03, boil: 0, print: 0.3 });
  g.add(part(new THREE.CylinderGeometry(0.45, 0.45, 30, 8), wood, [-6, 14.6, 0.6], [0.06, 0, 0.2]));
  g.add(part(new THREE.CylinderGeometry(0.45, 0.45, 30, 8), wood, [6, 14.6, 0.6], [0.06, 0, -0.2]));
  g.add(part(new THREE.CylinderGeometry(0.45, 0.45, 28, 8), wood, [0, 13.4, -5], [-0.36, 0, 0]));
  g.add(part(block(17, 1, 3, 0.3), wood, [0, 7.4, 1.6]));
  const board = pivot([0, 16.5, 1.9]);
  board.rotation.x = -0.1;
  board.add(part(block(20.5, 15.5, 0.9, 0.3), clay("#e9e2d2", { lump: 0.02, boil: 0 })));
  const face = part(
    new THREE.PlaneGeometry(19.4, 14.4),
    new THREE.MeshStandardMaterial({ color: "#efe6d2", roughness: 0.9 }),
    [0, 0, 0.47],
  );
  board.add(face);
  g.add(board);
  g.userData.canvas = face;
  return g;
}

/** A pot of paint: a bottle cap full of one colour, for one of the picture styles. */
export function paintPot(color) {
  const g = new THREE.Group();
  g.add(part(new THREE.CylinderGeometry(2, 2.1, 1.8, 20, 1, true), metal("#c9c6be", 0.35), [0, 0.9, 0]));
  g.add(
    part(
      new THREE.CylinderGeometry(1.9, 1.9, 0.3, 20),
      clay(color, { lump: 0.02, boil: 0.02, rough: 0.2 }),
      [0, 1.5, 0],
    ),
  );
  g.add(part(new THREE.CylinderGeometry(2.1, 2.1, 0.3, 20), metal("#9d9990", 0.4), [0, 0.15, 0]));
  return g;
}

/** A long paintbrush, its tip dipped in `color`. */
export function brush(color = "#c0503f") {
  const g = new THREE.Group();
  g.add(part(new THREE.CylinderGeometry(0.28, 0.2, 12, 8), clay("#b8433a", { lump: 0, boil: 0 }), [0, 6, 0]));
  g.add(part(new THREE.CylinderGeometry(0.34, 0.3, 1.4, 8), metal("#c9c6be", 0.3), [0, 12.6, 0]));
  g.add(part(new THREE.ConeGeometry(0.42, 2.4, 10), clay(color, { lump: 0, boil: 0.02 }), [0, 14.4, 0]));
  return g;
}

/* ---------- the animator's floor ---------- */

/** A 16 mm camera on a tripod, like the ones stop-motion was shot on. */
export function filmCamera() {
  const g = new THREE.Group();
  const body = clay("#8c8e93", { lump: 0.02, boil: 0, print: 0.3, rough: 0.45 });
  const black = clay("#1b1c20", { lump: 0, boil: 0, rough: 0.5 });
  const chrome = metal("#cfcbc2", 0.25);
  for (const a of [0, 2.1, 4.2]) {
    const leg = pivot([0, 13, 0]);
    leg.rotation.set(0.33 * Math.cos(a), a, 0.33 * Math.sin(a));
    leg.add(part(new THREE.CylinderGeometry(0.35, 0.3, 14, 8), black, [0, -7, 0]));
    g.add(leg);
  }
  g.add(part(new THREE.CylinderGeometry(1.6, 1.6, 1.2, 16), black, [0, 13.4, 0]));
  const head = pivot([0, 17.5, 0]);
  head.add(part(block(6, 6.6, 7.5, 1.2), body));
  head.add(part(block(1.2, 5.4, 6.4, 0.4), black, [-3.4, 0, 0]));
  const turret = pivot([0, 0.8, 4]);
  turret.add(part(new THREE.CylinderGeometry(2.4, 2.4, 0.8, 24), chrome, [0, 0, 0], [Math.PI / 2, 0, 0]));
  for (const [x, y, l] of [
    [0, 1.2, 3.4],
    [-1.1, -0.8, 2.2],
    [1.1, -0.8, 1.6],
  ]) {
    turret.add(
      part(new THREE.CylinderGeometry(0.7, 0.8, l, 16), black, [x, y, l / 2 + 0.4], [Math.PI / 2, 0, 0]),
    );
  }
  head.add(turret);
  head.add(part(roll(0.6, 3), black, [0.6, 3.8, -1.2], [Math.PI / 2, 0, 0]));
  const crank = pivot([3.4, -0.8, -1]);
  crank.add(part(block(0.6, 3, 0.6, 0.2), chrome, [0.4, -1.2, 0]), part(blob(0.6), black, [0.9, -2.6, 0]));
  head.add(crank);
  const pilot = part(blob(0.35), glow("#ff4a3a", 0.4), [2.2, 2.6, 3.2]);
  pilot.castShadow = false;
  head.add(pilot);
  g.add(head);
  g.userData.pilot = pilot;
  return g;
}

/** A plain table: a top and four legs. */
export function table(w, d, h, color = OAK) {
  const g = new THREE.Group();
  const wood = clay(color, { lump: 0.03, boil: 0, print: 0.3 });
  g.add(part(block(w, 1.4, d, 0.4), wood, [0, h - 0.7, 0]));
  for (const [x, z] of [
    [-1, -1],
    [1, -1],
    [-1, 1],
    [1, 1],
  ]) {
    g.add(
      part(new THREE.CylinderGeometry(0.6, 0.5, h - 1.4, 8), wood, [
        x * (w / 2 - 1.4),
        (h - 1.4) / 2,
        z * (d / 2 - 1.4),
      ]),
    );
  }
  return g;
}

/** A little model lighthouse on a board of cellophane sea: the set inside the set. */
export function modelLighthouse() {
  const g = new THREE.Group();
  g.add(part(block(26, 1, 14, 0.3), clay("#23324a", { lump: 0.02, boil: 0 }), [0, 0.5, 0]));
  for (const [z, c] of [
    [-3, "#28547c"],
    [1, "#2e5f8a"],
    [4.5, "#356a96"],
  ]) {
    const s = new THREE.Shape();
    s.moveTo(-13, 0);
    for (let x = -13; x < 13; x += 3) s.quadraticCurveTo(x + 1.5, 1.6, x + 3, 0.8);
    s.lineTo(13, -1);
    s.lineTo(-13, -1);
    g.add(part(cutout(s, 0.3, 0.1), cellophane(c, 0.8), [0, 1.8, z]));
  }
  const tower = lathe(
    [
      [2.4, 0],
      [2.3, 4],
      [1.9, 11],
      [0, 11.2],
    ],
    24,
  );
  g.add(part(blob(4.2, 1.8, 3.6), clay("#343a45", { lump: 0.3, boil: 0 }), [-7, 1.4, -2]));
  g.add(part(tower, clay("#ece3d0", { lump: 0.03, boil: 0 }), [-7, 2.6, -2]));
  for (const y of [4.6, 8]) {
    const r = 2.3 - ((y - 4) / 7) * 0.4 + 0.12;
    g.add(
      part(new THREE.CylinderGeometry(r - 0.06, r, 1.4, 24), clay("#b8473a", { lump: 0, boil: 0 }), [
        -7,
        2.6 + y,
        -2,
      ]),
    );
  }
  g.add(
    part(
      new THREE.CylinderGeometry(2.6, 2.6, 0.35, 24),
      clay("#2a2f3a", { lump: 0, boil: 0 }),
      [-7, 13.6, -2],
    ),
  );
  const light = part(blob(1.1), glow("#ffc56b", 2.5), [-7, 14.8, -2]);
  light.castShadow = false;
  g.add(light);
  return g;
}

/* ---------- the editor's floor ---------- */

/** The mixing desk: a long box of knobs and faders with a loudness meter on top. */
export function mixingDesk() {
  const g = new THREE.Group();
  const wood = clay("#5f3d22", { lump: 0.03, boil: 0, print: 0.3 });
  const top = clay("#2b2f38", { lump: 0.02, boil: 0, rough: 0.5 });
  g.add(part(block(30, 6, 14, 0.8), wood, [0, 3, 0]));
  const face = pivot([0, 6.2, 0]);
  face.rotation.x = 0.28;
  face.add(part(block(28, 0.8, 13, 0.3), top));
  const colors = ["#c0503f", "#f0b14a", "#3d8a5a", "#2f5a88", "#ece3d0"];
  for (let c = 0; c < 8; c++) {
    for (let r = 0; r < 3; r++) {
      face.add(
        part(
          new THREE.CylinderGeometry(0.75, 0.8, 0.9, 16),
          clay(colors[(c + r) % 5], { lump: 0, boil: 0.01, rough: 0.4 }),
          [-12 + c * 2.6, 0.8, -4.5 + r * 2.2],
        ),
      );
    }
  }
  const faders = [];
  for (let c = 0; c < 8; c++) {
    face.add(
      part(block(0.5, 0.3, 5, 0.1), clay("#0d0e11", { lump: 0, boil: 0 }), [-12 + c * 2.6, 0.45, 3.4]),
    );
    const cap = part(block(1.6, 1, 1, 0.3), clay(c < 2 ? "#f0b14a" : "#d9d4c8", { lump: 0, boil: 0 }), [
      -12 + c * 2.6,
      0.9,
      3.4,
    ]);
    face.add(cap);
    faders.push(cap);
  }
  g.add(face);
  const meter = pivot([8, 9.5, -5.5]);
  meter.add(part(block(10, 7, 3, 0.6), wood));
  const dial = painted(256, 160, (c, w, h) => {
    c.fillStyle = "#f3e2b4";
    c.fillRect(0, 0, w, h);
    c.strokeStyle = "#2b2f38";
    c.lineWidth = 3;
    c.beginPath();
    c.arc(w / 2, h + 20, 150, Math.PI * 1.2, Math.PI * 1.8);
    c.stroke();
    c.fillStyle = "#2b2f38";
    c.font = "700 20px 'Courier Prime', monospace";
    c.textAlign = "center";
    const marks = [-30, -24, -16, -10, -6];
    marks.forEach((m, i) => {
      const a = Math.PI * (1.2 + (0.6 * i) / (marks.length - 1));
      c.fillStyle = m === -16 ? "#b8433a" : "#2b2f38";
      c.fillText(String(m), w / 2 + Math.cos(a) * 118, h + 20 + Math.sin(a) * 118);
    });
    c.fillStyle = "#2b2f38";
    c.fillText("LUFS", w / 2, h - 18);
  });
  meter.add(
    part(
      new THREE.PlaneGeometry(8.6, 5.4),
      new THREE.MeshStandardMaterial({
        map: dial,
        roughness: 0.6,
        emissive: "#402a10",
        emissiveIntensity: 0.3,
      }),
      [0, 0, 1.55],
    ),
  );
  const needle = pivot([0, -2.4, 1.7]);
  needle.add(part(block(0.14, 4.6, 0.1, 0.02), clay("#b8433a", { lump: 0, boil: 0 }), [0, 2.3, 0]));
  meter.add(needle);
  g.add(meter);
  g.userData = { faders, needle };
  return g;
}

/** A reel of film on a hub, spoked like a wheel. */
export function reel(r = 5) {
  const g = new THREE.Group();
  const tin = metal("#9ca3ad", 0.35);
  const s = new THREE.Shape().absarc(0, 0, r, 0, TAU);
  for (let k = 0; k < 5; k++) {
    const a = (k / 5) * TAU;
    const h = new THREE.Path().absarc(Math.cos(a) * r * 0.55, Math.sin(a) * r * 0.55, r * 0.22, 0, TAU, true);
    s.holes.push(h);
  }
  for (const z of [-0.8, 0.8]) g.add(part(cutout(s, 0.25, 0.1), tin, [0, 0, z]));
  g.add(
    part(
      new THREE.CylinderGeometry(r * 0.45, r * 0.45, 1.4, 28),
      clay("#3a2a22", { lump: 0, boil: 0 }),
      [0, 0, 0],
      [Math.PI / 2, 0, 0],
    ),
  );
  return g;
}

/* ---------- the cinema ---------- */

/** A cotton reel, for a mouse to sit on. */
export function spool(color) {
  const g = new THREE.Group();
  const wood = clay("#c9a77c", { lump: 0.03, boil: 0 });
  g.add(part(new THREE.CylinderGeometry(2.6, 2.6, 0.8, 20), wood, [0, 0.4, 0]));
  g.add(part(new THREE.CylinderGeometry(2.1, 2.1, 3.4, 20), felt(color, { fuzz: 1.2 }), [0, 2.5, 0]));
  g.add(part(new THREE.CylinderGeometry(2.6, 2.6, 0.8, 20), wood, [0, 4.6, 0]));
  return g;
}

/** The screen, in a frame, with velvet curtains either side that can be drawn. */
export function screen(w = 30, h = 17) {
  const g = new THREE.Group();
  const frame = clay("#3a2a22", { lump: 0.03, boil: 0 });
  g.add(part(block(w + 3, h + 3, 1, 0.5), frame));
  const face = part(
    new THREE.PlaneGeometry(w, h),
    new THREE.MeshBasicMaterial({ color: "#1b1c22" }),
    [0, 0, 0.55],
  );
  face.castShadow = false;
  g.add(face);
  const velvet = felt("#8f2f2a", { fuzz: 0.8 });
  const curtains = [-1, 1].map((s) => {
    const c = pivot([(s * w) / 4, 0, 1.6]);
    const geo = new THREE.CylinderGeometry(1, 1, h + 6, 24, 1, false);
    geo.scale(w / 4 + 1, 1, 0.6);
    const pleats = geo.attributes.position;
    for (let i = 0; i < pleats.count; i++)
      pleats.setZ(i, pleats.getZ(i) + Math.sin(pleats.getX(i) * 1.6) * 0.5);
    geo.computeVertexNormals();
    c.add(part(geo, velvet));
    g.add(c);
    return c;
  });
  g.add(part(block(w + 10, 3, 3, 0.8), felt("#6d2521", { fuzz: 0.8 }), [0, h / 2 + 3, 2]));
  g.userData = { face, curtains };
  return g;
}

/* ---------- the jetty ---------- */

/** A post-box on a post: the letterbox where invitations are asked for. */
export function postbox() {
  const g = new THREE.Group();
  const red = clay("#b8433a", { lump: 0.05, boil: 0.01 });
  g.add(part(new THREE.CylinderGeometry(0.9, 1.1, 12, 10), clay(OAK_DK, { lump: 0.04, boil: 0 }), [0, 6, 0]));
  const box = pivot([0, 14, 0]);
  const body = new THREE.Shape();
  body.moveTo(-3.5, -3);
  body.lineTo(3.5, -3);
  body.lineTo(3.5, 1.5);
  body.absarc(0, 1.5, 3.5, 0, Math.PI);
  body.lineTo(-3.5, -3);
  box.add(part(cutout(body, 10, 0.5), red, [0, 0, 0], [0, Math.PI / 2, 0]));
  box.add(
    part(
      block(0.4, 1, 3.8, 0.2),
      clay("#1b1c20", { lump: 0, boil: 0 }),
      [0.3, 1.6, 5.35],
      [0, Math.PI / 2, 0],
    ),
  );
  const flag = pivot([3.9, -1, -2]);
  flag.add(
    part(block(0.3, 6, 0.6, 0.1), metal("#c9c6be", 0.3), [0, 3, 0]),
    part(block(0.3, 2, 2.6, 0.1), red, [0, 5.6, 1.1]),
  );
  box.add(flag);
  g.add(box);
  g.userData.flag = flag;
  return g;
}

/** The Marisol: a little red fishing boat with a cream stripe and a lantern on her mast. */
export function boat() {
  const g = new THREE.Group();
  const red = clay("#b8473a", { lump: 0.1, boil: 0.02, freq: 0.5 });
  const cream = clay(CREAM, { lump: 0.04, boil: 0.01, freq: 0.5 });
  const hull = lathe([
    [0, -7],
    [6.3, -6.2],
    [10.5, -2.8],
    [11.8, 1],
    [12, 3],
    [0, 3],
  ]);
  hull.scale(1, 1, 2.5);
  g.add(part(hull, red, [0, 6.4, 0]));
  const stripe = new THREE.LatheGeometry(
    [new THREE.Vector2(11.9, 0.9), new THREE.Vector2(12.1, 2), new THREE.Vector2(12.15, 2.9)],
    48,
  );
  stripe.scale(1, 1, 2.5);
  g.add(part(stripe, cream, [0, 6.4, 0]));
  g.add(part(block(10, 7, 12, 1.1), cream, [0, 12.8, -5.6]));
  const glass = glow("#ffc56b", 1.2);
  for (const z of [-2.2, -9])
    g.add(part(new THREE.PlaneGeometry(2.4, 2.2), glass, [5.02, 13.4, z], [0, Math.PI / 2, 0]));
  g.add(part(block(11, 1.1, 13.4, 0.4), clay(OAK_DK, { lump: 0, boil: 0 }), [0, 16.8, -5.6]));
  g.add(part(new THREE.CylinderGeometry(0.6, 0.7, 30, 8), clay(OAK_DK, { lump: 0, boil: 0 }), [0, 24, 7]));
  const lamp = pivot([0, 39.5, 7]);
  lamp.add(part(block(2.5, 3.4, 2.5, 0.4), metal(BRASS, 0.3)));
  const flame = part(blob(0.8, 1.2, 0.8), glow("#ffc56b", 3));
  flame.castShadow = false;
  lamp.add(flame);
  g.add(lamp);
  const name = painted(256, 48, (c, w) => {
    c.fillStyle = "#b8473a";
    c.fillRect(0, 0, w, 48);
    c.fillStyle = CREAM;
    c.font = "700 30px 'Courier Prime', monospace";
    c.textAlign = "center";
    c.fillText("MARISOL", w / 2, 35);
  });
  g.add(
    part(
      new THREE.PlaneGeometry(10, 1.9),
      card("#ffffff", name, 0.6),
      [11.85, 5.4, -8],
      [0, Math.PI / 2 + 0.06, 0],
    ),
  );
  return g;
}

/** A small work light on a stand, its can tipped down at what it lights. */
export function workLight(color = "#2c3342") {
  const g = new THREE.Group();
  const paint = clay(color, { lump: 0.02, boil: 0, rough: 0.45 });
  g.add(part(new THREE.CylinderGeometry(2.2, 2.6, 0.8, 20), paint, [0, 0.4, 0]));
  g.add(part(new THREE.CylinderGeometry(0.3, 0.3, 12, 8), metal("#c9c6be", 0.3), [0, 6.4, 0]));
  const head = pivot([0, 12.6, 0]);
  head.rotation.x = 0.9;
  const can = part(new THREE.CylinderGeometry(1.6, 2.6, 4, 20, 1, true), paint, [0, -1, 0]);
  can.material.side = THREE.DoubleSide;
  head.add(can);
  const bulb = part(blob(1.3, 1.3, 1.3, 14), glow("#fff1d0", 3), [0, -1.8, 0]);
  bulb.castShadow = false;
  head.add(bulb);
  g.add(head);
  return g;
}

/** A jetty of planks on posts, standing in the sea. */
export function jetty(len = 60, w = 12) {
  const g = new THREE.Group();
  const wood = clay("#6e5039", { lump: 0.06, boil: 0, print: 0.3 });
  const dark = clay("#4a3322", { lump: 0.08, boil: 0 });
  for (let k = 0; k < len / 2.4; k++) {
    g.add(
      part(
        block(2.2, 0.8, w, 0.2),
        wood,
        [k * 2.4, 0, 0],
        [0, (noise(k, 2) - 0.5) * 0.04, (noise(k, 3) - 0.5) * 0.04],
      ),
    );
  }
  for (let k = 0; k <= len / 12; k++) {
    for (const s of [-1, 1])
      g.add(part(new THREE.CylinderGeometry(0.9, 1, 20, 10), dark, [k * 12, -9, s * (w / 2 - 0.5)]));
  }
  return g;
}

/** A street lamp on the jetty, lit. */
export function lampPost() {
  const g = new THREE.Group();
  const iron = clay(IRON, { lump: 0.02, boil: 0 });
  g.add(part(new THREE.CylinderGeometry(0.5, 0.8, 22, 10), iron, [0, 11, 0]));
  g.add(
    part(
      lathe(
        [
          [0, 0],
          [2.2, 0.4],
          [2.6, 2.8],
          [1.6, 3.4],
          [0, 4.4],
        ],
        16,
      ),
      iron,
      [0, 22, 0],
    ),
  );
  const bulb = part(blob(1.4, 1.6, 1.4), glow("#ffd48a", 2.5), [0, 23.2, 0]);
  bulb.castShadow = false;
  g.add(bulb);
  return g;
}

/** An envelope with a wax seal, to post. */
export function envelope() {
  const g = new THREE.Group();
  g.add(part(block(6, 0.3, 4, 0.1), card("#efe6d2", null, 0.9)));
  g.add(
    part(
      new THREE.CylinderGeometry(0.8, 0.8, 0.3, 16),
      clay("#b8433a", { lump: 0.02, boil: 0.02 }),
      [0, 0.3, 0],
    ),
  );
  return g;
}
