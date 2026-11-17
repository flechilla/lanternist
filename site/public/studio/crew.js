/* The night crew: clay mice, one per job in the studio, all cast from the same pattern and dressed
 * for their work. A puppet is a tree of joints. Each frame it is set back to its rest pose, then
 * posed by what it is doing (an action, a list of key poses on the twelve-frame clock), by its idle
 * life (breath, blinks, a twitch of the tail) and by where it is looking. */

import * as THREE from "three";
import { bead, clay, felt, glow, metal } from "./clay.js";
import { blob, lathe, part, pivot, roll, taper, v3 } from "./shapes.js";
import { calm, noise } from "./engine.js";

const FUR = {
  wick: "#9b8878",
  quill: "#b9a58d",
  echo: "#7d7876",
  dab: "#c4a57f",
  nudge: "#8a8b95",
  splice: "#a27f66",
};
const CREAM = "#eddcc4";
const PINK = "#e59a92";
const NOSE = "#d4707a";

const HEAD = [
  [0, -1.9],
  [1.1, -1.65],
  [1.75, -1.0],
  [1.95, -0.2],
  [1.82, 0.55],
  [1.38, 1.2],
  [0.88, 1.75],
  [0.46, 2.2],
  [0, 2.45],
];
const BODY = [
  [0, 0],
  [1.55, 0.12],
  [2.15, 0.85],
  [2.22, 1.8],
  [1.95, 2.85],
  [1.45, 3.7],
  [0.8, 4.3],
  [0, 4.5],
];

/** A cupped ear: a thick disc with its rim brought forward. */
function earGeo(r, t) {
  const g = lathe([
    [0, -t],
    [r * 0.85, -t * 0.9],
    [r, 0],
    [r * 0.85, t * 0.9],
    [0, t],
  ]);
  g.rotateX(Math.PI / 2);
  // Cupped by bending the rim forward; the turned shape's own normals are kept, since recomputing them
  // leaves none at its poles.
  const pos = g.attributes.position;
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i);
    const y = pos.getY(i);
    pos.setZ(i, pos.getZ(i) + (0.32 * (x * x + y * y)) / (r * r));
  }
  return g;
}

const headGeo = () => {
  const g = lathe(HEAD, 40, 56);
  g.rotateX(Math.PI / 2);
  g.scale(1, 0.9, 1);
  return g;
};

/** The tail: a pink roll leaving the back, sagging and curling up at the tip. */
function tailGeo(curl = 0) {
  const pts = [
    v3(0, 0, 0),
    v3(0, -0.25, -1.4),
    v3(0.3 * curl, 0.1, -3.1),
    v3(0.9 * curl, 1.3, -4.3),
    v3(1.4 * curl, 2.6, -4.6),
  ];
  return taper(new THREE.CatmullRomCurve3(pts), 0.34, 0.1, 30, 10);
}

/** A little brass hurricane lantern, lit. Its flame is a light of its own. */
export function lantern() {
  const brass = metal("#b98a3a", 0.38);
  const g = new THREE.Group();
  g.add(part(new THREE.CylinderGeometry(0.9, 1.0, 0.3, 20), brass, [0, 0.15, 0]));
  g.add(part(new THREE.CylinderGeometry(0.55, 0.9, 0.45, 20), brass, [0, 2.75, 0]));
  g.add(part(new THREE.CylinderGeometry(0.2, 0.2, 0.25, 12), brass, [0, 3.08, 0]));
  for (const a of [0.8, 2.37, 3.93, 5.5]) {
    g.add(
      part(new THREE.CylinderGeometry(0.06, 0.06, 2.4, 6), brass, [
        Math.cos(a) * 0.82,
        1.45,
        Math.sin(a) * 0.82,
      ]),
    );
  }
  const handle = new THREE.TorusGeometry(0.75, 0.07, 6, 20, Math.PI);
  g.add(part(handle, brass, [0, 3.1, 0]));
  const flame = part(blob(0.22, 0.42, 0.22, 12), glow("#ffc46b", 4), [0, 1.35, 0]);
  flame.castShadow = false;
  g.add(flame);
  const glass = new THREE.Mesh(
    new THREE.CylinderGeometry(0.72, 0.8, 2.3, 20, 1, true),
    new THREE.MeshPhysicalMaterial({
      color: "#ffe2a8",
      transparent: true,
      opacity: 0.22,
      roughness: 0.1,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
  );
  glass.position.y = 1.45;
  g.add(glass);
  const light = new THREE.PointLight("#ffb257", 0, 60, 1.6);
  light.position.y = 1.4;
  g.add(light);
  g.userData = { flame, light };
  return g;
}

/** What each crew member wears for their job. */
const OUTFITS = {
  wick(p) {
    const scarf = felt("#b8433a");
    p.joints.neck.add(
      part(new THREE.TorusGeometry(1.45, 0.42, 10, 28), scarf, [0, 0.05, 0.1], [Math.PI / 2 + 0.12, 0, 0]),
    );
    p.joints.neck.add(part(roll(0.34, 1.3), scarf, [0.75, -0.85, 1.35], [0.25, 0, 0.35]));
  },
  quill(p) {
    const visor = new THREE.Mesh(
      new THREE.CylinderGeometry(1.9, 2.05, 0.35, 32, 1, true, -1.2, 2.4),
      new THREE.MeshPhysicalMaterial({
        color: "#3d8a5a",
        transparent: true,
        opacity: 0.7,
        roughness: 0.3,
        side: THREE.DoubleSide,
      }),
    );
    visor.position.set(0, 1.05, 0.25);
    visor.rotation.x = 0.35;
    p.joints.head.add(
      visor,
      part(
        new THREE.TorusGeometry(1.72, 0.12, 6, 32),
        clay("#2f6b48", { lump: 0 }),
        [0, 1.05, 0],
        [Math.PI / 2 - 0.35, 0, 0],
      ),
    );
    const pencil = new THREE.Group();
    pencil.add(part(new THREE.CylinderGeometry(0.16, 0.16, 3, 6), clay("#e3b23c", { lump: 0 })));
    pencil.add(part(new THREE.ConeGeometry(0.16, 0.5, 6), clay("#e8cfa6", { lump: 0 }), [0, 1.75, 0]));
    pencil.position.set(1.1, 1.5, -0.6);
    pencil.rotation.set(0.3, 0, -1.2);
    p.joints.head.add(pencil);
  },
  echo(p) {
    const band = clay("#2b2f38", { lump: 0.02 });
    p.joints.head.add(
      part(new THREE.TorusGeometry(1.95, 0.16, 8, 32, Math.PI), band, [0, 0.5, -0.4], [0, Math.PI / 2, 0]),
    );
    for (const s of [-1, 1])
      p.joints.head.add(part(blob(0.5, 0.75, 0.75), clay("#c0503f", { lump: 0.03 }), [s * 1.95, 0.4, -0.4]));
    p.joints.neck.add(part(blob(0.5, 0.36, 0.3), felt("#c0503f"), [-0.45, -0.05, 1.35], [0, 0, 0.6]));
    p.joints.neck.add(part(blob(0.5, 0.36, 0.3), felt("#c0503f"), [0.45, -0.05, 1.35], [0, 0, -0.6]));
  },
  dab(p) {
    const beret = felt("#3b3f7a");
    p.joints.head.add(part(blob(1.75, 0.5, 1.75), beret, [0.25, 1.6, -0.3], [0.1, 0, -0.25]));
    p.joints.head.add(part(new THREE.CylinderGeometry(0.08, 0.08, 0.35, 6), beret, [0.3, 2.15, -0.3]));
    const smock = felt("#e9e4da");
    p.joints.body.add(
      part(
        lathe(
          [
            [2.3, 0.7],
            [2.35, 1.8],
            [2.05, 2.9],
            [1.5, 3.75],
            [0, 3.85],
          ],
          36,
        ),
        smock,
        [0, 0, 0],
      ),
    );
    for (const [c, x, y] of [
      ["#c0503f", 0.8, 2.2],
      ["#f0b14a", -0.6, 1.5],
      ["#3d8a5a", 0.2, 3.1],
    ]) {
      p.joints.body.add(part(blob(0.28, 0.24, 0.1), clay(c, { lump: 0 }), [x, y, 2.2 - Math.abs(x) * 0.2]));
    }
  },
  nudge(p) {
    const loupe = new THREE.Group();
    loupe.add(part(new THREE.TorusGeometry(0.55, 0.14, 8, 20), metal("#2c3342", 0.4)));
    const lens = new THREE.Mesh(
      new THREE.CircleGeometry(0.5, 20),
      new THREE.MeshPhysicalMaterial({
        color: "#cfe6ff",
        transparent: true,
        opacity: 0.35,
        roughness: 0,
        clearcoat: 1,
      }),
    );
    loupe.add(lens);
    loupe.position.set(0.78, 0.3, 1.75);
    p.joints.head.add(loupe);
    p.joints.head.add(
      part(
        new THREE.TorusGeometry(1.9, 0.07, 6, 32),
        clay("#2c3342", { lump: 0 }),
        [0, 0.3, 0],
        [Math.PI / 2, 0, 0],
      ),
    );
  },
  splice(p) {
    const band = clay("#2b2f38", { lump: 0.02 });
    p.joints.neck.add(
      part(new THREE.TorusGeometry(1.55, 0.14, 8, 32, Math.PI), band, [0, 0, 0.3], [0.2, 0, 0]),
    );
    for (const s of [-1, 1])
      p.joints.neck.add(part(blob(0.45, 0.6, 0.6), clay("#3d8a5a", { lump: 0.03 }), [s * 1.5, -0.2, 0.9]));
    p.joints.neck.add(
      part(roll(0.22, 1.6), clay("#f0b14a", { lump: 0 }), [0, -0.1, 1.0], [Math.PI / 2, 0, Math.PI / 2]),
    );
  },
};

/** One mouse, dressed as `role`. Faces +z, feet on y = 0, about nine centimetres tall. */
export function mouse(role = "wick") {
  const fur = clay(FUR[role] ?? FUR.wick, { lump: 0.1, boil: 0.035 });
  const cream = clay(CREAM, { lump: 0.05, boil: 0.02 });
  const pink = clay(PINK, { lump: 0.04, boil: 0.02 });
  const nose = clay(NOSE, { lump: 0, boil: 0.01, rough: 0.4 });
  const eye = bead();

  const j = {};
  const root = new THREE.Group();
  j.hips = pivot();
  j.body = pivot();
  j.hips.add(j.body);
  root.add(j.hips);
  j.body.add(part(lathe(BODY), fur));
  j.body.add(part(blob(1.3, 1.55, 0.5), cream, [0, 1.8, 1.98], [-0.12, 0, 0]));
  for (const s of [-1, 1])
    j.hips.add(part(blob(0.62, 0.4, 1.2), pink, [s * 0.95, 0.32, 0.95], [0, s * -0.18, 0]));

  j.neck = pivot([0, 4.05, 0.15]);
  j.body.add(j.neck);
  j.head = pivot([0, 1.55, 0.25]);
  j.neck.add(j.head);
  j.head.add(part(headGeo(), fur));
  j.head.add(part(blob(0.95, 0.72, 0.9), cream, [0, -0.5, 1.4]));
  for (const s of [-1, 1]) {
    const ear = pivot([s * 1.25, 1.3, -0.55]);
    ear.rotation.set(-0.12, s * -0.35, s * -0.32);
    ear.add(part(earGeo(1.45, 0.2), fur));
    ear.add(part(earGeo(1.02, 0.12), pink, [0, 0, 0.26]));
    j.head.add(ear);
    j[s < 0 ? "earL" : "earR"] = ear;
    const e = pivot([s * 0.8, 0.28, 1.2]);
    e.add(part(blob(0.48, 0.52, 0.42, 20), eye));
    const shine = part(blob(0.09, 0.09, 0.05, 8), glow("#ffffff", 1.4), [-0.15, 0.2, 0.38]);
    shine.castShadow = false;
    e.add(shine);
    j.head.add(e);
    j[s < 0 ? "eyeL" : "eyeR"] = e;
    j.head.add(
      part(blob(0.35, 0.22, 0.14), clay("#eba19b", { lump: 0 }), [s * 1.12, -0.45, 1.05], [0, s * 0.6, 0]),
    );
    for (const a of [-0.22, 0, 0.2]) {
      const w = new THREE.CatmullRomCurve3([
        v3(0, 0, 0),
        v3(s * 1.2, a * 1.6 - 0.05, -0.25),
        v3(s * 2.4, a * 3.2 - 0.3, -0.35),
      ]);
      j.head.add(
        part(taper(w, 0.035, 0.012, 8, 4), clay("#f4ede2", { lump: 0, boil: 0 }), [s * 0.35, -0.1, 2.05]),
      );
    }
  }
  j.head.add(part(blob(0.36, 0.3, 0.32, 20), nose, [0, 0.04, 2.42]));

  // Replacement mouths, as a stop-motion puppet has them: shut in a smile, a little open, wide open.
  const mouthMat = clay("#4a2326", { lump: 0, boil: 0.01 });
  const mouths = [
    part(
      new THREE.TorusGeometry(0.26, 0.055, 6, 14, Math.PI),
      mouthMat,
      [0, -0.62, 1.98],
      [0.35, 0, Math.PI],
    ),
    part(blob(0.22, 0.14, 0.12), mouthMat, [0, -0.66, 1.98], [0.3, 0, 0]),
    part(blob(0.3, 0.26, 0.14), mouthMat, [0, -0.72, 1.92], [0.3, 0, 0]),
  ];
  for (const [k, m] of mouths.entries()) {
    m.visible = k === 0;
    j.head.add(m);
  }

  for (const s of [-1, 1]) {
    const arm = pivot([s * 1.55, 3.3, 0.45]);
    arm.rotation.z = s * 0.25;
    arm.add(part(roll(0.36, 1.25), fur, [0, -0.8, 0]));
    const paw = pivot([0, -1.72, 0.08]);
    paw.add(part(blob(0.5, 0.46, 0.5), pink));
    arm.add(paw);
    j.body.add(arm);
    j[s < 0 ? "armL" : "armR"] = arm;
    j[s < 0 ? "pawL" : "pawR"] = paw;
  }

  j.tail = pivot([0, 0.65, -1.75]);
  const tail = part(tailGeo(0.6), pink);
  j.tail.add(tail);
  j.hips.add(j.tail);

  const p = new Puppet(root, j, { mouths, eyes: [j.eyeL, j.eyeR] });
  OUTFITS[role]?.(p);
  return p;
}

/* ---------- posing ---------- */

const CHANNELS = ["x", "y", "z", "rx", "ry", "rz", "s", "sy"];

/** Blends key poses: `keys` is a list of [frame, {joint: {channel: value}}], eased in between. */
function sample(keys, f) {
  if (f <= keys[0][0]) return keys[0][1];
  for (let k = 1; k < keys.length; k++) {
    const [f1, p1] = keys[k];
    if (f > f1) continue;
    const [f0, p0] = keys[k - 1];
    const t = (f - f0) / (f1 - f0);
    const e = t * t * (3 - 2 * t);
    const out = {};
    for (const joint of new Set([...Object.keys(p0), ...Object.keys(p1)])) {
      out[joint] = {};
      for (const c of CHANNELS) {
        const a = p0[joint]?.[c] ?? 0;
        const b = p1[joint]?.[c] ?? 0;
        if (a || b) out[joint][c] = a + (b - a) * e;
      }
    }
    return out;
  }
  return keys.at(-1)[1];
}

export class Puppet {
  constructor(root, joints, { mouths = [], eyes = [] } = {}) {
    this.root = root;
    this.joints = joints;
    this.mouths = mouths;
    this.eyes = eyes;
    this.rest = new Map(
      Object.values(joints).map((o) => [
        o,
        { p: o.position.clone(), r: o.rotation.clone(), s: o.scale.clone() },
      ]),
    );
    this.action = null;
    this.loop = null;
    this.look = null;
    this.talk = 0;
    this.seed = Math.random() * 100;
  }

  /** Plays an action once from frame `f`, then goes back to the loop; resolves when it ends. */
  play(action, f) {
    this.action = { ...action, from: f };
    return new Promise((done) => (this.action.done = done));
  }

  /** Sets the pose the puppet holds between actions (typing, sleeping, standing). */
  hold(action) {
    this.loop = action;
  }

  pose(f) {
    for (const [o, r] of this.rest) {
      o.position.copy(r.p);
      o.rotation.copy(r.r);
      o.scale.copy(r.s);
    }
    const layers = [];
    if (this.loop) layers.push(sample(this.loop.keys, f % this.loop.len));
    if (this.action) {
      const at = f - this.action.from;
      if (at > this.action.len) {
        const done = this.action.done;
        this.action = null;
        done();
      } else layers.push(sample(this.action.keys, at));
    }
    if (!calm.matches) layers.push(this.idle(f));
    for (const layer of layers) this.apply(layer);
    if (this.look) this.aim(this.look);
    const k = this.talk > 0.5 ? 2 : this.talk > 0.15 ? 1 : 0;
    this.mouths.forEach((m, i) => (m.visible = i === k));
  }

  apply(layer) {
    for (const [name, ch] of Object.entries(layer)) {
      const o = this.joints[name];
      if (!o) continue;
      o.position.x += ch.x ?? 0;
      o.position.y += ch.y ?? 0;
      o.position.z += ch.z ?? 0;
      o.rotation.x += ch.rx ?? 0;
      o.rotation.y += ch.ry ?? 0;
      o.rotation.z += ch.rz ?? 0;
      if (ch.s) o.scale.multiplyScalar(1 + ch.s);
      if (ch.sy) o.scale.y *= 1 + ch.sy;
    }
  }

  /** Breath, blinks and a restless tail: what a puppet does when nobody is moving it. */
  idle(f) {
    const n = this.seed;
    const breath = Math.sin((f / (this.asleep ? 48 : 30)) * Math.PI * 2 + n);
    const blink = (f + Math.floor(n * 7)) % (48 + Math.floor(noise(n, Math.floor(f / 90)) * 40)) < 2;
    for (const e of this.eyes) e.scale.y = blink || this.asleep ? 0.12 : 1;
    return {
      body: { sy: (this.asleep ? 0.03 : 0.012) * breath },
      neck: { rx: this.asleep ? 0.3 : 0 },
      tail: { ry: 0.25 * Math.sin((f / 26) * Math.PI * 2 + n), rx: 0.08 * Math.sin((f / 40) * Math.PI * 2) },
      earL: { rz: noise(n, Math.floor(f / 3)) > 0.97 ? 0.18 : 0 },
      earR: { rz: noise(n + 1, Math.floor(f / 3)) > 0.97 ? -0.18 : 0 },
    };
  }

  /** Turns the head towards a point in the world, in small set steps, as an animator would. */
  aim(target) {
    const head = this.joints.neck;
    if (!head) return;
    const local = head.parent.worldToLocal(target.clone());
    local.sub(head.position);
    const yaw = Math.atan2(local.x, local.z);
    const pitch = -Math.atan2(local.y - 1.5, Math.hypot(local.x, local.z));
    const q = (a, lim) => Math.round(Math.max(-lim, Math.min(lim, a)) * 20) / 20;
    head.rotation.y += q(yaw, 0.85);
    head.rotation.x += q(pitch, 0.45);
  }
}

/* ---------- Luna ---------- */

const CAT = "#7f8793";
const CAT_DK = "#666d79";
const CAT_LT = "#dfe3e8";
const AMBER = "#f0b14a";

/** A pointed cat's ear: a cone with a pink cone inside. */
function catEar(s, fur, pink) {
  const ear = pivot([s * 2.3, 2.6, -0.4]);
  ear.rotation.set(-0.1, 0, s * -0.38);
  ear.add(part(new THREE.ConeGeometry(1.75, 3.4, 16), fur, [0, 1.3, 0]));
  ear.add(part(new THREE.ConeGeometry(1.15, 2.5, 12), pink, [0, 1.1, 0.55]));
  return ear;
}

/**
 * Luna, the lighthouse cat and the star of tonight's film: a small grey cat with amber eyes and a
 * pale chest, twice the height of the crew. `curled` lays her asleep, tail round her paws.
 */
export function cat({ curled = false } = {}) {
  const fur = clay(CAT, { lump: 0.14, boil: 0.035, freq: 0.8 });
  const dark = clay(CAT_DK, { lump: 0.1, boil: 0.03, freq: 0.8 });
  const light = clay(CAT_LT, { lump: 0.06, boil: 0.02 });
  const pink = clay(PINK, { lump: 0.02, boil: 0.01 });
  const j = {};
  const root = new THREE.Group();
  j.hips = pivot();
  j.body = pivot();
  j.hips.add(j.body);
  root.add(j.hips);

  j.head = pivot(curled ? [6.2, 4.6, 3.2] : [0, 15, 1.2]);
  if (curled) j.head.rotation.set(0.25, 0.7, 0.35);
  j.body.add(j.head);
  j.head.add(part(blob(3.9, 3.4, 3.5, 36), fur));
  for (const s of [-1, 1]) j.head.add(part(blob(1.9, 1.7, 1.8), fur, [s * 2.2, -1.2, 1.1]));
  j.head.add(part(blob(1.9, 1.3, 1.4), light, [0, -1.3, 2.6]));
  j.head.add(
    part(blob(0.5, 0.36, 0.4, 16), clay(NOSE, { lump: 0, boil: 0.01, rough: 0.4 }), [0, -0.55, 3.55]),
  );
  j.earL = catEar(-1, fur, pink);
  j.earR = catEar(1, fur, pink);
  j.head.add(j.earL, j.earR);
  for (const s of [-1, 1]) {
    for (const a of [-0.2, 0.05]) {
      const w = new THREE.CatmullRomCurve3([
        v3(0, 0, 0),
        v3(s * 2.5, a * 1.4, -0.3),
        v3(s * 5, a * 3 - 0.3, -0.6),
      ]);
      j.head.add(
        part(taper(w, 0.05, 0.015, 8, 4), clay("#f4ede2", { lump: 0, boil: 0 }), [s * 0.9, -1.1, 3]),
      );
    }
  }
  // Open eyes (amber, with slit pupils) and shut ones (two dark arcs); she sleeps with the second.
  const open = new THREE.Group();
  const shut = new THREE.Group();
  const lidMat = clay("#3c3f47", { lump: 0, boil: 0.01 });
  for (const s of [-1, 1]) {
    const e = pivot([s * 1.45, 0.5, 2.75]);
    e.rotation.y = s * 0.3;
    e.add(part(blob(1.0, 1.1, 0.55, 20), clay(AMBER, { lump: 0, boil: 0.01, rough: 0.2 })));
    e.add(part(blob(0.2, 0.82, 0.3, 12), bead(), [0, 0, 0.36]));
    e.add(part(blob(0.16, 0.16, 0.08, 8), glow("#ffffff", 1.4), [-0.3, 0.38, 0.52]));
    open.add(e);
    shut.add(
      part(
        new THREE.TorusGeometry(0.75, 0.13, 6, 14, Math.PI),
        lidMat,
        [s * 1.45, 0.25, 3.05],
        [0.2, s * 0.3, Math.PI],
      ),
    );
  }
  j.head.add(open, shut);
  open.visible = !curled;
  shut.visible = curled;

  if (curled) {
    j.body.add(part(blob(8.4, 4.4, 6.2, 40), fur, [0, 4.2, 0]));
    j.body.add(part(blob(4.2, 3, 3.4), light, [4.4, 3.2, 3.2]));
    for (const s of [-1, 1]) j.body.add(part(blob(1.6, 1.1, 2.4), light, [3 + s * 1.8, 1.1, 5.2]));
    j.tail = pivot([-7.4, 2.2, 1]);
    const tail = new THREE.CatmullRomCurve3([
      v3(0, 0, 0),
      v3(-1.2, -0.6, 3.4),
      v3(1.8, -1.2, 6.8),
      v3(6.5, -1.4, 7.6),
      v3(9.5, -1.4, 6.6),
    ]);
    j.tail.add(part(taper(tail, 1.1, 0.6, 30, 12), dark));
    j.body.add(j.tail);
  } else {
    const body = lathe([
      [0, 0],
      [4.6, 0.3],
      [5.4, 2.6],
      [4.8, 6],
      [3.6, 9.6],
      [2.6, 12.4],
      [0, 13.4],
    ]);
    j.body.add(part(body, fur));
    j.body.add(part(blob(2.4, 4, 1.4), light, [0, 7.4, 3.3], [-0.2, 0, 0]));
    for (const s of [-1, 1]) {
      j.body.add(part(blob(2.6, 3.2, 3.8), fur, [s * 3.8, 2.8, -0.6]));
      j.body.add(part(roll(1.05, 6.4), fur, [s * 1.5, 3.8, 3.4], [0.08, 0, 0]));
      j.body.add(part(blob(1.4, 0.9, 1.8), light, [s * 1.5, 0.8, 4.4]));
    }
    j.tail = pivot([0, 1.4, -4.2]);
    const tail = new THREE.CatmullRomCurve3([
      v3(0, 0, 0),
      v3(2.4, -0.4, -1.6),
      v3(6.2, -0.8, 0.4),
      v3(6.4, -0.8, 4.4),
      v3(3.6, -0.8, 6.6),
    ]);
    j.tail.add(part(taper(tail, 1.1, 0.55, 30, 12), dark));
    j.body.add(j.tail);
  }

  const p = new Puppet(root, j);
  /** Opens or shuts her eyes. */
  p.wake = (awake) => {
    open.visible = awake;
    shut.visible = !awake;
  };
  return p;
}
