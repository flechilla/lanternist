/* The opening: a short film before the page. On the gallery of a dark lighthouse a mouse strikes a
 * match, lights its lantern, then the great lamp; the beam comes round, the crew's windows wake one by
 * one, and the animator's hand swings the front of the tower open like a doll's-house door. It runs on
 * the set's own clock as a list of cues by frame. The visitor can skip it at any point, and the page
 * comes up where the film would have left it. */

import * as THREE from "three";
import { clay, felt, glow } from "./clay.js";
import { calm } from "./engine.js";
import { HOP, WAVE } from "./rooms.js";
import { blob, block, part, pivot, roll } from "./shapes.js";
import { FLOORS, LAMP_Y, radius } from "./tower.js";

const $ = (sel) => document.querySelector(sel);

const CLOSE = { look: [10.7, LAMP_Y + 17, 30], yaw: 0.2, pitch: 0.02, dist: 30, fov: 30, span: 15 };
const MEDIUM = {
  look: [6, LAMP_Y + 14, 8],
  yaw: 0.34,
  pitch: 0.1,
  dist: 86,
  fov: 30,
  span: 60,
  focus: [8, LAMP_Y + 10, 12],
};
const WIDE = { look: [0, 100, 0], yaw: 0.2, pitch: 0.05, dist: 470, fov: 30, span: 280, focus: [0, 100, 0] };
const OPEN = {
  look: [-30, 95, 20],
  yaw: 0.34,
  pitch: 0.06,
  dist: 520,
  fov: 30,
  span: 330,
  focus: [0, 95, 0],
};

/** The animator's hand: too big for the set, and never quite still. */
function animatorHand() {
  const skin = clay("#d9a882", { lump: 0.35, boil: 0.08, freq: 0.25 });
  const nail = clay("#e8c3a5", { lump: 0.02, boil: 0.02 });
  const hand = new THREE.Group();
  hand.add(part(block(24, 28, 10, 5), skin, [0, 14, 0]));
  const fingers = [-8.4, -2.8, 2.8, 8.4].map((x, k) => {
    const base = pivot([x, 0.5, 0]);
    const len = [8, 10, 9.4, 7.4][k];
    base.add(part(roll(2.9, len), skin, [0, -len / 2 - 2, 0]));
    const tip = pivot([0, -len - 3, 0]);
    tip.add(part(roll(2.7, len * 0.7), skin, [0, -len * 0.35 - 2, 0]));
    tip.add(part(blob(1.8, 1.2, 0.6), nail, [0, -len * 0.7 - 2.6, 2.2]));
    base.add(tip);
    hand.add(base);
    return { base, tip };
  });
  const thumb = pivot([-12, 14, 3]);
  thumb.rotation.z = -0.9;
  thumb.add(part(roll(3.4, 11), skin, [0, -8, 0]));
  hand.add(thumb);
  hand.add(part(new THREE.CylinderGeometry(10.5, 11, 8, 28), felt("#ece3cf", { fuzz: 0.8 }), [0, 31, 0]));
  hand.add(
    part(new THREE.CylinderGeometry(11.5, 12.5, 400, 28), felt("#2f3b52", { fuzz: 1.2 }), [0, 235, 0]),
  );
  hand.userData = { fingers, thumb };
  return hand;
}

/** A match: a stick with a red head, and the flame it will have. */
function match() {
  const g = new THREE.Group();
  g.add(
    part(new THREE.CylinderGeometry(0.13, 0.13, 3.4, 6), clay("#e3c48f", { lump: 0, boil: 0 }), [0, 1.7, 0]),
  );
  g.add(part(blob(0.26, 0.36, 0.26), clay("#8f2d24", { lump: 0, boil: 0 }), [0, 3.5, 0]));
  const flame = part(blob(0.32, 0.7, 0.32, 12), glow("#ffc46b", 5), [0, 4.1, 0]);
  flame.castShadow = false;
  flame.visible = false;
  g.add(flame);
  const light = new THREE.PointLight("#ffb257", 0, 40, 1.8);
  light.position.y = 4.2;
  g.add(light);
  g.userData = { flame, light };
  return g;
}

export function opening(ctx, { reveal }) {
  const box = $("#opening");
  const strike = $("#strike");
  const label = $("#strike-label");
  const skip = $("#skip");
  const foot = $("#opening-foot");
  const card = $("#title-card");
  const house = ctx.world.house.userData;
  const { wick, lantern } = ctx.rooms.lamp;
  const { rig, foley } = ctx;
  document.body.classList.add("opening-on");

  // The set before the film: the lamp out, the crew asleep, the tower shut.
  ctx.lamp(false);
  house.front.visible = true;
  FLOORS.forEach((_, i) => house.wake(i, false));
  const lanternOn = (on) => {
    lantern.userData.flame.visible = on;
    lantern.userData.light.intensity = on ? 40 : 0;
  };
  lanternOn(false);
  rig.side = "none";
  rig.cut(OPEN);

  const stick = match();
  stick.position.set(0, -0.6, 0.4);
  stick.rotation.set(0.5, 0, 0.3);
  wick.joints.pawL.add(stick);

  // The front of the tower hangs on a hinge at its left edge, so the hand can swing it open.
  const hinge = pivot([-radius(0), 0, 0]);
  house.front.parent.add(hinge);
  hinge.add(house.front);
  house.front.position.x = radius(0);
  const hand = animatorHand();
  hand.visible = false;
  ctx.scene.add(hand);

  let start = null;
  let done = false;
  const cues = [];
  const at = (f, fn) => cues.push([f, fn]);
  const say = (text) => {
    foot.hidden = !text;
    foot.textContent = text ?? "";
  };

  function finish() {
    if (done) return;
    done = true;
    ctx.onFrame = null;
    stick.removeFromParent();
    hand.removeFromParent();
    hinge.rotation.y = 0;
    house.front.visible = false;
    FLOORS.forEach((_, i) => house.wake(i, true));
    lanternOn(true);
    ctx.lamp(true);
    foley.music(null);
    box.classList.add("away");
    setTimeout(() => (box.hidden = true), 600);
    skipFilm?.remove();
    try {
      localStorage.setItem("lanternist-crew-seen", "1");
    } catch {
      // Private windows may refuse storage; the opening then plays again next time.
    }
    reveal();
  }

  // Where the hand holds the door: its right edge, a little below the middle.
  const grip = new THREE.Vector3();
  function holdDoor(open) {
    hinge.rotation.y = -1.95 * open;
    grip.set(radius(95) + radius(0), 95, 2).applyAxisAngle(new THREE.Vector3(0, 1, 0), hinge.rotation.y);
    grip.add(hinge.position);
    hand.position.set(grip.x + 11, grip.y - 2, grip.z + 4);
    hand.rotation.set(0.1, -0.6 + hinge.rotation.y * 0.6, 0.25);
  }

  let skipFilm = null;
  function play() {
    box.classList.add("playing");
    skipFilm = Object.assign(document.createElement("button"), {
      className: "btn ghost small skip-film",
      type: "button",
      textContent: "Skip",
    });
    skipFilm.addEventListener("click", finish);
    document.body.append(skipFilm);
    ctx.onFrame = (f) => {
      if (start === null) start = f;
      while (cues.length && cues[0][0] <= f - start) cues.shift()[1](f);
    };
  }

  // Shot 1: close on Wick in the dark. He strikes the match, lights the lantern, and waves.
  at(0, () => {
    rig.cut(CLOSE);
    foley.beds({ sea: 0.35, wind: 0.3 });
    foley.music("intro", 0.75);
  });
  at(8, (f) =>
    wick.play(
      {
        len: 6,
        keys: [
          [0, {}],
          [2, { armL: { rx: -1.6, rz: -0.5 } }],
          [4, { armL: { rx: -0.6, rz: -0.2 } }],
          [6, {}],
        ],
      },
      f,
    ),
  );
  at(10, () => {
    foley.play("match", { gain: 0.9 });
    stick.userData.flame.visible = true;
    stick.userData.light.intensity = 14;
  });
  at(22, (f) =>
    wick.play(
      {
        len: 16,
        keys: [
          [0, {}],
          [5, { armL: { rx: -1.1, rz: 0.9 }, head: { ry: -0.4, rx: 0.2 } }],
          [12, { armL: { rx: -1.1, rz: 0.9 }, head: { ry: -0.4, rx: 0.2 } }],
          [16, {}],
        ],
      },
      f,
    ),
  );
  at(30, () => {
    foley.play("lantern-light", { gain: 0.8 });
    lanternOn(true);
  });
  at(38, () => {
    stick.userData.flame.visible = false;
    stick.userData.light.intensity = 0;
    stick.visible = false;
  });
  at(44, (f) => {
    foley.play("squeak-hello", { gain: 0.8 });
    wick.play(WAVE, f);
  });

  // Shot 2: the camera draws back; the great lamp catches and the beam comes round.
  at(66, (f) => rig.to(MEDIUM, 20, f));
  at(84, (f) => wick.play(HOP, f));
  at(88, () => {
    foley.play("lamp-whoomp", { gain: 0.9 });
    ctx.lamp(true);
  });

  // Shot 3: out wide. The crew wakes, a floor at a time, from the bottom up.
  at(108, (f) => rig.to(WIDE, 30, f));
  at(116, () => {
    say("Every night, at the edge of the sea, when the lighthouse keeper is fast asleep…");
    foley.say("vo-1", { gain: 0.9 });
  });
  FLOORS.forEach((_, i) =>
    at(126 + i * 7, () => {
      house.wake(i, true);
      foley.play("click", { gain: 0.35, rate: 0.9 + i * 0.05 });
    }),
  );

  // Shot 4: the hand swings the tower open.
  at(176, () => {
    say("…a very small crew goes to work. They make films, from one line.");
    foley.say("vo-2", { gain: 0.9 });
    hand.visible = true;
    holdDoor(0);
    hand.position.y += 160;
  });
  for (let k = 1; k <= 8; k++) at(176 + k, () => (hand.position.y -= 20));
  const grasp = (on) => {
    for (const { base, tip } of hand.userData.fingers) {
      base.rotation.x = on ? 0.7 : 0;
      tip.rotation.x = on ? 0.8 : 0;
    }
    hand.userData.thumb.rotation.z = on ? -0.45 : -0.9;
  };
  at(186, () => {
    grasp(true);
    foley.play("creak", { gain: 0.9 });
  });
  for (let k = 1; k <= 14; k++) at(188 + k, () => holdDoor(k / 14));
  // With the front off, a work light comes up on the floors so the crew can be seen at work.
  at(192, () => {
    const { key } = ctx.world;
    key.position.set(160, 260, 520);
    key.target.position.set(0, 80, 0);
    key.angle = 0.33;
    key.distance = 1400;
    key.color.set("#ffd9a8");
    key.intensity = 0;
  });
  for (let k = 1; k <= 6; k++) at(192 + k, () => (ctx.world.key.intensity = k * 22000));
  at(204, () => grasp(false));
  for (let k = 1; k <= 8; k++) at(206 + k, () => (hand.position.y += 26 + k * 4));
  at(214, () => {
    card.hidden = false;
    say(null);
  });

  // Shot 5: in to the lamp room, and the page.
  at(250, (f) => {
    card.hidden = true;
    house.front.visible = false;
    rig.to(ctx.rooms.lamp.shot, 24, f);
  });
  at(276, finish);

  strike.addEventListener("click", async () => {
    await ctx.turnSound(true);
    if (calm.matches) return finish();
    play();
  });
  skip.addEventListener("click", finish);
  new MutationObserver(() => document.documentElement.dataset.skip && finish()).observe(
    document.documentElement,
    {
      attributes: true,
      attributeFilter: ["data-skip"],
    },
  );
  addEventListener(
    "keydown",
    (e) => e.key === "Escape" && !done && document.body.classList.contains("opening-on") && finish(),
  );
  $("#replay")?.addEventListener("click", () => location.assign("?opening"));

  if (document.documentElement.dataset.skip) return finish();
  strike.disabled = false;
  label.textContent = "Strike a match";
}
