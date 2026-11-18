/* =====================================================================
   The hero scene: a solar plant drawn frame by frame as you scroll.

   This replaces the usual "scroll-driven image sequence", where 200-odd
   rendered PNGs are preloaded and swapped on scroll. That technique looks
   the part and costs 10-40 MB, which is the opposite of the brief. Here the
   same effect is computed: sky, sun, panel array, shadows and the flow of
   energy are all drawn to a canvas from one number — how far down the hero
   you are — so the page ships no scene imagery at all.

   Everything is parametric, so "more panels", "longer day", "different sun
   colour" are one constant away.
   ===================================================================== */
const TAU = Math.PI * 2;
const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const lerp = (a, b, t) => a + (b - a) * t;
const ease = (t) => t * t * (3 - 2 * t);           // smoothstep
const mix = (c1, c2, t) => [
  Math.round(lerp(c1[0], c2[0], t)),
  Math.round(lerp(c1[1], c2[1], t)),
  Math.round(lerp(c1[2], c2[2], t)),
];
const rgb = (c, a = 1) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;

/* Dawn → noon → dusk. The scroll position is the time of day. */
const SKY = {
  dawn: { top: [26, 35, 64], bottom: [214, 136, 86], sun: [255, 183, 94] },
  noon: { top: [78, 150, 214], bottom: [196, 226, 244], sun: [255, 241, 196] },
  dusk: { top: [31, 42, 74], bottom: [196, 104, 92], sun: [255, 150, 92] },
};

const ROWS = 4;
const COLS = 7;

export function createScene(canvas) {
  const ctx = canvas.getContext('2d', { alpha: false });
  let w = 0;
  let h = 0;
  let dpr = 1;
  let progress = 0;
  let drawn = -1;
  let raf = 0;

  // A fixed particle set, re-used every frame: allocating inside the draw
  // loop is what makes canvas animations stutter on cheap phones.
  const sparks = Array.from({ length: 34 }, (_, i) => ({
    row: i % ROWS,
    offset: Math.random(),
    speed: 0.45 + Math.random() * 0.75,
  }));

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);  // 3x costs a lot, shows little
    const rect = canvas.getBoundingClientRect();
    w = rect.width;
    h = rect.height;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    drawn = -1;
    schedule();
  }

  /* ---------------------------------------------------------------- sky */
  function palette(t) {
    // 0 → dawn, 0.5 → noon, 1 → dusk
    if (t < 0.5) {
      const k = ease(t / 0.5);
      return {
        top: mix(SKY.dawn.top, SKY.noon.top, k),
        bottom: mix(SKY.dawn.bottom, SKY.noon.bottom, k),
        sun: mix(SKY.dawn.sun, SKY.noon.sun, k),
      };
    }
    const k = ease((t - 0.5) / 0.5);
    return {
      top: mix(SKY.noon.top, SKY.dusk.top, k),
      bottom: mix(SKY.noon.bottom, SKY.dusk.bottom, k),
      sun: mix(SKY.noon.sun, SKY.dusk.sun, k),
    };
  }

  function drawSky(p) {
    const g = ctx.createLinearGradient(0, 0, 0, h);
    g.addColorStop(0, rgb(p.top));
    g.addColorStop(1, rgb(p.bottom));
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);
  }

  function sunPosition(t) {
    // A flattened arc: rises at the right (RTL reading order), sets left.
    const a = Math.PI * clamp(t);
    return {
      x: w * (0.94 - 0.88 * clamp(t)),
      y: h * 0.78 - Math.sin(a) * h * 0.56,
    };
  }

  function drawSun(p, t) {
    const { x, y } = sunPosition(t);
    const r = Math.min(w, h) * 0.055;
    const glow = ctx.createRadialGradient(x, y, 0, x, y, r * 7);
    glow.addColorStop(0, rgb(p.sun, 0.55));
    glow.addColorStop(0.35, rgb(p.sun, 0.14));
    glow.addColorStop(1, rgb(p.sun, 0));
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, w, h);
    ctx.beginPath();
    ctx.arc(x, y, r, 0, TAU);
    ctx.fillStyle = rgb(p.sun, 0.96);
    ctx.fill();
    return { x, y };
  }

  /* --------------------------------------------------------------- land */
  function drawGround(p, t) {
    const horizon = h * 0.62;
    const g = ctx.createLinearGradient(0, horizon, 0, h);
    const near = mix([58, 74, 48], [32, 44, 30], ease(t));
    g.addColorStop(0, rgb(mix(near, p.bottom, 0.35)));
    g.addColorStop(1, rgb(near));
    ctx.fillStyle = g;
    ctx.fillRect(0, horizon, w, h - horizon);
    return horizon;
  }

  /* -------------------------------------------------------------- array */
  // One-point perspective: a row's depth 0..1 maps to a scale and a y offset,
  // which is enough to read as 3D without a matrix library.
  function rowGeometry(row, horizon) {
    const depth = row / (ROWS - 1);
    const scale = lerp(0.34, 1, ease(depth));
    const y = lerp(horizon + h * 0.055, h * 0.98, ease(depth));
    return { depth, scale, y };
  }

  function drawPanels(sun, horizon, t) {
    const tilt = lerp(0.52, 0.30, Math.sin(Math.PI * clamp(t)));  // tracks the sun
    for (let row = 0; row < ROWS; row++) {
      const { scale, y } = rowGeometry(row, horizon);
      const panelW = (w * 0.115) * scale;
      const panelH = panelW * tilt;
      const gap = panelW * 0.18;
      const total = COLS * panelW + (COLS - 1) * gap;
      const startX = (w - total) / 2;

      for (let col = 0; col < COLS; col++) {
        const x = startX + col * (panelW + gap);

        // Shadow first, thrown away from the sun and long at dawn/dusk.
        const lean = (x + panelW / 2 - sun.x) / w;
        const length = 1 + 2.4 * (1 - Math.sin(Math.PI * clamp(t)));
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(x + panelW, y);
        ctx.lineTo(x + panelW + lean * panelW * length, y + panelH * 0.5 * length);
        ctx.lineTo(x + lean * panelW * length, y + panelH * 0.5 * length);
        ctx.closePath();
        ctx.fillStyle = `rgba(12,18,10,${0.16 + 0.1 * (1 - scale)})`;
        ctx.fill();

        // The panel face: darker at the top edge, catching sun at the lower.
        const face = ctx.createLinearGradient(x, y - panelH, x, y);
        const lit = clamp(0.25 + 0.75 * Math.sin(Math.PI * clamp(t)));
        face.addColorStop(0, `rgba(${18 + lit * 40},${30 + lit * 60},${58 + lit * 90},1)`);
        face.addColorStop(1, `rgba(${10 + lit * 18},${18 + lit * 28},${38 + lit * 48},1)`);
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(x + panelW, y);
        ctx.lineTo(x + panelW * 0.93, y - panelH);
        ctx.lineTo(x + panelW * 0.07, y - panelH);
        ctx.closePath();
        ctx.fillStyle = face;
        ctx.fill();

        // Cell grid, skipped on the far rows where it would be mush.
        if (scale > 0.55) {
          ctx.strokeStyle = `rgba(255,255,255,${0.07 * scale})`;
          ctx.lineWidth = Math.max(0.5, scale);
          for (let i = 1; i < 4; i++) {
            const fx = x + (panelW * i) / 4;
            ctx.beginPath();
            ctx.moveTo(fx, y);
            ctx.lineTo(fx - panelW * 0.03 * (i - 2), y - panelH);
            ctx.stroke();
          }
        }

        // Specular streak — the thing that sells glass.
        const spec = ctx.createLinearGradient(x, y - panelH, x + panelW, y);
        spec.addColorStop(0, `rgba(255,255,255,0)`);
        spec.addColorStop(clamp(0.5 - lean * 0.4, 0.05, 0.95), `rgba(255,255,255,${0.2 * lit * scale})`);
        spec.addColorStop(1, `rgba(255,255,255,0)`);
        ctx.fillStyle = spec;
        ctx.fill();
      }
    }
  }

  /* ------------------------------------------------------- energy flow */
  function drawSparks(horizon, t) {
    const strength = Math.sin(Math.PI * clamp(t));
    if (strength <= 0.02) return;
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    for (const s of sparks) {
      const { scale, y } = rowGeometry(s.row, horizon);
      const k = (s.offset + progress * s.speed * 2.2) % 1;
      const x = lerp(w * 0.08, w * 0.92, k);
      const r = Math.max(1, 2.4 * scale);
      ctx.beginPath();
      ctx.arc(x, y - 2 * scale, r, 0, TAU);
      ctx.fillStyle = `rgba(126,231,135,${0.5 * strength * scale})`;
      ctx.fill();
    }
    ctx.restore();
  }

  /* --------------------------------------------------------------- draw */
  function render() {
    raf = 0;
    if (!w || !h) return;
    const t = clamp(progress);
    const p = palette(t);
    drawSky(p);
    const sun = drawSun(p, t);
    const horizon = drawGround(p, t);
    drawPanels(sun, horizon, t);
    drawSparks(horizon, t);
    drawn = t;
  }

  function schedule() {
    if (!raf) raf = requestAnimationFrame(render);
  }

  function setProgress(value) {
    const next = clamp(value);
    // Sub-frame changes are invisible; skipping them keeps a scroll cheap.
    if (Math.abs(next - drawn) < 0.0015) return;
    progress = next;
    schedule();
  }

  const ro = new ResizeObserver(resize);
  ro.observe(canvas);
  resize();

  return { setProgress, destroy: () => { ro.disconnect(); cancelAnimationFrame(raf); } };
}
