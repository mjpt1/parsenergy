/* AI helpers: panel buttons ([data-ai-task]) and the customer chat bubble.
 * Delegated listeners, so buttons in pages loaded by the ajax router work too. */
(function () {
  'use strict';

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    var input = document.querySelector('input[name=csrfmiddlewaretoken]');
    return input ? input.value : '';
  }

  // ---- panel tasks -------------------------------------------------------
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-ai-task]');
    if (!btn) return;
    e.preventDefault();
    var box = btn.closest('[data-ai-box]') || btn.parentNode;
    var out = box.querySelector('[data-ai-output]');
    var fill = btn.getAttribute('data-ai-fill');
    var label = btn.textContent;
    btn.disabled = true;
    btn.textContent = '… در حال تحلیل';
    if (out) { out.hidden = false; out.textContent = 'چند ثانیه صبر کنید…'; }
    var body = new FormData();
    body.append('task', btn.getAttribute('data-ai-task'));
    body.append('target', btn.getAttribute('data-ai-target') || '');
    fetch('/analytics/ai/task/', {
      method: 'POST', body: body, credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' }
    }).then(function (r) { return r.json(); }).then(function (data) {
      if (data.error) { if (out) out.textContent = data.error; return; }
      if (fill) {
        var target = document.querySelector(fill);
        if (target) { target.value = data.text; target.focus(); }
        if (out) out.textContent = 'پیش‌نویس در کادر پاسخ قرار گرفت (' + data.provider + '). قبل از ارسال بخوانید.';
      } else if (out) {
        out.textContent = data.text + '\n\n— ' + data.provider;
      }
    }).catch(function () {
      if (out) out.textContent = 'ارتباط برقرار نشد. دوباره تلاش کنید.';
    }).finally(function () { btn.disabled = false; btn.textContent = label; });
  });

  // ---- customer chat -----------------------------------------------------
  var root = document.getElementById('ai-chat');
  if (!root) return;
  var history = [];
  var panel = root.querySelector('.aic-panel');
  var log = root.querySelector('.aic-log');
  var form = root.querySelector('form');
  var input = form.querySelector('input');

  root.querySelector('.aic-toggle').addEventListener('click', function () {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) input.focus();
  });

  function add(role, text) {
    var p = document.createElement('div');
    p.className = 'aic-msg ' + role;
    p.textContent = text;
    log.appendChild(p);
    log.scrollTop = log.scrollHeight;
    return p;
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text) return;
    input.value = '';
    add('user', text);
    history.push({ role: 'user', content: text });
    var wait = add('assistant', '…');
    fetch('/analytics/ai/chat/', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
      body: JSON.stringify({ messages: history.slice(-6) })
    }).then(function (r) { return r.json(); }).then(function (data) {
      var answer = data.text || data.error || 'پاسخی دریافت نشد.';
      wait.textContent = answer;
      if (data.text) history.push({ role: 'assistant', content: data.text });
    }).catch(function () { wait.textContent = 'ارتباط برقرار نشد.'; });
  });
})();
