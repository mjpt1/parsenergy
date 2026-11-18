/* =====================================================================
   Page behaviour: scroll scene, reveals, live figures, estimator.

   Plain ES modules, no framework and no build step. Everything that can be
   done by the browser's own scheduler (IntersectionObserver, rAF) is left to
   it rather than run on a scroll handler.
   ===================================================================== */
import { createScene } from './scene.js';
import { getBourse, getProduction, faNum } from './live.js';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

/* ------------------------------------------------------------- the scene */
(function heroScene() {
  const canvas = $('#scene');
  const hero = $('.hero');
  if (!canvas || !hero) return;

  const scene = createScene(canvas);
  let ticking = false;

  function update() {
    ticking = false;
    const rect = hero.getBoundingClientRect();
    // 0 at the top of the hero, 1 once it has scrolled fully past.
    const span = rect.height || 1;
    scene.setProgress((-rect.top) / span);
  }

  function onScroll() {
    if (!ticking) {
      ticking = true;
      requestAnimationFrame(update);
    }
  }

  // The scene still renders with reduced motion — it is the page's one
  // illustration. It just stops being driven by the scroll position.
  if (reduced) {
    scene.setProgress(0.42);
  } else {
    addEventListener('scroll', onScroll, { passive: true });
    update();
  }
})();

/* -------------------------------------------------------------- the nav */
(function nav() {
  const bar = $('#nav');
  const burger = $('#burger');
  const links = $('#links');
  if (!bar) return;

  const sync = () => bar.classList.toggle('is-top', scrollY < 40 && !links?.classList.contains('open'));
  addEventListener('scroll', sync, { passive: true });
  sync();

  burger?.addEventListener('click', () => {
    const open = links.classList.toggle('open');
    burger.setAttribute('aria-expanded', String(open));
    sync();
  });
  // Following a link should close the drawer, not leave it hanging open.
  links?.addEventListener('click', (e) => {
    if (e.target.closest('a')) {
      links.classList.remove('open');
      burger?.setAttribute('aria-expanded', 'false');
      sync();
    }
  });
})();

/* ----------------------------------------------------------- reveals */
(function reveals() {
  const items = $$('[data-rise]');
  items.forEach((el) => el.style.setProperty('--d', el.dataset.riseD || 0));
  if (reduced || !('IntersectionObserver' in window)) {
    items.forEach((el) => el.classList.add('in'));
    return;
  }
  const io = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      entry.target.classList.add('in');
      io.unobserve(entry.target);   // reveal once; re-animating on scroll-up is noise
    }
  }, { rootMargin: '0px 0px -12% 0px', threshold: 0.08 });
  items.forEach((el) => io.observe(el));
})();

/* -------------------------------------------------------- live figures */
(function live() {
  const kw = $('#liveKw');
  const today = $('#liveToday');
  const price = $('#livePrice');
  const meta = $('#priceMeta');
  const note = $('#liveNote');
  const statPlants = $('#statPlants');
  const statCap = $('#statCap');

  // Count up to a value instead of snapping — it reads as a live instrument.
  function countTo(el, value, digits = 0) {
    if (!el) return;
    const from = Number(el.dataset.v || 0);
    el.dataset.v = value;
    if (reduced) { el.textContent = faNum(value, digits); return; }
    const t0 = performance.now();
    const dur = 900;
    (function step(now) {
      const k = Math.min(1, (now - t0) / dur);
      const eased = 1 - Math.pow(1 - k, 3);
      el.textContent = faNum(from + (value - from) * eased, digits);
      if (k < 1) requestAnimationFrame(step);
    })(t0);
  }

  const demos = [];

  async function refresh() {
    const [prod, bourse] = await Promise.all([getProduction(), getBourse()]);

    countTo(kw, prod.power_kw, 0);
    countTo(today, prod.today_kwh, 0);
    if (statPlants) statPlants.textContent = faNum(prod.plants);
    if (statCap) statCap.textContent = faNum(1780);

    countTo(price, bourse.value, 0);
    if (meta) {
      const when = bourse.updatedAt.toLocaleDateString('fa-IR');
      meta.textContent = bourse.isDemo
        ? `نمونهٔ نمایشی — ${when}`
        : `${bourse.source} — ${when}`;
    }

    // Say it plainly, in the page, when a number is not real yet. A
    // placeholder that looks live is the kind of thing that gets quoted back
    // at you in a meeting as if it were a measurement.
    demos.length = 0;
    if (prod.isDemo) demos.push('تولید زنده');
    if (bourse.isDemo) demos.push('قیمت بورس');
    if (note) {
      if (demos.length) {
        note.hidden = false;
        note.textContent =
          `توجه: ${demos.join(' و ')} در این نسخه نمونهٔ نمایشی است و به منبع داده وصل نشده. `
          + 'پس از تعیین منبع، همین بخش بدون تغییر ظاهر به داده واقعی وصل می‌شود.';
      } else {
        note.hidden = true;
      }
    }
  }

  refresh();
  // Production moves; the exchange price does not move minute to minute.
  setInterval(refresh, 60000);
})();

/* --------------------------------------------------------- the estimator */
(function estimator() {
  const area = $('#area');
  const bill = $('#bill');
  if (!area || !bill) return;

  // Stated in the UI next to the result, so the arithmetic is auditable
  // rather than a black box that produces a flattering number.
  const M2_PER_KW = 7;         // متر مربع لازم برای هر کیلووات
  const KWH_PER_KW_YEAR = 1600; // تولید سالانه هر کیلووات در اقلیم ایران
  const PANEL_W = 610;         // توان هر پنل معمول امروز (وات)
  const RIAL_PER_KWH = 7200;   // مرتبهٔ بزرگی تعرفه، فقط برای برآورد پوشش

  const out = {
    area: $('#areaOut'), bill: $('#billOut'),
    kw: $('#outKw'), kwh: $('#outKwh'),
    cover: $('#outCover'), panels: $('#outPanels'),
  };

  function compute() {
    const m2 = Number(area.value);
    const millionToman = Number(bill.value);

    const kw = Math.max(1, Math.round(m2 / M2_PER_KW));
    const kwhYear = kw * KWH_PER_KW_YEAR;
    const panels = Math.max(1, Math.round((kw * 1000) / PANEL_W));

    // Monthly bill in Toman → rough annual kWh consumed.
    const consumedYear = (millionToman * 1e6 * 10 * 12) / RIAL_PER_KWH;
    const cover = consumedYear > 0 ? Math.min(999, Math.round((kwhYear / consumedYear) * 100)) : 0;

    out.area.textContent = `${faNum(m2)} متر مربع`;
    out.bill.textContent = `${faNum(millionToman)} میلیون تومان در ماه`;
    out.kw.textContent = faNum(kw);
    out.kwh.textContent = faNum(kwhYear);
    out.cover.textContent = faNum(cover);
    out.panels.textContent = faNum(panels);
  }

  area.addEventListener('input', compute);
  bill.addEventListener('input', compute);
  compute();
})();

/* ------------------------------------------------------------- trimmings */
const yr = document.getElementById('yr');
if (yr) yr.textContent = new Intl.DateTimeFormat('fa-IR', { year: 'numeric' }).format(new Date());
