/**
 * Shared mutable uniform store — the bridge between scroll timelines and the
 * WebGL stage. Scene timelines tween these plain numbers (GSAP mutates the
 * object directly); the GL ticker reads them every frame. No React state on
 * the scroll path, zero re-renders during scroll.
 */
export const uniforms = {
  /** global night-world scroll progress 0..1 (S1 top → S4 flood) */
  scroll: 0,
  /** beam intensity 0..1 */
  beam: 0.9,
  /** beam focus x in clip-ish space 0..1 (tracks the traveling command) */
  beamX: 0.5,
  /** slam blowout: 0 = alive, 1 = the light has died */
  die: 0,
  /** lerped pointer, 0..1 viewport space */
  pointerX: 0.5,
  pointerY: 0.5,
};
