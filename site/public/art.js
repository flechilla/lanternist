/* The paper cut-outs: every character, prop and set on the page, drawn as flat shapes the way they'd
 * be cut from card for a lantern show. Each function returns SVG markup. A part that moves carries
 * `data-m` (a motion from stage.js, or `@name` for one its scene supplies) and `data-o` (the pin it
 * turns on), so one drawing serves both a still and a video. Groups marked `data-cut` are the layers
 * of card: they get the paper shadow and the line boil. */

export const PAL = {
  night0: "#0b1424",
  night1: "#13213a",
  night2: "#1a2b47",
  night3: "#233a5e",
  storm0: "#0d1628",
  storm1: "#1f2b40",
  storm2: "#2a3852",
  sea0: "#18324f",
  sea1: "#1e3c60",
  sea2: "#264b75",
  sea3: "#2f5a88",
  rock0: "#232833",
  rock1: "#323946",
  paper: "#f3dcb4",
  cream: "#ece6d9",
  crater: "#dcc394",
  thread: "rgba(236,230,217,.28)",
  madder: "#c0503f",
  madderDk: "#8f3528",
  lamp: "#f0b14a",
  glow: "#ffe2a8",
  oak: "#7b5230",
  oakDk: "#5f3d22",
  brass: "#c9973f",
  brassDk: "#9a6f28",
  dark: "#2c3342",
  cat: "#9aa1ad",
  catMid: "#8b93a0",
  catDk: "#747c89",
  catLt: "#d9dde3",
  nose: "#ef8a7f",
  pupil: "#1a1407",
  oilskin: "#e0a83a",
  oilskinDk: "#b7832a",
  skin: "#e6b58f",
  skinDk: "#cf9a73",
  beard: "#eeeae2",
  boot: "#262c38",
};

const r1 = (n) => Math.round(n * 10) / 10;
const place = (x, y, s = 1, flip = false) =>
  `transform="translate(${r1(x)} ${r1(y)}) scale(${flip ? -s : s} ${s})"`;

export function starPath(r, points = 5, inner = 0.46) {
  let d = "";
  for (let i = 0; i < points * 2; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / points;
    const rr = i % 2 ? r * inner : r;
    d += `${i ? "L" : "M"}${r1(rr * Math.cos(a))} ${r1(rr * Math.sin(a))}`;
  }
  return `${d}Z`;
}

/* ---------- the sky ---------- */

/** A paper star on a thread from the top of the frame, swinging on its pin. */
export const hangingStar = (x, len, r = 14, ph = 0, fill = PAL.paper) =>
  `<g transform="translate(${x} 0)"><g data-m="sway 5 44 ${ph}" data-o="50% 0%">` +
  `<line x1="0" y1="-20" x2="0" y2="${len}" stroke="${PAL.thread}" stroke-width="1.5"/>` +
  `<path transform="translate(0 ${r1(len + r * 0.9)})" d="${starPath(r)}" fill="${fill}"/></g></g>`;

export const hangingMoon = (x, len, r = 58) =>
  `<g transform="translate(${x} 0)"><g data-m="sway 2.5 70" data-o="50% 0%">` +
  `<line x1="0" y1="-20" x2="0" y2="${len}" stroke="${PAL.thread}" stroke-width="1.5"/>` +
  `<circle cx="0" cy="${len + r}" r="${r}" fill="${PAL.paper}"/>` +
  `<circle cx="${-r * 0.3}" cy="${len + r * 0.8}" r="${r * 0.17}" fill="${PAL.crater}"/>` +
  `<circle cx="${r * 0.32}" cy="${len + r * 1.25}" r="${r * 0.12}" fill="${PAL.crater}"/>` +
  `<circle cx="${r * 0.12}" cy="${len + r * 0.55}" r="${r * 0.08}" fill="${PAL.crater}"/></g></g>`;

const CLOUD = "M0 40C-6 18 22 4 42 18C52-4 96-6 108 18C126 6 156 18 150 40Z";

/** A cloud cut from card, held up on a rod from the top of the frame. */
export const cloud = (x, y, s = 1, fill = PAL.night3, drift = "drift 26 110 0") =>
  `<g ${place(x, y, s)}><g data-m="${drift}">` +
  `<line x1="75" y1="${r1(-y / s - 20)}" x2="75" y2="12" stroke="${PAL.thread}" stroke-width="${r1(2 / s)}"/>` +
  `<path d="${CLOUD}" fill="${fill}"/></g></g>`;

/** A night sky of flat bands, darker at the top. */
export const nightSky = (top = PAL.night1, band = PAL.night2) =>
  `<rect x="-100" y="-100" width="1800" height="1100" fill="${top}"/>` +
  `<path d="M-100 470Q300 430 800 468T1700 452V1000H-100Z" fill="${band}"/>`;

/** A lightning bolt and the flash that lights the sky with it, on the same beat. */
export const lightning = (x, per = 43, ph = 0) =>
  `<rect x="-100" y="-100" width="1800" height="1100" fill="${PAL.cream}" opacity="0" data-m="flash ${per} ${ph} .16"/>` +
  `<path transform="translate(${x} 60)" d="M40 0L0 150H38L8 330L96 120H54L84 0Z" fill="${PAL.glow}" opacity="0" data-m="flash ${per} ${ph}"/>`;

/** Rain: one patterned sheet, jumped to a new place every frame, so every frame has new drops. */
export const rain = (opacity = 0.45) =>
  `<rect x="-200" y="-200" width="2000" height="1300" fill="url(#rain)" opacity="${opacity}" data-m="rain"/>`;

/* ---------- the sea ---------- */

/** A strip of card with a scalloped top, wider than the frame so it can slide under the others. */
export function sea({ y, amp = 16, len = 120, fill, dx = 30, dy = 6, per = 36, ph = 0, foam = false }) {
  let top = `M-240 ${y}`;
  for (let x = -240; x < 1840; x += len) top += `a${len / 2} ${amp} 0 0 1 ${len} 0`;
  const body = `${top}V1000H-240Z`;
  const crest = foam
    ? `<path d="${top}" fill="none" stroke="${PAL.cream}" stroke-width="4" stroke-dasharray="${r1(len * 0.45)} ${r1(len * 0.9)}" opacity=".8"/>`
    : "";
  return `<g data-m="wave ${dx} ${dy} ${per} ${ph}"><path d="${body}" fill="${fill}"/>${crest}</g>`;
}

export const seas = ({ calm = true, colors = [PAL.sea0, PAL.sea1, PAL.sea2, PAL.sea3], y = 600 } = {}) => {
  const k = calm ? 1 : 1.9;
  const per = calm ? 40 : 20;
  return [
    sea({ y, amp: 8 * k, len: 90, fill: colors[0], dx: 14, dy: 3 * k, per: per + 6, ph: 0.1 }),
    sea({ y: y + 70, amp: 12 * k, len: 130, fill: colors[1], dx: 24, dy: 5 * k, per, ph: 0.35 }),
    sea({ y: y + 150, amp: 15 * k, len: 160, fill: colors[2], dx: 34, dy: 6 * k, per: per - 4, ph: 0.6 }),
    sea({
      y: y + 230,
      amp: 18 * k,
      len: 190,
      fill: colors[3],
      dx: 44,
      dy: 8 * k,
      per: per - 8,
      ph: 0.85,
      foam: !calm,
    }),
  ];
};

/* ---------- the lighthouse ---------- */

const hw = (y) => 85 - (30 * -y) / 330;
const band = (y0, y1) => `M${-hw(y0)} ${y0}L${hw(y0)} ${y0}L${hw(y1)} ${y1}L${-hw(y1)} ${y1}Z`;

/** The lighthouse on its rock. `lamp` is the motion of the light: a flicker, or a scene's own. */
export function lighthouse({ x, y, s = 1, lamp = "flick .82", window = true, lit = true }) {
  const glass = lit ? PAL.lamp : "#1d2636";
  const posts = Array.from({ length: 12 }, (_, i) => -66 + i * 12)
    .map((px) => `<rect x="${px}" y="-366" width="3" height="24" fill="${PAL.dark}"/>`)
    .join("");
  const cat = window
    ? `<rect x="-12" y="-250" width="24" height="30" rx="3" fill="${PAL.lamp}" data-m="${lamp}"/>` +
      `<path d="M-7-220V-232L-6-240L-3-235H1L4-240L5-232V-220Z" fill="${PAL.dark}"/>`
    : `<rect x="-12" y="-250" width="24" height="30" rx="3" fill="#1d2636"/>`;
  return (
    `<g ${place(x, y, s)}>` +
    `<path d="M-190 60L-168 12L-120-8L-60 0L0-10L64 0L118-14L160 4L196 60Z" fill="${PAL.rock0}"/>` +
    `<path d="M-120-8L-60 0L-86 30L-150 38Z" fill="${PAL.rock1}"/><path d="M64 0L118-14L130 26L80 34Z" fill="${PAL.rock1}"/>` +
    `<path d="M-85 0L85 0L55-330L-55-330Z" fill="${PAL.cream}"/>` +
    `<path d="${band(-48, -98)}${band(-156, -206)}${band(-264, -312)}" fill="${PAL.madder}"/>` +
    `<path d="M-17 0V-34A17 17 0 0 1 17-34V0Z" fill="${PAL.dark}"/>` +
    `<rect x="-6" y="-140" width="12" height="24" rx="6" fill="${PAL.dark}"/>` +
    cat +
    `<rect x="-74" y="-342" width="148" height="14" fill="${PAL.dark}"/>${posts}` +
    `<rect x="-72" y="-370" width="144" height="5" fill="${PAL.dark}"/>` +
    `<rect x="-40" y="-412" width="80" height="72" fill="${glass}"/>` +
    (lit ? `<circle cx="0" cy="-376" r="46" fill="url(#g-glow)" data-m="${lamp}"/>` : "") +
    `<path d="M-40-412H40M-14-412V-340M14-412V-340" stroke="${PAL.dark}" stroke-width="5"/>` +
    `<path d="M-52-410L52-410L32-442Q0-466-32-442Z" fill="${PAL.dark}"/>` +
    `<circle cx="0" cy="-470" r="7" fill="${PAL.dark}"/></g>`
  );
}

/** The lighthouse beam, seen from the side: two wedges that lengthen and shorten as the lamp turns. */
export const beam = (x, y, s = 1, fn = "beam") =>
  `<g ${place(x, y, s)}>` +
  `<path d="M0-7L1200-110V110L0 7Z" fill="url(#g-beam)" data-m="@${fn} 1" data-o="0% 50%"/>` +
  `<path d="M0-7L-1200-110V110L0 7Z" fill="url(#g-beam-l)" data-m="@${fn} -1" data-o="100% 50%"/>` +
  `<circle r="90" fill="url(#g-glow)" data-m="@${fn} 0"/></g>`;

/** The beam turning: `side` 1 is the right wedge, -1 the left, 0 the flash when it faces us. */
export function turningBeam(t, side, on = 1) {
  const a = (t / 60) * Math.PI * 2;
  if (side === 0) return { opacity: r1(on * Math.max(0, Math.sin(a)) ** 6) };
  return { transform: `scale(${r1(Math.max(0, side * Math.cos(a)) * on)},1)` };
}

/* ---------- Luna, and the animals built on her pattern ---------- */

const EAR = {
  cat: ["M-4-120L-2-152L18-130Z", "M24-132L44-156L48-122Z"],
  fox: ["M-6-118L-6-166L20-132Z", "M22-134L50-170L50-120Z"],
  rabbit: ["M-2-126C-14-190 6-214 14-150Z", "M22-134C24-204 50-208 40-130Z"],
  bear: ["M-6-126A16 16 0 1 1 14-138Z", "M28-138A16 16 0 1 1 48-122Z"],
  mouse: ["M-10-118A26 26 0 1 1 14-140Z", "M26-140A26 26 0 1 1 52-118Z"],
  dog: ["M-6-128C-26-128-30-86-14-82C-6-98-4-112 2-126Z", "M36-132C58-134 64-94 50-88C44-104 40-116 32-128Z"],
  dragon: ["M-2-124L-18-160L12-132Z", "M26-134L30-176L46-124Z"],
};
const TAIL = {
  cat: "M-36-8C-70-10-78-50-66-80C-62-90-52-88-54-80C-64-52-58-24-30-20Z",
  fox: "M-34-6C-90-2-104-60-80-92C-70-76-60-40-30-22Z",
  rabbit: "M-40-24A16 16 0 1 1-40-25Z",
  bear: "M-40-20A9 9 0 1 1-40-21Z",
  mouse: "M-36-8C-70-6-96-20-110-50C-100-26-72-14-34-16Z",
  dog: "M-36-24C-60-34-66-60-58-76C-52-60-46-44-30-34Z",
  dragon: "M-34-6C-84 0-120-20-140-54L-150-34L-128-30C-108-10-70-6-30-20Z",
};

/**
 * A sitting animal on Luna's pattern: body, haunch, chest, one front leg, head, ears, tail.
 * Luna is the default; the others change ears, tail and colours. Facing right; the ground is y = 0.
 */
export function critter({
  x,
  y,
  s = 1,
  flip = false,
  kind = "cat",
  body = PAL.cat,
  mid = PAL.catMid,
  dark = PAL.catDk,
  light = PAL.catLt,
  eye = PAL.lamp,
  m = "",
  tail = "sway 7 30",
  eyes = "blink 56",
  look = "",
  cut = true,
}) {
  const [earB, earF] = EAR[kind];
  const tailFill = kind === "fox" ? body : dark;
  const tip =
    kind === "fox" ? `<path d="M-80-92C-84-80-86-68-84-58C-74-66-70-78-72-88Z" fill="${PAL.cream}"/>` : "";
  const snout =
    kind === "bear" || kind === "dog" ? `<ellipse cx="32" cy="-100" rx="18" ry="12" fill="${light}"/>` : "";
  const spikes =
    kind === "dragon"
      ? `<path d="M-30-64L-40-80L-22-74L-24-92L-8-84L-4-100L8-90" fill="none" stroke="${dark}" stroke-width="8" stroke-linejoin="round"/>` +
        `<path d="M-20-60C-50-110-10-130 10-96C-10-100-18-86-20-60Z" fill="${mid}" data-m="sway 10 14" data-o="100% 100%"/>`
      : "";
  return (
    `<g ${place(x, y, s, flip)}><g ${cut ? "data-cut" : ""} ${m ? `data-m="${m}"` : ""} data-o="50% 100%">` +
    `<g data-m="${tail}" data-o="100% 100%"><path d="${TAIL[kind]}" fill="${tailFill}"/>${tip}</g>` +
    spikes +
    `<path d="M-40 0C-52-30-44-78-10-92C12-100 34-86 38-60C42-36 36-12 30 0Z" fill="${body}"/>` +
    `<ellipse cx="-18" cy="-26" rx="26" ry="24" fill="${mid}"/>` +
    `<path d="M22-84C36-70 38-40 30-16C22-36 16-64 22-84Z" fill="${light}"/>` +
    `<path d="M12-40H26L28-5Q28 0 23 0H13Q9 0 10-5Z" fill="${mid}"/><ellipse cx="19" cy="-3" rx="9" ry="4" fill="${light}"/>` +
    `<g data-m="sway 3 70 .2" data-o="30% 90%">` +
    `<path d="${earB}" fill="${dark}"/><path d="${earF}" fill="${body}"/>` +
    (kind === "cat" || kind === "fox"
      ? `<path d="M28-132L41-148L43-128Z" fill="${PAL.nose}" opacity=".7"/>`
      : "") +
    `<ellipse cx="20" cy="-112" rx="32" ry="28" fill="${body}"/>` +
    `<ellipse cx="29" cy="-100" rx="14" ry="10" fill="${light}"/>${snout}` +
    `<g data-m="${eyes}" data-o="50% 50%">` +
    `<path d="M5-117Q12-124 19-117Q12-110 5-117ZM27-117Q34-124 41-117Q34-110 27-117Z" fill="${eye}"/>` +
    `<g ${look ? `data-m="${look}"` : ""}><ellipse cx="12" cy="-117" rx="1.8" ry="5" fill="${PAL.pupil}"/>` +
    `<ellipse cx="34" cy="-117" rx="1.8" ry="5" fill="${PAL.pupil}"/></g></g>` +
    `<path d="M26-106H34L30-101Z" fill="${PAL.nose}"/>` +
    `<path d="M30-101q-3 4-6 2M30-101q3 4 6 2" fill="none" stroke="${PAL.pupil}" stroke-width="1.3"/>` +
    `<path d="M38-103L62-108M38-100L62-98M20-103L-2-107M20-100L-2-99" stroke="${PAL.cream}" stroke-width="1.2" opacity=".7"/>` +
    `</g></g></g>`
  );
}

/** Luna asleep, curled into a loaf with her tail round her paws. */
export const lunaCurled = ({ x, y, s = 1, flip = false, breathe = "breathe .04 40" }) =>
  `<g ${place(x, y, s, flip)}><g data-cut><g data-m="${breathe}" data-o="50% 100%">` +
  `<ellipse cx="0" cy="-30" rx="70" ry="32" fill="${PAL.cat}"/>` +
  `<ellipse cx="-30" cy="-34" rx="30" ry="24" fill="${PAL.catMid}"/>` +
  `<path d="M-60-8C-30 6 40 8 66-10C72-16 66-23 59-17C38-2-20 0-56-16Z" fill="${PAL.catDk}"/>` +
  `<path d="M30-44L36-72L50-50ZM52-48L66-72L70-40Z" fill="${PAL.cat}"/>` +
  `<ellipse cx="50" cy="-30" rx="28" ry="22" fill="${PAL.cat}"/><ellipse cx="60" cy="-22" rx="13" ry="8" fill="${PAL.catLt}"/>` +
  `<path d="M38-32q5 4 10 0M56-32q5 4 10 0" fill="none" stroke="${PAL.pupil}" stroke-width="2"/>` +
  `<path d="M62-26H69L65.5-22Z" fill="${PAL.nose}"/></g></g></g>`;

/* ---------- Tomás ---------- */

/** Old Tomás in his oilskin and sou'wester. `arm` is "up" (lighting the lamp) or "lantern". */
export function tomas({ x, y, s = 1, flip = false, arm = "lantern", m = "" }) {
  const lantern =
    `<g transform="translate(4 74)"><path d="M-2-14h14" stroke="${PAL.oakDk}" stroke-width="3"/>` +
    `<rect x="-6" y="-8" width="22" height="30" rx="3" fill="${PAL.oakDk}"/><rect x="-2" y="-4" width="14" height="22" fill="${PAL.lamp}" data-m="flick .75"/>` +
    `<circle cx="5" cy="7" r="30" fill="url(#g-glow)" data-m="flick .7"/></g>`;
  const taper = `<path d="M8 72L20 150" stroke="${PAL.cream}" stroke-width="4"/><path d="M20 150q-8 10 1 22q8-12-1-22Z" fill="${PAL.lamp}" data-m="flick .7"/>`;
  const armPart =
    arm === "up"
      ? `<g transform="translate(22 -168) rotate(-128)"><path d="M-8 0H10L14 70H-4Z" fill="${PAL.oilskinDk}"/><circle cx="5" cy="74" r="10" fill="${PAL.skin}"/>${taper}</g>`
      : `<g transform="translate(22 -166) rotate(-8)"><g data-m="sway 3 48" data-o="50% 0%"><path d="M-8 0H10L14 70H-4Z" fill="${PAL.oilskinDk}"/><circle cx="5" cy="74" r="10" fill="${PAL.skin}"/>${lantern}</g></g>`;
  return (
    `<g ${place(x, y, s, flip)}><g data-cut ${m ? `data-m="${m}"` : ""} data-o="50% 100%">` +
    `<path d="M-24-44H-4V-6H-30Q-32 0-26 0H-4ZM4-44H24V0H6Q-2 0 4-6Z" fill="${PAL.boot}"/>` +
    `<path d="M-34-172H34L54-40H-54Z" fill="${PAL.oilskin}"/>` +
    `<path d="M0-172V-40" stroke="${PAL.oilskinDk}" stroke-width="3"/>` +
    `<circle cx="-7" cy="-140" r="3.5" fill="${PAL.oilskinDk}"/><circle cx="-7" cy="-108" r="3.5" fill="${PAL.oilskinDk}"/><circle cx="-7" cy="-76" r="3.5" fill="${PAL.oilskinDk}"/>` +
    `<path d="M-40-160L-34-172H-10L-24-146Z" fill="${PAL.oilskinDk}"/>` +
    `<g data-m="sway 2 64" data-o="50% 100%">` +
    `<circle cx="0" cy="-198" r="27" fill="${PAL.skin}"/>` +
    `<path d="M-24-196C-26-166-8-150 6-152C20-154 28-170 25-196C16-186-14-186-24-196Z" fill="${PAL.beard}"/>` +
    `<path d="M4-188Q14-194 24-186Q14-182 4-188Z" fill="${PAL.beard}"/>` +
    `<circle cx="24" cy="-196" r="6" fill="${PAL.skinDk}"/>` +
    `<g data-m="blink 70 20" data-o="50% 50%"><circle cx="12" cy="-206" r="2.8" fill="${PAL.pupil}"/></g>` +
    `<path d="M6-214q7-4 13 0" fill="none" stroke="${PAL.beard}" stroke-width="3"/>` +
    `<path d="M-24-212C-22-240 22-240 24-212Z" fill="${PAL.oilskin}"/>` +
    `<path d="M-38-206Q0-218 44-200L42-194Q0-210-38-200Z" fill="${PAL.oilskinDk}"/></g>` +
    armPart +
    `</g></g>`
  );
}

/* ---------- the boat ---------- */

/** The Marisol, a little red boat with a lantern on her mast. The waterline is y = 0. */
export const boat = ({ x, y, s = 1, flip = false, m = "rock 5 5 34", name = true }) =>
  `<g ${place(x, y, s, flip)}><g data-cut data-m="${m}" data-o="50% 60%">` +
  `<path d="M40-24V-136" stroke="${PAL.oakDk}" stroke-width="6"/>` +
  `<path d="M43-132L80-120L43-108Z" fill="${PAL.cream}" data-m="sway 8 10" data-o="0% 50%"/>` +
  `<rect x="28" y="-158" width="24" height="22" rx="3" fill="${PAL.oakDk}"/><rect x="32" y="-154" width="16" height="14" fill="${PAL.lamp}" data-m="flick .7"/>` +
  `<circle cx="40" cy="-147" r="44" fill="url(#g-glow)" data-m="flick .6"/>` +
  `<rect x="-46" y="-72" width="70" height="9" fill="${PAL.oakDk}"/>` +
  `<rect x="-40" y="-64" width="56" height="40" fill="${PAL.cream}"/><rect x="-28" y="-56" width="16" height="14" fill="${PAL.lamp}"/>` +
  `<path d="M-104-26H104Q90 10 62 22H-66Q-92 10-104-26Z" fill="${PAL.madder}"/>` +
  `<path d="M-102-20H102L99-11H-99Z" fill="${PAL.cream}"/>` +
  (name
    ? `<text x="-4" y="12" text-anchor="middle" font-family="Courier Prime, monospace" font-size="15" font-weight="700" fill="${PAL.cream}" letter-spacing="2">MARISOL</text>`
    : "") +
  `</g></g>`;

/* ---------- the magic lantern ---------- */

/** The lantern itself, side on: oak body, chimney, the slide in its carrier, the brass lens. */
export const magicLantern = () =>
  `<g data-cut>` +
  `<g opacity=".7"><circle cx="128" cy="18" r="10" fill="${PAL.thread}" data-m="smoke 30 0"/>` +
  `<circle cx="132" cy="18" r="12" fill="${PAL.thread}" data-m="smoke 30 .5"/></g>` +
  `<rect x="100" y="44" width="56" height="74" fill="${PAL.oakDk}"/>` +
  `<rect x="88" y="30" width="80" height="16" rx="3" fill="${PAL.brass}"/>` +
  `<g fill="${PAL.lamp}" data-m="flick .55">` +
  [0, 1, 2, 3]
    .map((i) => `<circle cx="${112 + i * 11}" cy="62" r="3"/><circle cx="${117 + i * 11}" cy="76" r="3"/>`)
    .join("") +
  `</g>` +
  `<rect x="40" y="116" width="184" height="138" rx="10" fill="${PAL.oak}"/>` +
  `<rect x="40" y="116" width="184" height="14" rx="6" fill="${PAL.brass}"/>` +
  `<rect x="40" y="240" width="184" height="14" rx="6" fill="${PAL.brass}"/>` +
  `<circle cx="104" cy="186" r="22" fill="${PAL.oakDk}"/><circle cx="104" cy="186" r="13" fill="${PAL.madder}" data-m="flick .6"/>` +
  `<path d="M60 254L52 292M204 254L212 292" stroke="${PAL.oakDk}" stroke-width="10" stroke-linecap="round"/>` +
  `<rect x="224" y="96" width="22" height="178" rx="3" fill="${PAL.oakDk}"/>` +
  `<rect x="229" y="104" width="12" height="162" fill="${PAL.night3}"/>` +
  `<rect x="246" y="150" width="70" height="72" rx="4" fill="${PAL.brass}"/>` +
  `<rect x="262" y="146" width="10" height="80" rx="3" fill="${PAL.brassDk}"/>` +
  `<rect x="316" y="158" width="44" height="56" rx="4" fill="${PAL.brass}"/>` +
  `<rect x="338" y="154" width="8" height="64" rx="3" fill="${PAL.brassDk}"/>` +
  `<ellipse cx="362" cy="186" rx="10" ry="30" fill="${PAL.glow}" data-m="flick .85"/>` +
  `</g>`;

/* ---------- the workshop: the animator's hand and the scissors ---------- */

/** The animator's hand reaching down from above, index finger out, as it does between two frames. */
export const hand = () =>
  `<g data-cut><rect x="-44" y="-420" width="128" height="132" fill="${PAL.night3}"/>` +
  `<rect x="-46" y="-300" width="132" height="16" fill="${PAL.cream}"/>` +
  `<path d="M-36-286H76L80-176Q78-128 52-116L22-110Q-26-114-34-160Z" fill="#d9a882"/>` +
  `<path d="M-34-214Q-64-178-54-140Q-46-124-30-142L-24-190Z" fill="#c68f69"/>` +
  `<path d="M22-126Q34-92 46-122Q58-94 70-124Q80-110 78-150L22-150Z" fill="#c68f69"/>` +
  `<path d="M-8-132L22-130L20-10Q18 4 6 4Q-8 4-10-10Z" fill="#d9a882"/>` +
  `<path d="M-2-14Q6-6 14-14" fill="none" stroke="#b67f5c" stroke-width="3"/></g>`;

/** Scissors, open by `a` degrees on each blade. */
export const scissors = (a = 14) =>
  `<g data-cut><g transform="rotate(${-a})"><path d="M0-5L118-2Q124 0 118 2L0 5Z" fill="${PAL.cream}"/>` +
  `<path d="M-6 0C-30-2-54 6-56 22C-58 38-36 42-24 32C-14 24-10 12-6 0Z" fill="${PAL.madder}"/><circle cx="-36" cy="22" r="9" fill="${PAL.night1}"/></g>` +
  `<g transform="rotate(${a})"><path d="M0-5L118-2Q124 0 118 2L0 5Z" fill="#d7d0c2"/>` +
  `<path d="M-6 0C-30 2-54-6-56-22C-58-38-36-42-24-32C-14-24-10-12-6 0Z" fill="${PAL.madder}"/><circle cx="-36" cy="-22" r="9" fill="${PAL.night1}"/></g>` +
  `<circle r="5" fill="${PAL.brass}"/></g>`;
