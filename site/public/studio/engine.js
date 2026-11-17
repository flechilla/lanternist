/* The studio's camera and clock. The set is shot the way a stop-motion film is: twelve frames a
 * second, and nothing in between. A frame is drawn only when the clock moves on, so the look of a
 * miniature (soft shadows in the corners, shallow focus, lamps that glow) costs a fifth of what it
 * would at sixty. On every frame the exposure wanders a little and the film sits a hair off in the
 * gate, as on a real camera. With reduced motion asked for, the clock still runs the parts a visitor
 * starts, and the camera cuts instead of moving. */

import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import {
  BloomEffect,
  DepthOfFieldEffect,
  Effect,
  EffectComposer,
  EffectPass,
  RenderPass,
  ToneMappingEffect,
  ToneMappingMode,
} from "postprocessing";
import { N8AOPostPass } from "n8ao";

export const FPS = 12;
export const calm = matchMedia("(prefers-reduced-motion: reduce)");
/** The frame the puppets were last touched on; every clay material reads it (clay.js). */
export const FRAME = { value: 0 };

/** The same number for the same thing on the same frame: a hand placed it, nothing tweened it. */
export const noise = (i, t) => {
  const x = Math.sin(i * 12.9898 + t * 78.233) * 43758.5453;
  return x - Math.floor(x);
};

const FILM = /* glsl */ `
uniform float exposure;
uniform float grain;
uniform float seed;
uniform vec2 weave;
uniform float vignette;
float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233)) + seed) * 43758.5453); }
void mainUv(inout vec2 uv) { uv += weave; }
void mainImage(const in vec4 inputColor, const in vec2 uv, out vec4 outputColor) {
  vec3 c = inputColor.rgb * exposure;
  vec2 d = uv - 0.5;
  c *= 1.0 - vignette * smoothstep(0.3, 0.85, length(d * vec2(1.15, 1.0)));
  float luma = dot(c, vec3(0.299, 0.587, 0.114));
  c += (hash(floor(gl_FragCoord.xy / 1.5)) - 0.5) * grain * (1.0 - 0.7 * luma);
  outputColor = vec4(c, inputColor.a);
}`;

/** Exposure flicker, gate weave, grain and vignette: what the camera adds to every frame. */
class FilmEffect extends Effect {
  constructor() {
    super("FilmEffect", FILM, {
      uniforms: new Map([
        ["exposure", new THREE.Uniform(1)],
        ["grain", new THREE.Uniform(0.045)],
        ["seed", new THREE.Uniform(0)],
        ["weave", new THREE.Uniform(new THREE.Vector2())],
        ["vignette", new THREE.Uniform(0.55)],
      ]),
    });
  }
}

/** How much of the look each machine can afford: the tier drops when frames come late. A big screen
 * is drawn at no more than `pixels` and scaled up; the grain hides the difference. */
const TIERS = [
  { dpr: 1, pixels: 1.2e6, ao: false, dof: false },
  { dpr: 1.25, pixels: 2e6, ao: true, half: true, dof: true },
  { dpr: 1.75, pixels: 3.2e6, ao: true, half: false, dof: true },
];

export function studio(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: "high-performance" });
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.14;

  const camera = new THREE.PerspectiveCamera(32, 1, 2, 6000);

  const composer = new EffectComposer(renderer, { frameBufferType: THREE.HalfFloatType });
  composer.addPass(new RenderPass(scene, camera));
  const ao = new N8AOPostPass(scene, camera, 1, 1);
  Object.assign(ao.configuration, { aoRadius: 4, distanceFalloff: 1.2, intensity: 2.6, aoSamples: 16 });
  composer.addPass(ao);
  const dof = new DepthOfFieldEffect(camera, { focusDistance: 60, focusRange: 18, bokehScale: 2.2 });
  const dofPass = new EffectPass(camera, dof);
  composer.addPass(dofPass);
  const film = new FilmEffect();
  const bloom = new BloomEffect({
    intensity: 0.7,
    luminanceThreshold: 1,
    luminanceSmoothing: 0.25,
    mipmapBlur: true,
    radius: 0.6,
  });
  composer.addPass(
    new EffectPass(camera, bloom, new ToneMappingEffect({ mode: ToneMappingMode.ACES_FILMIC }), film),
  );

  let tier = TIERS.length - 1;
  function setTier(n) {
    tier = n;
    const t = TIERS[tier];
    ao.enabled = t.ao;
    if (t.ao) ao.configuration.halfRes = t.half;
    dofPass.enabled = t.dof;
    resize();
  }

  function resize() {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (!w || !h) return;
    const t = TIERS[tier];
    renderer.setPixelRatio(Math.min(devicePixelRatio, t.dpr, Math.sqrt(t.pixels / (w * h))));
    renderer.setSize(w, h, false);
    composer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    s.dirty = true;
  }

  const s = {
    renderer,
    scene,
    camera,
    dof,
    frame: 0,
    dirty: true,
    /** Frame listeners, called with the frame number before the frame is drawn. */
    acts: new Set(),
  };

  function draw() {
    const f = s.frame;
    FRAME.value = f;
    for (const act of s.acts) act(f);
    const u = film.uniforms;
    if (!calm.matches) {
      u.get("exposure").value = 1 + (noise(7, f) - 0.5) * 0.045;
      u.get("weave").value.set((noise(8, f) - 0.5) * 0.0012, (noise(9, f) - 0.5) * 0.0012);
    }
    u.get("seed").value = noise(10, f) * 100;
    composer.render();
  }

  // Frames that come late drop the tier, so a slow machine gets a plainer set, never a stutter.
  let late = 0;
  let last = performance.now();
  function tick(now) {
    requestAnimationFrame(tick);
    const f = Math.floor((now / 1000) * FPS);
    if (f === s.frame && !s.dirty) return;
    const gap = now - last;
    last = now;
    late = Math.max(0, late + (gap > 1000 / FPS + 60 && f !== s.frame ? 1 : -0.05));
    if (late > 8 && tier > 0) {
      late = 0;
      setTier(tier - 1);
    }
    s.frame = f;
    s.dirty = false;
    draw();
  }

  new ResizeObserver(resize).observe(canvas);
  setTier(tier);
  requestAnimationFrame(tick);
  return s;
}
