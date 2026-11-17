/* The motion-control rig. The camera never glides: a move from one shot to the next is planned, then
 * taken a frame at a time and eased in and out, as a rig on a track is moved between exposures. A shot
 * names what the lens looks at, from which side and how far, and what is in focus. The page says which
 * side of the frame the title card covers, and the rig shifts the picture to the other side (a shift
 * lens, not a turn), so the set keeps its perspective. */

import * as THREE from "three";
import { calm } from "./engine.js";

const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
const lerp = (a, b, t) => a + (b - a) * t;

/** Where the lens is for a shot: `look` from `dist` away, turned by `yaw`, raised by `pitch`. */
function eyeFor(s, aspect) {
  // A narrow screen steps back until the shot's width fits.
  const need = s.span / 2 / (Math.tan(THREE.MathUtils.degToRad(s.fov) / 2) * aspect);
  const d = Math.max(s.dist, need);
  return new THREE.Vector3(
    s.look[0] + Math.sin(s.yaw) * Math.cos(s.pitch) * d,
    s.look[1] + Math.sin(s.pitch) * d,
    s.look[2] + Math.cos(s.yaw) * Math.cos(s.pitch) * d,
  );
}

export function rig(studio) {
  const cam = studio.camera;
  const pose = { look: new THREE.Vector3(), eye: new THREE.Vector3(), focus: new THREE.Vector3(), fov: 32 };
  let shot = null;
  let move = null;
  let side = "center";
  let shift = 0;

  const target = (s) => ({
    look: new THREE.Vector3(...s.look),
    eye: eyeFor(s, cam.aspect),
    focus: new THREE.Vector3(...(s.focus ?? s.look)),
    fov: s.fov,
  });

  /** Shifts the picture so the subject sits clear of the title card: aside on a wide screen, up on a
   * narrow one, where the card sits at the bottom. */
  function frame() {
    const w = studio.renderer.domElement.clientWidth || 1;
    const h = studio.renderer.domElement.clientHeight || 1;
    const narrow = w < 860;
    const want = narrow ? 0 : side === "left" ? 0.19 : side === "right" ? -0.19 : 0;
    shift = lerp(shift, want, 0.34);
    if (Math.abs(shift - want) < 0.004) shift = want;
    const up = narrow && side !== "none" ? 0.2 : 0;
    cam.setViewOffset(w, h, -shift * w, up * h, w, h);
    cam.updateProjectionMatrix();
  }

  function apply() {
    cam.position.copy(pose.eye);
    cam.lookAt(pose.look);
    cam.fov = pose.fov;
    frame();
    studio.dof.target = pose.focus;
  }

  return {
    /** Cuts straight to a shot. */
    cut(s) {
      shot = s;
      move = null;
      Object.assign(pose, target(s));
      apply();
    },
    /** Moves to a shot over `frames` frames, starting on frame `f`; a cut when motion is reduced. */
    to(s, frames, f) {
      if (calm.matches || frames <= 0) return this.cut(s);
      shot = s;
      const from = {
        look: pose.look.clone(),
        eye: pose.eye.clone(),
        focus: pose.focus.clone(),
        fov: pose.fov,
      };
      move = { from, to: target(s), start: f, len: frames };
    },
    /** Which side of the frame the page's card covers: "left", "right", "center" or "none". */
    set side(v) {
      side = v;
    },
    update(f) {
      if (move) {
        const t = Math.min(1, (f - move.start) / move.len);
        const e = ease(t);
        const { from, to } = move;
        pose.look.lerpVectors(from.look, to.look, e);
        pose.focus.lerpVectors(from.focus, to.focus, e);
        pose.fov = lerp(from.fov, to.fov, e);
        // The eye swings round the subject rather than cutting through the set.
        const a = from.eye.clone().sub(from.look);
        const b = to.eye.clone().sub(to.look);
        const dir = a.clone().normalize().lerp(b.clone().normalize(), e).normalize();
        pose.eye.copy(pose.look).addScaledVector(dir, lerp(a.length(), b.length(), e));
        if (t >= 1) move = null;
      } else if (shot) {
        // Hold the shot, but refit it if the window changed shape.
        pose.eye.copy(eyeFor(shot, cam.aspect));
      }
      apply();
    },
  };
}
