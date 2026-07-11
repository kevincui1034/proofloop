export const VERTEX = /* glsl */ `
attribute vec2 uv;
attribute vec2 position;
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = vec4(position, 0.0, 1.0);
}
`;

/**
 * The night court's atmosphere in one fullscreen pass: an analytic amber
 * light shaft from the bench (upper right), hash-based dust drifting in the
 * beam, film grain, and a deep vignette. uDie blows the light out (the slam)
 * and then kills it.
 */
export const FRAGMENT = /* glsl */ `
precision highp float;

uniform float uTime;
uniform float uBeam;    // beam intensity 0..1
uniform float uBeamX;   // beam focus x 0..1
uniform float uDie;     // 0 alive -> 1 dead (with a flicker on the way)
uniform vec2 uRes;
uniform vec2 uPointer;  // lerped, 0..1

varying vec2 vUv;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}

void main() {
  vec2 uv = vUv;
  float aspect = uRes.x / max(uRes.y, 1.0);
  vec2 p = vec2(uv.x * aspect, uv.y);

  // ——— the shaft: anchored above the viewport, leaning toward uBeamX ———
  vec2 anchor = vec2((uBeamX + (uPointer.x - 0.5) * 0.05) * aspect, 1.35);
  vec2 dir = normalize(vec2(-0.18, -1.0));
  vec2 toP = p - anchor;
  float along = dot(toP, dir);                 // distance down the shaft
  float side = abs(dot(toP, vec2(-dir.y, dir.x))); // distance off-axis
  float width = 0.16 + along * 0.38;           // cone opens as it falls
  float shaft = smoothstep(width, width * 0.25, side) * smoothstep(-0.1, 0.6, along);
  shaft *= 0.55 + 0.45 * smoothstep(1.8, 0.2, along); // fade with depth

  // ——— dust motes drifting in the light ———
  float dust = 0.0;
  for (int i = 0; i < 3; i++) {
    float fi = float(i);
    vec2 g = p * (26.0 + fi * 18.0) + vec2(uTime * (0.014 + fi * 0.008), uTime * (0.05 + fi * 0.022));
    vec2 cell = floor(g);
    vec2 f = fract(g) - 0.5;
    float r = hash(cell);
    float mote = smoothstep(0.11, 0.0, length(f + (vec2(r, hash(cell + 7.3)) - 0.5) * 0.6));
    dust += mote * step(0.82, r) * (0.5 + 0.5 * sin(uTime * (0.6 + r) + r * 40.0));
  }
  dust *= shaft * 2.2;

  // ——— the slam: exposure flicker, then the light dies ———
  float flicker = 1.0 + uDie * (1.0 - uDie) * 4.0 * sin(uTime * 90.0);
  float alive = (1.0 - smoothstep(0.35, 1.0, uDie)) * flicker;

  float intensity = (shaft * 0.85 + dust) * uBeam * alive;
  vec3 amber = vec3(0.961, 0.722, 0.239);
  vec3 col = amber * intensity;

  // ——— vignette (always on, even after the light dies) ———
  float vig = smoothstep(1.25, 0.45, length(uv - vec2(0.5, 0.45)));
  col *= mix(0.75, 1.0, vig);

  // ——— film grain ———
  float grain = (hash(uv * uRes.xy * 0.5 + fract(uTime) * 61.7) - 0.5) * 0.055;
  col += grain * (0.4 + intensity);

  // premultiplied-ish alpha: the canvas floats over the page background
  float a = clamp(intensity * 0.85 + abs(grain) * 0.6, 0.0, 1.0);
  gl_FragColor = vec4(col, a);
}
`;
