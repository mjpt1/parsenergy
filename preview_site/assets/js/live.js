/* =====================================================================
   Live figures: the energy-exchange price, and what the fleet is producing.

   Both are behind one contract, so switching from the demo feed to the real
   one is editing `SOURCES` and nothing else.

       { value, unit, updatedAt, source, isDemo }

   Why a demo at all: the Iran Energy Exchange publishes no free public API,
   and the production feed needs a CORS-enabled endpoint on pars-tida.ir that
   exposes aggregates only. Until both exist, these numbers are generated —
   and the page says so, in the UI, on purpose. A plausible-looking number
   with no source behind it is worse than an honest placeholder: it gets
   quoted back at you in a meeting.
   ===================================================================== */

export const SOURCES = {
  // Replace `demo: false` and fill `url` when the endpoints exist.
  // The endpoint should answer: {"value": 7450, "updatedAt": "2026-10-14T09:00:00Z"}
  bourse: { demo: true, url: '/api/public/power-price/' },
  // {"power_kw": 812.4, "today_kwh": 4190, "total_mwh": 1260, "plants": 24}
  production: { demo: true, url: '/api/public/fleet-live/' },
};

const FA = new Intl.NumberFormat('fa-IR');
export const faNum = (n, digits = 0) =>
  FA.format(Number(n).toFixed(digits)).replace(/٫/, '٫');

async function fetchJson(url, timeout = 6000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  try {
    const res = await fetch(url, { signal: ctrl.signal, headers: { Accept: 'application/json' } });
    if (!res.ok) throw new Error(String(res.status));
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

/* ------------------------------------------------------------- demo feed */
// Deterministic per day, so the figure does not jump around while a client
// is looking at it, but still moves from one day to the next.
function daySeed() {
  const d = new Date();
  return d.getFullYear() * 1000 + d.getMonth() * 40 + d.getDate();
}

function pseudo(seed) {
  const x = Math.sin(seed) * 10000;
  return x - Math.floor(x);
}

function demoBourse() {
  const base = 7200;                       // ریال بر کیلووات‌ساعت، مرتبهٔ واقعی
  const drift = (pseudo(daySeed()) - 0.5) * 900;
  return {
    value: Math.round((base + drift) / 10) * 10,
    unit: 'ریال / کیلووات‌ساعت',
    updatedAt: new Date(),
    source: 'نمونه',
    isDemo: true,
  };
}

function demoProduction() {
  // A plant does nothing at night and peaks around solar noon; the demo at
  // least behaves like a solar plant rather than a random number.
  const now = new Date();
  const hour = now.getHours() + now.getMinutes() / 60;
  const daylight = Math.max(0, Math.sin(((hour - 6) / 12) * Math.PI));
  const capacity = 1780;                   // kW, مجموع ظرفیت نصب‌شده
  const power = capacity * 0.78 * daylight;
  const todayKwh = capacity * 4.6 * Math.min(1, Math.max(0, (hour - 6) / 12));
  return {
    power_kw: power,
    today_kwh: todayKwh,
    total_mwh: 1260 + Math.floor(pseudo(daySeed()) * 40),
    plants: 24,
    updatedAt: now,
    isDemo: true,
  };
}

/* ----------------------------------------------------------------- public */
export async function getBourse() {
  const cfg = SOURCES.bourse;
  if (cfg.demo) return demoBourse();
  try {
    const data = await fetchJson(cfg.url);
    return {
      value: data.value,
      unit: data.unit || 'ریال / کیلووات‌ساعت',
      updatedAt: data.updatedAt ? new Date(data.updatedAt) : new Date(),
      source: data.source || 'بورس انرژی ایران',
      isDemo: false,
    };
  } catch (err) {
    // A dead feed must not leave an empty box on a sales page.
    return { ...demoBourse(), unavailable: true };
  }
}

export async function getProduction() {
  const cfg = SOURCES.production;
  if (cfg.demo) return demoProduction();
  try {
    const data = await fetchJson(cfg.url);
    return { ...data, updatedAt: new Date(), isDemo: false };
  } catch (err) {
    return { ...demoProduction(), unavailable: true };
  }
}
