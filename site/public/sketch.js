/* The visitor's idea, put on a slide. This is a toy, and says so on the page: it picks paper figures
 * for the words it knows (in English, Spanish and Portuguese), sets them in a place and throws the
 * slide up with the idea as its title. The real writer and image models do the rest in the app. */

import { PAL, boat, critter, hangingMoon, hangingStar, nightSky, seas, starPath, tomas } from "./art.js";

const r1 = (n) => Math.round(n * 10) / 10;
const at = (x, y, s = 1, flip = false) =>
  `transform="translate(${r1(x)} ${r1(y)}) scale(${flip ? -s : s} ${s})"`;
const cut = (s) => `<g data-cut>${s}</g>`;

/* ---------- figures ---------- */

const ANIMALS = {
  cat: {},
  fox: { body: "#d9772b", mid: "#c86a22", dark: "#a8561a", light: "#f3e3cf" },
  rabbit: { body: "#d8cbb8", mid: "#cbbca6", dark: "#b4a58e", light: "#f3ece1" },
  bear: { body: "#8a5a3b", mid: "#7b5033", dark: "#5f3d22", light: "#c89b72" },
  mouse: { body: "#a7a1a6", mid: "#9a949a", dark: "#7f7a80", light: "#e7dfe3" },
  dog: { body: "#c8935a", mid: "#b98450", dark: "#7b5230", light: "#efdcc2" },
  dragon: { body: "#4f9a73", mid: "#43875f", dark: "#2f6b4a", light: "#cfe3b0", eye: PAL.glow },
};

const smallLantern = (x, y) =>
  `<g transform="translate(${x} ${y})"><rect x="-10" y="-14" width="20" height="26" rx="3" fill="${PAL.oakDk}"/>` +
  `<rect x="-6" y="-10" width="12" height="18" fill="${PAL.lamp}" data-m="flick .7"/><circle r="34" fill="url(#g-glow)" data-m="flick .6"/></g>`;

const HATS = {
  witch: `<path d="M-42-152H42L32-144H-32Z" fill="#3a2c5a"/><path d="M-22-152L10-226L24-152Z" fill="#3a2c5a"/>`,
  crown: `<path d="M-18-158V-178L-9-167L0-182L9-167L18-178V-158Z" fill="${PAL.brass}"/>`,
  bun: `<circle cx="-18" cy="-160" r="13" fill="#c9c4bc"/>`,
  none: "",
};

function person({
  x,
  y,
  s = 1,
  flip = false,
  coat = PAL.madder,
  hair = "#5f3d22",
  hat = "none",
  elder = false,
  lantern = false,
}) {
  const hairShape = elder
    ? `<path d="M-27-134C-30-166 30-166 27-134C22-146-22-146-27-134Z" fill="#c9c4bc"/>`
    : `<path d="M-28-128C-34-170 32-172 28-128C24-150-20-152-28-128Z" fill="${hair}"/><path d="M-28-130C-32-110-24-100-18-104L-20-130Z" fill="${hair}"/>`;
  return (
    `<g ${at(x, y, s, flip)}><g data-cut data-m="bob 2 30" data-o="50% 100%">` +
    `<path d="M-15-42H-4V0H-18ZM4-42H15V0H2Z" fill="${PAL.boot}"/>` +
    `<path d="M-26-112H26L38-36H-38Z" fill="${coat}"/>` +
    `<g transform="translate(20 -106)"><g data-m="sway 5 36" data-o="50% 0%"><path d="M-6 0H8L10 52H-3Z" fill="${coat}"/>` +
    `<circle cx="3" cy="56" r="8" fill="${PAL.skin}"/>${lantern ? smallLantern(4, 80) : ""}</g></g>` +
    `<circle cx="0" cy="-134" r="26" fill="${PAL.skin}"/>${hairShape}` +
    `<g data-m="blink 64 12" data-o="50% 50%"><circle cx="11" cy="-138" r="2.6" fill="${PAL.pupil}"/></g>` +
    `<circle cx="16" cy="-127" r="5" fill="${PAL.nose}" opacity=".5"/>` +
    `<path d="M8-122q5 3 10-1" fill="none" stroke="${PAL.pupil}" stroke-width="2"/>` +
    (elder ? `<circle cx="12" cy="-138" r="7" fill="none" stroke="${PAL.dark}" stroke-width="2"/>` : "") +
    HATS[hat] +
    `</g></g>`
  );
}

const owl = (x, y, s = 1) =>
  `<g ${at(x, y, s)}><g data-cut data-m="bob 2 36" data-o="50% 100%">` +
  `<path d="M-50 0C-60-60-40-120 0-124C40-120 60-60 50 0Z" fill="#8a6a4a"/><path d="M-28 0C-34-40-20-70 0-72C20-70 34-40 28 0Z" fill="#c9a77c"/>` +
  `<path d="M-40-110L-46-146L-20-120ZM40-110L46-146L20-120Z" fill="#8a6a4a"/>` +
  `<circle cx="-20" cy="-92" r="18" fill="${PAL.cream}"/><circle cx="20" cy="-92" r="18" fill="${PAL.cream}"/>` +
  `<g data-m="blink 50" data-o="50% 50%"><circle cx="-20" cy="-92" r="9" fill="${PAL.lamp}"/><circle cx="20" cy="-92" r="9" fill="${PAL.lamp}"/>` +
  `<circle cx="-20" cy="-92" r="4" fill="${PAL.pupil}"/><circle cx="20" cy="-92" r="4" fill="${PAL.pupil}"/></g>` +
  `<path d="M-7-78L7-78L0-64Z" fill="${PAL.brass}"/></g></g>`;

const whale = (x, y, s = 1) =>
  `<g ${at(x, y, s)}><g data-cut data-m="bob 6 40" data-o="50% 100%">` +
  `<g data-m="flick .3"><path d="M-20-120q-10-30 0-50M0-124q0-34 0-56M20-120q10-30 0-50" fill="none" stroke="${PAL.cream}" stroke-width="6" stroke-linecap="round"/></g>` +
  `<path d="M-140 0C-150-70-80-110 0-110C90-110 150-60 150 0Z" fill="${PAL.sea3}"/>` +
  `<path d="M-130-2C-100 10 100 10 146-2L140 10H-126Z" fill="${PAL.cream}"/>` +
  `<g data-m="sway 10 30" data-o="100% 100%"><path d="M-140-20C-170-40-200-30-210-60C-190-50-170-60-160-80C-160-50-150-40-130-34Z" fill="${PAL.sea3}"/></g>` +
  `<circle cx="80" cy="-50" r="6" fill="${PAL.pupil}"/><path d="M90-26q20 6 40-4" fill="none" stroke="${PAL.pupil}" stroke-width="3"/></g></g>`;

const robot = (x, y, s = 1) =>
  `<g ${at(x, y, s)}><g data-cut data-m="bob 3 20" data-o="50% 100%">` +
  `<rect x="-26" y="-40" width="16" height="40" fill="#7d8796"/><rect x="10" y="-40" width="16" height="40" fill="#7d8796"/>` +
  `<rect x="-44" y="-120" width="88" height="84" rx="8" fill="#a7b3c2"/><rect x="-20" y="-100" width="40" height="30" rx="4" fill="#7d8796"/>` +
  `<circle cx="-8" cy="-85" r="5" fill="${PAL.madder}" data-m="flick .3"/><circle cx="8" cy="-85" r="5" fill="${PAL.lamp}" data-m="flick .3"/>` +
  `<g data-m="sway 4 40" data-o="50% 100%"><rect x="-32" y="-184" width="64" height="56" rx="10" fill="#b9c4d1"/>` +
  `<rect x="-20" y="-168" width="14" height="10" rx="2" fill="${PAL.lamp}"/><rect x="6" y="-168" width="14" height="10" rx="2" fill="${PAL.lamp}"/>` +
  `<path d="M-10-146H10" stroke="#7d8796" stroke-width="4"/><path d="M0-184V-206" stroke="#7d8796" stroke-width="4"/>` +
  `<circle cy="-210" r="7" fill="${PAL.madder}"/><circle cy="-210" r="22" fill="url(#g-glow)" data-m="flick .4"/></g></g></g>`;

const ghost = (x, y, s = 1) =>
  `<g ${at(x, y, s)}><g data-cut data-m="bob 10 36" data-o="50% 50%">` +
  `<path d="M-50-20C-56-110-30-160 0-160C30-160 56-110 50-20L38-30L26-16L12-30L0-16L-12-30L-26-16L-38-30Z" fill="#e8eef2"/>` +
  `<g data-m="blink 70" data-o="50% 50%"><ellipse cx="-14" cy="-110" rx="7" ry="10" fill="${PAL.night1}"/><ellipse cx="14" cy="-110" rx="7" ry="10" fill="${PAL.night1}"/></g>` +
  `<ellipse cx="0" cy="-84" rx="8" ry="6" fill="${PAL.night1}"/></g></g>`;

const bird = (x, y, s = 1) =>
  `<g ${at(x, y, s)}><g data-cut data-m="bob 4 10" data-o="50% 100%">` +
  `<path d="M-6 0V-14M8 0V-14" stroke="${PAL.brass}" stroke-width="4"/>` +
  `<ellipse cx="0" cy="-44" rx="40" ry="32" fill="${PAL.madder}"/><ellipse cx="10" cy="-36" rx="20" ry="18" fill="${PAL.paper}"/>` +
  `<g data-m="sway 20 8" data-o="100% 0%"><path d="M-30-56C-60-60-60-30-30-34Z" fill="${PAL.madderDk}"/></g>` +
  `<path d="M36-54L56-48L36-42Z" fill="${PAL.brass}"/><circle cx="22" cy="-56" r="4" fill="${PAL.pupil}"/></g></g>`;

/** Who may be cast, the words that call them, and how each is drawn at (x, y), facing `flip`. */
const CAST = [
  {
    id: "dragon",
    words: ["dragon", "dragón", "dragão"],
    draw: (x, y, f) => critter({ x, y, s: 1.35, flip: f, kind: "dragon", ...ANIMALS.dragon }),
  },
  {
    id: "cat",
    words: ["cat", "kitten", "kitty", "gato", "gata", "gatito", "gatita", "gatinho", "gatinha"],
    draw: (x, y, f) => critter({ x, y, s: 1.25, flip: f }),
  },
  {
    id: "fox",
    words: ["fox", "zorro", "zorra", "raposa"],
    draw: (x, y, f) => critter({ x, y, s: 1.25, flip: f, kind: "fox", ...ANIMALS.fox }),
  },
  {
    id: "rabbit",
    words: ["rabbit", "bunny", "hare", "conejo", "coelho"],
    draw: (x, y, f) => critter({ x, y, s: 1.2, flip: f, kind: "rabbit", ...ANIMALS.rabbit }),
  },
  {
    id: "bear",
    words: ["bear", "teddy", "oso", "osito", "urso", "ursinho"],
    draw: (x, y, f) => critter({ x, y, s: 1.5, flip: f, kind: "bear", ...ANIMALS.bear }),
  },
  {
    id: "mouse",
    words: ["mouse", "mice", "ratón", "raton", "rato", "ratinho"],
    draw: (x, y, f) => critter({ x, y, s: 1, flip: f, kind: "mouse", ...ANIMALS.mouse }),
  },
  {
    id: "dog",
    words: ["dog", "puppy", "pup", "perro", "perrito", "cachorro", "cão"],
    draw: (x, y, f) => critter({ x, y, s: 1.3, flip: f, kind: "dog", ...ANIMALS.dog }),
  },
  { id: "owl", words: ["owl", "búho", "buho", "lechuza", "coruja"], draw: (x, y) => owl(x, y, 1.2) },
  { id: "whale", words: ["whale", "ballena", "baleia"], sea: true, draw: (x) => whale(x, 690, 1.3) },
  { id: "robot", words: ["robot", "robô", "robo", "android"], draw: (x, y) => robot(x, y, 1.1) },
  { id: "ghost", words: ["ghost", "fantasma", "spirit"], draw: (x, y) => ghost(x, y - 60, 1.1) },
  {
    id: "bird",
    words: ["bird", "pájaro", "pajaro", "pássaro", "passarinho", "sparrow", "robin", "ave"],
    draw: (x, y, f) => bird(x, y, f ? -1.2 : 1.2),
  },
  {
    id: "witch",
    words: ["witch", "wizard", "bruja", "brujo", "bruxa", "bruxo", "mago", "maga"],
    draw: (x, y, f) => person({ x, y, s: 1.4, flip: f, coat: "#4b3b72", hat: "witch" }),
  },
  {
    id: "royal",
    words: ["king", "queen", "prince", "princess", "rey", "reina", "príncipe", "princesa", "rei", "rainha"],
    draw: (x, y, f) => person({ x, y, s: 1.4, flip: f, coat: PAL.madder, hat: "crown", hair: "#c98b3a" }),
  },
  {
    id: "grandma",
    words: ["grandma", "granny", "grandmother", "abuela", "abuelita", "avó", "vovó"],
    draw: (x, y, f) => person({ x, y, s: 1.45, flip: f, coat: "#5a7d6e", elder: true, hat: "bun" }),
  },
  {
    id: "grandpa",
    words: [
      "grandpa",
      "grandfather",
      "abuelo",
      "abuelito",
      "avô",
      "vovô",
      "sailor",
      "marinero",
      "marinheiro",
      "keeper",
    ],
    draw: (x, y, f) => tomas({ x, y, s: 1.05, flip: f }),
  },
  {
    id: "child",
    words: [
      "girl",
      "boy",
      "kid",
      "child",
      "children",
      "niña",
      "niño",
      "nena",
      "nene",
      "menina",
      "menino",
      "criança",
      "chica",
      "chico",
    ],
    draw: (x, y, f) => person({ x, y, s: 1.35, flip: f, lantern: true }),
  },
];

/* ---------- props ---------- */

const sock = (x, y, color, ph) =>
  `<g transform="translate(${x} ${y})"><g data-m="sway 6 30 ${ph}" data-o="50% 0%"><path d="M-12 0H12V44Q12 56 24 60Q40 66 34 78Q28 88 10 80L-8 72Q-14 68-12 58Z" fill="${color}"/>` +
  `<path d="M-12 14H12V22H-12ZM-12 30H12V38H-12Z" fill="${PAL.cream}" opacity=".8"/></g></g>`;

const tree = (x, s = 1, dark = "#1c3a30", light = "#285043") =>
  `<g ${at(x, 720, s)}><rect x="-10" y="-80" width="20" height="90" fill="${PAL.oakDk}"/>` +
  `<path d="M0-300L-70-150H-30L-90-60H90L30-150H70Z" fill="${dark}"/><path d="M0-300L-30-220L20-200Z" fill="${light}"/></g>`;

const house = (x, s = 1, wall = "#b98450") =>
  `<g ${at(x, 720, s)}><rect x="-70" y="-110" width="140" height="120" fill="${wall}"/><path d="M-90-106L0-190L90-106Z" fill="${PAL.madderDk}"/>` +
  `<rect x="-44" y="-84" width="30" height="30" fill="${PAL.lamp}" data-m="flick .7"/><rect x="14" y="-54" width="30" height="64" fill="${PAL.oakDk}"/></g>`;

/** Props, the words that call them, and whether they hang in the sky or stand on the ground. */
const PROPS = [
  { id: "moon", words: ["moon", "luna", "lua"], sky: true, draw: (x) => hangingMoon(x, 40, 60) },
  {
    id: "sun",
    words: ["sun", "sol", "sunny", "summer", "verano", "verão"],
    sky: true,
    draw: (x) =>
      `<g transform="translate(${x} 170)"><g data-m="spin .6">${Array.from({ length: 10 }, (_, i) => `<path transform="rotate(${i * 36})" d="M-9-80L0-120L9-80Z" fill="${PAL.lamp}"/>`).join("")}</g><circle r="66" fill="${PAL.glow}"/></g>`,
  },
  {
    id: "star",
    words: ["star", "stars", "estrella", "estrellas", "estrela", "estrelas", "wish", "deseo", "desejo"],
    sky: true,
    draw: (x) => hangingStar(x - 60, 80, 22, 0.2) + hangingStar(x + 50, 160, 16, 0.6),
  },
  {
    id: "planet",
    words: ["planet", "planeta", "saturn", "mars", "marte", "galaxy", "galaxia", "galáxia"],
    sky: true,
    draw: (x) =>
      `<g transform="translate(${x} 0)"><g data-m="sway 3 60" data-o="50% 0%"><line y1="-20" y2="110" stroke="${PAL.thread}" stroke-width="1.5"/>` +
      `<circle cy="170" r="56" fill="${PAL.madder}"/><ellipse cy="170" rx="96" ry="18" fill="none" stroke="${PAL.paper}" stroke-width="8"/></g></g>`,
  },
  {
    id: "rocket",
    words: ["rocket", "spaceship", "cohete", "nave", "foguete"],
    sky: true,
    draw: (x) =>
      `<g transform="translate(${x} 250) rotate(20)"><g data-m="bob 8 16"><path d="M0-110C30-80 34-20 26 30H-26C-34-20-30-80 0-110Z" fill="${PAL.cream}"/>` +
      `<circle cy="-40" r="14" fill="${PAL.sea3}" stroke="${PAL.brass}" stroke-width="5"/><path d="M-26 0L-50 40H-24ZM26 0L50 40H24Z" fill="${PAL.madder}"/>` +
      `<path d="M-18 30Q0 90 18 30Z" fill="${PAL.lamp}" data-m="flick .4"/></g></g>`,
  },
  {
    id: "balloon",
    words: ["balloon", "globo", "balão", "balao"],
    sky: true,
    draw: (x) =>
      `<g transform="translate(${x} 150)"><g data-m="sway 6 40" data-o="50% 100%"><ellipse rx="54" ry="66" fill="${PAL.madder}"/><path d="M-8 64H8L0 76Z" fill="${PAL.madderDk}"/>` +
      `<path d="M0 76Q-20 160 10 260" fill="none" stroke="${PAL.cream}" stroke-width="2"/></g></g>`,
  },
  {
    id: "kite",
    words: ["kite", "cometa", "pipa", "papagaio"],
    sky: true,
    draw: (x) =>
      `<g transform="translate(${x} 170)"><g data-m="sway 10 24" data-o="50% 100%"><path d="M0-80L56 0L0 90L-56 0Z" fill="${PAL.lamp}"/><path d="M0-80V90M-56 0H56" stroke="${PAL.oakDk}" stroke-width="4"/>` +
      `<path d="M0 90Q30 150 0 210Q-30 260 10 320" fill="none" stroke="${PAL.cream}" stroke-width="2"/></g></g>`,
  },
  {
    id: "sock",
    words: ["sock", "socks", "calcetín", "calcetines", "calcetin", "meia", "meias"],
    draw: (x, y = 430) =>
      `<g><path d="M${x - 170} ${y}Q${x} ${y + 40} ${x + 170} ${y}" fill="none" stroke="${PAL.cream}" stroke-width="3"/>` +
      sock(x - 110, y + 16, PAL.madder, 0) +
      sock(x, y + 22, PAL.sea3, 0.3) +
      sock(x + 100, y + 16, PAL.lamp, 0.6) +
      `</g>`,
  },
  {
    id: "lantern",
    words: [
      "lantern",
      "lamp",
      "light",
      "farol",
      "linterna",
      "lámpara",
      "lampara",
      "luz",
      "lanterna",
      "lâmpada",
    ],
    draw: (x) => `<g transform="translate(${x} 690) scale(2.2)">${smallLantern(0, 0)}</g>`,
  },
  {
    id: "book",
    words: ["book", "books", "library", "libro", "libros", "livro", "livros", "biblioteca"],
    draw: (x) =>
      `<g transform="translate(${x} 700)"><path d="M-90 0L0 16L90 0V-60L0-44L-90-60Z" fill="${PAL.oak}"/><path d="M-84-6L0 8V-50L-84-66ZM84-6L0 8V-50L84-66Z" fill="${PAL.cream}"/>` +
      `<path d="M-70-50L-14-40M-70-34L-14-24M14-40L70-50M14-24L70-34" stroke="${PAL.crater}" stroke-width="3"/></g>`,
  },
  {
    id: "cake",
    words: [
      "cake",
      "bakery",
      "bread",
      "baker",
      "pastel",
      "tarta",
      "panadería",
      "pan",
      "bolo",
      "padaria",
      "pão",
      "cookie",
      "galleta",
      "biscoito",
    ],
    draw: (x) =>
      `<g transform="translate(${x} 720)"><rect x="-80" y="-60" width="160" height="60" rx="8" fill="${PAL.paper}"/><rect x="-60" y="-110" width="120" height="54" rx="8" fill="${PAL.nose}"/>` +
      `<path d="M-80-40Q-60-20-40-40T0-40T40-40T80-40" fill="none" stroke="${PAL.cream}" stroke-width="8"/><rect x="-4" y="-150" width="8" height="40" fill="${PAL.cream}"/>` +
      `<path d="M0-150q-10-14 0-30q10 16 0 30Z" fill="${PAL.lamp}" data-m="flick .5"/></g>`,
  },
  {
    id: "clock",
    words: ["clock", "watch", "reloj", "relógio", "relogio"],
    draw: (x) =>
      `<g transform="translate(${x} 560)"><rect x="-10" y="60" width="20" height="100" fill="${PAL.oakDk}"/><circle r="72" fill="${PAL.brass}"/><circle r="60" fill="${PAL.cream}"/>` +
      `<g data-m="spin 6"><path d="M-3 0V-50H3V0Z" fill="${PAL.dark}"/></g><g data-m="spin .5"><path d="M-4 0V-34H4V0Z" fill="${PAL.madder}"/></g></g>`,
  },
  {
    id: "flower",
    words: ["flower", "flowers", "rose", "flor", "flores", "rosa", "girasol", "girassol"],
    draw: (x) =>
      [-60, 0, 60]
        .map(
          (dx, i) =>
            `<g transform="translate(${x + dx} 720)"><g data-m="sway 6 30 ${i * 0.3}" data-o="50% 100%"><path d="M0 0V-${90 + i * 20}" stroke="#4f9a73" stroke-width="6"/>` +
            `<g transform="translate(0 -${90 + i * 20})">${[0, 72, 144, 216, 288].map((a) => `<ellipse transform="rotate(${a}) translate(0 -18)" rx="11" ry="18" fill="${i === 1 ? PAL.lamp : PAL.nose}"/>`).join("")}<circle r="10" fill="${PAL.brass}"/></g></g></g>`,
        )
        .join(""),
  },
  { id: "tree", words: ["tree", "trees", "árbol", "arbol", "árvore", "arvore"], draw: (x) => tree(x, 0.85) },
  {
    id: "house",
    words: ["house", "home", "cottage", "casa", "hogar", "cabin", "cabaña", "cabana"],
    draw: (x) => house(x, 0.85),
  },
  {
    id: "castle",
    words: ["castle", "palace", "tower", "castillo", "palacio", "castelo", "palácio", "torre"],
    draw: (x) =>
      `<g transform="translate(${x} 720)"><path d="M-110 0V-160H-80V-180H-60V-160H-40V-180H-20V-160H20V-180H40V-160H60V-180H80V-160H110V0Z" fill="#8d95a3"/>` +
      `<rect x="-150" y="-250" width="50" height="250" fill="#7d8594"/><path d="M-160-250L-125-310L-90-250Z" fill="${PAL.madderDk}"/>` +
      `<rect x="100" y="-230" width="50" height="230" fill="#7d8594"/><path d="M90-230L125-290L160-230Z" fill="${PAL.madderDk}"/>` +
      `<path d="M-24 0V-50A24 24 0 0 1 24-50V0Z" fill="${PAL.dark}"/><rect x="-130" y="-200" width="12" height="22" fill="${PAL.lamp}" data-m="flick .6"/></g>`,
  },
  {
    id: "boat",
    words: ["boat", "ship", "barco", "barca", "navío", "navio", "barquito", "barquinho"],
    sea: true,
    draw: (x) => boat({ x, y: 690, s: 0.9, name: false }),
  },
];

/* ---------- places ---------- */

const PLACES = [
  {
    id: "sea",
    words: [
      "sea",
      "ocean",
      "beach",
      "island",
      "lighthouse",
      "mar",
      "océano",
      "oceano",
      "playa",
      "praia",
      "isla",
      "ilha",
      "faro",
      "farol",
      "wave",
      "ola",
      "onda",
      "pirate",
      "pirata",
    ],
  },
  {
    id: "space",
    words: ["space", "espacio", "espaço", "universe", "universo", "astronaut", "astronauta", "cosmos"],
  },
  {
    id: "snow",
    words: [
      "snow",
      "snowy",
      "nevado",
      "nevada",
      "winter",
      "ice",
      "arctic",
      "polar",
      "nieve",
      "invierno",
      "hielo",
      "neve",
      "inverno",
      "gelo",
      "christmas",
      "navidad",
      "natal",
    ],
  },
  { id: "forest", words: ["forest", "woods", "wood", "jungle", "bosque", "selva", "floresta", "mata"] },
  {
    id: "mountain",
    words: [
      "mountain",
      "mountains",
      "hill",
      "volcano",
      "montaña",
      "montana",
      "montanha",
      "colina",
      "volcán",
      "vulcão",
    ],
  },
  {
    id: "city",
    words: [
      "city",
      "town",
      "street",
      "village",
      "ciudad",
      "pueblo",
      "calle",
      "cidade",
      "vila",
      "rua",
      "bakery",
      "panadería",
      "padaria",
    ],
  },
  { id: "garden", words: ["garden", "park", "jardín", "jardin", "jardim", "parque", "huerto", "horta"] },
];

const DAY = [
  "morning",
  "day",
  "sunny",
  "sun",
  "summer",
  "mañana",
  "día",
  "dia",
  "manhã",
  "tarde",
  "afternoon",
  "sol",
];

const tokens = (idea) => idea.toLowerCase().match(/[\p{L}]+/gu) || [];
const has = (words, list) => list.some((w) => words.includes(w));

/** What the sketch understood: up to two of the cast, three props, a place, and night or day. */
export function read(idea) {
  const words = tokens(idea);
  const cast = CAST.filter((c) => has(words, c.words)).slice(0, 2);
  const props = PROPS.filter((p) => has(words, p.words)).slice(0, 3);
  const place =
    PLACES.find((p) => has(words, p.words))?.id ??
    (props.some((p) => p.sea) || cast.some((c) => c.sea)
      ? "sea"
      : props.some((p) => p.id === "planet" || p.id === "rocket")
        ? "space"
        : "meadow");
  const day = has(words, DAY) && place !== "space";
  return {
    cast: cast.length ? cast : [CAST.find((c) => c.id === "child")],
    props,
    place,
    day,
    guessed: !cast.length,
  };
}

function backdrop(place, day) {
  const sky = day
    ? nightSky("#7fa7c9", "#bcd3df")
    : place === "space"
      ? nightSky("#070c19", "#0b1426")
      : nightSky();
  const ground = (fill, light) =>
    cut(
      `<path d="M-100 700Q300 640 800 690T1700 670V1000H-100Z" fill="${fill}"/><path d="M-100 760Q500 720 900 760T1700 750V1000H-100Z" fill="${light}"/>`,
    );
  const starry = day
    ? ""
    : cut(
        [
          [470, 90, 12, 0.1],
          [700, 20, 10, 0.5],
          [900, 150, 13, 0.3],
          [1140, 110, 11, 0.8],
        ]
          .map(([x, l, r, ph]) => hangingStar(x, l, r, ph))
          .join(""),
      );
  switch (place) {
    case "sea":
      return sky + starry + seas({ y: 620 }).map(cut).join("");
    case "space":
      return (
        sky +
        cut(
          Array.from(
            { length: 26 },
            (_, i) =>
              `<path transform="translate(${(i * 263) % 1600} ${((i * 131) % 520) + 30})" d="${starPath(4 + (i % 4) * 2)}" fill="${PAL.paper}" data-m="flick .3"/>`,
          ).join(""),
        ) +
        cut(
          `<path d="M-100 740Q800 600 1700 740V1000H-100Z" fill="#8d8a86"/><ellipse cx="420" cy="760" rx="60" ry="14" fill="#77736f"/><ellipse cx="1180" cy="780" rx="80" ry="16" fill="#77736f"/>`,
        )
      );
    case "snow":
      return (
        sky +
        starry +
        ground("#c7d3de", "#e3eaf0") +
        cut(
          Array.from(
            { length: 30 },
            (_, i) =>
              `<circle cx="${(i * 197) % 1600}" cy="${(i * 89) % 640}" r="${3 + (i % 3) * 2}" fill="#f2f5f8" data-m="drift ${10 + (i % 4) * 6} ${30 + (i % 5) * 8} ${(i % 7) / 7}"/>`,
          ).join(""),
        )
      );
    case "forest":
      return (
        sky +
        starry +
        [80, 330, 1300, 1530].map((x, i) => tree(x, 1.2 + (i % 2) * 0.3)).join("") +
        ground(day ? "#4f8a5d" : "#1f3a33", day ? "#5f9a6b" : "#28473d")
      );
    case "mountain":
      return (
        sky +
        starry +
        cut(
          `<path d="M-100 700L300 260L560 560L820 300L1200 700Z" fill="${day ? "#6a7fa0" : "#2b3a55"}"/><path d="M300 260L240 330L300 316L360 340ZM820 300L760 370L830 356L880 380Z" fill="${PAL.cream}"/>` +
            `<path d="M700 700L1180 220L1700 700Z" fill="${day ? "#5a6e90" : "#34466a"}"/><path d="M1180 220L1110 300L1190 284L1250 306Z" fill="${PAL.cream}"/>`,
        ) +
        ground(day ? "#4f8a5d" : "#1f3a33", day ? "#5f9a6b" : "#28473d")
      );
    case "city":
      return (
        sky +
        starry +
        [120, 1480].map((x) => house(x, 1.1, "#8a6a4a")).join("") +
        ground(day ? "#8d95a3" : "#2a2f3a", day ? "#a7aeb9" : "#343a47")
      );
    case "garden":
      return (
        sky +
        starry +
        ground(day ? "#4f8a5d" : "#1f3a33", day ? "#5f9a6b" : "#28473d") +
        PROPS.find((p) => p.id === "flower").draw(1400)
      );
    default:
      return sky + starry + ground(day ? "#4f8a5d" : "#1f3a33", day ? "#5f9a6b" : "#28473d");
  }
}

/** The slide for an idea: its set, its cast facing each other, its props in the sky and on the ground. */
export function slide(idea) {
  const r = read(idea);
  const two = r.cast.length === 2;
  // The lantern's slide is round: only the middle of the 16:9 frame shows, so everything stays inside it.
  const castX = two ? [630, 980] : [800];
  const sky = [1010, 590];
  const ground = two ? [470, 1140] : [560, 1040];
  let skyN = 0;
  let groundN = 0;
  const props = r.props
    .map((p) => {
      if (p.sky) return p.draw(sky[skyN++ % 2]);
      if (p.id === "sock") return p.draw(800, 260);
      return p.draw(ground[groundN++ % 2]);
    })
    .join("");
  // At sea, whoever can't swim stands on a sandbank.
  const land = r.place === "sea" ? r.cast.filter((c) => !c.sea).map((c) => castX[r.cast.indexOf(c)]) : [];
  const banks = land
    .map((x) =>
      cut(`<path d="M${x - 210} 800C${x - 120} 700 ${x + 120} 700 ${x + 210} 800Z" fill="#c9a77c"/>`),
    )
    .join("");
  const cast = r.cast.map((c, i) => c.draw(castX[i], 720, i === 1)).join("");
  const svg =
    `<svg viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true"><g class="cam">` +
    backdrop(r.place, r.day) +
    props +
    banks +
    cast +
    // A whale or a boat sits in the water, not on it.
    (r.place === "sea" ? cut(seas({ y: 700 }).at(-1)) : "") +
    `</g></svg>`;
  return { svg, read: r };
}

/** The idea as a slide title: sentence case kept, the first letter raised. */
export const title = (idea) => {
  const t = idea
    .trim()
    .replace(/\s+/g, " ")
    .replace(/[.!]+$/, "");
  return t.charAt(0).toUpperCase() + t.slice(1);
};

const WHO = {
  dragon: "a dragon",
  cat: "a cat",
  fox: "a fox",
  rabbit: "a rabbit",
  bear: "a bear",
  mouse: "a mouse",
  dog: "a dog",
  owl: "an owl",
  whale: "a whale",
  robot: "a robot",
  ghost: "a ghost",
  bird: "a bird",
  witch: "a witch",
  royal: "someone with a crown",
  grandma: "a grandmother",
  grandpa: "a grandfather",
  child: "a child",
};

/** A few words on what the sketch understood, for the caption under the slide. */
export function describe(r) {
  const names = {
    meadow: "a meadow",
    sea: "the sea",
    space: "space",
    snow: "the snow",
    forest: "a forest",
    mountain: "the mountains",
    city: "a town",
    garden: "a garden",
  };
  const who = r.guessed ? "a child with a lantern" : r.cast.map((c) => WHO[c.id]).join(" and ");
  const what = r.props.length ? `, with ${r.props.map((p) => p.id).join(", ")}` : "";
  return `${who}${what}, in ${names[r.place]} by ${r.day ? "day" : "night"}`;
}
