/*
 * limboAudit for Overleaf & arXiv -- floating toolbar pill + slide-over drawer.
 * Runs as an extension content script (isolated world) or inside the 1-click bookmarklet (page world).
 * Zero server upload: the buffer is scanned locally by LimboScanner and never leaves the tab.
 */
(function () {
  'use strict';
  var W = window;
  var D = document;
  if (W.__limboAuditUI) {
    W.__limboAuditUI.toggle(true);
    return;
  }
  var S = W.LimboScanner;
  if (!S) {
    return;
  }
  var IS_EXT = typeof chrome !== 'undefined' && !!(chrome && chrome.runtime && chrome.runtime.id);
  var IS_BOOKMARKLET = !IS_EXT;
  var HOST = String(W.location.hostname || '');
  var IS_OVERLEAF = /(^|\.)overleaf\.com$/.test(HOST);
  var IS_ARXIV = /(^|\.)arxiv\.org$/.test(HOST);
  var VENUE_KEY = 'limboVenue';

  var state = { venue: S.DEFAULT_VENUE, result: null, source: '', open: false, lastText: null };
  var els = {};

  if (typeof __LIMBO_CSS__ === 'string' && !D.getElementById('limbo-audit-style')) {
    var st = D.createElement('style');
    st.id = 'limbo-audit-style';
    st.textContent = __LIMBO_CSS__;
    (D.head || D.documentElement).appendChild(st);
  }

  function h(tag, attrs, kids) {
    var el = D.createElement(tag);
    var a = attrs || {};
    for (var k in a) {
      if (!Object.prototype.hasOwnProperty.call(a, k)) {
        continue;
      }
      if (k === 'text') {
        el.textContent = a[k];
      } else if (k === 'onclick') {
        el.addEventListener('click', a[k]);
      } else {
        el.setAttribute(k, a[k]);
      }
    }
    var list = kids || [];
    for (var i = 0; i < list.length; i++) {
      if (list[i]) {
        el.appendChild(typeof list[i] === 'string' ? D.createTextNode(list[i]) : list[i]);
      }
    }
    return el;
  }

  function loadVenue(cb) {
    if (IS_EXT && chrome.storage && chrome.storage.sync) {
      try {
        chrome.storage.sync.get(VENUE_KEY, function (v) {
          if (v && S.VENUES[v[VENUE_KEY]]) {
            state.venue = v[VENUE_KEY];
          }
          cb();
        });
        return;
      } catch (e) {
        cb();
        return;
      }
    }
    try {
      var lv = W.localStorage.getItem(VENUE_KEY);
      if (S.VENUES[lv]) {
        state.venue = lv;
      }
    } catch (e2) {
      // storage blocked: keep the default venue
    }
    cb();
  }

  function saveVenue(v) {
    state.venue = v;
    var o = {};
    o[VENUE_KEY] = v;
    try {
      if (IS_EXT && chrome.storage && chrome.storage.sync) {
        chrome.storage.sync.set(o);
      } else {
        W.localStorage.setItem(VENUE_KEY, v);
      }
    } catch (e) {
      // storage blocked: the choice lasts for this page only
    }
  }

  function askBridge() {
    if (typeof W.__limboReadEditor === 'function') {
      return Promise.resolve(W.__limboReadEditor());
    }
    return new Promise(function (resolve) {
      var id = 'limbo-' + Math.random().toString(36).slice(2);
      var done = false;
      function onMsg(ev) {
        if (ev.source !== W || !ev.data || ev.data.__limbo !== 'res' || ev.data.id !== id) {
          return;
        }
        done = true;
        W.removeEventListener('message', onMsg);
        resolve(ev.data.payload || null);
      }
      W.addEventListener('message', onMsg);
      W.postMessage({ __limbo: 'req', id: id }, W.location.origin);
      setTimeout(function () {
        if (!done) {
          W.removeEventListener('message', onMsg);
          resolve(null);
        }
      }, 400);
    });
  }

  function domLines(selector) {
    var nodes = D.querySelectorAll(selector);
    var out = [];
    for (var i = 0; i < nodes.length; i++) {
      out.push(nodes[i].textContent);
    }
    return out;
  }

  function firstVisibleLineNumber() {
    var g = D.querySelectorAll('.cm-lineNumbers .cm-gutterElement');
    for (var i = 0; i < g.length; i++) {
      var n = parseInt(g[i].textContent, 10);
      if (n > 0) {
        return n;
      }
    }
    return 1;
  }

  function readBuffer() {
    return askBridge().then(function (ed) {
      var domSel = '';
      try {
        domSel = String(W.getSelection ? W.getSelection().toString() : '');
      } catch (e) {
        domSel = '';
      }
      if (ed && ed.text !== undefined && ed.text !== null) {
        var name = ed.fileName ? ' \u00B7 ' + ed.fileName : '';
        if (ed.selection && ed.selection.trim().length > 0) {
          return { text: ed.selection, lineOffset: (ed.selectionLine || 1) - 1, source: 'Selected text (' + ed.source + ')' + name, kind: kindFromName(ed.fileName) };
        }
        return { text: ed.text, lineOffset: 0, source: 'Full buffer (' + ed.source + ')' + name, kind: kindFromName(ed.fileName) };
      }
      if (domSel.trim().length > 20) {
        return { text: domSel, lineOffset: 0, source: 'Selected text', kind: null };
      }
      var cm = domLines('.cm-content .cm-line');
      if (cm.length) {
        return { text: cm.join('\n'), lineOffset: firstVisibleLineNumber() - 1, source: 'Visible editor lines (CodeMirror)', kind: null };
      }
      var mo = domLines('.monaco-editor .view-line');
      if (mo.length) {
        return { text: mo.join('\n'), lineOffset: 0, source: 'Visible editor lines (Monaco)', kind: null };
      }
      var ace = domLines('.ace_editor .ace_line');
      if (ace.length) {
        return { text: ace.join('\n'), lineOffset: 0, source: 'Visible editor lines (Ace)', kind: null };
      }
      if (IS_ARXIV) {
        var abs = D.querySelector('blockquote.abstract');
        if (abs) {
          var body = String(abs.textContent || '').replace(/^\s*Abstract:\s*/i, '');
          return { text: '\\begin{abstract}\n' + body + '\n\\end{abstract}', lineOffset: 0, source: 'arXiv abstract', kind: 'tex' };
        }
        var pre = D.querySelector('pre');
        if (pre) {
          return { text: pre.textContent, lineOffset: 0, source: 'arXiv source view', kind: null };
        }
      }
      var ta = D.activeElement && D.activeElement.tagName === 'TEXTAREA' ? D.activeElement.value : '';
      if (ta) {
        return { text: ta, lineOffset: 0, source: 'Focused text area', kind: null };
      }
      return { text: '', lineOffset: 0, source: 'No editor buffer found (open a .tex/.bib file or select text)', kind: null };
    });
  }

  function kindFromName(name) {
    if (/\.bib$/i.test(name || '')) {
      return 'bib';
    }
    if (/\.(tex|ltx|sty|cls)$/i.test(name || '')) {
      return 'tex';
    }
    return null;
  }

  function runScan(force) {
    return readBuffer().then(function (buf) {
      var key = state.venue + '|' + buf.lineOffset + '|' + buf.text;
      if (!force && state.result && key === state.lastText) {
        return state.result;
      }
      state.lastText = key;
      state.source = buf.source;
      state.result = S.scan(buf.text, { venue: state.venue, lineOffset: buf.lineOffset, kind: buf.kind || undefined });
      render();
      return state.result;
    });
  }

  function copyText(text) {
    function fallback() {
      var ta = h('textarea', { 'aria-hidden': 'true', style: 'position:fixed;left:-9999px;top:0;' });
      ta.value = text;
      D.body.appendChild(ta);
      ta.select();
      var ok = false;
      try {
        ok = D.execCommand('copy');
      } catch (e) {
        ok = false;
      }
      ta.remove();
      return ok;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(function () {
        return true;
      }, function () {
        return fallback();
      });
    }
    return Promise.resolve(fallback());
  }

  function toast(msg) {
    var t = h('div', { id: 'limbo-audit-toast', role: 'status', text: msg });
    var old = D.getElementById('limbo-audit-toast');
    if (old) {
      old.remove();
    }
    D.body.appendChild(t);
    setTimeout(function () {
      t.remove();
    }, 2600);
  }

  function openUrl(url) {
    W.open(url, '_blank', 'noopener');
  }

  function gotoLine(line) {
    if (typeof W.__limboGotoLine === 'function') {
      W.__limboGotoLine(line);
    } else {
      W.postMessage({ __limbo: 'goto', line: line }, W.location.origin);
    }
  }

  function buildPill() {
    var pill = h('button', { id: 'limbo-audit-pill', type: 'button', title: 'limboAudit: 100% client-side manuscript check', 'aria-haspopup': 'dialog', 'aria-expanded': 'false' }, [
      h('span', { 'class': 'limbo-pill-icon', 'aria-hidden': 'true', text: '\uD83D\uDEE1\uFE0F' }),
      h('span', { 'class': 'limbo-pill-label', text: 'limboAudit: \u2026/100' })
    ]);
    pill.addEventListener('click', function () {
      toggle();
    });
    els.pill = pill;
    els.pillLabel = pill.querySelector('.limbo-pill-label');
    placePill();
  }

  var TOOLBAR_SELECTORS = [
    '.ide-redesign-toolbar-actions',
    '.toolbar-header .toolbar-right',
    'header.toolbar .toolbar-right',
    '.toolbar.toolbar-header .toolbar-right',
    '.toolbar-right'
  ];

  function placePill() {
    var pill = els.pill;
    if (!pill) {
      return;
    }
    var target = null;
    if (IS_OVERLEAF) {
      for (var i = 0; i < TOOLBAR_SELECTORS.length && !target; i++) {
        target = D.querySelector(TOOLBAR_SELECTORS[i]);
      }
    }
    if (target) {
      pill.classList.remove('limbo-floating');
      if (pill.parentNode !== target) {
        target.insertBefore(pill, target.firstChild);
      }
    } else {
      pill.classList.add('limbo-floating');
      if (pill.parentNode !== D.body) {
        D.body.appendChild(pill);
      }
    }
  }

  function buildDrawer() {
    var venueSel = h('select', { id: 'limbo-venue', 'aria-label': 'Target venue' });
    for (var vk in S.VENUES) {
      if (Object.prototype.hasOwnProperty.call(S.VENUES, vk)) {
        venueSel.appendChild(h('option', { value: vk, text: vk + ' \u00B7 ' + S.VENUES[vk].abstractWords + 'w abstract' }));
      }
    }
    venueSel.addEventListener('change', function () {
      saveVenue(venueSel.value);
      runScan(true);
    });
    var closeBtn = h('button', { 'class': 'limbo-close', type: 'button', 'aria-label': 'Close limboAudit', text: '\u00D7', onclick: function () {
      toggle(false);
    } });
    var rescan = h('button', { 'class': 'limbo-link', type: 'button', text: '\u21BB Re-scan', onclick: function () {
      runScan(true);
    } });
    var drawer = h('aside', { id: 'limbo-audit-drawer', role: 'dialog', 'aria-label': 'limboAudit findings', 'aria-hidden': 'true' }, [
      h('div', { 'class': 'limbo-head' }, [
        h('div', { 'class': 'limbo-brand' }, [
          h('div', { 'class': 'limbo-eyebrow', text: 'AveryCorp \u00B7 limboAudit' }),
          h('div', { 'class': 'limbo-title', text: 'Pre-Submission Check' })
        ]),
        closeBtn
      ]),
      h('div', { 'class': 'limbo-scorebar' }, [
        h('div', { 'class': 'limbo-score', id: 'limbo-score', text: '\u2026' }),
        h('div', { 'class': 'limbo-scoremeta' }, [
          h('div', { id: 'limbo-counts', 'class': 'limbo-counts' }),
          h('div', { id: 'limbo-source', 'class': 'limbo-source' })
        ])
      ]),
      h('div', { 'class': 'limbo-controls' }, [h('label', { 'for': 'limbo-venue', text: 'Target venue' }), venueSel, rescan]),
      h('div', { id: 'limbo-wordcount', 'class': 'limbo-wordcount' }),
      h('div', { id: 'limbo-findings', 'class': 'limbo-findings' }),
      h('div', { 'class': 'limbo-ctas' }, [
        h('button', { type: 'button', 'class': 'limbo-cta limbo-cta-gold', id: 'limbo-cta-fix', text: S.CTA.fixPack.label, onclick: function () {
          openUrl(S.CTA.fixPack.url);
        } }),
        h('button', { type: 'button', 'class': 'limbo-cta', id: 'limbo-cta-audit', text: S.CTA.executiveAudit.label, onclick: function () {
          openUrl(S.CTA.executiveAudit.url);
        } }),
        h('button', { type: 'button', 'class': 'limbo-cta limbo-cta-ghost', id: 'limbo-cta-memo', text: S.CTA.piMemo.label, onclick: function () {
          copyText(S.buildPiMemo(state.result, { venue: S.VENUES[state.venue].label })).then(function (ok) {
            toast(ok ? 'PI memo copied to clipboard' : 'Copy blocked by the browser: select and copy manually');
          });
        } })
      ]),
      h('div', { 'class': 'limbo-foot', id: 'limbo-foot', text: '100% client-side \u00B7 zero upload \u00B7 zero LLM training' })
    ]);
    els.drawer = drawer;
    els.venue = venueSel;
    D.body.appendChild(drawer);
    D.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape' && state.open) {
        toggle(false);
      }
    });
  }

  function render() {
    var r = state.result;
    if (!r) {
      return;
    }
    if (els.pillLabel) {
      els.pillLabel.textContent = 'limboAudit: ' + r.score + '/100';
      els.pill.setAttribute('data-grade', r.grade);
    }
    if (!els.drawer) {
      return;
    }
    els.venue.value = state.venue;
    var scoreEl = D.getElementById('limbo-score');
    scoreEl.textContent = String(r.score);
    scoreEl.setAttribute('data-grade', r.grade);
    D.getElementById('limbo-counts').textContent = r.counts.high + ' high \u00B7 ' + r.counts.medium + ' medium \u00B7 ' + r.counts.low + ' low';
    D.getElementById('limbo-source').textContent = state.source + ' \u00B7 ' + r.kind.toUpperCase() + ' \u00B7 ' + r.lines + ' lines';
    D.getElementById('limbo-foot').textContent = '100% client-side \u00B7 zero upload \u00B7 zero LLM training \u00B7 scanned in ' + r.elapsedMs + ' ms';

    var wc = D.getElementById('limbo-wordcount');
    wc.textContent = '';
    if (r.wordCount) {
      var chips = [];
      for (var vk in r.wordCount.venues) {
        if (Object.prototype.hasOwnProperty.call(r.wordCount.venues, vk)) {
          var v = r.wordCount.venues[vk];
          chips.push(h('span', { 'class': 'limbo-chip' + (v.over ? ' limbo-chip-over' : '') + (vk === r.venue ? ' limbo-chip-target' : ''), text: vk + ' ' + v.limit + 'w ' + (v.over ? '\u2716' : '\u2714') }));
        }
      }
      wc.appendChild(h('div', { 'class': 'limbo-wc-row' }, [h('strong', { text: 'Abstract: ' + r.wordCount.words + ' words' })].concat(chips)));
    }

    var list = D.getElementById('limbo-findings');
    list.textContent = '';
    if (!r.findings.length) {
      list.appendChild(h('div', { 'class': 'limbo-empty', text: r.lines > 1 || r.bibEntries ? 'No findings in this buffer. Clean bill of health.' : 'Open a .tex or .bib file (or select text) to scan it.' }));
      return;
    }
    for (var cat in S.CATEGORIES) {
      if (!Object.prototype.hasOwnProperty.call(S.CATEGORIES, cat)) {
        continue;
      }
      var items = [];
      for (var i = 0; i < r.findings.length; i++) {
        if (r.findings[i].category === cat) {
          items.push(r.findings[i]);
        }
      }
      if (!items.length) {
        continue;
      }
      list.appendChild(h('div', { 'class': 'limbo-cat', text: S.CATEGORIES[cat] + ' (' + items.length + ')' }));
      for (var j = 0; j < items.length; j++) {
        list.appendChild(findingRow(items[j]));
      }
    }
  }

  function findingRow(f) {
    return h('button', { type: 'button', 'class': 'limbo-finding limbo-sev-' + f.severity, title: 'Jump to line ' + f.line, onclick: function () {
      gotoLine(f.line);
    } }, [
      h('span', { 'class': 'limbo-line', text: 'L' + f.line }),
      h('span', { 'class': 'limbo-msg' }, [
        h('span', { 'class': 'limbo-sev', text: f.severity }),
        ' ' + f.message,
        h('code', { text: f.snippet })
      ])
    ]);
  }

  function toggle(force) {
    if (!els.drawer) {
      buildDrawer();
    }
    state.open = typeof force === 'boolean' ? force : !state.open;
    els.drawer.classList.toggle('limbo-open', state.open);
    els.drawer.setAttribute('aria-hidden', state.open ? 'false' : 'true');
    if (els.pill) {
      els.pill.setAttribute('aria-expanded', state.open ? 'true' : 'false');
    }
    if (state.open) {
      runScan(true);
    }
  }

  var debounceTimer = null;
  function scheduleScan() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(function () {
      runScan(false);
    }, 700);
  }

  W.__limboAuditUI = {
    toggle: toggle,
    scan: function () {
      return runScan(true);
    },
    state: state
  };

  if (IS_EXT) {
    chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
      if (!msg || typeof msg.type !== 'string') {
        return false;
      }
      if (msg.type === 'limbo:scan') {
        if (msg.venue && S.VENUES[msg.venue]) {
          state.venue = msg.venue;
        }
        runScan(true).then(function (r) {
          sendResponse({ ok: true, result: r, source: state.source });
        });
        return true;
      }
      if (msg.type === 'limbo:open') {
        toggle(true);
        sendResponse({ ok: true });
        return false;
      }
      return false;
    });
  }

  loadVenue(function () {
    buildPill();
    if (IS_BOOKMARKLET) {
      toggle(true);
    } else {
      runScan(true);
    }
    D.addEventListener('keyup', scheduleScan, true);
    D.addEventListener('mouseup', scheduleScan, true);
    setInterval(function () {
      placePill();
      if (!D.hidden && IS_OVERLEAF) {
        runScan(false);
      }
    }, 4000);
  });
})();
