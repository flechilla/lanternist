/* The workshop's tools: how a part is shaped before it is painted. Everything is built at its real
 * size in centimetres, a puppet about nine tall, so the clay's lumps and prints come out the same size
 * on every part. Nothing is scaled after it's made. */

import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";

export const TAU = Math.PI * 2;
export const v3 = (x = 0, y = 0, z = 0) => new THREE.Vector3(x, y, z);

/** A part: a mesh that casts and takes the set's shadows, placed and turned. */
export function part(geo, mat, [x = 0, y = 0, z = 0] = [], [rx = 0, ry = 0, rz = 0] = []) {
  const m = new THREE.Mesh(geo, mat);
  m.position.set(x, y, z);
  m.rotation.set(rx, ry, rz);
  m.castShadow = true;
  m.receiveShadow = true;
  return m;
}

/** A pivot to hang parts from: a joint of a puppet, the hinge of a lid. */
export function pivot([x = 0, y = 0, z = 0] = [], ...children) {
  const g = new THREE.Group();
  g.position.set(x, y, z);
  if (children.length) g.add(...children);
  return g;
}

/** A turned shape: a profile of [radius, height] points, smoothed and spun round the y axis. */
export function lathe(profile, segs = 36, steps = 48) {
  const pts = new THREE.SplineCurve(profile.map(([r, y]) => new THREE.Vector2(r, y))).getPoints(steps);
  for (const p of pts) p.x = Math.max(0, p.x);
  return new THREE.LatheGeometry(pts, segs);
}

/** A ball, pressed into an egg or a bean by its three radii. */
export function blob(rx, ry = rx, rz = rx, segs = 32) {
  const g = new THREE.SphereGeometry(1, segs, Math.round(segs * 0.75));
  g.scale(rx, ry, rz);
  return g;
}

/** A roll of clay: a capsule of radius r whose straight part is `len` long, along y. */
export const roll = (r, len, segs = 16) => new THREE.CapsuleGeometry(r, len, 6, segs);

/** A cut and sanded block. */
export const block = (w, h, d, r = 0.4, segs = 3) =>
  new RoundedBoxGeometry(w, h, d, segs, Math.min(r, w / 2, h / 2, d / 2));

/** A tube that thins from r0 to r1 along a curve: a tail, a whisker, a cable. */
export function taper(curve, r0, r1, segs = 28, radial = 10) {
  const g = new THREE.TubeGeometry(curve, segs, 1, radial, false);
  const pos = g.attributes.position;
  const c = new THREE.Vector3();
  const p = new THREE.Vector3();
  for (let i = 0; i <= segs; i++) {
    curve.getPointAt(i / segs, c);
    const r = r0 + (r1 - r0) * (i / segs);
    for (let j = 0; j <= radial; j++) {
      const k = i * (radial + 1) + j;
      p.fromBufferAttribute(pos, k).sub(c).multiplyScalar(r).add(c);
      pos.setXYZ(k, p.x, p.y, p.z);
    }
  }
  return g;
}

/** A flat shape cut from card and given a thickness, with its edges softened. */
export function cutout(shape, depth, bevel = 0.3) {
  const g = new THREE.ExtrudeGeometry(shape, {
    depth,
    bevelEnabled: bevel > 0,
    bevelThickness: bevel,
    bevelSize: bevel,
    bevelSegments: 3,
    curveSegments: 16,
  });
  g.translate(0, 0, -depth / 2);
  return g;
}

/** A five-pointed star shape, for the paper stars. */
export function star(r, inner = 0.45, points = 5) {
  const s = new THREE.Shape();
  for (let i = 0; i < points * 2; i++) {
    const a = Math.PI / 2 + (i * Math.PI) / points;
    const rr = i % 2 ? r * inner : r;
    s[i ? "lineTo" : "moveTo"](rr * Math.cos(a), rr * Math.sin(a));
  }
  return s;
}

/* ---------- painted surfaces ---------- */

/** A texture painted on a canvas by `paint(ctx, w, h)`, in the page's colour space. */
export function painted(w, h, paint) {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  paint(c.getContext("2d"), w, h);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

const rnd = (i) => {
  const x = Math.sin(i * 91.3458) * 47453.5453;
  return x - Math.floor(x);
};

/** Planks of stained wood, grain running along them. */
export function planks(color = "#6b4a2e", n = 8, w = 512, h = 512) {
  const t = painted(w, h, (g) => {
    const base = new THREE.Color(color);
    for (let i = 0; i < n; i++) {
      const c = base.clone().offsetHSL(0, 0, (rnd(i) - 0.5) * 0.08);
      g.fillStyle = `#${c.getHexString()}`;
      const y = (i * h) / n;
      g.fillRect(0, y, w, h / n);
      g.strokeStyle = "rgba(0,0,0,.08)";
      g.lineWidth = 1;
      for (let k = 0; k < 14; k++) {
        const yy = y + rnd(i * 31 + k) * (h / n);
        g.beginPath();
        g.moveTo(0, yy);
        for (let x = 0; x <= w; x += 32) g.lineTo(x, yy + Math.sin(x / 60 + k + i) * 2.5);
        g.stroke();
      }
      g.fillStyle = "rgba(0,0,0,.45)";
      g.fillRect(0, y, w, 2);
    }
  });
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}

/** Whitewashed brick, the inside of the tower. */
export function bricks(color = "#d9cdb8", rows = 16, w = 512, h = 512) {
  const t = painted(w, h, (g) => {
    g.fillStyle = "#a89c89";
    g.fillRect(0, 0, w, h);
    const bh = h / rows;
    for (let r = 0; r < rows; r++) {
      const off = r % 2 ? 0.5 : 0;
      for (let k = -1; k < 5; k++) {
        const c = new THREE.Color(color).offsetHSL(0, 0, (rnd(r * 13 + k) - 0.5) * 0.07);
        g.fillStyle = `#${c.getHexString()}`;
        g.fillRect((k + off) * (w / 4) + 3, r * bh + 3, w / 4 - 6, bh - 6);
      }
    }
  });
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}

/** A sheet of paper with words on it, set by `write(ctx, w, h)` over a warm cream ground. */
export function paper(w, h, write, ground = "#f1e6cf") {
  return painted(w, h, (g) => {
    g.fillStyle = ground;
    g.fillRect(0, 0, w, h);
    for (let i = 0; i < 900; i++) {
      g.fillStyle = `rgba(90,70,40,${rnd(i) * 0.05})`;
      g.fillRect(rnd(i + 1) * w, rnd(i + 2) * h, 2, 2);
    }
    write(g, w, h);
  });
}
