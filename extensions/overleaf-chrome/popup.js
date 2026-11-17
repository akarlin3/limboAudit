/* limboAudit popup: talks only to the active tab's content script and chrome.storage. */
(function () {
  'use strict';
  var S = window.LimboScanner;
  var VENUE_KEY = 'limboVenue';
  var state = { venue: S.DEFAULT_VENUE, result: null, tabId: null };

  function $(id) {
    return document.getElementById(id);
  }

  function showResult(r, source) {
    state.result = r;
    var score = $('score');
    score.textContent = String(r.score);
    score.className = 'score' + (r.score < 60 ? ' bad' : '');
    $('summary').textContent = r.counts.high + ' high · ' + r.counts.medium + ' medium · ' + r.counts.low + ' low';
    $('source').textContent = (source || '') + ' · ' + r.elapsedMs + ' ms';
  }

  function listFindings(r) {
    var ul = $('findings');
    ul.textContent = '';
    var max = Math.min(r.findings.length, 12);
    for (var i = 0; i < max; i++) {
      var f = r.findings[i];
      var li = document.createElement('li');
      li.className = f.severity;
      var ln = document.createElement('span');
      ln.className = 'ln';
      ln.textContent = 'L' + f.line;
      li.appendChild(ln);
      li.appendChild(document.createTextNode(f.message));
      ul.appendChild(li);
    }
    if (!r.findings.length) {
      var ok = document.createElement('li');
      ok.textContent = 'No findings. Clean bill of health.';
      ul.appendChild(ok);
    }
  }

  function injectAndRetry(tabId) {
    if (!chrome.scripting) {
      return Promise.reject(new Error('scripting unavailable'));
    }
    return chrome.scripting.executeScript({ target: { tabId: tabId }, files: ['bridge.js'], world: 'MAIN' })
      .catch(function () {
        return null;
      })
      .then(function () {
        return chrome.scripting.insertCSS({ target: { tabId: tabId }, files: ['styles.css'] });
      })
      .then(function () {
        return chrome.scripting.executeScript({ target: { tabId: tabId }, files: ['scanner.js', 'content.js'] });
      })
      .then(function () {
        return chrome.tabs.sendMessage(tabId, { type: 'limbo:scan', venue: state.venue });
      });
  }

  function scanTab() {
    chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
      var tab = tabs && tabs[0];
      if (!tab) {
        return;
      }
      state.tabId = tab.id;
      chrome.tabs.sendMessage(tab.id, { type: 'limbo:scan', venue: state.venue })
        .catch(function () {
          return injectAndRetry(tab.id);
        })
        .then(function (resp) {
          if (resp && resp.ok) {
            showResult(resp.result, resp.source);
          } else {
            throw new Error('no response');
          }
        })
        .catch(function () {
          $('score').textContent = '—';
          $('summary').textContent = 'Open an Overleaf project or arXiv page, or paste text below.';
          $('source').textContent = '';
        });
    });
  }

  function copyMemo() {
    var text = S.buildPiMemo(state.result, { venue: S.VENUES[state.venue].label });
    navigator.clipboard.writeText(text).then(function () {
      $('memo-status').textContent = 'PI memo copied to clipboard.';
    }, function () {
      $('memo-status').textContent = 'Clipboard blocked: paste box filled instead.';
      $('paste').value = text;
    });
  }

  function init() {
    var sel = $('venue');
    for (var vk in S.VENUES) {
      if (Object.prototype.hasOwnProperty.call(S.VENUES, vk)) {
        var o = document.createElement('option');
        o.value = vk;
        o.textContent = S.VENUES[vk].label + ' · ' + S.VENUES[vk].abstractWords + ' words';
        sel.appendChild(o);
      }
    }
    $('cta-fix').textContent = S.CTA.fixPack.label;
    $('cta-audit').textContent = S.CTA.executiveAudit.label;
    $('cta-memo').textContent = S.CTA.piMemo.label;
    $('cta-fix').addEventListener('click', function () {
      chrome.tabs.create({ url: S.CTA.fixPack.url });
    });
    $('cta-audit').addEventListener('click', function () {
      chrome.tabs.create({ url: S.CTA.executiveAudit.url });
    });
    $('cta-memo').addEventListener('click', copyMemo);
    $('open-drawer').addEventListener('click', function () {
      if (state.tabId !== null) {
        chrome.tabs.sendMessage(state.tabId, { type: 'limbo:open' }).then(function () {
          window.close();
        }, function () {
          $('summary').textContent = 'The drawer is available on Overleaf and arXiv pages.';
        });
      }
    });
    $('scan-paste').addEventListener('click', function () {
      var r = S.scan($('paste').value, { venue: state.venue });
      showResult(r, 'Pasted text');
      listFindings(r);
    });
    sel.addEventListener('change', function () {
      state.venue = sel.value;
      var o2 = {};
      o2[VENUE_KEY] = sel.value;
      chrome.storage.sync.set(o2);
      scanTab();
    });
    chrome.storage.sync.get(VENUE_KEY, function (v) {
      if (v && S.VENUES[v[VENUE_KEY]]) {
        state.venue = v[VENUE_KEY];
      }
      sel.value = state.venue;
      scanTab();
    });
  }

  document.addEventListener('DOMContentLoaded', init);
})();
