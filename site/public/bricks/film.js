/* The film of "The Little Red Brick", built in bricks and shot on the page's 12 fps clock.
 *
 * Each shot is a set and what moves on it, drawn again every frame the way an animator nudges the
 * models between pictures. A shot marked still holds its key picture while the camera moves slowly
 * across it, as the app's still shots do; a moving shot plays its motion. Shots in one paragraph cut
 * from one to the next; between paragraphs the picture dissolves, a brick at a time. Each shot lasts
 * as long as its narration takes to read. */

import { FPS, PLATE, Stage, mirror, model, noise, onTick, part } from "./brick.js";
import {
  BRICK,
  CLOUD,
  DIGITS,
  FLAME,
  LOOSE,
  PICKLE_ASLEEP,
  PICKLE_HEAD,
  PICKLE_NOSE,
  PUFF,
  ROCKET,
  ROCKET_TOP,
  SLIPPER,
  SOFA,
  SUN,
  VACUUM,
  WINDOW,
  face,
  leg,
  pickleMouth,
  slab,
} from "./models.js";
import { SHOTS, seconds } from "./tale.js";

/* ---------- the sets ---------- */

// One playroom: pale blue up to a white rail, pale yellow above it. Floor shots are drawn with the
// floor at 0, table shots with the table's top at 0, so the rail falls where it should in both.
const TABLE_H = 120;
const RAIL = 80;
const TABLE_X = -30;
const EDGE = TABLE_X + 92; // where the table ends, and the drop begins
const TABLE_TOP = slab(92, 1, "tan", { kind: "t", long: 8 });
const TABLE_FRONT = slab(92, 2, "brown", { long: 8 });
const FLOOR = slab(220, 4, "brown", { kind: "p", long: 10 });
const SKIRTING = slab(220, 2, "white", { kind: "p", long: 12 });
const RAIL_TILE = slab(220, 1, "white", { kind: "t", long: 12 });
const RUG = model(
  { r: "red", y: "yellow", b: "blue" },
  ["r", "y", "b"].map((c) => `p ${c.repeat(86)}`).join("\n"),
  { long: 7 },
);
const LEG = leg(TABLE_H / 3 - 3);
const RX = 30; // where the rocket stands on the table
const WX = 6; // the window's bottom-left corner, above the table
const WY = 14;
const PILE = [
  [15, 0],
  [18, 0],
  [23, 0],
  [45, 0],
  [47.5, 0],
  [51, 0],
];
const LIFT_ROCKET = 23; // in the lift, the rocket stands just right of Pickle's nose
const VACUUM_LEFT = mirror(VACUUM);
const NOSE = PICKLE_NOSE[1] / PLATE; // plates from the bottom of Pickle's head to the top of her nose
const parts = [];
const rocketPart = (i) => (parts[i] ??= part(ROCKET, i));

/** How the rocket goes together in the first shot: half built, then a piece every `per` frames. */
const pace = (d) => {
  const all = ROCKET.pieces.length;
  const first = Math.floor(all * 0.5);
  return { all, first, per: Math.max(3, Math.floor((d * 0.8) / (all - first))) };
};

/** A little arc, `h` plates high, every `per` frames: how a brick walks. */
const hop = (t, per, h) => {
  const f = (t % per) / per;
  return h * 4 * f * (1 - f);
};
const clamp = (v) => Math.max(0, Math.min(1, v));

/** The little red brick with its face, and its shadow on the ground under it. */
function red(s, x, y, mood, look, { ground = 0, ...opts } = {}) {
  if (y - ground < 12) s.shadow(x, ground, 2, 0.3 * (1 - (y - ground) / 12));
  s.put(BRICK, x, y, { ...opts, prints: face(mood, look) });
}

/** The playroom's walls, with the floor at `base`. */
function room(s, base) {
  s.bond("paleBlue", -80, base, 240, base + RAIL);
  s.bond("paleYellow", -80, base + RAIL + 1, 240, base + 420);
  s.put(RAIL_TILE, -80, base + RAIL);
  s.put(SKIRTING, -80, base);
}

/** The floorboards under `base`, down past the bottom of the frame. */
function boards(s, base) {
  s.rect(-100, base - 200, 400, 196, "#6d3a1d");
  s.put(FLOOR, -80, base - 4);
}

/** The sky through the window: the sun, two clouds drifting a stud every eight frames. */
function sky(s, t, extra) {
  const [x0, top] = s.at(WX, WY + 40);
  const [x1, bottom] = s.at(WX + 18, WY);
  const g = s.g;
  g.save();
  g.beginPath();
  g.rect(x0, top, x1 - x0, bottom - top);
  g.clip();
  s.wash([
    [0, "#7ccaff"],
    [1, "#dcf3ff"],
  ]);
  s.put(SUN, WX + 11, WY + 22);
  s.put(CLOUD, WX - 9 + (Math.floor(t / 8) % 30), WY + 25);
  s.put(CLOUD, WX - 9 + ((Math.floor(t / 8) + 16) % 30), WY + 12);
  extra?.();
  g.restore();
}

/** The table by the window, its top at 0. */
function table(s, t, extra) {
  room(s, -TABLE_H);
  sky(s, t, extra);
  s.put(WINDOW, WX, WY);
  // The table's shadow on the wall under it.
  const [x0, y0] = s.at(TABLE_X, -7);
  const [x1, y1] = s.at(EDGE, -40);
  const shade = s.g.createLinearGradient(0, y0, 0, y1);
  shade.addColorStop(0, "rgba(90,60,20,.34)");
  shade.addColorStop(1, "rgba(90,60,20,0)");
  s.g.fillStyle = shade;
  s.g.fillRect(x0, y0, x1 - x0, y1 - y0);
  s.put(TABLE_FRONT, TABLE_X, -7);
  s.put(TABLE_TOP, TABLE_X, -1);
}

/** The floor at toy height, the floor at 0: the walls, the sofa at `sofa`, the floorboards, a rug. */
function floor(s, sofa = 10) {
  room(s, 0);
  // The sofa is across the room: smaller, and in a little haze.
  s.put(SOFA, sofa, 2, { sx: 0.62, sy: 0.62 });
  s.g.fillStyle = "rgba(255,255,255,.22)";
  s.g.fillRect(0, 0, s.W, s.at(0, 0)[1]);
  boards(s, 0);
  s.put(RUG, 6, -3);
}

/** Z's rising from a sleeper's nose. */
function snores(s, t, x, y) {
  s.print(
    [0, 1, 2].map((i) => {
      const f = ((t + i * 12) % 36) / 36;
      return { k: "text", x: x + f * 4 + i, y: y + f * 16, s: 1.3 + i * 0.4, t: "z", c: "blue", a: 1 - f };
    }),
    0,
    0,
  );
}

/** A burst of sparkles around (x, y), `f` of the way through. */
function sparkles(s, x, y, f) {
  s.print(
    Array.from({ length: 10 }, (_, i) => {
      const a = (i / 10) * Math.PI * 2 + 0.4;
      const r = 1.2 + f * 4.5;
      return {
        k: "star",
        x: x + Math.cos(a) * r,
        y: y + (Math.sin(a) * r) / PLATE,
        r: (i % 2 ? 0.55 : 0.85) * (1 - f * 0.8),
        c: i % 2 ? "white" : "yellow",
      };
    }),
    0,
    0,
  );
}

/* ---------- the shots ---------- */

/**
 * One entry a shot: the camera (`view` studs across, from and to; its centre `cam`, from and to, or a
 * function of the way through), the `key` picture a still holds, how the set is drawn at frame `t` of
 * `d`, and the sounds it makes (`sfx`).
 */
const SETS = [
  {
    view: [56, 50],
    cam: [
      [30, 27],
      [31, 24],
    ],
    key: 0.8,
    draw(s, t, d) {
      table(s, t);
      LOOSE.forEach((m, i) => s.put(m, ...PILE[i]));
      const { all, first, per } = pace(d);
      const n = Math.min(all, first + Math.floor(t / per));
      s.shadow(RX, 0, 8, 0.32);
      s.build(ROCKET, RX, 0, { n, prints: false });
      const done = n ? ROCKET.pieces[n - 1].y : 0;
      s.print(
        ROCKET.prints.filter((p) => p.y + 3 < done),
        RX,
        0,
      );
      if (n < all) {
        // The next piece hops over from the pile.
        const f = (t % per) / per;
        const p = ROCKET.pieces[n];
        s.put(rocketPart(n), 21 + (RX + p.x - 21) * f, p.y * f + 22 * 4 * f * (1 - f));
      }
      red(s, 41, hop(t, 12, 3), "happy", [-0.7, 0.3]);
    },
    sfx(t, d) {
      const { per } = pace(d);
      return t % per === per - 1 ? ["click"] : [];
    },
  },
  {
    view: [22, 19],
    cam: [
      [59, 8],
      [60, 7],
    ],
    key: 0.3,
    draw(s, t, d) {
      table(s, t);
      LOOSE.slice(3).forEach((m, i) => s.put(m, ...PILE[i + 3]));
      const slip = Math.round(d * 0.62);
      if (t < slip) {
        red(s, 60.4, 0, "oh", [0.7, -0.7], { rot: 0.07 + 0.1 * (Math.floor(t / 3) % 2) });
      } else {
        const f = t - slip;
        const y = -0.8 * f * f;
        if (y > -90) red(s, 60.8 + f * 0.35, y, "worried", [0.7, -0.7], { rot: 0.25 + f * 0.32 });
      }
    },
    sfx(t, d) {
      const slip = Math.round(d * 0.62);
      if (t < slip && t % 3 === 0) return ["tap"];
      if (t === slip) return ["slip"];
      if (t === slip + 14) return ["clatter"];
      return [];
    },
  },
  {
    view: [62, 62],
    cam: [[52, 33]],
    key: 0.55,
    draw(s, t, d) {
      floor(s);
      s.shadow(46, 0, 32, 0.24);
      s.put(PICKLE_ASLEEP, 46, 0, { sy: Math.floor(t / 10) % 2 ? 1.03 : 1 });
      snores(s, t, 76, 24);
      red(s, 4 + (t / d) * 88, hop(t, 8, 6), "set", [1, 0.1]);
    },
    sfx: (t) => (t % 8 === 0 ? ["tap"] : t % 36 === 6 ? ["snore"] : []),
  },
  {
    view: [46, 46],
    cam: [[42, 25]],
    key: 0.86,
    draw(s, t, d) {
      floor(s, -12);
      const p = t / d;
      // The vacuum crosses from the right, in front of the slipper.
      const v = (p - 0.3) / 0.46;
      const vx = 70 - v * 100;
      const near = v > 0 && v < 1 && Math.abs(vx + 11 - 39) < 22;
      let brick;
      if (p < 0.2) {
        const alarmed = p > 0.1;
        brick = {
          x: 58 - (p / 0.2) * 10,
          y: hop(t, 6, 4),
          mood: alarmed ? "oh" : "set",
          look: [alarmed ? 1 : -1, 0],
        };
      } else if (p < 0.32) {
        const f = (p - 0.2) / 0.12;
        brick = {
          x: 48 - f * 14,
          y: 3 * f + 24 * 4 * f * (1 - f),
          mood: "worried",
          look: [-1, -0.3],
          inside: f > 0.55,
        };
      } else {
        const peek = p > 0.8;
        brick = {
          x: 34,
          y: peek ? 7.6 : 3,
          mood: p > 0.92 ? "happy" : "worried",
          look: [0.7, 0],
          inside: true,
        };
      }
      const drawBrick = () =>
        red(s, brick.x, brick.y, brick.mood, brick.look, { ground: brick.inside ? 99 : 0 });
      if (brick.inside) drawBrick();
      s.shadow(30, 0, 19, 0.24);
      s.put(SLIPPER, 30, 0, { rot: near ? (t % 2 ? 0.035 : -0.035) : 0 });
      if (!brick.inside) drawBrick();
      if (v > 0 && v < 1) {
        s.shadow(vx, 0, 23, 0.3);
        s.put(VACUUM_LEFT, vx, 0);
        s.print(
          [0, 1, 2].map((i) => ({
            k: "line",
            pts: [
              [vx + 24 + i * 1.5, 3 + i * 3],
              [vx + 27 + i * 1.5 + (t % 2), 3 + i * 3],
            ],
            c: "grey",
            a: 0.6,
            wd: 0.18,
          })),
          0,
          0,
        );
      }
    },
    sfx(t, d) {
      const p = t / d;
      if (Math.abs(p - 0.3) < 0.5 / d) return ["whirr"];
      if (p < 0.2 && t % 6 === 0) return ["tap"];
      return [];
    },
  },
  {
    view: [96, 106],
    cam: [
      [50, 62],
      [50, 70],
    ],
    key: 0.5,
    draw(s, t, d) {
      room(s, 0);
      boards(s, 0);
      s.put(LEG, 12, 0);
      s.put(LEG, 86, 0);
      // The rocket's nose shows over the edge of the table, far above.
      const [, edge] = s.at(0, TABLE_H + 7);
      s.g.save();
      s.g.beginPath();
      s.g.rect(0, 0, s.W, edge);
      s.g.clip();
      s.put(ROCKET, 45, TABLE_H + 7 - 20);
      s.g.restore();
      s.put(TABLE_FRONT, 4, TABLE_H);
      s.put(TABLE_TOP, 4, TABLE_H + 6);
      // The brick is close to the camera, so it looks big against the table far behind it.
      const f = clamp((t / d) * 3);
      const y = t / d > 0.6 ? hop(t, 12, 3) : 0;
      s.shadow(24, -3, 5, 0.3);
      s.put(BRICK, 24, y - 3, { sx: 2.6, sy: 2.6, rot: -0.1 * f, prints: face("oh", [0.2, 1]) });
    },
  },
  {
    view: [44, 44],
    cam(p) {
      return [24, Math.max(30, liftY(p) + 44)];
    },
    key: 0.28,
    draw(s, t, d) {
      const p = t / d;
      const hy = liftY(p);
      room(s, 0);
      boards(s, 0);
      s.put(LEG, 37, 0);
      s.put(ROCKET, LIFT_ROCKET, TABLE_H + 7);
      s.put(TABLE_FRONT, -52, TABLE_H);
      s.put(TABLE_TOP, -52, TABLE_H + 6);
      // Pickle stands up and stretches: her chest a column of honey bricks under her head.
      s.bond("nougat", 6, -8, 15, hy + 8, 4);
      s.put(PICKLE_HEAD, 3, hy, { prints: pickleMouth(p > 0.03 && p < 0.16) });
      if (p < 0.22) red(s, 27, 0, "oh", [-0.8, 0.4]);
      else if (p < 0.34) {
        const f = (p - 0.22) / 0.12;
        red(s, 27 - f * 7, hy + NOSE * f + 14 * 4 * f * (1 - f), "happy", [-0.5, 0], { ground: 0 });
      } else red(s, 20, hy + NOSE, "joy", [0, 0], { ground: -99 });
    },
    sfx(t, d) {
      const p = t / d;
      if (Math.abs(p - 0.04) < 0.5 / d) return ["yawn"];
      if (Math.abs(p - 0.33) < 0.5 / d) return ["tap"];
      if (p > 0.36 && t % 4 === 0 && p < 0.96) return ["step"];
      return [];
    },
  },
  {
    view: [22, 22],
    cam: [[31, 30]],
    key: 0.92,
    draw(s, t, d) {
      table(s, t);
      s.put(ROCKET, RX, 0);
      const p = t / d;
      const [gx, gy] = [RX + ROCKET_TOP[0], ROCKET_TOP[1]];
      // Pickle's nose, the brick on it, level with the gap, just left of the rocket.
      const reach = RX - PICKLE_HEAD.w + 0.4;
      const hx = reach - (p < 0.12 ? (1 - p / 0.12) * 14 : p > 0.64 ? ((p - 0.64) / 0.2) * 34 : 0);
      const hy = gy - NOSE;
      s.put(PICKLE_HEAD, hx, hy, { prints: pickleMouth(false) });
      const nose = hx + PICKLE_NOSE[0];
      if (p < 0.14) red(s, nose, hy + NOSE, "set", [1, 0], { ground: -99 });
      else if (p < 0.34) {
        const f = (p - 0.14) / 0.2;
        red(s, nose + (gx - nose) * f, gy + 2 * f + 12 * 4 * f * (1 - f), "set", [1, -0.4], { ground: -99 });
      } else if (p < 0.54) {
        const f = (p - 0.34) / 0.2;
        red(s, gx, gy + 2 - Math.floor(f * 4) * 0.5, "set", [0, -0.5], {
          ground: -99,
          rot: t % 4 < 2 ? 0.14 : -0.14,
        });
      } else {
        red(s, gx, gy, p < 0.8 ? "joy" : "happy", [0, 0], { ground: -99 });
        const f = (p - 0.54) / 0.3;
        if (f < 1) sparkles(s, gx + 1, gy + 2, f);
        if (t === Math.ceil(d * 0.54)) {
          s.g.fillStyle = "rgba(255,255,255,.45)";
          s.g.fillRect(0, 0, s.W, s.H);
        }
      }
    },
    sfx(t, d) {
      const p = t / d;
      if (Math.abs(p - 0.14) < 0.5 / d) return ["boing"];
      if (p > 0.34 && p < 0.54 && t % 2 === 0) return ["tap"];
      if (t === Math.ceil(d * 0.54)) return ["snap", "sparkle"];
      return [];
    },
  },
  {
    view: [58, 58],
    cam: [[32, 27]],
    key: 0.3,
    draw(s, t, d) {
      const p = t / d;
      const lift = clamp((p - 0.8) / 0.12);
      const flyby = clamp((p - 0.9) / 0.1);
      table(s, t, () => {
        if (flyby > 0 && flyby < 1)
          s.put(ROCKET, WX - 4 + flyby * 26, WY + 8 + flyby * 20, { sx: 0.22, sy: 0.22, rot: 0.5 });
      });
      LOOSE.slice(4).forEach((m, i) => s.put(m, ...PILE[i + 4]));
      const count = p < 0.44 ? 0 : p < 0.56 ? 3 : p < 0.68 ? 2 : p < 0.78 ? 1 : 0;
      if (count) {
        const from = [0.44, 0.56, 0.68][3 - count];
        const since = t - Math.ceil(from * d);
        const digit = DIGITS[count];
        s.build(digit, 45, 22, {
          lift: (i) => (i > since * 3 ? null : Math.max(0, (i / 3 - since + 2) * 4)),
        });
      }
      const shake = p > 0.72 && p < 0.8 ? (t % 2 ? 0.14 : -0.14) : 0;
      const ry = Math.round(lift * lift * 150);
      if (p > 0.72) {
        const age = t - Math.ceil(0.72 * d);
        for (let i = 0; i < 8; i++) {
          const a = age - i * 2;
          if (a < 0) continue;
          const side = i % 2 ? 1 : -1;
          s.put(PUFF, RX + 1.5 + side * (2 + a * 0.45) - (side < 0 ? 3 : 0), Math.min(a * 0.3, 6), {
            alpha: Math.max(0, 1 - a / 50),
            sx: 0.7 + a * 0.02,
            sy: 0.7 + a * 0.02,
          });
        }
        if (lift < 1) {
          // The flames hit the tabletop: nothing of them shows below its edge.
          const [, top] = s.at(0, 0);
          s.g.save();
          s.g.beginPath();
          s.g.rect(0, 0, s.W, top);
          s.g.clip();
          for (const fx of [RX + 0.5, RX + 3.5]) {
            s.glow(fx + 2, ry - 5, 5, "flame", 0.5);
            s.put(FLAME, fx, ry - 15, { sy: t % 2 ? 1 : 1.2, alpha: 0.95 });
          }
          s.g.restore();
        }
      }
      if (lift < 1) {
        s.shadow(RX, 0, 8, 0.32 * (1 - lift));
        s.put(ROCKET, RX + shake, ry);
        s.put(BRICK, RX + ROCKET_TOP[0] + shake, ry + ROCKET_TOP[1], { prints: face("joy") });
      }
    },
    sfx(t, d) {
      const p = t / d;
      const at = (q) => t === Math.ceil(q * d);
      if (at(0.44) || at(0.56) || at(0.68)) return ["tick"];
      if (at(0.72)) return ["rumble"];
      if (at(0.8)) return ["whoosh"];
      return p < 0.4 && t % 12 === 0 ? ["tap"] : [];
    },
  },
];

/** How high Pickle's head is in the lift: low for the brick to climb on, then up to the rocket's top. */
function liftY(p) {
  const low = -24;
  const top = TABLE_H + 7 + ROCKET_TOP[1] - NOSE;
  if (p < 0.36) return low;
  const f = clamp((p - 0.36) / 0.58);
  // She rises a brick at a time, the way it would be animated.
  return Math.round((low + (top - low) * f * f * (3 - 2 * f)) / 3) * 3;
}

/** How many frames shot `i` lasts in `lang`. */
const frames = (i, lang) => Math.round(seconds(SHOTS[i].narration[lang], lang) * FPS);

/** Draws shot `i` at frame `t` of `d`; a still holds its key picture while its camera moves. */
function render(s, i, t, d, still) {
  const set = SETS[i];
  const p = clamp(t / Math.max(1, d - 1));
  const [v0, v1 = v0] = set.view;
  s.cam.view = v0 + (v1 - v0) * p;
  s.res = s.W / Math.min(v0, v1);
  const at = still ? Math.round(set.key * d) : t;
  if (typeof set.cam === "function") [s.cam.x, s.cam.y] = set.cam(at / d);
  else {
    const [[x0, y0], [x1, y1] = [x0, y0]] = set.cam;
    s.cam.x = x0 + (x1 - x0) * p;
    s.cam.y = y0 + (y1 - y0) * p;
  }
  set.draw(s, at, d);
}

/** Paints shot `i`'s key picture into a canvas of its own: a thumbnail, or the picture for a mosaic. */
export function picture(canvas, i, { at = null } = {}) {
  const s = new Stage(canvas, { fixed: true });
  const d = frames(i, "en");
  render(s, i, Math.round((at ?? SETS[i].key) * d), d, false);
  return canvas;
}

/** The sounds shot `i` makes at frame `t`. */
const sounds = (i, t, d, still) => (still ? [] : (SETS[i].sfx?.(t, d) ?? []));

/**
 * The film on a canvas. It plays on the clock, a shot at a time, and tells the page when a shot
 * starts (`onShot`), each frame (`onFrame`), when to make a sound (`onCue`) and when it ends. While
 * `waiting` is set (the voice hasn't finished a line), the last frame of the shot holds.
 */
export class Film {
  constructor(canvas, { onShot = () => {}, onFrame = () => {}, onCue = () => {}, onEnd = () => {} } = {}) {
    this.s = new Stage(canvas, { view: 58 });
    Object.assign(this, { onShot, onFrame, onCue, onEnd });
    this.modes = SHOTS.map((shot) => shot.mode);
    this.lang = "en";
    this.i = 0;
    this.t = 0;
    this.waiting = false;
    this.fade = null;
    this.stop = null;
    this.s.onfit = () => this.draw();
    this.draw();
  }

  get d() {
    return frames(this.i, this.lang);
  }
  get playing() {
    return !!this.stop;
  }

  play() {
    if (this.stop) return;
    if (this.ended) this.seek(0);
    this.stop = onTick(() => this.tick());
    this.onShot(this.i);
  }

  pause() {
    this.stop?.();
    this.stop = null;
  }

  seek(i) {
    Object.assign(this, { i, t: 0, fade: null, ended: false, waiting: false });
    this.draw();
    if (this.stop) this.onShot(i);
  }

  tick() {
    if (this.t < this.d - 1) this.t++;
    else if (this.waiting) return;
    else {
      if (this.i === SHOTS.length - 1) {
        this.pause();
        this.ended = true;
        this.onEnd();
        return;
      }
      if (!SHOTS[this.i + 1].continues) {
        const c = document.createElement("canvas");
        c.width = this.s.W;
        c.height = this.s.H;
        c.getContext("2d").drawImage(this.s.canvas, 0, 0);
        this.fade = c;
      }
      this.i++;
      this.t = 0;
      this.onShot(this.i);
    }
    this.draw();
    this.onFrame(this.i, this.t, this.d);
    for (const cue of sounds(this.i, this.t, this.d, this.modes[this.i] === "still")) this.onCue(cue);
  }

  draw() {
    render(this.s, this.i, this.t, this.d, this.modes[this.i] === "still");
    if (!this.fade) return;
    // The paragraph before comes away a brick at a time.
    const f = this.t / 6;
    if (f >= 1 || this.fade.width !== this.s.W) {
      this.fade = null;
      return;
    }
    const w = Math.max(8, Math.round(this.s.W / 48));
    const h = Math.round(w * 1.2);
    let k = 0;
    for (let y = 0; y < this.s.H; y += h)
      for (let x = 0; x < this.s.W; x += w, k++)
        if (noise(k, 3) > f) this.s.g.drawImage(this.fade, x, y, w, h, x, y, w, h);
  }
}
