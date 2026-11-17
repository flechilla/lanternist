/* What the set is made of. Plasticine is lumpy where it was pressed and never quite the same colour
 * twice; between two frames the animator's fingers touch it again, so its dents and prints move.
 * That is the boil of a clay film, and it is done here in the shader: the surface is pushed out by a
 * slow noise (the lumps, fixed) and a fast one (the touch, new every frame), and printed with the
 * contour lines of a third noise, which look like fingerprints. Felt, card, wood and brass are the
 * other materials a miniature set is built from. */

import * as THREE from "three";
import { FRAME } from "./engine.js";

// Simplex noise in 3D (Ashima Arts and Stefan Gustavson, MIT licence).
const NOISE = /* glsl */ `
vec3 c_m289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 c_m289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 c_perm(vec4 x) { return c_m289(((x * 34.0) + 10.0) * x); }
float c_snoise(vec3 v) {
  const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
  const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
  vec3 i = floor(v + dot(v, C.yyy));
  vec3 x0 = v - i + dot(i, C.xxx);
  vec3 g = step(x0.yzx, x0.xyz);
  vec3 l = 1.0 - g;
  vec3 i1 = min(g.xyz, l.zxy);
  vec3 i2 = max(g.xyz, l.zxy);
  vec3 x1 = x0 - i1 + C.xxx;
  vec3 x2 = x0 - i2 + C.yyy;
  vec3 x3 = x0 - D.yyy;
  i = c_m289(i);
  vec4 p = c_perm(c_perm(c_perm(i.z + vec4(0.0, i1.z, i2.z, 1.0)) + i.y + vec4(0.0, i1.y, i2.y, 1.0))
    + i.x + vec4(0.0, i1.x, i2.x, 1.0));
  vec3 ns = 0.142857142857 * D.wyz - D.xzx;
  vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
  vec4 x_ = floor(j * ns.z);
  vec4 y_ = floor(j - 7.0 * x_);
  vec4 x = x_ * ns.x + ns.yyyy;
  vec4 y = y_ * ns.x + ns.yyyy;
  vec4 h = 1.0 - abs(x) - abs(y);
  vec4 b0 = vec4(x.xy, y.xy);
  vec4 b1 = vec4(x.zw, y.zw);
  vec4 s0 = floor(b0) * 2.0 + 1.0;
  vec4 s1 = floor(b1) * 2.0 + 1.0;
  vec4 sh = -step(h, vec4(0.0));
  vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
  vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
  vec3 p0 = vec3(a0.xy, h.x);
  vec3 p1 = vec3(a0.zw, h.y);
  vec3 p2 = vec3(a1.xy, h.z);
  vec3 p3 = vec3(a1.zw, h.w);
  vec4 norm = 1.79284291400159 - 0.85373472095314 * vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3));
  p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
  vec4 m = max(0.5 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
  m = m * m;
  return 105.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
}
`;

const VERTEX_PARS = /* glsl */ `
uniform float uFrame;
uniform float uLump;
uniform float uBoil;
uniform float uFreq;
uniform float uSeed;
varying vec3 vClay;
float clayField(vec3 q) {
  vec3 o = vec3(uFrame * 3.17, uFrame * 1.93, uFrame * 2.41);
  return uLump * c_snoise(q * 0.45) + uBoil * c_snoise(q * 1.7 + o);
}
`;

// The surface is pushed along its normal, and the normal is bent to match, from two neighbours. A
// pole of a turned shape can have no normal at all; it gets one, since one NaN pixel would be smeared
// across the whole frame by the bloom.
const VERTEX_NORMAL = /* glsl */ `
vec3 clayN = dot(objectNormal, objectNormal) > 1e-10 ? normalize(objectNormal) : vec3(0.0, 1.0, 0.0);
vec3 clayQ = position * uFreq + uSeed;
vec3 clayT = normalize(cross(clayN, abs(clayN.y) < 0.95 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0)));
vec3 clayB = cross(clayN, clayT);
float clayD = clayField(clayQ);
float clayStep = 0.08 / uFreq;
float clayDT = clayField(clayQ + clayT * 0.08) - clayD;
float clayDB = clayField(clayQ + clayB * 0.08) - clayD;
objectNormal = normalize(clayN - clayT * clayDT / clayStep - clayB * clayDB / clayStep);
vClay = clayQ;
`;

const FRAGMENT_PARS = /* glsl */ `
uniform float uFrame;
uniform float uPrint;
uniform float uFuzz;
uniform float uMottle;
varying vec3 vClay;
float clayBump(vec3 q) {
  float t = floor(uFrame / 2.0);
  vec3 o = vec3(t * 1.37, t * 0.71, t * 2.13);
  float smudge = c_snoise(q * 2.3 + o * 0.3);
  float whorl = sin(c_snoise(q * 0.8 + o) * 30.0);
  float mask = smoothstep(0.25, 0.7, c_snoise(q * 0.5 - o * 0.5));
  float fuzz = c_snoise(q * 22.0);
  return uPrint * (0.014 * smudge + 0.005 * whorl * mask) + uFuzz * 0.01 * fuzz;
}
`;

const FRAGMENT_BUMP = /* glsl */ `
{
  float clayH = clayBump(vClay);
  vec3 dpdx = dFdx(-vViewPosition);
  vec3 dpdy = dFdy(-vViewPosition);
  vec3 r1 = cross(dpdy, normal);
  vec3 r2 = cross(normal, dpdx);
  float det = dot(dpdx, r1) * faceDirection;
  vec3 grad = sign(det) * (dFdx(clayH) * r1 + dFdy(clayH) * r2);
  vec3 bent = abs(det) * normal - grad;
  if (dot(bent, bent) > 1e-12) normal = normalize(bent);
}
`;

let seeds = 0;

/** Adds the lumps, the boil and the prints to a standard material; its program is shared by all. */
function handmade(material, { lump = 0.12, boil = 0.03, print = 1, fuzz = 0, freq = 1, mottle = 0.06 }) {
  const uniforms = {
    uFrame: FRAME,
    uLump: { value: lump },
    uBoil: { value: boil },
    uFreq: { value: freq },
    uSeed: { value: (seeds++ * 7.31) % 50 },
    uPrint: { value: print },
    uFuzz: { value: fuzz },
    uMottle: { value: mottle },
  };
  material.userData.clay = uniforms;
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", `#include <common>\n${NOISE}\n${VERTEX_PARS}`)
      .replace("#include <beginnormal_vertex>", `#include <beginnormal_vertex>\n${VERTEX_NORMAL}`)
      .replace("#include <begin_vertex>", "#include <begin_vertex>\ntransformed += clayN * clayD;");
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <common>", `#include <common>\n${NOISE}\n${FRAGMENT_PARS}`)
      .replace(
        "#include <color_fragment>",
        "#include <color_fragment>\ndiffuseColor.rgb *= 1.0 + uMottle * c_snoise(vClay * 0.6);",
      )
      .replace("#include <normal_fragment_maps>", `#include <normal_fragment_maps>\n${FRAGMENT_BUMP}`);
  };
  material.customProgramCacheKey = () => `handmade-${material.type}`;
  return material;
}

/** Plasticine: a puppet's body, a prop that was sculpted. Tiny parts pass `lump: 0`. */
export const clay = (color, opts = {}) =>
  handmade(new THREE.MeshStandardMaterial({ color, roughness: opts.rough ?? 0.58, metalness: 0 }), opts);

/** Felt and wool: a scarf, a beret, the seats. Soft sheen at the edges, fuzz on the face. */
export const felt = (color, opts = {}) =>
  handmade(
    new THREE.MeshPhysicalMaterial({
      color,
      roughness: 0.95,
      sheen: 1,
      sheenRoughness: 0.6,
      sheenColor: new THREE.Color(color).lerp(new THREE.Color("#ffffff"), 0.15),
    }),
    { lump: 0.05, boil: 0.02, print: 0, fuzz: 0.5, mottle: 0.1, ...opts },
  );

/** A bead: the glossy black eyes that catch every light on the set. */
export const bead = (color = "#0d0a08") =>
  new THREE.MeshPhysicalMaterial({ color, roughness: 0.12, clearcoat: 1, clearcoatRoughness: 0.05 });

/** Brass and tin, lit by the room's reflections. */
export const metal = (color, rough = 0.34) =>
  new THREE.MeshStandardMaterial({ color, metalness: 1, roughness: rough });

/** Something that gives light: a flame, a bulb, the lamp's heart. Bright enough to bloom. */
export const glow = (color, strength = 3) =>
  new THREE.MeshBasicMaterial({ color: new THREE.Color(color).multiplyScalar(strength), toneMapped: true });

/** Card, painted wood, plaster: a flat material with a texture and no boil. */
export const card = (color, map = null, rough = 0.85) =>
  new THREE.MeshStandardMaterial({ color, map, roughness: rough, metalness: 0 });

/** Cellophane water and glass: see-through, with a rainbow sheen where the light glances off it. */
export const cellophane = (color, opacity = 0.62) =>
  new THREE.MeshPhysicalMaterial({
    color,
    transparent: true,
    opacity,
    roughness: 0.12,
    metalness: 0,
    clearcoat: 1,
    iridescence: 0.6,
    iridescenceIOR: 1.4,
    side: THREE.DoubleSide,
    depthWrite: false,
  });
