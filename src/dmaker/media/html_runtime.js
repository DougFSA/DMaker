/* Runtime do DMaker dentro da página da composição em HTML.
 *
 * O Python grava `window.__dmakerConfig` antes deste arquivo e o injeta antes de qualquer script da página.
 * Ele faz quatro coisas:
 *   1. troca o relógio do navegador (performance.now, Date, setTimeout, setInterval, requestAnimationFrame) por
 *      um relógio virtual que só anda quando o DMaker manda, para a mesma composição sair sempre igual;
 *   2. posiciona no instante pedido o que anda sozinho: animações CSS e Web Animations, GSAP (se a página o
 *      trouxer) e animações Lottie, e chama a função opcional `window.dmakerSeek(segundos)` da página;
 *   3. entrega à página o objeto `dmaker`: tempo, tamanho, dados, cores da marca e ruído suave (simplex);
 *   4. espera a página ficar pronta (fontes, imagens, Lottie) antes do primeiro quadro.
 */
(() => {
  "use strict";
  const cfg = window.__dmakerConfig;
  if (!cfg || window.top !== window) return;

  const realSetTimeout = window.setTimeout.bind(window);
  const realClearTimeout = window.clearTimeout.bind(window);
  const RealDate = Date;

  // ---------- relógio virtual ----------

  const clock = { now: 0 }; // ms desde o começo da composição
  let order = 0;
  let nextId = 0;
  const timers = new Map();
  let frameCallbacks = [];
  const MAX_TIMER_RUNS = 200000;

  function addTimer(callback, delay, args, interval) {
    if (typeof callback !== "function") return 0;
    const wait = Math.max(Number(delay) || 0, 0);
    const id = ++nextId;
    timers.set(id, { id, callback, args, at: clock.now + wait, interval: interval ? Math.max(wait, 1) : null, order: ++order });
    return id;
  }

  function reportError(error) {
    // o erro de um callback não pode parar o resto; vira um erro de página, que o DMaker mostra como aviso
    realSetTimeout(() => {
      throw error;
    });
  }

  function runTimersUpTo(target) {
    let runs = 0;
    for (;;) {
      let next = null;
      for (const timer of timers.values()) {
        if (timer.at > target) continue;
        if (next === null || timer.at < next.at || (timer.at === next.at && timer.order < next.order)) next = timer;
      }
      if (next === null) break;
      if (++runs > MAX_TIMER_RUNS) throw new Error("os temporizadores da composição não terminam (setTimeout ou setInterval em laço)");
      clock.now = Math.max(clock.now, next.at);
      if (next.interval !== null) {
        next.at += next.interval;
        next.order = ++order;
      } else {
        timers.delete(next.id);
      }
      try {
        next.callback(...next.args);
      } catch (error) {
        reportError(error);
      }
    }
    clock.now = target;
  }

  function runFrameCallbacks() {
    const due = frameCallbacks;
    frameCallbacks = [];
    for (const entry of due) {
      if (entry.cancelled) continue;
      try {
        entry.callback(clock.now);
      } catch (error) {
        reportError(error);
      }
    }
  }

  window.setTimeout = (callback, delay, ...args) => addTimer(callback, delay, args, false);
  window.setInterval = (callback, delay, ...args) => addTimer(callback, delay, args, true);
  window.clearTimeout = window.clearInterval = (id) => void timers.delete(id);
  window.requestAnimationFrame = (callback) => {
    const entry = { id: ++nextId, callback, cancelled: false };
    frameCallbacks.push(entry);
    return entry.id;
  };
  window.cancelAnimationFrame = (id) => {
    for (const entry of frameCallbacks) if (entry.id === id) entry.cancelled = true;
  };
  window.requestIdleCallback = (callback) =>
    addTimer(() => callback({ didTimeout: false, timeRemaining: () => 50 }), 1, [], false);
  window.cancelIdleCallback = window.clearTimeout;
  performance.now = () => clock.now;

  const epoch = cfg.epoch;
  function VirtualDate(...args) {
    if (!new.target) return new RealDate(epoch + clock.now).toString();
    return Reflect.construct(RealDate, args.length ? args : [epoch + clock.now], new.target);
  }
  VirtualDate.prototype = RealDate.prototype;
  Object.setPrototypeOf(VirtualDate, RealDate);
  VirtualDate.now = () => epoch + clock.now;
  window.Date = VirtualDate;

  // Math.random com semente fixa: o que a composição sorteia é o mesmo em todo render
  function mulberry32(seed) {
    let state = seed >>> 0;
    return () => {
      state = (state + 0x6d2b79f5) >>> 0;
      let t = state;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  Math.random = mulberry32(cfg.seed);

  // o WebGL só guarda o quadro desenhado se pedir; sem isso a captura pode pegar o buffer já limpo
  const realGetContext = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (kind, attributes) {
    if (typeof kind === "string" && kind.includes("webgl")) attributes = { ...attributes, preserveDrawingBuffer: true };
    return realGetContext.call(this, kind, attributes);
  };

  // ---------- ruído simplex (3D), escrito aqui a partir do algoritmo de domínio público ----------

  const GRADIENTS = [
    [1, 1, 0], [-1, 1, 0], [1, -1, 0], [-1, -1, 0],
    [1, 0, 1], [-1, 0, 1], [1, 0, -1], [-1, 0, -1],
    [0, 1, 1], [0, -1, 1], [0, 1, -1], [0, -1, -1],
  ];
  const SKEW = 1 / 3;
  const UNSKEW = 1 / 6;

  function permutationFor(seed) {
    const random = mulberry32(seed);
    const table = Array.from({ length: 256 }, (_, i) => i);
    for (let i = 255; i > 0; i--) {
      const j = Math.floor(random() * (i + 1));
      [table[i], table[j]] = [table[j], table[i]];
    }
    return Uint8Array.from({ length: 512 }, (_, i) => table[i & 255]);
  }

  let permutation = permutationFor(cfg.seed);

  function corner(x, y, z, hash) {
    let t = 0.6 - x * x - y * y - z * z;
    if (t < 0) return 0;
    const g = GRADIENTS[hash % 12];
    t *= t;
    return t * t * (g[0] * x + g[1] * y + g[2] * z);
  }

  function noise3(x, y, z) {
    const skew = (x + y + z) * SKEW;
    const i = Math.floor(x + skew);
    const j = Math.floor(y + skew);
    const k = Math.floor(z + skew);
    const unskew = (i + j + k) * UNSKEW;
    const x0 = x - (i - unskew);
    const y0 = y - (j - unskew);
    const z0 = z - (k - unskew);
    let i1, j1, k1, i2, j2, k2;
    if (x0 >= y0) {
      if (y0 >= z0) [i1, j1, k1, i2, j2, k2] = [1, 0, 0, 1, 1, 0];
      else if (x0 >= z0) [i1, j1, k1, i2, j2, k2] = [1, 0, 0, 1, 0, 1];
      else [i1, j1, k1, i2, j2, k2] = [0, 0, 1, 1, 0, 1];
    } else if (y0 < z0) [i1, j1, k1, i2, j2, k2] = [0, 0, 1, 0, 1, 1];
    else if (x0 < z0) [i1, j1, k1, i2, j2, k2] = [0, 1, 0, 0, 1, 1];
    else [i1, j1, k1, i2, j2, k2] = [0, 1, 0, 1, 1, 0];
    const ii = i & 255;
    const jj = j & 255;
    const kk = k & 255;
    const p = permutation;
    const n0 = corner(x0, y0, z0, p[ii + p[jj + p[kk]]]);
    const n1 = corner(x0 - i1 + UNSKEW, y0 - j1 + UNSKEW, z0 - k1 + UNSKEW, p[ii + i1 + p[jj + j1 + p[kk + k1]]]);
    const n2 = corner(x0 - i2 + 2 * UNSKEW, y0 - j2 + 2 * UNSKEW, z0 - k2 + 2 * UNSKEW, p[ii + i2 + p[jj + j2 + p[kk + k2]]]);
    const n3 = corner(x0 - 1 + 3 * UNSKEW, y0 - 1 + 3 * UNSKEW, z0 - 1 + 3 * UNSKEW, p[ii + 1 + p[jj + 1 + p[kk + 1]]]);
    return 32 * (n0 + n1 + n2 + n3); // fica entre -1 e 1
  }

  // ---------- o objeto `dmaker` da página ----------

  const dmaker = {
    width: cfg.width,
    height: cfg.height,
    fps: cfg.fps,
    duration: cfg.duration,
    data: cfg.data,
    brand: cfg.brand,
    fontFamily: cfg.fontFamily,
    time: 0,
    frame: 0,
    progress: 0,
    noise3,
    noise2: (x, y) => noise3(x, y, 0),
    noiseSeed(seed) {
      permutation = permutationFor(seed);
    },
    random: mulberry32,
  };
  window.dmaker = dmaker;

  // estilo do DMaker: variáveis da marca, a Poppins e as animações CSS paradas desde o nascimento (sem isso,
  // elas andariam em tempo real entre o carregamento e o primeiro quadro)
  const style = document.createElement("style");
  style.id = "dmaker-style";
  style.textContent = cfg.css;
  function mountStyle() {
    if (document.documentElement) {
      document.documentElement.prepend(style);
      return true;
    }
    return false;
  }
  if (!mountStyle()) {
    const observer = new MutationObserver(() => {
      if (mountStyle()) observer.disconnect();
    });
    observer.observe(document, { childList: true });
  }

  // ---------- o que anda sozinho ----------

  let booted = false;
  const animationOrigin = new WeakMap();
  const lottieOrigin = new WeakMap();

  function originOf(map, item, nowMs) {
    // o que já existia ao carregar a página nasce em 0; o que a página cria depois conta do quadro em que o DMaker o vê
    if (!map.has(item)) map.set(item, booted ? nowMs : 0);
    return map.get(item);
  }

  function syncAnimations(seconds) {
    const nowMs = seconds * 1000;
    for (const animation of document.getAnimations()) {
      if (animation.timeline !== document.timeline) continue;
      const origin = originOf(animationOrigin, animation, nowMs);
      if (animation.playState !== "paused") animation.pause();
      animation.currentTime = Math.max(nowMs - origin, 0);
    }
  }

  function syncGsap() {
    const gsap = window.gsap;
    // o GSAP limita saltos grandes de tempo (lagSmoothing); aqui o salto é de propósito, até o meio da composição
    if (gsap && gsap.ticker && typeof gsap.ticker.lagSmoothing === "function") gsap.ticker.lagSmoothing(0);
  }

  function syncLottie(seconds) {
    const lottie = window.lottie;
    if (!lottie || typeof lottie.getRegisteredAnimations !== "function") return;
    const nowMs = seconds * 1000;
    for (const animation of lottie.getRegisteredAnimations()) {
      if (!animation.isLoaded) continue;
      const origin = originOf(lottieOrigin, animation, nowMs);
      const durationMs = animation.getDuration(false) * 1000;
      // ao terminar, o Lottie para no penúltimo instante (o último quadro está fora do intervalo da animação)
      const lastMs = Math.max(animation.totalFrames - 1, 0) / animation.frameRate * 1000;
      let local = Math.max(nowMs - origin, 0) * (animation.playSpeed || 1);
      if (animation.loop && durationMs > 0) {
        const plays = animation.loop === true ? Infinity : Number(animation.loop);
        local = local >= plays * durationMs ? lastMs : local % durationMs;
      } else {
        local = Math.min(local, lastMs);
      }
      animation.goToAndStop(local, false);
    }
  }

  function guard(promise, label, ms) {
    return new Promise((resolve, reject) => {
      const timer = realSetTimeout(() => reject(new Error(`${label} passou de ${ms / 1000} s sem terminar`)), ms);
      promise.then(
        (value) => {
          realClearTimeout(timer);
          resolve(value);
        },
        (error) => {
          realClearTimeout(timer);
          reject(error);
        },
      );
    });
  }

  function poll(check, ms) {
    return new Promise((resolve) => {
      let waited = 0;
      const step = () => {
        if (check() || waited >= ms) return resolve(check());
        waited += 25;
        realSetTimeout(step, 25);
      };
      step();
    });
  }

  async function whenReady() {
    if (document.readyState === "loading") {
      await new Promise((resolve) => document.addEventListener("DOMContentLoaded", resolve, { once: true }));
    }
    if (document.fonts) {
      await document.fonts.ready;
      const faces = cfg.fontFaces.map((face) => document.fonts.load(face).catch(() => []));
      await Promise.all(faces);
    }
    await Promise.all(
      Array.from(document.images).map((image) =>
        image.complete ? Promise.resolve() : new Promise((resolve) => {
          image.addEventListener("load", resolve, { once: true });
          image.addEventListener("error", resolve, { once: true });
        }),
      ),
    );
    const lottie = window.lottie;
    if (lottie && typeof lottie.getRegisteredAnimations === "function") {
      await poll(() => lottie.getRegisteredAnimations().every((animation) => animation.isLoaded), 10000);
    }
    if (window.dmakerReady) await window.dmakerReady;
    syncGsap();
    booted = true;
  }

  const host = {
    /** Espera a página ficar pronta e deixa tudo parado no instante 0. */
    ready: () => guard(whenReady(), "a composição não ficou pronta em 30 s (fontes, imagens ou animação Lottie ainda carregando)", 30000).then(() => host.seek(0)),
    /** Leva a composição ao instante `seconds` (sempre para frente) e espera ela desenhar. */
    seek: async (seconds) => {
      const nowMs = seconds * 1000;
      if (nowMs < clock.now - 1e-6) throw new Error("o relógio da composição não anda para trás");
      dmaker.time = seconds;
      dmaker.frame = Math.round(seconds * cfg.fps);
      dmaker.progress = cfg.duration > 0 ? Math.min(Math.max(seconds / cfg.duration, 0), 1) : 0;
      runTimersUpTo(Math.max(nowMs, clock.now));
      syncAnimations(seconds);
      syncGsap();
      syncLottie(seconds);
      runFrameCallbacks();
      syncAnimations(seconds);
      syncLottie(seconds);
      if (typeof window.dmakerSeek === "function") {
        await guard(
          Promise.resolve(window.dmakerSeek(seconds)),
          "dmakerSeek não terminou em 20 s (dentro dela não espere setTimeout nem requestAnimationFrame: o relógio só anda quando o DMaker manda)",
          20000,
        );
      }
    },
  };
  Object.defineProperty(window, "__dmakerHost", { value: host });
})();
