// Proposal builder form (reports/proposal/): live hints, AJAX submit, in-page preview.
// Everything is delegated from document: panel navigation swaps #panelContent
// without running page scripts, so nothing here may depend on a page load.
(() => {
  const FA = '۰۱۲۳۴۵۶۷۸۹';
  const AR = '٠١٢٣٤٥٦٧٨٩';
  const num = (s) => parseFloat(String(s)
    .replace(/[۰-۹]/g, (d) => FA.indexOf(d)).replace(/[٠-٩]/g, (d) => AR.indexOf(d))
    .replace(/٫/g, '.').replace(/[٬,\s]/g, ''));
  const fa = (n, digits = 0) => n.toLocaleString('fa-IR', { maximumFractionDigits: digits });
  const toman = (rial) => {
    const t = rial / 10;
    if (t >= 1e9) return fa(t / 1e9, 2) + ' میلیارد تومان';
    if (t >= 1e6) return fa(t / 1e6, 2) + ' میلیون تومان';
    return fa(t) + ' تومان';
  };
  const formOf = (el) => (el && el.closest ? el.closest('form[data-proposal-form]') : null);

  function refresh(form) {
    const months = [...form.querySelectorAll('[data-pf-month]')];
    const vals = months.map((i) => num(i.value));
    const max = Math.max(0, ...vals.filter((v) => v > 0));
    months.forEach((input, k) => {
      const bar = input.closest('.pf-m').querySelector('i');
      bar.style.height = (vals[k] > 0 ? Math.max(6, (vals[k] / max) * 100) : 0) + '%';
    });
    form.elements.monthly.value = vals.map((v) => (Number.isFinite(v) ? v : '')).join(',');

    const mwh = num(form.elements.mwh.value);
    const sum = vals.reduce((a, v) => a + (v > 0 ? v : 0), 0);
    const sumEl = form.querySelector('[data-pf-sum]');
    sumEl.hidden = !sum;
    const off = mwh > 0 && Math.abs(sum - mwh) / mwh > 0.02;
    sumEl.classList.toggle('warn', off);
    sumEl.textContent = 'جمع ۱۲ ماه: ' + fa(sum, 1) + ' MWh' + (off ? ' — با تولید سالانه (' + fa(mwh, 1) + ') نمی‌خواند' : '');

    form.querySelectorAll('[data-pf-money]').forEach((box) => {
      const hint = box.parentElement.querySelector('.pf-hint');
      const v = num(box.querySelector('input').value);
      hint.classList.toggle('live', v > 0);
      hint.textContent = v > 0 ? fa(v) + ' ریال ≈ ' + toman(v) : '';
    });

    const rate = num(form.elements.rate.value);
    const value = mwh > 0 && rate > 0 ? Math.round(mwh * 1000) * rate : 0;
    form.querySelector('[data-pf-value]').textContent = value ? fa(value) + ' ریال ≈ ' + toman(value) : '—';
  }

  function showErrors(form, errors) {
    form.querySelectorAll('[data-err]').forEach((el) => {
      const msgs = errors[el.dataset.err];
      el.textContent = msgs ? msgs.join(' ') : '';
      el.closest('.pf-f').classList.toggle('bad', !!msgs);
    });
    const alert = form.querySelector('[data-pf-alert]');
    const general = errors.__all__ ? errors.__all__.join(' ') : '';
    alert.textContent = general;
    alert.hidden = !general;
    const first = form.querySelector('.pf-f.bad') || (general && alert);
    if (first) first.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  function closeView() {
    const view = document.querySelector('[data-pf-view]');
    if (!view || view.hidden) return;
    view.hidden = true;
    document.body.style.overflow = '';
  }

  document.addEventListener('input', (e) => { const form = formOf(e.target); if (form) refresh(form); });

  document.addEventListener('change', (e) => {
    const drop = e.target.closest && e.target.closest('.pf-drop');
    if (!drop || e.target.type !== 'file') return;
    const file = e.target.files[0];
    const img = drop.querySelector('img');
    drop.classList.toggle('has', !!file);
    img.hidden = !file;
    drop.querySelector('.pf-drop-t').lastChild.textContent = file ? 'تغییر تصویر' : 'انتخاب تصویر یا رها کردن در این‌جا';
    if (file) img.src = URL.createObjectURL(file);
  });

  // Capture phase + preventDefault: main.js's "one tap, one submission" lock
  // only unlocks on a page load, which an AJAX submit never causes.
  document.addEventListener('submit', async (e) => {
    const form = formOf(e.target);
    if (!form) return;
    e.preventDefault();
    if (form.dataset.busy) return;
    refresh(form);
    form.dataset.busy = '1';
    showErrors(form, {});
    try {
      const response = await fetch(form.action, {
        method: 'POST', body: new FormData(form), headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });
      // Session expired: the server answered with the login page.
      if (response.redirected) { window.location.href = response.url; return; }
      if (response.status === 400) {
        showErrors(form, (await response.json()).errors);
      } else if (response.ok) {
        const view = document.querySelector('[data-pf-view]');
        view.querySelector('iframe').srcdoc = await response.text();
        view.hidden = false;
        document.body.style.overflow = 'hidden';
      } else {
        throw new Error('HTTP ' + response.status);
      }
    } catch (error) {
      console.error(error);
      showErrors(form, { __all__: ['ارسال نشد. اتصال اینترنت را بررسی کنید و دوباره «ساخت پیشنهاد» را بزنید.'] });
    } finally {
      delete form.dataset.busy;
    }
  }, true);

  document.addEventListener('click', (e) => {
    if (!e.target.closest) return;
    if (e.target.closest('[data-pf-close]')) closeView();
    if (e.target.closest('[data-pf-print]')) {
      const frame = document.querySelector('[data-pf-view] iframe');
      frame.contentWindow.focus();
      frame.contentWindow.print();
    }
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeView(); });
})();
