/* Country → province → city lists for any form.
 *
 * Markup contract (no framework, no CDN):
 *   <script type="application/json" id="cities-data">{province: [cities]}</script>
 *   <select data-loc="country">          optional; Iran shows the lists
 *   <select data-loc="province">
 *   <select data-loc="city" name="city" data-selected="…">   used for Iran
 *   <input  data-loc="city-text" name="city">                 used abroad
 * Exactly one of the two `city` controls is enabled at a time, so the form
 * posts a single value. Wrappers marked [data-loc-iran] / [data-loc-abroad]
 * are shown or hidden with the country.
 */
(function () {
  'use strict';
  var IRAN = 'ایران';

  function init(form) {
    if (form.dataset.locInit) return;
    form.dataset.locInit = '1';
    var dataEl = document.getElementById('cities-data');
    var cities = {};
    try { cities = JSON.parse(dataEl ? dataEl.textContent : '{}'); } catch (e) { cities = {}; }

    var country = form.querySelector('[data-loc="country"]');
    var province = form.querySelector('[data-loc="province"]');
    var city = form.querySelector('[data-loc="city"]');
    var cityText = form.querySelector('[data-loc="city-text"]');
    if (!province || !city) return;

    function fillCities(selected) {
      var list = cities[province.value] || [];
      city.innerHTML = '';
      var first = document.createElement('option');
      first.value = '';
      first.textContent = province.value ? 'انتخاب شهر' : 'ابتدا استان را انتخاب کنید';
      city.appendChild(first);
      list.forEach(function (name) {
        var opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        if (name === selected) opt.selected = true;
        city.appendChild(opt);
      });
      // A saved city that is no longer in the list is kept, not silently lost.
      if (selected && list.indexOf(selected) === -1) {
        var keep = document.createElement('option');
        keep.value = selected; keep.textContent = selected; keep.selected = true;
        city.appendChild(keep);
      }
      city.disabled = !province.value && !(country && country.value !== IRAN);
    }

    function applyCountry() {
      var inIran = !country || country.value === IRAN;
      form.querySelectorAll('[data-loc-iran]').forEach(function (el) { el.hidden = !inIran; });
      form.querySelectorAll('[data-loc-abroad]').forEach(function (el) { el.hidden = inIran; });
      province.disabled = !inIran;
      if (cityText) cityText.disabled = inIran;
      if (inIran) { fillCities(city.getAttribute('data-selected') || ''); }
      else { city.disabled = true; }
    }

    province.addEventListener('change', function () {
      city.setAttribute('data-selected', '');
      fillCities('');
    });
    city.addEventListener('change', function () { city.setAttribute('data-selected', city.value); });
    if (country) country.addEventListener('change', applyCountry);
    applyCountry();
  }

  function boot() {
    document.querySelectorAll('form[data-location-form]').forEach(init);
  }
  // The admin panel swaps #panelContent over AJAX without running its
  // scripts; main.js calls this after every swap.
  window.LocationSelect = { boot: boot };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
