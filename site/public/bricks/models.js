/* Every model on the page: the cast and sets of "The Little Red Brick", and the heroes, places and
 * wishes a visitor snaps together on the box. The characters are carved from simple shapes (an oval
 * body, a box of a snout), which `carve()` turns into bricks and plates with rounded edges; the
 * buildings are drawn letter by letter, where the exact brick matters. Sizes are in studs. */

import { box, carve, finish, model, oval, poly } from "./brick.js";

/* ---------- the little red brick ---------- */

/** The hero of the film: one red brick, two studs long. Its face is printed on frame by frame. */
export const BRICK = model({ r: "red" }, "b rr");

/** The brick's face for a mood, looking along `look` (-1 left to 1 right, then down to up). */
export function face(mood = "happy", look = [0.35, 0]) {
  const eyes = (extra = {}) => [
    { k: "eye", x: 0.6, y: 1.95, r: 0.27, look, ...extra },
    { k: "eye", x: 1.4, y: 1.95, r: 0.27, look, ...extra },
  ];
  const mouths = {
    happy: [{ k: "mouth", x: 1, y: 0.95, w: 0.46 }],
    joy: [{ k: "mouth", x: 1, y: 0.9, w: 0.5, open: 0.7 }],
    oh: [{ k: "mouth", x: 1, y: 0.85, w: 0.34, open: 1 }],
    worried: [{ k: "mouth", x: 1, y: 0.8, w: 0.4, bend: -0.6 }],
    set: [{ k: "mouth", x: 1, y: 0.9, w: 0.36, bend: 0.1 }],
  };
  if (mood === "joy") return [...eyes({ shut: "up" }), ...mouths.joy];
  if (mood === "worried") return [...eyes({ brow: -1 }), ...mouths.worried];
  if (mood === "set") return [...eyes({ brow: 1 }), ...mouths.set];
  return [...eyes(), ...(mouths[mood] ?? mouths.happy)];
}

/* ---------- the playroom ---------- */

/** A slab of one colour: a wall, a floor, a table top. `kind` is the row height, `b`, `p` or `t`. */
export function slab(w, rows, colour, { kind = "b", long = 6 } = {}) {
  const row = `${kind} ${"x".repeat(w)}`;
  return model({ x: colour }, Array(rows).fill(row).join("\n"), { long });
}

/** The rocket the bricks are building, missing its top brick: the little red brick's place. */
export const ROCKET = model(
  {
    r: "red",
    R: ["red", "curve"],
    w: "white",
    b: "blue",
    B: ["blue", "slope"],
    k: "grey",
    y: "yellow",
  },
  `
  b ..RrrR..
  b .RrrrrR.
  b .wwwwww.
  b .wwwwww.
  b .wwwwww.
  b .rrrrrr.
  b .wwwwww.
  b .wwwwww.
  b Bwwwwwwb
  b bbyyyybb
  p bbkkkkbb
  p ..k..k..
  `,
  {
    prints: [
      { k: "ring", x: 4, y: 20.2, r: 1.25, c: "azure", rim: "lightGrey" },
      { k: "ring", x: 4, y: 11.2, r: 0.8, c: "azure", rim: "lightGrey" },
    ],
  },
);
/** Where the missing brick goes, from the rocket's bottom-left corner. */
export const ROCKET_TOP = [3, 32];

/** Loose bricks lying about on the table. */
export const LOOSE = [
  model({ y: "yellow" }, "b yy"),
  model({ b: "blue" }, "b bbbb"),
  model({ g: "green" }, "p gggg"),
  model({ o: "orange" }, "b o"),
  model({ w: "white" }, "b ww"),
  model({ a: "azure", A: ["azure", "slope"] }, "b aA"),
];

/** Pickle, a big soft dog, asleep on the rug with her chin on her paws. */
export const PICKLE_ASLEEP = carve(
  32,
  10.4,
  [
    ["nougat", oval(2.8, 2.4, 2.7, 1.3)],
    ["nougat", oval(12, 4.6, 9.6, 4.6)],
    ["brown", oval(9.6, 7.4, 3.2, 1.8)],
    ["nougat", oval(24, 5.4, 5.3, 4.9)],
    ["white", oval(28, 3.2, 3.7, 2.4)],
    ["black", oval(31, 4.5, 1, 0.9)],
    ["brown", oval(21.6, 5.2, 2.2, 4)],
    ["white", box(17.5, 0, 12.5, 1.4, 0.7)],
  ],
  { prints: [{ k: "eye", x: 25.6, y: 6.9, r: 0.72, shut: true }] },
);

/** Pickle's head from the side, awake, looking down her nose at whatever sits on it. */
export const PICKLE_HEAD = carve(
  24,
  17.2,
  [
    ["nougat", box(3, 0, 10, 8)],
    ["nougat", oval(10, 10, 7.5, 7)],
    ["nougat", box(13, 5, 8.6, 5.6, 2.6)],
    ["white", box(14, 5, 7.2, 2.2, 1)],
    ["black", oval(21.4, 9.2, 1.5, 1.3)],
    ["brown", oval(6.8, 10, 3, 5.6)],
    ["brown", oval(12.6, 14.8, 1.6, 0.8)],
  ],
  { prints: [{ k: "eye", x: 13, y: 12.6, r: 1, look: [0.6, -0.5] }] },
);
/** Pickle's mouth, drawn over her head: a smile, or a big yawn. */
export const pickleMouth = (yawn) =>
  yawn
    ? [{ k: "mouth", x: 18.4, y: 6.2, w: 3, open: 0.9 }]
    : [{ k: "mouth", x: 18.4, y: 6.3, w: 2.4, bend: 0.8 }];
/** Where a brick sits on Pickle's nose, from the head's bottom-left corner. */
export const PICKLE_NOSE = [17, 10.6];

/** The robot vacuum: a flat grey disc on wheels, two blue lights for eyes. */
export const VACUUM = carve(
  23,
  5.4,
  [
    ["grey", box(0.5, 0.9, 22, 3.1, 1.5)],
    ["lightGrey", box(1.2, 3.4, 20.6, 1.1, 0.5)],
    ["black", box(20.8, 1.2, 2, 2.2, 0.7)],
    ["black", oval(5.5, 0.6, 1.6, 0.7)],
    ["black", oval(17, 0.6, 1.6, 0.7)],
    ["sky", oval(11.5, 4.9, 0.8, 0.5)],
  ],
  {
    prints: [
      { k: "dot", x: 18.6, y: 2.6, r: 0.36, c: "azure", t: 0.2 },
      { k: "dot", x: 19.8, y: 2.6, r: 0.36, c: "azure", t: 0.2 },
    ],
  },
);

/** A pink slipper with a pompom, big enough to hide in. */
export const SLIPPER = carve(19, 6.6, [
  ["white", box(0, 0, 19, 1, 0.5)],
  ["pink", oval(11, 1, 8, 3.9)],
  ["pink", box(0.4, 0.8, 9, 2.3, 1.1)],
  ["white", oval(15.2, 5, 1.9, 1.6)],
]);

/* ---------- the heroes ---------- */

/**
 * The heroes a visitor may cast. `hand` is where a balloon string is held and `nose` where a sneeze
 * comes out, both in studs from the model's bottom-left corner.
 */
export const HEROES = {
  dragon: {
    m: carve(
      15,
      12.8,
      [
        [
          "green",
          poly([
            [0, 3.8],
            [5, 1.4],
            [6, 4.6],
            [1.4, 5.2],
          ]),
        ],
        ["green", oval(7, 4, 4.6, 3.8)],
        ["yellow", oval(8.6, 3.5, 2.5, 2.9)],
        ["green", box(4.4, 0, 2, 1.6, 0.4)],
        ["green", box(8.8, 0, 2, 1.6, 0.4)],
        [
          "lime",
          poly([
            [3.4, 6.4],
            [1.6, 11.4],
            [4.4, 9.8],
            [7.4, 7.2],
          ]),
        ],
        ["green", oval(10.9, 8.7, 3.5, 3.1)],
        ["green", box(11.8, 6.3, 3.2, 2.6, 1.1)],
        [
          "orange",
          poly([
            [9.2, 11.1],
            [9.6, 12.8],
            [10.6, 11.4],
          ]),
        ],
        [
          "orange",
          poly([
            [11.8, 11.4],
            [12.6, 12.8],
            [13, 11.1],
          ]),
        ],
      ],
      {
        prints: [
          { k: "eye", x: 11.8, y: 9.4, r: 0.62, look: [0.5, 0] },
          { k: "dot", x: 14.4, y: 8.3, r: 0.16, c: "darkGreen" },
          { k: "mouth", x: 13.3, y: 7.1, w: 1.1 },
          { k: "dot", x: 10.6, y: 7.9, r: 0.5, ry: 0.3, c: "pink", a: 0.6 },
        ],
      },
    ),
    hand: [11, 4.6],
    nose: [15, 7.6],
  },
  dinosaur: {
    m: carve(
      16,
      13,
      [
        [
          "teal",
          poly([
            [0, 2.4],
            [5.4, 1.4],
            [5.4, 4.6],
          ]),
        ],
        ["teal", oval(7.6, 3.9, 5, 3.2)],
        ["teal", box(4, 0, 2, 2)],
        ["teal", box(9.2, 0, 2, 2)],
        ["lime", oval(6, 5.2, 1, 0.7)],
        ["lime", oval(8.8, 5.8, 0.9, 0.6)],
        ["lime", oval(7.4, 3.4, 0.8, 0.6)],
        [
          "teal",
          poly([
            [10, 4],
            [12.6, 4],
            [14.2, 10.6],
            [12.2, 11],
          ]),
        ],
        ["teal", oval(13.8, 11.2, 2.2, 1.6)],
      ],
      {
        prints: [
          { k: "eye", x: 14.3, y: 11.7, r: 0.45, look: [0.5, 0] },
          { k: "mouth", x: 15.1, y: 10.6, w: 0.7 },
        ],
      },
    ),
    hand: [12.6, 6],
    nose: [16, 11.2],
  },
  bunny: {
    m: carve(
      10,
      14,
      [
        ["white", oval(5, 3.6, 3.6, 3.4)],
        ["white", oval(3, 0.6, 1.6, 0.7)],
        ["white", oval(7, 0.6, 1.6, 0.7)],
        ["white", oval(1.3, 3, 1.1, 1.1)],
        ["white", oval(5.6, 8, 3, 2.7)],
        ["white", box(2, 9.4, 3, 4.8, 1.2)],
        ["white", box(6, 9.4, 3, 4.8, 1.2)],
        ["pink", box(3, 10.4, 1, 3)],
        ["pink", box(7, 10.4, 1, 3)],
      ],
      {
        prints: [
          { k: "eye", x: 4.6, y: 8.4, r: 0.42, look: [0.3, 0] },
          { k: "eye", x: 6.8, y: 8.4, r: 0.42, look: [0.3, 0] },
          { k: "dot", x: 5.8, y: 7.4, r: 0.26, c: "pink", t: -0.1 },
          { k: "mouth", x: 5.8, y: 6.8, w: 0.6 },
          { k: "dot", x: 3.8, y: 7.2, r: 0.4, ry: 0.25, c: "pink", a: 0.7 },
          { k: "dot", x: 7.8, y: 7.2, r: 0.4, ry: 0.25, c: "pink", a: 0.7 },
        ],
      },
    ),
    hand: [8.4, 4],
    nose: [8.4, 7.6],
  },
  robot: {
    m: carve(
      10,
      14,
      [
        ["grey", box(2.4, 0, 1.8, 2.2)],
        ["grey", box(5.8, 0, 1.8, 2.2)],
        ["lightGrey", box(1, 2, 8, 5.2, 0.6)],
        ["blue", box(3, 3, 4, 2.8, 0.3)],
        ["grey", box(0, 2.8, 1.3, 3.6, 0.5)],
        ["grey", box(8.7, 2.8, 1.3, 3.6, 0.5)],
        ["grey", box(4, 7, 2, 1)],
        ["lightGrey", box(1.4, 7.8, 7.2, 4.2, 1)],
        ["grey", box(4.6, 11.8, 0.8, 1.2)],
        ["red", oval(5, 13.2, 0.9, 0.8)],
      ],
      {
        prints: [
          { k: "eye", x: 3.8, y: 10.2, r: 0.62, iris: "azure", look: [0.3, 0] },
          { k: "eye", x: 6.2, y: 10.2, r: 0.62, iris: "azure", look: [0.3, 0] },
          { k: "mouth", x: 5, y: 8.8, w: 1.4, bend: 0.5 },
          { k: "dot", x: 4.2, y: 4.4, r: 0.3, c: "yellow" },
          { k: "dot", x: 5.8, y: 4.4, r: 0.3, c: "lime" },
        ],
      },
    ),
    hand: [9.6, 3],
    nose: [8.6, 9.6],
  },
  penguin: {
    m: carve(
      10,
      11.4,
      [
        ["black", oval(5, 5.4, 4, 5.2)],
        ["white", oval(5.4, 4.4, 2.9, 3.9)],
        ["white", oval(5.4, 7.8, 2.4, 1.9)],
        ["black", oval(1.2, 4.6, 0.9, 2.6)],
        [
          "orange",
          poly([
            [6.2, 7.8],
            [8.9, 7],
            [6.2, 6.1],
          ]),
        ],
        ["orange", oval(3.4, 0.5, 1.5, 0.6)],
        ["orange", oval(6.8, 0.5, 1.5, 0.6)],
      ],
      {
        prints: [
          { k: "eye", x: 4.6, y: 8.3, r: 0.4, look: [0.4, 0] },
          { k: "eye", x: 6.4, y: 8.3, r: 0.4, look: [0.4, 0] },
          { k: "dot", x: 4, y: 7, r: 0.35, ry: 0.22, c: "pink", a: 0.7 },
        ],
      },
    ),
    hand: [8.6, 4.4],
    nose: [9.2, 6.8],
  },
  shark: {
    m: carve(
      17,
      9,
      [
        [
          "steel",
          poly([
            [0, 0.4],
            [3.6, 2.4],
            [3.6, 4.6],
            [0, 6.8],
            [1.4, 3.6],
          ]),
        ],
        ["steel", oval(8.6, 3.4, 7.8, 3.1)],
        ["white", oval(9.6, 2.2, 6, 1.6)],
        [
          "steel",
          poly([
            [5.6, 5.6],
            [8.8, 9],
            [11.2, 5.8],
          ]),
        ],
        [
          "steel",
          poly([
            [8.4, 1.6],
            [6.8, -0.2],
            [10.2, 1.4],
          ]),
        ],
      ],
      {
        prints: [
          { k: "eye", x: 13.2, y: 4.5, r: 0.5, look: [0.5, 0] },
          { k: "mouth", x: 14.4, y: 2.9, w: 1.5, bend: 0.7 },
          {
            k: "line",
            pts: [
              [11.2, 4.2],
              [11, 3.2],
            ],
            c: "darkBlue",
            wd: 0.1,
          },
          {
            k: "line",
            pts: [
              [11.8, 4.2],
              [11.6, 3.2],
            ],
            c: "darkBlue",
            wd: 0.1,
          },
        ],
      },
    ),
    hand: [9, 1.4],
    nose: [16.4, 3.8],
  },
};

/* ---------- the wishes ---------- */

/** What a hero wishes for, set beside it (or above it) on the box. `at` is where, from the hero. */
export const WISHES = {
  fly: {
    m: carve(
      10,
      16,
      [
        ["red", oval(2.2, 11.4, 2, 2.4)],
        ["blue", oval(7.6, 11, 2, 2.4)],
        ["yellow", oval(5, 13.2, 2, 2.4)],
      ],
      {
        prints: [
          {
            k: "line",
            pts: [
              [2.2, 9],
              [4.4, 0],
            ],
            c: "grey",
            wd: 0.07,
          },
          {
            k: "line",
            pts: [
              [5, 10.8],
              [4.6, 0],
            ],
            c: "grey",
            wd: 0.07,
          },
          {
            k: "line",
            pts: [
              [7.6, 8.6],
              [4.8, 0],
            ],
            c: "grey",
            wd: 0.07,
          },
        ],
      },
    ),
  },
  birthday: {
    m: carve(
      11,
      10,
      [
        ["white", box(0, 0, 11, 0.6)],
        ["pink", box(0.5, 0.6, 10, 3.2, 0.5)],
        ["white", box(0.5, 3.4, 10, 0.8, 0.4)],
        ["yellow", box(2, 4, 7, 2.6, 0.4)],
        ["white", box(2, 6.2, 7, 0.8, 0.4)],
        ["red", box(3, 6.8, 1, 1.9)],
        ["azure", box(5, 6.8, 1, 1.9)],
        ["lime", box(7, 6.8, 1, 1.9)],
        ["flame", oval(3.5, 9.3, 0.45, 0.7)],
        ["flame", oval(5.5, 9.3, 0.45, 0.7)],
        ["flame", oval(7.5, 9.3, 0.45, 0.7)],
      ],
      {
        prints: [
          { k: "dot", x: 2.6, y: 2.4, r: 0.35, c: "white" },
          { k: "dot", x: 5.4, y: 1.8, r: 0.35, c: "white" },
          { k: "dot", x: 8.2, y: 2.4, r: 0.35, c: "white" },
        ],
      },
    ),
    lights: [
      [3.5, 9.3],
      [5.5, 9.3],
      [7.5, 9.3],
    ],
  },
  treasure: {
    m: carve(
      15,
      9,
      [
        ["sand", box(0, 1.2, 7, 7.6, 0.4)],
        ["darkTan", box(0.3, 0, 0.8, 9)],
        ["brown", box(8, 0, 7, 3.2, 0.3)],
        ["brown", box(8, 3.2, 7, 1.9, 0.9)],
        ["yellow", box(11, 0.6, 1, 4.4)],
        ["yellow", oval(9.6, 5.2, 0.8, 0.4)],
        ["yellow", oval(13.4, 5.3, 0.8, 0.4)],
      ],
      {
        prints: [
          {
            k: "line",
            pts: [
              [1.8, 2.6],
              [3.2, 3.8],
              [2.4, 5.2],
              [4.4, 6.2],
            ],
            c: "darkTan",
            t: -0.3,
            wd: 0.14,
          },
          {
            k: "line",
            pts: [
              [4.4, 7.4],
              [5.8, 6.2],
            ],
            c: "red",
            wd: 0.2,
          },
          {
            k: "line",
            pts: [
              [4.4, 6.2],
              [5.8, 7.4],
            ],
            c: "red",
            wd: 0.2,
          },
        ],
      },
    ),
  },
  dance: {
    m: model(
      { k: "black", K: ["black", "slope"] },
      `
      b ......kkkK
      b ......k..k
      b ..kK..k..k
      b ..k..kk.kk
      b ..k..kk.kk
      b kkk.......
      `,
    ),
  },
  friend: {
    m: carve(
      11,
      9,
      [
        ["red", oval(3.4, 0.8, 3, 2.4)],
        ["black", oval(6.4, 0.9, 1.2, 1)],
        ["black", box(3.1, 0.6, 0.6, 2.6)],
        ["red", oval(6.2, 6.6, 1.5)],
        ["red", oval(9, 6.6, 1.5)],
        [
          "red",
          poly([
            [4.8, 6.2],
            [7.6, 3],
            [10.4, 6.2],
          ]),
        ],
      ],
      {
        prints: [
          { k: "dot", x: 1.8, y: 1.6, r: 0.36, c: "black" },
          { k: "dot", x: 5, y: 1.9, r: 0.36, c: "black" },
          { k: "eye", x: 6.8, y: 1.1, r: 0.28, look: [0.5, 0.2] },
        ],
      },
    ),
  },
  sneeze: {
    m: carve(8, 5, [
      ["white", oval(1.6, 2.2, 1.5)],
      ["white", oval(4, 3, 1.9)],
      ["white", oval(6.4, 2, 1.5)],
    ]),
  },
};

/* ---------- the places ---------- */

const trunk = (x, h) => ["darkTan", box(x, 0, 1, h)];

/** A pine tree with snow on its branches. */
const pine = (x, s = 1) => [
  ["brown", box(x - 0.5, 0, 1, 1.6 * s)],
  [
    "darkGreen",
    poly([
      [x - 3.2 * s, 1.4 * s],
      [x, 6 * s],
      [x + 3.2 * s, 1.4 * s],
    ]),
  ],
  [
    "darkGreen",
    poly([
      [x - 2.5 * s, 4.2 * s],
      [x, 8.6 * s],
      [x + 2.5 * s, 4.2 * s],
    ]),
  ],
  [
    "white",
    poly([
      [x - 1.4 * s, 6.8 * s],
      [x, 8.8 * s],
      [x + 1.4 * s, 6.8 * s],
    ]),
  ],
];

/** A palm tree: a trunk of stacked rounds and a crown of leaves. */
const palm = (x, h) => [
  trunk(x, h),
  [
    "green",
    poly([
      [x + 0.5, h],
      [x - 5, h - 2.4],
      [x - 4.4, h + 0.4],
    ]),
  ],
  [
    "green",
    poly([
      [x + 0.5, h],
      [x + 6, h - 2.4],
      [x + 5.4, h + 0.4],
    ]),
  ],
  [
    "lime",
    poly([
      [x + 0.5, h - 0.4],
      [x - 3.4, h + 2.6],
      [x + 0.5, h + 1.4],
    ]),
  ],
  [
    "lime",
    poly([
      [x + 0.5, h - 0.4],
      [x + 4.4, h + 2.6],
      [x + 0.5, h + 1.4],
    ]),
  ],
  ["brown", oval(x + 1.4, h - 0.8, 0.7)],
];

/**
 * Where a story can happen. `sky` is the backdrop's colours top to bottom, `back` the models behind
 * the hero and `ground` what it stands on, each `[model, x, y]` on a stage 40 studs wide with the
 * ground at 0. `fx` names what drifts in the air, and `icon` which back model stands for the place.
 */
export const PLACES = {
  castle: {
    icon: 1,
    sky: ["#7fcbff", "#d8f1ff"],
    back: [
      [
        carve(44, 7, [
          ["lime", oval(8, -3, 16, 8)],
          ["green", oval(34, -5, 16, 10)],
        ]),
        -2,
        0,
      ],
      [
        carve(34, 25.4, [
          ["tan", box(6, 0, 22, 11)],
          ...[6, 10, 14, 18, 22, 26].map((x) => ["tan", box(x, 10.8, 2, 1.4)]),
          ["lightGrey", box(1, 0, 7, 16)],
          ["lightGrey", box(26, 0, 7, 16)],
          [
            "blue",
            poly([
              [0.2, 15.8],
              [4.5, 22.4],
              [8.8, 15.8],
            ]),
          ],
          [
            "blue",
            poly([
              [25.2, 15.8],
              [29.5, 22.4],
              [33.8, 15.8],
            ]),
          ],
          ["grey", box(4, 22, 1, 3.4)],
          ["grey", box(29, 22, 1, 3.4)],
          [
            "red",
            poly([
              [5, 25.4],
              [8, 24.4],
              [5, 23.2],
            ]),
          ],
          [
            "red",
            poly([
              [30, 25.4],
              [33, 24.4],
              [30, 23.2],
            ]),
          ],
          ["darkBrown", box(14, 0, 6, 6)],
          ["darkBrown", oval(17, 6, 3, 2.6)],
          ["black", box(4, 10, 1, 2.4)],
          ["black", box(29, 10, 1, 2.4)],
          ["black", box(10, 6.4, 1, 2)],
          ["black", box(23, 6.4, 1, 2)],
        ]),
        3,
        0,
      ],
    ],
    ground: ["lime", "green", "darkGreen"],
  },
  sea: {
    icon: 1,
    sky: ["#66d3ee", "#1476ad"],
    back: [
      [
        carve(40, 16, [
          ["green", box(3, 0, 1, 3)],
          ["green", box(4, 3, 1, 3)],
          ["green", box(3, 6, 1, 3)],
          ["green", box(4, 9, 1, 3)],
          ["lime", box(7, 0, 1, 2.4)],
          ["lime", box(6, 2.4, 1, 2.4)],
          ["lime", box(7, 4.8, 1, 2.4)],
          ["pink", oval(31, 2.6, 2.4, 2.6)],
          ["pink", oval(34, 4.6, 1.8, 3)],
          ["orange", oval(28.4, 1.6, 1.6, 1.6)],
          ["green", box(36, 0, 1, 3)],
          ["green", box(37, 3, 1, 3)],
          ["green", box(36, 6, 1, 3)],
          ["grey", oval(22, 0, 4, 2)],
        ]),
        0,
        0,
      ],
      [
        carve(
          6,
          3,
          [
            ["orange", oval(3.4, 1.5, 2.4, 1.4)],
            [
              "orange",
              poly([
                [0, 0.2],
                [1.4, 1.5],
                [0, 2.8],
              ]),
            ],
          ],
          { prints: [{ k: "eye", x: 4.6, y: 1.8, r: 0.3, look: [0.5, 0] }] },
        ),
        27,
        48,
      ],
    ],
    ground: ["sand", "sand", "tan"],
    fx: "bubbles",
  },
  moon: {
    icon: 0,
    sky: ["#101640", "#3c2b78"],
    back: [
      [
        carve(9, 9, [
          ["blue", oval(4.5, 4.5, 4.4)],
          ["green", oval(3, 5.6, 1.8, 1.6)],
          ["green", oval(6.2, 3, 1.6, 1.2)],
          ["white", oval(5, 8.4, 1.6, 0.5)],
        ]),
        29,
        46,
      ],
      [
        carve(40, 4, [
          ["lightGrey", oval(8, 0, 9, 3)],
          ["lightGrey", oval(30, 0, 10, 3.6)],
          ["grey", oval(30, 2.2, 2.4, 0.7)],
        ]),
        0,
        0,
      ],
      [
        carve(5, 8, [
          ["lightGrey", box(0, 0, 1, 8)],
          ["yellow", box(1, 5, 4, 3)],
        ]),
        31,
        4,
      ],
    ],
    ground: ["lightGrey", "grey", "grey"],
    fx: "stars",
  },
  jungle: {
    icon: 0,
    sky: ["#d9f59a", "#f7ffe0"],
    back: [
      [carve(13, 20, palm(6, 17)), -1, 0],
      [carve(13, 17, palm(6, 14)), 27, 0],
      [
        carve(40, 6, [
          ["darkGreen", oval(2, 1, 4, 4)],
          ["green", oval(37, 1, 4.4, 4.6)],
          ["pink", oval(8, 1.6, 1, 1)],
          ["yellow", oval(35, 4.4, 0.9, 0.9)],
          ["orange", oval(29, 1.2, 1, 1)],
        ]),
        0,
        0,
      ],
    ],
    ground: ["green", "darkGreen", "brown"],
  },
  snow: {
    icon: 2,
    sky: ["#b8e1ff", "#f2faff"],
    back: [
      [
        carve(44, 8, [
          ["white", oval(10, -2, 15, 8)],
          ["paleBlue", oval(36, -4, 14, 10)],
        ]),
        -2,
        0,
      ],
      [carve(40, 18, [...pine(4, 1.6), ...pine(35, 1.3)]), 0, 0],
      [
        carve(10, 6, [
          ["white", oval(5, 0, 5, 5.4)],
          ["black", oval(5, 0, 1.4, 2.6)],
        ]),
        26,
        0,
      ],
    ],
    ground: ["white", "paleBlue", "lightGrey"],
    fx: "snow",
  },
};

/** The ground a place stands on: a plate of its top colour on three bricks, wider than the stage. */
export function ground([top, mid, low], w = 48) {
  const rows = [`p ${"a".repeat(w)}`, `b ${"b".repeat(w)}`, `b ${"c".repeat(w)}`, `b ${"c".repeat(w)}`];
  return model({ a: top, b: mid, c: low }, rows.join("\n"), { long: 6 });
}

/* ---------- the playroom ---------- */

/** The window over the table: four panes, empty, so the sky painted behind them shows through. */
export const WINDOW = carve(18, 16, [
  ["white", box(0, 1, 18, 15)],
  [null, box(1, 2, 7.5, 6.5)],
  [null, box(9.5, 2, 7.5, 6.5)],
  [null, box(1, 9.5, 7.5, 5.5)],
  [null, box(9.5, 9.5, 7.5, 5.5)],
  ["white", box(0, 0, 18, 1)],
]);

/** A cloud and the sun, for the sky behind the window. */
export const CLOUD = carve(9, 4, [
  ["white", oval(2.4, 1.4, 2.2, 1.4)],
  ["white", oval(5, 2.2, 2.6, 1.8)],
  ["white", oval(7.2, 1.4, 1.8, 1.3)],
]);
export const SUN = carve(6, 6, [
  ["orange", oval(3, 3, 3)],
  ["yellow", oval(3, 3, 2.3)],
]);

/** The sofa behind the rug. */
export const SOFA = carve(56, 21, [
  ["darkBrown", box(4, 0, 2, 1.4)],
  ["darkBrown", box(50, 0, 2, 1.4)],
  ["purple", box(1, 1.2, 54, 3)],
  ["lavender", box(4, 3.6, 24, 5, 1.2)],
  ["lavender", box(28, 3.6, 24, 5, 1.2)],
  ["lavender", box(5, 8.2, 22.5, 11.6, 2.6)],
  ["lavender", box(28.5, 8.2, 22.5, 11.6, 2.6)],
  ["purple", box(0, 3.4, 5.4, 12, 2.2)],
  ["purple", box(50.6, 3.4, 5.4, 12, 2.2)],
  ["yellow", box(40, 8.6, 8, 7.4, 2.6)],
]);

/** A table leg: a column of `h` round bricks, two studs across. */
export const leg = (h) =>
  finish(
    Array.from({ length: h }, (_, i) => ({ x: 0, y: i * 3, w: 2, h: 3, c: "darkTan", k: "round", dir: "u" })),
  );

/** Smoke, a flame and sparks for the launch. */
export const PUFF = carve(5, 4.4, [
  ["white", oval(1.6, 1.6, 1.5)],
  ["white", oval(3.2, 2.4, 1.8)],
]);
export const FLAME = carve(4, 6, [
  [
    "fire",
    poly([
      [0.2, 5],
      [2, 0],
      [3.8, 5],
    ]),
  ],
  ["flame", oval(2, 4.4, 1.4, 1.6)],
]);

/** The countdown, in big yellow bricks: each dot of a 3 by 5 digit is two studs by two bricks. */
const digit = (rows) =>
  model(
    { y: "yellow" },
    rows
      .flatMap((r) => {
        const line = `b ${[...r].map((c) => (c === "#" ? "yy" : "..")).join("")}`;
        return [line, line];
      })
      .join("\n"),
  );
export const DIGITS = {
  3: digit(["###", "..#", ".##", "..#", "###"]),
  2: digit(["###", "..#", "###", "#..", "###"]),
  1: digit([".#.", "##.", ".#.", ".#.", "###"]),
};
