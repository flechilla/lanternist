/* Toy bricks, drawn flat.
 *
 * Everything on this page is built from bricks seen square from the front, the way a builder looks at
 * a model at eye level: a brick is a block with its studs on top, a plate is a third of its height, a
 * tile is a plate with no studs. A model is drawn either as rows of letters (`model()`), a letter one
 * stud wide and a row a brick or a plate high, or as simple shapes (`carve()`) filled in with bricks
 * and plates. Either way the rows are cut into real brick lengths with the seams staggered the way a
 * builder staggers them, and a stud shows only where nothing sits on it. A painted model is cached, so
 * a frame costs a few image draws. The page moves on one 12 fps clock, the rate films made with toy
 * bricks are usually shot at, so a brick jumps from place to place instead of gliding. */

export const FPS = 12;
export const calm = matchMedia("(prefers-reduced-motion: reduce)");

/** A plate is 3.2 mm high on an 8 mm stud grid; a brick is three plates. */
export const PLATE = 0.4;

/** The colours bricks come in. The mosaic in bag 3 picks its studs from the solid ones, too. */
const PALETTE = {
  red: "#e0261d",
  darkRed: "#8a1512",
  orange: "#ff7f11",
  yellow: "#ffc40c",
  cream: "#fde7a7",
  lime: "#a5d23a",
  green: "#1f9d48",
  darkGreen: "#17623a",
  teal: "#00a3a0",
  azure: "#35a9ec",
  blue: "#1b5fd0",
  darkBlue: "#162c5a",
  purple: "#7a4fd0",
  lavender: "#bda6ef",
  pink: "#ff8cbd",
  magenta: "#d0348a",
  white: "#f7f6f0",
  lightGrey: "#b7bcc1",
  grey: "#6c7379",
  black: "#232428",
  tan: "#e6c98c",
  darkTan: "#a98a58",
  nougat: "#e5a56e",
  brown: "#8f4a24",
  darkBrown: "#4a2a17",
  steel: "#5d86ab",
  paleBlue: "#cfe7f6",
  paleYellow: "#fbefc6",
  mint: "#cdeedd",
  blush: "#fcd6d0",
  sand: "#f1dfb4",
  sky: ["#8fd0ff", 0.55],
  flame: ["#ffb230", 0.8],
  fire: ["#ff6a1a", 0.75],
};

const rgbOf = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));

export const COLORS = Object.fromEntries(
  Object.entries(PALETTE).map(([name, v]) => {
    const [hex, a = 1] = Array.isArray(v) ? v : [v];
    return [name, { name, hex, rgb: rgbOf(hex), a }];
  }),
);

/** A colour as CSS, lighter towards white (t > 0) or darker towards black (t < 0). */
function css(color, t = 0, alpha = 1) {
  const c = typeof color === "string" ? COLORS[color] : color;
  const to = t < 0 ? 0 : 255;
  const k = Math.abs(t);
  const [r, g, b] = c.rgb.map((v) => Math.round(v + (to - v) * k));
  return `rgba(${r},${g},${b},${+(alpha * c.a).toFixed(3)})`;
}

/* ---------- models ---------- */

let ids = 0;
const STUDLESS = new Set(["tile", "slope", "curve", "dome"]);

/** Where the seams fall in a run from `a` to `b`: every `long` studs, half a brick along on odd rows. */
function cut(a, b, odd, long) {
  const shift = odd ? Math.floor(long / 2) : 0;
  const out = [];
  let start = a;
  for (let x = a + 1; x < b; x++)
    if ((x + shift) % long === 0) {
      out.push([start, x]);
      start = x;
    }
  out.push([start, b]);
  return out;
}

/**
 * A model from rows of letters, written top to bottom as they look. Each row starts with its height:
 * `b` a brick, `p` a plate, `t` a smooth tile. `legend` maps a letter to a colour, or to
 * `[colour, kind]`: `round` for a round brick, `slope` or `curve` for a sloped or rounded piece (its
 * face turns away from its neighbour), `dome` for a rounded top. `.` is empty. `prints` are the
 * decorations printed on the pieces (eyes, a smile), in studs across and plates up.
 */
export function model(legend, art, { long = 4, prints = [] } = {}) {
  const rows = art
    .trim()
    .split("\n")
    .map((line) => {
      const [kind, cells = ""] = line.trim().split(/\s+/);
      return { h: kind === "b" ? 3 : 1, tile: kind === "t", cells };
    })
    .reverse();
  const pieces = [];
  let y = 0;
  rows.forEach(({ h, tile, cells }, row) => {
    for (let x = 0; x < cells.length;) {
      const ch = cells[x];
      if (ch === ".") {
        x++;
        continue;
      }
      const [c, k = "brick"] = [].concat(legend[ch]);
      let end = x + 1;
      if (k === "brick") while (cells[end] === ch) end++;
      const left = x > 0 && cells[x - 1] !== ".";
      const right = end < cells.length && cells[end] !== ".";
      const dir = left && !right ? "r" : right && !left ? "l" : "u";
      for (const [a, b] of cut(x, end, row % 2, long))
        pieces.push({ x: a, y, w: b - a, h, c, k: tile && k === "brick" ? "tile" : k, dir });
      x = end;
    }
    y += h;
  });
  return finish(pieces, prints);
}

/** A model from pieces placed by hand; works out which studs show (nothing sits on them) and its size. */
export function finish(pieces, prints = []) {
  const taken = new Set();
  for (const p of pieces)
    for (let i = 0; i < p.w; i++) for (let j = 0; j < p.h; j++) taken.add(`${p.x + i},${p.y + j}`);
  for (const p of pieces)
    p.studs = STUDLESS.has(p.k)
      ? ""
      : Array.from({ length: p.w }, (_, i) => (taken.has(`${p.x + i},${p.y + p.h}`) ? "0" : "1")).join("");
  pieces.sort((a, b) => a.y - b.y || a.x - b.x);
  const w = Math.max(0, ...pieces.map((p) => p.x + p.w));
  const h = Math.max(0, ...pieces.map((p) => p.y + p.h));
  return { id: ++ids, pieces, prints, w, h };
}

/** The same model the other way round, lit from the same side. */
export function mirror(m) {
  const flip = { l: "r", r: "l", u: "u" };
  return finish(
    m.pieces.map((p) => ({ ...p, x: m.w - p.x - p.w, dir: flip[p.dir] })),
    m.prints.map((d) => ({
      ...d,
      x: m.w - d.x,
      look: d.look && [-d.look[0], d.look[1]],
      pts: d.pts?.map(([x, y]) => [m.w - x, y]),
    })),
  );
}

/** Piece `i` of a model on its own, to fly it into place. */
export const part = (m, i) => finish([{ ...m.pieces[i], x: 0, y: 0 }]);

/** Several models as one: `[model, x, y]`, in studs and plates. */
export function join(parts, prints = []) {
  return finish(
    parts.flatMap(([m, dx, dy]) => m.pieces.map((p) => ({ ...p, x: p.x + dx, y: p.y + dy }))),
    [
      ...parts.flatMap(([m, dx, dy]) =>
        m.prints.map((d) => ({
          ...d,
          x: d.x + dx,
          y: d.y + dy,
          pts: d.pts?.map(([x, y]) => [x + dx, y + dy]),
        })),
      ),
      ...prints,
    ],
  );
}

/* ---------- carving models from shapes ---------- */

/** Shapes to carve a model from, in studs, y up. */
export const oval =
  (cx, cy, rx, ry = rx) =>
  (x, y) =>
    ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1;

export const box =
  (x0, y0, w, h, r = 0) =>
  (x, y) => {
    if (x < x0 || x > x0 + w || y < y0 || y > y0 + h) return false;
    const dx = Math.max(x0 + r - x, 0, x - (x0 + w - r));
    const dy = Math.max(y0 + r - y, 0, y - (y0 + h - r));
    return dx * dx + dy * dy <= r * r;
  };

export const poly = (pts) => (x, y) => {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i];
    const [xj, yj] = pts[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
};

/**
 * A model carved from a drawing, the way a builder copies one: `shapes` are `[colour, shape]` pairs in
 * studs, each drawn over the ones before it, and a null colour cuts a hole. Each stud-wide column is
 * filled plate by plate; three plates of one colour stacked become a brick, and a brick on the outline
 * is rounded off, on top or underneath. `prints` are placed in studs too.
 */
export function carve(w, h, shapes, { long = 4, prints = [] } = {}) {
  const rows = Math.ceil(h / PLATE);
  const at = Array.from({ length: rows }, (_, j) =>
    Array.from({ length: w }, (_, i) => {
      let c = null;
      for (const [colour, inside] of shapes) if (inside(i + 0.5, (j + 0.5) * PLATE)) c = colour;
      return c;
    }),
  );
  const cell = (i, j) => at[j]?.[i] ?? null;
  const pieces = [];
  for (let j0 = 0; j0 < rows; j0 += 3) {
    // The columns that are one colour all the way up this brick's height.
    const solid = at[j0].map((c, i) => (c && cell(i, j0 + 1) === c && cell(i, j0 + 2) === c ? c : null));
    const open = (i) => !cell(i, j0 + 1) && !cell(i, j0 + 2);
    const rounded = (i, dir) => {
      const k = !cell(i, j0 + 3) ? "curve" : !cell(i, j0 - 1) ? "under" : null;
      if (k) pieces.push({ x: i, y: j0, w: 1, h: 3, c: solid[i], k, dir });
      return !!k;
    };
    for (let i = 0; i < w;) {
      const c = solid[i];
      let end = i + 1;
      while (c && solid[end] === c) end++;
      if (!c) i = end;
      else if (end - i === 1 && open(i - 1) && open(i + 1) && !cell(i, j0 + 3)) {
        pieces.push({ x: i, y: j0, w: 1, h: 3, c, k: "dome", dir: "u" });
        i = end;
      } else {
        let a = i;
        let z = end;
        if (open(a - 1) && rounded(a, "l")) a++;
        if (z > a && open(z) && rounded(z - 1, "r")) z--;
        if (z > a)
          for (const [p, q] of cut(a, z, (j0 / 3) % 2, long))
            pieces.push({ x: p, y: j0, w: q - p, h: 3, c, k: "brick", dir: "u" });
        i = end;
      }
    }
    // What is left in this band is plates.
    for (let j = j0; j < Math.min(j0 + 3, rows); j++)
      for (let i = 0; i < w;) {
        const c = solid[i] ? null : at[j][i];
        let end = i + 1;
        while (c && end < w && at[j][end] === c && !solid[end]) end++;
        if (c)
          for (const [p, q] of cut(i, end, j % 2, long))
            pieces.push({ x: p, y: j, w: q - p, h: 1, c, k: "brick", dir: "u" });
        i = end;
      }
  }
  return finish(
    pieces,
    prints.map((d) => ({ ...d, y: d.y / PLATE, pts: d.pts?.map(([x, y]) => [x, y / PLATE]) })),
  );
}

/* ---------- painting ---------- */

const snap = Math.round;

const studs = new Map();
/** One stud, painted once per colour and size. */
function studImage(c, U) {
  const key = `${c.name}|${U.toFixed(2)}`;
  let img = studs.get(key);
  if (!img) {
    const w = U * 0.62;
    const h = Math.max(1.5, U * 0.22);
    img = document.createElement("canvas");
    img.width = Math.ceil(w) + 2;
    img.height = Math.ceil(h) + 2;
    const g = img.getContext("2d");
    const grad = g.createLinearGradient(1, 0, 1 + w, 0);
    grad.addColorStop(0, css(c, -0.12));
    grad.addColorStop(0.26, css(c, 0.5));
    grad.addColorStop(0.5, css(c, 0.12));
    grad.addColorStop(1, css(c, -0.36));
    g.fillStyle = grad;
    g.beginPath();
    g.roundRect(1, 1, w, h + 2, [h * 0.45, h * 0.45, 0, 0]);
    g.fill();
    g.fillStyle = css(c, 0.6, 0.9);
    g.fillRect(1 + w * 0.14, 1, w * 0.72, Math.max(0.8, U * 0.03));
    img.w = w;
    img.h = h;
    studs.set(key, img);
  }
  return img;
}

/** The outline of a piece whose body's top-left corner is at (x, y). */
function outline(g, p, x, y, w, h) {
  const lip = Math.min(h * 0.24, w * 0.3);
  g.beginPath();
  if (p.k === "slope" && p.dir !== "u") {
    const [hi, lo] = p.dir === "r" ? [x, x + w] : [x + w, x];
    g.moveTo(hi, y);
    g.lineTo(lo, y + h - lip);
    g.lineTo(lo, y + h);
    g.lineTo(hi, y + h);
  } else if (p.k === "curve" && p.dir !== "u") {
    const [hi, lo] = p.dir === "r" ? [x, x + w] : [x + w, x];
    g.moveTo(hi, y + h);
    g.lineTo(hi, y);
    g.quadraticCurveTo(lo, y, lo, y + h - lip);
    g.lineTo(lo, y + h);
  } else if (p.k === "dome" || p.k === "curve") {
    g.moveTo(x, y + h);
    g.lineTo(x, y + h * 0.6);
    g.quadraticCurveTo(x, y, x + w / 2, y);
    g.quadraticCurveTo(x + w, y, x + w, y + h * 0.6);
    g.lineTo(x + w, y + h);
  } else if (p.k === "under" && p.dir !== "u") {
    const [hi, lo] = p.dir === "r" ? [x, x + w] : [x + w, x];
    g.moveTo(hi, y);
    g.lineTo(lo, y);
    g.lineTo(lo, y + lip);
    g.quadraticCurveTo(lo, y + h, hi, y + h);
  } else if (p.k === "round") {
    const inset = w * 0.04;
    g.rect(x + inset, y, w - inset * 2, h);
  } else g.rect(x, y, w, h);
  g.closePath();
}

/** Paints one piece, its body's top-left corner at (x, y), `U` pixels to a stud. */
function paintPiece(g, p, U, x0, y0) {
  const c = COLORS[p.c];
  const x = snap(x0);
  const y = snap(y0);
  const w = snap(x0 + p.w * U) - x;
  const h = snap(y0 + p.h * PLATE * U) - y;
  const e = Math.max(1, U * 0.055);
  const shaped = p.k === "slope" || p.k === "curve" || p.k === "dome";

  outline(g, p, x, y, w, h);
  const grad =
    p.k === "round"
      ? g.createLinearGradient(x, 0, x + w, 0)
      : g.createLinearGradient(0, y - (shaped ? h * 0.2 : 0), 0, y + h);
  if (p.k === "round") {
    grad.addColorStop(0, css(c, -0.22));
    grad.addColorStop(0.3, css(c, 0.28));
    grad.addColorStop(0.55, css(c, 0.04));
    grad.addColorStop(1, css(c, -0.34));
  } else {
    grad.addColorStop(0, css(c, shaped ? 0.3 : 0.14));
    grad.addColorStop(0.45, css(c, 0));
    grad.addColorStop(1, css(c, -0.1));
  }
  g.fillStyle = grad;
  g.fill();

  g.save();
  g.clip();
  if (!shaped) {
    g.fillStyle = css(c, 0.55, 0.95);
    g.fillRect(x, y, w, e);
  }
  g.fillStyle = css(c, 0.26, 0.7);
  g.fillRect(x, y, e * 0.8, h);
  g.fillStyle = css(c, -0.3);
  g.fillRect(x + w - e, y, e, h);
  g.fillStyle = css(c, -0.4);
  g.fillRect(x, y + h - e, w, e);
  // The sheen moulded plastic has, high on its face.
  if (h > 6 && !shaped) {
    const sw = Math.max(2, Math.min(w - U * 0.3, U * 1.6));
    const sheen = g.createLinearGradient(x + U * 0.14, 0, x + U * 0.14 + sw, 0);
    sheen.addColorStop(0, `rgba(255,255,255,${c.a < 1 ? 0.45 : 0.26})`);
    sheen.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = sheen;
    g.beginPath();
    g.roundRect(x + U * 0.14, y + h * 0.18, sw, Math.max(1, h * 0.09), 4);
    g.fill();
  }
  g.restore();

  if (shaped) {
    // A rim of light along the sloped or rounded edge.
    g.save();
    g.clip();
    g.strokeStyle = css(c, 0.5, 0.9);
    g.lineWidth = e * 1.6;
    outline(g, p, x, y, w, h);
    g.stroke();
    g.restore();
  }

  if (p.studs.includes("1")) {
    const img = studImage(c, U);
    for (let i = 0; i < p.w; i++)
      if (p.studs[i] === "1")
        g.drawImage(
          img,
          snap(x0 + (i + 0.5) * U - img.w / 2 - 1),
          snap(y - img.h - 1),
          img.width,
          img.height,
        );
  }
}

/** Paints a decoration printed on a model; (bx, by) is the model's bottom-left corner. */
function paintPrint(g, d, U, bx, by) {
  const X = (x) => bx + x * U;
  const Y = (y) => by - y * PLATE * U;
  g.save();
  if (d.k === "eye") {
    const r = d.r * U;
    const cx = X(d.x);
    const cy = Y(d.y);
    if (d.shut) {
      // Shut: a sleeping curve, or a happy one ("up") that squeezes the cheeks.
      g.strokeStyle = css("black");
      g.lineWidth = Math.max(1.2, r * 0.32);
      g.lineCap = "round";
      g.beginPath();
      if (d.shut === "up") g.arc(cx, cy + r * 0.45, r * 0.8, Math.PI * 1.2, Math.PI * 1.8);
      else g.arc(cx, cy - r * 0.3, r * 0.8, Math.PI * 0.2, Math.PI * 0.8);
      g.stroke();
    } else {
      const [lx = 0, ly = 0] = d.look ?? [];
      g.fillStyle = "#fff";
      g.beginPath();
      g.ellipse(cx, cy, r, r * 1.12, 0, 0, Math.PI * 2);
      g.fill();
      g.fillStyle = css(d.iris ?? "black");
      g.beginPath();
      g.arc(cx + lx * r * 0.36, cy - ly * r * 0.36, r * 0.58, 0, Math.PI * 2);
      g.fill();
      g.fillStyle = "rgba(255,255,255,.9)";
      g.beginPath();
      g.arc(cx + lx * r * 0.36 - r * 0.2, cy - ly * r * 0.36 - r * 0.24, r * 0.2, 0, Math.PI * 2);
      g.fill();
      if (d.brow) {
        g.strokeStyle = css("black");
        g.lineWidth = Math.max(1.2, r * 0.3);
        g.lineCap = "round";
        g.beginPath();
        g.moveTo(cx - r * 0.9, cy - r * 1.5 - d.brow * r * 0.4);
        g.lineTo(cx + r * 0.9, cy - r * 1.5 + d.brow * r * 0.4);
        g.stroke();
      }
    }
  } else if (d.k === "mouth") {
    const w = d.w * U;
    const cx = X(d.x);
    const cy = Y(d.y);
    g.strokeStyle = css(d.c ?? "black");
    g.fillStyle = css("darkRed");
    g.lineWidth = Math.max(1.2, U * 0.09);
    g.lineCap = "round";
    g.beginPath();
    if (d.open) {
      g.ellipse(cx, cy, w * 0.32, w * 0.36 * d.open, 0, 0, Math.PI * 2);
      g.fill();
      g.stroke();
    } else {
      const bend = (d.bend ?? 1) * w * 0.35;
      g.moveTo(cx - w / 2, cy);
      g.quadraticCurveTo(cx, cy + bend, cx + w / 2, cy);
      g.stroke();
    }
  } else if (d.k === "dot") {
    g.fillStyle = css(d.c ?? "black", d.t ?? 0, d.a ?? 1);
    g.beginPath();
    g.ellipse(X(d.x), Y(d.y), d.r * U, (d.ry ?? d.r) * U, 0, 0, Math.PI * 2);
    g.fill();
  } else if (d.k === "line") {
    g.strokeStyle = css(d.c ?? "black", d.t ?? 0, d.a ?? 1);
    g.lineWidth = Math.max(1, (d.wd ?? 0.08) * U);
    g.lineCap = "round";
    g.lineJoin = "round";
    g.beginPath();
    d.pts.forEach(([x, y], i) => (i ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y))));
    g.stroke();
  } else if (d.k === "ring") {
    // A porthole or a bubble: a rim, the glass, a glint.
    const cx = X(d.x);
    const cy = Y(d.y);
    const r = d.r * U;
    g.fillStyle = css(d.rim ?? "white");
    g.beginPath();
    g.arc(cx, cy, r, 0, Math.PI * 2);
    g.fill();
    g.fillStyle = css(d.c ?? "azure", 0, d.a ?? 1);
    g.beginPath();
    g.arc(cx, cy, r * 0.72, 0, Math.PI * 2);
    g.fill();
    g.strokeStyle = "rgba(255,255,255,.75)";
    g.lineWidth = Math.max(1, r * 0.14);
    g.lineCap = "round";
    g.beginPath();
    g.arc(cx, cy, r * 0.48, Math.PI * 1.05, Math.PI * 1.45);
    g.stroke();
  } else if (d.k === "star") {
    // A four-pointed sparkle.
    const cx = X(d.x);
    const cy = Y(d.y);
    const r = d.r * U;
    g.fillStyle = css(d.c ?? "white", d.t ?? 0, d.a ?? 1);
    g.beginPath();
    for (let i = 0; i < 8; i++) {
      const a = (i * Math.PI) / 4 - Math.PI / 2;
      const q = i % 2 ? r * 0.28 : r;
      g.lineTo(cx + Math.cos(a) * q, cy + Math.sin(a) * q);
    }
    g.fill();
  } else if (d.k === "text") {
    g.fillStyle = css(d.c ?? "black", d.t ?? 0, d.a ?? 1);
    g.font = `700 ${d.s * U}px Fredoka, system-ui, sans-serif`;
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.fillText(d.t, X(d.x), Y(d.y));
  }
  g.restore();
}

/**
 * Paints a model with its bottom-left corner at (bx, by): its first `n` pieces, each `lift(i)` plates
 * above its place (null leaves it out), and its prints once the pieces under them are down.
 */
function paint(g, m, U, bx, by, { n = m.pieces.length, lift = null, prints = n >= m.pieces.length } = {}) {
  for (let i = 0; i < n; i++) {
    const p = m.pieces[i];
    const dy = lift ? lift(i) : 0;
    if (dy === null) continue;
    paintPiece(g, p, U, bx + p.x * U, by - (p.y + p.h + dy) * PLATE * U);
  }
  if (prints) for (const d of m.prints) paintPrint(g, d, U, bx, by);
}

const images = new Map();
/** A model painted once at `U` pixels a stud, with room around it for studs and shading. */
function image(m, U) {
  const key = `${m.id}@${U.toFixed(2)}`;
  let img = images.get(key);
  if (!img) {
    if (images.size > 400) images.clear();
    const pad = Math.ceil(U * 0.4) + 2;
    img = document.createElement("canvas");
    img.width = Math.ceil(m.w * U) + pad * 2;
    img.height = Math.ceil(m.h * PLATE * U) + pad * 2;
    paint(img.getContext("2d"), m, U, pad, img.height - pad);
    Object.assign(img, { pad, U });
    images.set(key, img);
  }
  return img;
}

/* ---------- a stage ---------- */

/**
 * A canvas looking at a world laid out in studs across and plates up. The camera is centred on
 * (`cam.x`, `cam.y`) and shows `view` studs across. Models are drawn from their cached images, painted
 * at `res` pixels a stud when a camera move needs them sharper than the current frame.
 */
export class Stage {
  constructor(canvas, { view = 48, x = 0, y = 0, fixed = false } = {}) {
    this.canvas = canvas;
    this.g = canvas.getContext("2d");
    this.cam = { x, y, view };
    this.res = 0;
    // A fixed stage keeps the canvas's own size: a thumbnail, or a picture painted off screen.
    if (fixed) return;
    this.fit();
    new ResizeObserver(() => this.fit()).observe(canvas);
  }

  fit() {
    const r = this.canvas.getBoundingClientRect();
    const dpr = Math.min(2, devicePixelRatio || 1);
    const w = Math.max(1, Math.round(r.width * dpr));
    const h = Math.max(1, Math.round(r.height * dpr));
    if (w === this.canvas.width && h === this.canvas.height) return;
    this.canvas.width = w;
    this.canvas.height = h;
    this.onfit?.();
  }

  get W() {
    return this.canvas.width;
  }
  get H() {
    return this.canvas.height;
  }
  /** Pixels a stud. */
  get U() {
    return this.W / this.cam.view;
  }
  /** Studs and plates the frame shows. */
  get span() {
    return [this.cam.view, this.H / (this.U * PLATE)];
  }

  /** Where a world point lands on the canvas. */
  at(x, y) {
    return [this.W / 2 + (x - this.cam.x) * this.U, this.H / 2 - (y - this.cam.y) * PLATE * this.U];
  }

  /**
   * Draws a model with its bottom-left corner at (x, y). It turns by `rot` and squashes by `sx`, `sy`
   * around its bottom centre, the way a hand tips a model, and `prints` (a face) go with it.
   */
  put(m, x, y, { rot = 0, sx = 1, sy = 1, alpha = 1, prints = null } = {}) {
    const U = this.U;
    const img = image(m, this.res || U);
    const k = U / img.U;
    const [X, Y] = this.at(x + m.w / 2, y);
    const g = this.g;
    g.save();
    g.globalAlpha *= alpha;
    g.translate(X, Y);
    if (rot) g.rotate(rot);
    if (sx !== 1 || sy !== 1) g.scale(sx, sy);
    g.drawImage(
      img,
      (-m.w / 2) * U - img.pad * k,
      -(img.height - img.pad) * k,
      img.width * k,
      img.height * k,
    );
    if (prints) for (const d of prints) paintPrint(g, d, U, (-m.w / 2) * U, 0);
    g.restore();
  }

  /** Draws a model part-built, piece by piece (see `paint`). */
  build(m, x, y, opts) {
    const [X, Y] = this.at(x, y);
    paint(this.g, m, this.U, X, Y, opts);
  }

  /**
   * A wall of bricks laid in running bond between (x0, y0) and (x1, y1). Nothing sits on a wall's
   * bricks but more bricks, so no studs show: only the seams, and a catch of light along each course.
   */
  bond(colour, x0, y0, x1, y1, long = 4) {
    const g = this.g;
    const U = this.U;
    const [X0, Top] = this.at(x0, y1);
    const [X1, Bottom] = this.at(x1, y0);
    const seam = Math.max(1, U * 0.05);
    g.fillStyle = css(colour);
    g.fillRect(X0, Top, X1 - X0, Bottom - Top);
    for (let y = y0, row = 0; y < y1; y += 3, row++) {
      const yb = this.at(0, y)[1];
      const yt = this.at(0, y + 3)[1];
      if (yb < Top || yt > Bottom) continue;
      g.fillStyle = css(colour, 0.4, 0.9);
      g.fillRect(X0, yt, X1 - X0, seam);
      g.fillStyle = css(colour, -0.13);
      g.fillRect(X0, yb - seam, X1 - X0, seam);
      const shift = row % 2 ? long / 2 : 0;
      for (let x = Math.floor((x0 - shift) / long) * long + shift; x < x1; x += long) {
        const xs = this.at(x, 0)[0];
        g.fillStyle = css(colour, -0.13);
        g.fillRect(xs - seam, yt, seam, yb - yt);
        g.fillStyle = css(colour, 0.3, 0.8);
        g.fillRect(xs, yt, seam, yb - yt);
      }
    }
  }

  /** The soft shadow of something `w` studs wide standing at (x, y). */
  shadow(x, y, w, a = 0.28) {
    const [X, Y] = this.at(x + w / 2, y);
    const rx = (w / 2) * this.U * 1.1;
    const g = this.g;
    g.save();
    g.translate(X, Y);
    g.scale(1, 0.16);
    const grad = g.createRadialGradient(0, 0, 0, 0, 0, rx);
    grad.addColorStop(0, `rgba(30,20,10,${a})`);
    grad.addColorStop(1, "rgba(30,20,10,0)");
    g.fillStyle = grad;
    g.fillRect(-rx, -rx, rx * 2, rx * 2);
    g.restore();
  }

  /** Prints drawn over a model placed at (x, y): a face that changes from frame to frame. */
  print(prints, x, y) {
    const [X, Y] = this.at(x, y);
    for (const d of prints) paintPrint(this.g, d, this.U, X, Y);
  }

  /** A soft light, in studs, added over what is there. */
  glow(x, y, r, color, a = 0.6) {
    const [X, Y] = this.at(x, y);
    const R = r * this.U;
    const g = this.g;
    const grad = g.createRadialGradient(X, Y, 0, X, Y, R);
    grad.addColorStop(0, css(color, 0.3, a));
    grad.addColorStop(1, css(color, 0, 0));
    g.save();
    g.globalCompositeOperation = "lighter";
    g.fillStyle = grad;
    g.fillRect(X - R, Y - R, R * 2, R * 2);
    g.restore();
  }

  /** Fills the frame top to bottom with the given stops. */
  wash(stops) {
    const grad = this.g.createLinearGradient(0, 0, 0, this.H);
    stops.forEach(([at, c]) => grad.addColorStop(at, c));
    this.g.fillStyle = grad;
    this.g.fillRect(0, 0, this.W, this.H);
  }

  /** A flat rectangle in world units, for what isn't built of bricks: a shadow, a flash of light. */
  rect(x, y, w, h, fill) {
    const [X, Y] = this.at(x, y + h);
    this.g.fillStyle = fill;
    this.g.fillRect(X, Y, w * this.U, h * PLATE * this.U);
  }
}

/* ---------- the clock ---------- */

const jobs = new Set();
/** Calls `fn(frame)` on every tick of the 12 fps clock; returns the way to stop. */
export const onTick = (fn) => (jobs.add(fn), () => jobs.delete(fn));

let frame = -1;
requestAnimationFrame(function tick(now) {
  const f = Math.floor((now * FPS) / 1000);
  if (f !== frame) {
    frame = f;
    for (const fn of jobs) fn(f);
  }
  requestAnimationFrame(tick);
});

/** Runs `fn` on the clock only while `el` is on screen. */
export function whileSeen(el, fn) {
  let stop = null;
  new IntersectionObserver(
    ([e]) => {
      if (e.isIntersecting && !stop) stop = onTick(fn);
      else if (!e.isIntersecting && stop) {
        stop();
        stop = null;
      }
    },
    { rootMargin: "120px" },
  ).observe(el);
}

/** The same number for the same thing on the same frame, so a brick is placed, not jiggled. */
export const noise = (i, t = 0) => {
  const x = Math.sin(i * 12.9898 + t * 78.233) * 43758.5453;
  return x - Math.floor(x);
};
