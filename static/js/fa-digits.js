// Show numbers in Persian digits everywhere on the page, so a screen never mixes
// "3101.5" with "۱۴۰۵/۰۸/۲۶". Only the displayed text changes: inputs, code,
// scripts, charts and anything marked data-latin keep their own digits, and so
// does any word containing Latin letters (serials like A3F125L9066059, "kW").
(() => {
  const FA = '۰۱۲۳۴۵۶۷۸۹';
  const SKIP = 'SCRIPT,STYLE,TEXTAREA,INPUT,SELECT,OPTION,CODE,PRE,KBD,SAMP,SVG,CANVAS,NOSCRIPT';
  const skipTags = new Set(SKIP.split(','));
  const token = /[0-9A-Za-z][0-9A-Za-z._\-\/:,]*/g;

  const convert = (text) => text.replace(token, (word) => {
    if (/[A-Za-z@]/.test(word)) return word;
    return word.replace(/(\d)\.(\d)/g, '$1٫$2').replace(/\d/g, (d) => FA[d]);
  });

  const skipped = (el) => {
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      if (skipTags.has(n.tagName) || n.isContentEditable || n.hasAttribute('data-latin')
          || n.classList.contains('leaflet-control-attribution')) return true;
    }
    return false;
  };

  const walk = (root) => {
    if (!root || (root.nodeType === 1 && skipped(root))) return;
    if (root.nodeType === 3) {
      if (/\d/.test(root.nodeValue) && !skipped(root.parentElement)) {
        const next = convert(root.nodeValue);
        if (next !== root.nodeValue) root.nodeValue = next;
      }
      return;
    }
    const it = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => (/\d/.test(n.nodeValue) && !skipped(n.parentElement)
        ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT),
    });
    const nodes = [];
    while (it.nextNode()) nodes.push(it.currentNode);
    nodes.forEach((n) => { const v = convert(n.nodeValue); if (v !== n.nodeValue) n.nodeValue = v; });
  };

  const start = () => {
    walk(document.body);
    // Panels swapped in by AJAX navigation and live-updated numbers.
    new MutationObserver((records) => records.forEach((r) => {
      if (r.type === 'characterData') walk(r.target);
      r.addedNodes.forEach(walk);
    })).observe(document.body, { childList: true, subtree: true, characterData: true });
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
