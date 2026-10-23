/* WebGL game feel for the lobby, no libraries (the CSP only allows our own scripts).
 *  - #fxBg: a full-screen shader: an arena floor grid running to the horizon, light beams and haze.
 *    It reacts to lobby state: idle, searching (faster + pulsing), found (shockwave), match (team tint).
 *  - #fxTop: an additive particle layer for bursts (correct answer, match found, victory).
 * Falls back to the CSS background (body.nofx) when WebGL is missing, the user turns effects off,
 * or the system asks for reduced motion (then we draw one still frame and no particles).
 * API: window.FX = { mode, pulse, team, burst, burstAt, setCb, enable, enabled }
 */
(function () {
"use strict";
const reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const MODES = { idle: 0, search: 1, found: 2, match: 3, win: 4, loss: 5 };
const SPEED = { 0: 0.12, 1: 0.55, 2: 0.9, 3: 0.28, 4: 0.5, 5: 0.06 };
const RGB = {
  signal: [1.0, 0.43, 0.22], good: [0.46, 0.86, 0.48], warn: [1.0, 0.8, 0.36], ink: [0.95, 0.92, 0.86],
  red: [0.95, 0.34, 0.3], blue: [0.4, 0.64, 0.97], redCb: [1.0, 0.66, 0.22], blueCb: [0.5, 0.46, 0.97],
};
let cb = false, on = true;
const col = name => (cb && (name === "red" || name === "blue") ? RGB[name + "Cb"] : RGB[name]) || RGB.signal;

/* ---------- shared helpers ---------- */
function compile(gl, type, src) {
  const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) || "shader");
  return s;
}
function program(gl, vs, fs) {
  const p = gl.createProgram();
  gl.attachShader(p, compile(gl, gl.VERTEX_SHADER, vs)); gl.attachShader(p, compile(gl, gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p) || "link");
  return p;
}
function context(canvas, opts) {
  try { return canvas.getContext("webgl", Object.assign({ antialias: false, premultipliedAlpha: true, powerPreference: "low-power" }, opts)); }
  catch (_) { return null; }
}

/* ---------- backdrop ---------- */
const BG_VS = "attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}";
const BG_FS = `
precision mediump float;
uniform vec2 res; uniform float t, travel, pulse, wave, team, mode;
uniform vec3 cSig, cRed, cBlue;
float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
float noise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);
  return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);}
void main(){
  vec2 uv=gl_FragCoord.xy/res; float asp=res.x/res.y;
  vec3 base=vec3(0.075,0.062,0.055);
  vec3 c=base;
  float hz=0.52;                                   // horizon height
  // sky: warm haze toward the horizon, slow drifting dust
  float sky=smoothstep(hz+0.45,hz,uv.y);
  c+=cSig*0.10*sky;
  c+=vec3(0.02)*noise(vec2(uv.x*asp*3.,uv.y*3.-t*0.05));
  // light beams fanning from above the arena
  vec2 o=vec2(0.5,1.15); vec2 d=uv-o; d.x*=asp;
  float ang=atan(d.x,-d.y);
  float beams=pow(max(0.,sin(ang*9.+sin(t*0.21)*0.8)),18.)*smoothstep(1.4,0.2,length(d));
  c+=cSig*beams*(0.08+0.10*pulse);
  // floor grid in perspective
  if(uv.y<hz){
    float y=hz-uv.y;
    float z=0.22/y;                                // depth
    float x=(uv.x-0.5)*asp*z;
    vec2 g=vec2(x*1.6, z+travel);
    vec2 gd=abs(fract(g)-0.5);
    float w=0.012*z+0.004;
    float lx=1.-smoothstep(0.,w*1.6,0.5-gd.x);
    float lz=1.-smoothstep(0.,w*1.6,0.5-gd.y);
    float grid=max(lx,lz);
    float fade=exp(-z*0.35);
    vec3 gc=cSig;
    if(team>0.5){ gc=mix(cRed,cBlue,smoothstep(-0.25,0.25,x/z*0.9)); }
    c+=gc*grid*fade*(0.32+0.35*pulse);
    // shockwave ring when a match is found
    float r=length(vec2(x*0.6,z-2.2));
    c+=cSig*smoothstep(0.35,0.,abs(r-wave*7.))*step(0.001,wave)*(1.-wave)*0.9;
    // floor sheen
    c+=gc*0.05*fade;
  }
  // horizon glow line
  c+=cSig*exp(-abs(uv.y-hz)*55.)*(0.35+0.4*pulse);
  // result tint
  if(mode>3.5&&mode<4.5){ c+=vec3(0.04,0.09,0.04)*sky; }
  if(mode>4.5){ c*=0.82; }
  // vignette
  vec2 v=uv-0.5; v.x*=asp*0.7;
  c*=1.-dot(v,v)*0.9;
  gl_FragColor=vec4(c,1.);
}`;

const bg = { gl: null, prog: null, loc: {}, travel: 0, pulse: 0, wave: 0, mode: 0, team: 0, last: 0, raf: 0 };
function bgInit() {
  const canvas = document.getElementById("fxBg");
  const gl = canvas && context(canvas, { alpha: false });
  if (!gl) return false;
  try { bg.prog = program(gl, BG_VS, BG_FS); } catch (_) { return false; }
  bg.gl = gl;
  const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  gl.useProgram(bg.prog);
  const p = gl.getAttribLocation(bg.prog, "p"); gl.enableVertexAttribArray(p); gl.vertexAttribPointer(p, 2, gl.FLOAT, false, 0, 0);
  for (const n of ["res", "t", "travel", "pulse", "wave", "team", "mode", "cSig", "cRed", "cBlue"]) bg.loc[n] = gl.getUniformLocation(bg.prog, n);
  canvas.addEventListener("webglcontextlost", e => { e.preventDefault(); cancelAnimationFrame(bg.raf); bg.gl = null; });
  canvas.addEventListener("webglcontextrestored", () => { if (bgInit()) bgLoop(); });
  return true;
}
function bgSize() {
  const canvas = document.getElementById("fxBg"), gl = bg.gl; if (!gl) return;
  const scale = Math.min(window.devicePixelRatio || 1, 1.5) * 0.6;        // the backdrop is soft: render small, stretch
  const w = Math.max(2, Math.round(innerWidth * scale)), h = Math.max(2, Math.round(innerHeight * scale));
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; gl.viewport(0, 0, w, h); }
}
function bgDraw(now) {
  const gl = bg.gl; if (!gl) return;
  const dt = Math.min(0.05, (now - (bg.last || now)) / 1000); bg.last = now;
  bg.travel += dt * SPEED[bg.mode];
  bg.pulse = Math.max(0, bg.pulse - dt * 0.9);
  if (bg.mode === 1) bg.pulse = Math.max(bg.pulse, 0.25 + 0.25 * Math.sin(now / 260));
  if (bg.wave > 0) { bg.wave += dt * 0.9; if (bg.wave >= 1) bg.wave = 0; }
  bgSize();
  gl.uniform2f(bg.loc.res, gl.drawingBufferWidth, gl.drawingBufferHeight);
  gl.uniform1f(bg.loc.t, now / 1000); gl.uniform1f(bg.loc.travel, bg.travel);
  gl.uniform1f(bg.loc.pulse, bg.pulse); gl.uniform1f(bg.loc.wave, bg.wave);
  gl.uniform1f(bg.loc.team, bg.team); gl.uniform1f(bg.loc.mode, bg.mode);
  gl.uniform3fv(bg.loc.cSig, col("signal")); gl.uniform3fv(bg.loc.cRed, col("red")); gl.uniform3fv(bg.loc.cBlue, col("blue"));
  gl.drawArrays(gl.TRIANGLES, 0, 3);
}
function bgLoop() {
  cancelAnimationFrame(bg.raf);
  if (!on || !bg.gl) return;
  if (reduced) { bgDraw(performance.now()); return; }                  // one still frame
  const tick = now => { if (!document.hidden) bgDraw(now); bg.raf = requestAnimationFrame(tick); };
  bg.raf = requestAnimationFrame(tick);
}

/* ---------- particles ---------- */
const PT_VS = `attribute vec2 p;attribute vec4 c;attribute float s;uniform vec2 res;varying vec4 vc;
void main(){vc=c;gl_Position=vec4(p/res*2.-1.,0.,1.);gl_Position.y=-gl_Position.y;gl_PointSize=s;}`;
const PT_FS = `precision mediump float;varying vec4 vc;
void main(){vec2 d=gl_PointCoord-0.5;float a=smoothstep(0.5,0.,length(d));gl_FragColor=vec4(vc.rgb*vc.a*a,vc.a*a);}`;
const MAX = 900, STRIDE = 7;   // x, y, r, g, b, a, size
const pt = { gl: null, prog: null, buf: null, data: new Float32Array(MAX * STRIDE), list: [], raf: 0, loc: {}, dpr: 1 };
function ptInit() {
  const canvas = document.getElementById("fxTop");
  const gl = canvas && context(canvas, { alpha: true });
  if (!gl) return false;
  try { pt.prog = program(gl, PT_VS, PT_FS); } catch (_) { return false; }
  pt.gl = gl; pt.buf = gl.createBuffer();
  gl.useProgram(pt.prog);
  pt.loc.res = gl.getUniformLocation(pt.prog, "res");
  const F = 4;
  gl.bindBuffer(gl.ARRAY_BUFFER, pt.buf);
  gl.bufferData(gl.ARRAY_BUFFER, pt.data.byteLength, gl.DYNAMIC_DRAW);
  const a = n => gl.getAttribLocation(pt.prog, n);
  gl.enableVertexAttribArray(a("p")); gl.vertexAttribPointer(a("p"), 2, gl.FLOAT, false, STRIDE * F, 0);
  gl.enableVertexAttribArray(a("c")); gl.vertexAttribPointer(a("c"), 4, gl.FLOAT, false, STRIDE * F, 2 * F);
  gl.enableVertexAttribArray(a("s")); gl.vertexAttribPointer(a("s"), 1, gl.FLOAT, false, STRIDE * F, 6 * F);
  gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE);                     // additive glow
  canvas.addEventListener("webglcontextlost", e => { e.preventDefault(); pt.gl = null; pt.list = []; });
  canvas.addEventListener("webglcontextrestored", () => ptInit());
  return true;
}
function ptSize() {
  const canvas = document.getElementById("fxTop"), gl = pt.gl;
  pt.dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.round(innerWidth * pt.dpr), h = Math.round(innerHeight * pt.dpr);
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; gl.viewport(0, 0, w, h); }
}
function ptFrame(now) {
  const gl = pt.gl; if (!gl) return;
  const dt = Math.min(0.04, (now - (pt.last || now)) / 1000); pt.last = now;
  ptSize();
  let n = 0;
  pt.list = pt.list.filter(q => (q.life -= dt) > 0);
  for (const q of pt.list) {
    q.vy += 900 * dt * q.g; q.vx *= 0.985; q.vy *= 0.985;
    q.x += q.vx * dt; q.y += q.vy * dt;
    const k = n * STRIDE, life = q.life / q.max;
    pt.data[k] = q.x * pt.dpr; pt.data[k + 1] = q.y * pt.dpr;
    pt.data[k + 2] = q.c[0]; pt.data[k + 3] = q.c[1]; pt.data[k + 4] = q.c[2]; pt.data[k + 5] = Math.min(1, life * 1.6);
    pt.data[k + 6] = q.s * pt.dpr * (0.5 + life * 0.5);
    if (++n >= MAX) break;
  }
  gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
  if (n) {
    gl.useProgram(pt.prog); gl.uniform2f(pt.loc.res, gl.drawingBufferWidth, gl.drawingBufferHeight);
    gl.bindBuffer(gl.ARRAY_BUFFER, pt.buf); gl.bufferSubData(gl.ARRAY_BUFFER, 0, pt.data.subarray(0, n * STRIDE));
    gl.drawArrays(gl.POINTS, 0, n);
  }
  pt.raf = pt.list.length ? requestAnimationFrame(ptFrame) : 0;          // sleep when nothing is flying
  if (!pt.raf) pt.last = 0;
}

/* ---------- public API ---------- */
function burst(x, y, opts) {
  if (!on || reduced || !pt.gl) return;
  const o = Object.assign({ color: "signal", count: 60, speed: 420, size: 7, gravity: 0.35, life: 1.1, spread: Math.PI * 2, dir: -Math.PI / 2 }, opts);
  const c = col(o.color);
  for (let i = 0; i < o.count && pt.list.length < MAX; i++) {
    const a = o.dir + (Math.random() - 0.5) * o.spread, v = o.speed * (0.35 + Math.random() * 0.65);
    const life = o.life * (0.6 + Math.random() * 0.6);
    pt.list.push({ x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, life, max: life, s: o.size * (0.6 + Math.random() * 0.8), g: o.gravity,
      c: [Math.min(1, c[0] + Math.random() * 0.1), Math.min(1, c[1] + Math.random() * 0.1), Math.min(1, c[2] + Math.random() * 0.1)] });
  }
  if (!pt.raf) pt.raf = requestAnimationFrame(ptFrame);
}
function burstAt(el, opts) {
  if (!el || !el.getBoundingClientRect) return;
  const r = el.getBoundingClientRect();
  burst(r.left + r.width / 2, r.top + r.height / 2, opts);
}
function mode(m) {
  const v = MODES[m] != null ? MODES[m] : 0;
  if (v === 2 && bg.mode !== 2) { bg.wave = 0.001; bg.pulse = 1; }
  if (v === 4) bg.pulse = 1;
  bg.mode = v;
  if (reduced) bgDraw(performance.now());
}
function enable(b) {
  on = !!b;
  document.body.classList.toggle("nofx", !on || !bg.gl);
  if (on) bgLoop(); else { cancelAnimationFrame(bg.raf); pt.list = []; }
}

let ok = false;
function boot() {
  ok = bgInit();
  if (ok) ptInit();
  document.body.classList.toggle("nofx", !ok || !on);
  if (!ok) return;
  ptSize();
  addEventListener("resize", () => { if (reduced) bgDraw(performance.now()); });
  bgLoop();
}
window.FX = Object.freeze({
  mode, burst, burstAt, enable,
  pulse: s => { bg.pulse = Math.max(bg.pulse, Number(s) || 0.6); },
  team: b => { bg.team = b ? 1 : 0; },
  setCb: b => { cb = !!b; },
  enabled: () => ok && on,
});
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
