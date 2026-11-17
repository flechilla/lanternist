/* The seven stars Luna counted on the stairs, hidden one to a floor. A found star flies up and out
 * to the sky; when all seven are back, they hang round the lamp and the crew cheers. A game for the
 * curious, and a reason to look into the corners of every set. */

import * as THREE from "three";
import { card } from "./clay.js";
import { cutout, part, star } from "./shapes.js";
import { floorY, LAMP_Y, SEA_Y } from "./tower.js";

/** Where each star hides, in the room it hides in. */
const HIDING = {
  writer: [20, floorY("writer") + 9.6, -7],
  voice: [22.5, floorY("voice") + 17.5, -11],
  paint: [13.5, floorY("paint") + 5, -10],
  motion: [3, floorY("motion") + 18.5, -15],
  mix: [-15, floorY("mix") + 17.4, -17],
  cinema: [-12.5, floorY("cinema") + 1.4, -2.5],
  jetty: [32, SEA_Y + 8.5, 44],
};

export function hideStars(ctx, found) {
  const shape = cutout(star(1.7), 0.35, 0.15);
  const stars = [];
  for (const [room, [x, y, z]] of Object.entries(HIDING)) {
    const m = part(shape, card("#f3dcb4", null, 0.7), [x, y, z]);
    m.material.emissive = new THREE.Color("#ffd48a");
    m.material.emissiveIntensity = 0.35;
    m.userData.room = room;
    ctx.scene.add(m);
    stars.push(m);
    ctx.rooms[room].hot.push({
      object: m,
      label: "a paper star",
      act: (f) => {
        if (m.userData.flying !== undefined) return;
        m.userData.flying = f;
        ctx.foley.play("twinkle", { gain: 0.8 });
        found(stars.filter((s) => s.userData.flying !== undefined).length);
      },
    });
  }
  // Seven threads round the lamp room, for the stars to hang from once they're all home.
  const home = stars.map((_, i) => {
    const a = (i / 7) * Math.PI * 2 + 0.3;
    return new THREE.Vector3(Math.sin(a) * 52, LAMP_Y + 64 + (i % 3) * 9, Math.cos(a) * 52);
  });
  return {
    stars,
    /** Twinkles the hidden stars; a found one spins up and away, then waits, hung by the lamp. */
    update(f, all) {
      stars.forEach((m, i) => {
        const from = m.userData.flying;
        if (from === undefined) {
          m.rotation.z = Math.sin((f + i * 7) / 5) * 0.15;
          m.material.emissiveIntensity = (f + i * 5) % 36 < 2 ? 1.4 : 0.35;
          return;
        }
        const k = f - from;
        if (k < 14) {
          m.position.y += 1.2 + k * 0.25;
          m.rotation.y += 0.6;
          m.scale.setScalar(Math.max(0.1, 1 - k / 14));
        } else if (all) {
          m.visible = true;
          m.position.copy(home[i]);
          m.scale.setScalar(3.2);
          m.rotation.set(0, 0, Math.sin((f + i * 11) / 9) * 0.12);
          m.material.emissiveIntensity = 0.8;
        } else m.visible = false;
      });
    },
  };
}
