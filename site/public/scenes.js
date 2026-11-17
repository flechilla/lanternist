/* The paper sets for the seven shots of "Luna and the Lamp". Each returns the SVG of one 16:9 frame
 * (1600 × 900) and the scene's own motions: the beam that turns, the lamp that dies, Luna's climb. */

import {
  PAL,
  beam,
  boat,
  cloud,
  critter,
  hangingMoon,
  hangingStar,
  lighthouse,
  lightning,
  lunaCurled,
  nightSky,
  rain,
  seas,
  starPath,
  tomas,
  turningBeam,
} from "./art.js";
import { noise } from "./stage.js";

const cut = (s) => `<g data-cut>${s}</g>`;
const frame = (body, origin = "50% 50%") =>
  `<svg viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true">` +
  `<g class="cam" style="transform-origin:${origin}"><g class="take">${body}</g></g></svg>`;

const STARS = [
  [150, 60, 13, 0.1],
  [270, 210, 11, 0.4],
  [660, 120, 15, 0.7],
  [770, 30, 10, 0.2],
  [1250, 80, 12, 0.5],
  [1400, 190, 16, 0.9],
  [1510, 40, 11, 0.3],
];
const stars = (list = STARS) => list.map(([x, len, r, ph]) => hangingStar(x, len, r, ph)).join("");

/** When the lamp in the storm is on: steady, then guttering, then out. */
const lampOn = (t) => (t < 34 ? 1 : t < 48 ? (noise(9, t) > 0.45 ? 1 : 0.1) : 0);
/** Lightning in the storm scenes strikes on this beat (see `flash` in stage.js). */
const STRIKE = 43;
const struck = (t) => t % STRIKE >= STRIKE - 2;

function night() {
  const [far, ...near] = seas();
  return {
    svg: frame(
      nightSky() +
        cut(
          hangingMoon(480, 60, 56) +
            stars() +
            cloud(560, 190, 1.1) +
            cloud(1290, 250, 0.8, PAL.night3, "drift 20 130 .5"),
        ) +
        cut(far) +
        beam(1030, 264) +
        cut(lighthouse({ x: 1030, y: 640 })) +
        near.map(cut).join(""),
      "64% 40%",
    ),
    fns: { beam: (t, [side]) => turningBeam(t, side) },
  };
}

function lampRoom() {
  const planks = Array.from(
    { length: 17 },
    (_, i) => `<rect x="${i * 100 - 20}" y="0" width="4" height="700" fill="#33261f"/>`,
  ).join("");
  const rings = Array.from({ length: 7 }, (_, i) => {
    const y = 300 + i * 38;
    return `<path d="M${712 - Math.sin((i / 6) * Math.PI) * 26} ${y}H${888 + Math.sin((i / 6) * Math.PI) * 26}" stroke="${PAL.brassDk}" stroke-width="5"/>`;
  }).join("");
  return {
    svg: frame(
      `<rect x="-100" y="-100" width="1800" height="1100" fill="#2a1f1c"/>${planks}` +
        cut(
          `<path d="M1110 460V250A90 90 0 0 1 1290 250V460Z" fill="${PAL.night1}"/>` +
            `<path transform="translate(1160 260)" d="${starPath(10)}" fill="${PAL.paper}" data-m="flick .5"/>` +
            `<path transform="translate(1240 330)" d="${starPath(7)}" fill="${PAL.paper}" data-m="flick .4"/>` +
            `<path d="M1200 160V460M1110 330H1290" stroke="#3b2b22" stroke-width="10"/>` +
            `<path d="M1100 470H1300V490H1100Z" fill="#3b2b22"/>`,
        ) +
        `<rect x="-100" y="700" width="1800" height="300" fill="#3a2a22"/>` +
        `<ellipse cx="820" cy="730" rx="520" ry="110" fill="url(#g-warm)"/>` +
        `<circle cx="800" cy="420" r="330" fill="url(#g-glow)" opacity=".55" data-m="flick .8"/>` +
        cut(
          `<path d="M740 700L760 560H840L860 700Z" fill="${PAL.brass}"/><rect x="720" y="690" width="160" height="16" rx="4" fill="${PAL.brassDk}"/>` +
            `<path d="M712 560C680 460 680 380 712 280H888C920 380 920 460 888 560Z" fill="${PAL.lamp}"/>` +
            rings +
            `<circle cx="800" cy="420" r="36" fill="${PAL.glow}" data-m="flick .7"/>` +
            `<path d="M700 282Q800 200 900 282Z" fill="${PAL.brass}"/><circle cx="800" cy="226" r="12" fill="${PAL.brassDk}"/>`,
        ) +
        tomas({ x: 540, y: 790, s: 1.35, arm: "up" }) +
        lunaCurled({ x: 1010, y: 752, s: 1.35 }),
      "66% 76%",
    ),
    fns: {},
  };
}

function storm() {
  const [far, ...near] = seas({ calm: false });
  const clouds =
    cloud(80, 90, 2.2, PAL.storm1, "drift 60 40 0") +
    cloud(700, 40, 2.6, PAL.storm2, "drift 70 36 .4") +
    cloud(1200, 120, 2, PAL.storm1, "drift 50 44 .7");
  return {
    svg: frame(
      nightSky(PAL.storm0, "#16233a") +
        lightning(380) +
        cut(clouds) +
        cut(far) +
        beam(1030, 264, 1, "beamOut") +
        cut(lighthouse({ x: 1030, y: 640, lamp: "@lampOut" })) +
        near.map(cut).join("") +
        rain(0.5),
    ),
    fns: {
      beamOut: (t, [side]) => turningBeam(t, side, lampOn(t)),
      lampOut: (t) => ({ opacity: lampOn(t) }),
    },
  };
}

function openSea() {
  const [far, mid, near, front] = seas({ calm: false, y: 560 });
  return {
    svg: frame(
      nightSky(PAL.storm0, "#16233a") +
        lightning(1180, STRIKE) +
        cut(
          cloud(-40, 60, 2.4, PAL.storm1, "drift 60 40 .2") +
            cloud(900, 20, 2.8, PAL.storm2, "drift 70 36 .6"),
        ) +
        cut(
          `<g transform="translate(1340 572) scale(.32)">${lighthouse({ x: 0, y: 0, lit: false, window: false })}</g>`,
        ) +
        cut(far) +
        cut(mid) +
        boat({ x: 780, y: 690, s: 1.35, m: "rock 9 16 22" }) +
        cut(near) +
        cut(front) +
        rain(0.45),
    ),
    fns: {},
  };
}

const STEPS = 11;
const STEP_FRAMES = 9;
const stepAt = (k) => [260 + k * 78, 830 - k * 58];

function stairs() {
  const steps = Array.from({ length: STEPS }, (_, k) => {
    const [x, y] = stepAt(k);
    return `<rect x="${x}" y="${y}" width="120" height="16" fill="#46506a"/><rect x="${x}" y="${y + 16}" width="120" height="44" fill="#2b3348"/>`;
  }).join("");
  const counted = Array.from({ length: STEPS }, (_, k) => {
    const [x, y] = stepAt(k);
    return `<path transform="translate(${x + 60} ${y - 150})" d="${starPath(11)}" fill="${PAL.paper}" data-m="@counted ${k}"/>`;
  }).join("");
  const wall = Array.from({ length: 14 }, (_, i) => {
    const x = 800 + 900 * Math.sin((i / 13 - 0.5) * Math.PI);
    return `<rect x="${Math.round(x)}" y="-100" width="3" height="1100" fill="#16213a"/>`;
  }).join("");
  const hop = (t) => {
    const k = Math.min(STEPS - 1, Math.floor(t / STEP_FRAMES));
    const p = (t % STEP_FRAMES) / STEP_FRAMES;
    const [x, y] = stepAt(k);
    const [nx, ny] = stepAt(Math.min(STEPS - 1, k + 1));
    const going = k < STEPS - 1 && p > 0.5;
    const q = going ? (p - 0.5) * 2 : 0;
    const lift = going ? Math.sin(q * Math.PI) * 46 : 0;
    return { k, x: x + 60 + (nx - x) * q, y: y + (ny - y) * q - lift };
  };
  return {
    svg: frame(
      `<rect x="-100" y="-100" width="1800" height="1100" fill="#0f1726"/>${wall}` +
        cut(
          `<path d="M1210 380V220A70 70 0 0 1 1350 220V380Z" fill="#1b2740"/>` +
            `<path d="M1210 380V220A70 70 0 0 1 1350 220V380Z" fill="${PAL.cream}" opacity="0" data-m="flash ${STRIKE} 0 .5"/>` +
            `<path d="M1280 150V380M1210 290H1350" stroke="#0f1726" stroke-width="8"/>`,
        ) +
        cut(
          steps +
            `<path d="M${stepAt(0)[0] + 20} ${stepAt(0)[1] - 190}L${stepAt(STEPS - 1)[0] + 120} ${stepAt(STEPS - 1)[1] - 190}" stroke="#5a4636" stroke-width="8"/>`,
        ) +
        counted +
        `<g data-m="@climb">${critter({ x: 0, y: 0, s: 0.85, tail: "sway 12 12", eyes: "blink 40" })}</g>` +
        `<rect x="-100" y="-100" width="1800" height="1100" fill="url(#g-vignette)"/>`,
    ),
    fns: {
      climb: (t) => {
        const { x, y } = hop(t);
        return `translate(${Math.round(x)}px,${Math.round(y)}px)`;
      },
      counted: (t, [k]) => ({ opacity: hop(t).k > k || k === 0 ? 1 : 0 }),
    },
  };
}

function eyes() {
  const view =
    `<svg x="880" y="150" width="600" height="470" viewBox="0 0 600 470" preserveAspectRatio="xMidYMid slice">` +
    `<rect width="600" height="470" fill="#1a2740"/>` +
    `<rect width="600" height="470" fill="${PAL.cream}" opacity="0" data-m="flash ${STRIKE} 0 .35"/>` +
    seas({ calm: false, y: 280 }).slice(0, 2).join("") +
    `<g data-m="@turn">${boat({ x: 300, y: 350, s: 0.5, m: "rock 8 8 20", name: false })}</g>` +
    rain(0.4) +
    `</svg>`;
  const glowing =
    `<g transform="translate(1000 820) scale(1.7)">` +
    `<circle cx="23" cy="-117" r="70" fill="url(#g-glow)" data-m="@blaze"/></g>` +
    critter({
      x: 1000,
      y: 820,
      s: 1.7,
      body: "#161f2e",
      mid: "#1a2436",
      dark: "#111826",
      light: "#1e293b",
      eye: PAL.glow,
      tail: "sway 5 40",
      eyes: "blink 50 10",
    });
  const rings = Array.from(
    { length: 9 },
    (_, i) =>
      `<path d="M${230 - Math.sin((i / 8) * Math.PI) * 30} ${220 + i * 62}H${590 + Math.sin((i / 8) * Math.PI) * 30}" stroke="#26344c" stroke-width="6"/>`,
  ).join("");
  return {
    svg: frame(
      `<rect x="-100" y="-100" width="1800" height="1100" fill="#0b111c"/>` +
        cut(
          `<path d="M230 780C170 600 170 380 230 180H590C650 380 650 600 590 780Z" fill="#141d2c"/>${rings}`,
        ) +
        cut(
          `${view}<path d="M870 140H1490V630H870ZM1180 140V630M870 380H1490" fill="none" stroke="#1d2433" stroke-width="18"/>`,
        ) +
        `<rect x="-100" y="-100" width="1800" height="1100" fill="${PAL.cream}" opacity="0" data-m="flash ${STRIKE} 0 .08"/>` +
        glowing,
    ),
    fns: {
      turn: (t, _, i, s) =>
        t < s.dur * 0.5
          ? "translate(0px,0px)"
          : `translate(${-Math.round((t - s.dur * 0.5) * 2)}px,0px) scale(-1,1)`,
      blaze: (t) => ({ opacity: struck(t) ? 1 : 0.6 }),
    },
  };
}

function dawn() {
  const [far, mid, near] = seas({ colors: ["#6c8fb2", "#5b7fa3", "#4a6e95", "#3d5f86"], y: 610 });
  const posts = Array.from(
    { length: 16 },
    (_, i) => `<rect x="${i * 110 - 40}" y="640" width="14" height="150" fill="${PAL.oakDk}"/>`,
  ).join("");
  const rays = Array.from(
    { length: 12 },
    (_, i) => `<path transform="rotate(${i * 30})" d="M-8-130L0-190L8-130Z" fill="${PAL.glow}"/>`,
  ).join("");
  const gull = (x, y, ph) =>
    `<g transform="translate(${x} ${y})"><g data-m="drift 40 80 ${ph}"><path d="M-30 0Q-15-16 0 0Q15-16 30 0" fill="none" stroke="${PAL.night1}" stroke-width="5" data-m="flap 6"/></g></g>`;
  return {
    svg: frame(
      `<rect x="-100" y="-100" width="1800" height="1100" fill="#5e6390"/>` +
        `<path d="M-100 250Q400 200 800 240T1700 230V1000H-100Z" fill="#9b7f9f"/>` +
        `<path d="M-100 400Q400 360 800 400T1700 390V1000H-100Z" fill="#e2a28c"/>` +
        `<path d="M-100 520Q400 500 800 520T1700 510V1000H-100Z" fill="#f0c592"/>` +
        cut(
          `<g transform="translate(1180 610)"><g data-m="spin .5">${rays}</g><circle r="112" fill="${PAL.glow}"/></g>`,
        ) +
        cut(far) +
        cut(`<path d="M1230 628H1560V640H1230Z" fill="${PAL.oakDk}"/>`) +
        boat({ x: 1390, y: 640, s: 0.5, m: "rock 2 3 40", name: false }) +
        cut(mid) +
        cut(near) +
        gull(560, 200, 0) +
        gull(760, 150, 0.3) +
        cut(
          `<rect x="60" y="120" width="360" height="560" fill="${PAL.lamp}"/><path d="M60 120H420V680H60ZM180 120V680M300 120V680" fill="none" stroke="${PAL.dark}" stroke-width="14"/>`,
        ) +
        `<circle cx="240" cy="420" r="220" fill="url(#g-glow)" opacity=".5"/>` +
        cut(
          `<rect x="-100" y="780" width="1800" height="220" fill="${PAL.dark}"/>${posts}<rect x="-100" y="630" width="1800" height="18" fill="${PAL.oak}"/>`,
        ) +
        lunaCurled({ x: 520, y: 790, s: 1.3 }) +
        tomas({ x: 860, y: 800, s: 1.55, flip: true }),
      "40% 70%",
    ),
    fns: {},
  };
}

/** The seven sets, in shot order. */
export const SCENES = [night, lampRoom, storm, openSea, stairs, eyes, dawn];

/** A still holds the frame that tells its story best. */
export const HOLD = [0, 0, 20, 8, 58, 70, 0];

/** How long a preview loops, in frames: long enough for each scene's story beat. */
export const LOOP = [120, 96, 96, 96, STEPS * STEP_FRAMES + 18, 110, 120];
