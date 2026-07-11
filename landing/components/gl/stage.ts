import { Renderer, Program, Mesh, Triangle, Vec2 } from "ogl";
import { gsap } from "@/components/experience/gsap-setup";
import { uniforms } from "@/components/experience/uniform-store";
import { VERTEX, FRAGMENT } from "./shaders";

export type StageHandle = { destroy: () => void };

/**
 * One fullscreen triangle, one fragment shader, uniforms read from the
 * shared store inside GSAP's ticker (no second rAF). Returns null when a
 * WebGL context can't be created — the CSS beam fallback simply stays.
 */
export function createStage(container: HTMLElement): StageHandle | null {
  let renderer: Renderer;
  try {
    renderer = new Renderer({
      dpr: Math.min(
        window.devicePixelRatio || 1,
        window.innerWidth < 800 ? 1.5 : 1.75
      ),
      alpha: true,
      antialias: false,
      depth: false,
      stencil: false,
      powerPreference: "high-performance",
    });
  } catch {
    return null;
  }
  const gl = renderer.gl;
  if (!gl) return null;

  gl.clearColor(0, 0, 0, 0);
  const canvas = gl.canvas as HTMLCanvasElement;
  canvas.style.position = "absolute";
  canvas.style.inset = "0";
  canvas.style.width = "100%";
  canvas.style.height = "100%";
  container.appendChild(canvas);

  const glUniforms = {
    uTime: { value: 0 },
    uBeam: { value: uniforms.beam },
    uBeamX: { value: uniforms.beamX },
    uDie: { value: uniforms.die },
    uRes: { value: new Vec2(1, 1) },
    uPointer: { value: new Vec2(0.5, 0.5) },
  };

  const program = new Program(gl, {
    vertex: VERTEX,
    fragment: FRAGMENT,
    uniforms: glUniforms,
    transparent: true,
  });
  const mesh = new Mesh(gl, { geometry: new Triangle(gl), program });

  const resize = () => {
    const { clientWidth: w, clientHeight: h } = container;
    renderer.setSize(w, h);
    glUniforms.uRes.value.set(w, h);
  };
  resize();
  window.addEventListener("resize", resize);

  // render only while the night chapter is on screen
  let visible = true;
  const io = new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting;
  });
  io.observe(container);

  // lerped pointer — the beam sways, it never twitches
  let px = 0.5;
  let py = 0.5;

  const tick = () => {
    if (!visible || document.hidden) return;
    px += (uniforms.pointerX - px) * 0.04;
    py += (uniforms.pointerY - py) * 0.04;
    glUniforms.uTime.value = gsap.ticker.time;
    glUniforms.uBeam.value = uniforms.beam;
    glUniforms.uBeamX.value = uniforms.beamX;
    glUniforms.uDie.value = uniforms.die;
    glUniforms.uPointer.value.set(px, py);
    renderer.render({ scene: mesh });
  };
  gsap.ticker.add(tick);

  return {
    destroy() {
      gsap.ticker.remove(tick);
      window.removeEventListener("resize", resize);
      io.disconnect();
      gl.getExtension("WEBGL_lose_context")?.loseContext();
      canvas.remove();
    },
  };
}
