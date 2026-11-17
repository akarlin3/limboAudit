/*
 * limboAudit for Overleaf & arXiv -- deterministic client-side scanner.
 * 100% client-side: no network calls, no uploads, no LLM, no telemetry.
 * Shared by content.js, popup.js, the 1-click bookmarklet, and the Node test harness.
 * Style rule: every statement ends in an explicit semicolon and comments sit on
 * their own lines, so the bookmarklet minifier can safely strip them.
 */
(function (root) {
  'use strict';

  var VERSION = '1.0.0';

  var SERVICES_URL = 'https://averycorp.org/services.html';
  var CTA = {
    fixPack: {
      label: '\u26A1 Instant Auto-Fix Macro & BibTeX Pack ($19)',
      url: SERVICES_URL + '?from=overleaf#diagnostic-dropzone'
    },
    executiveAudit: {
      label: '\uD83C\uDFDB\uFE0F Full 48h Executive Audit & Referee #2 Dossier ($650)',
      url: SERVICES_URL + '?tier=1a&from=overleaf'
    },
    piMemo: {
      label: '\uD83D\uDCE7 Copy P-Card Quote + NIH DMS Memo for My PI'
    }
  };

  var VENUES = {
    MRM: { label: 'Magnetic Resonance in Medicine (MRM)', abstractWords: 250 },
    Nature: { label: 'Nature', abstractWords: 150 },
    PLOS: { label: 'PLOS ONE', abstractWords: 300 }
  };
  var DEFAULT_VENUE = 'MRM';

  var SEVERITY_WEIGHTS = { high: 10, medium: 3, low: 1 };

  var CATEGORIES = {
    numbers: 'Untraced Numbers & Fragile Stats',
    citations: 'Citation & DOI Hygiene',
    leaks: 'Figure/Table & Anonymization Leaks',
    wordcount: 'Target-Venue Word Count'
  };

  var SP = '(?:\\s|\\\\[,;:! ]|~|\\$)*';
  var P_RE = new RegExp('(^|[^A-Za-z\\\\])[pP]' + SP + '(=|<|>|\\\\leq?|\\\\geq?|\\\\lt|\\\\gt|\\u2264|\\u2265)' + SP + '(0?\\.\\d+)', 'g');
  var R_RE = new RegExp('(^|[^A-Za-z\\\\])r' + SP + '(?:\\(\\s*\\d+\\s*\\))?' + SP + '=' + SP + '(-|\\u2212)?(0?\\.\\d+|1\\.0+)\\b', 'g');
  var N_RE = new RegExp('(^|[^A-Za-z\\\\])([Nn])' + SP + '=' + SP + '(\\d[\\d,]*)', 'g');
  var PM_RE = new RegExp('(\\d+(?:\\.\\d+)?)' + SP + '(\\u00B1|\\\\pm\\b|\\+/-)' + SP + '(\\d+(?:\\.\\d+)?)', 'g');
  var PCT_RE = new RegExp('(\\d+(?:\\.\\d+)?)' + SP + '(\\\\%|\\\\percent\\b)', 'g');
  var MEAN_RE = /(?:^|[^A-Za-z\\])(?:M|mean|Mean|average|Average)\s*(?:=|of|was|is|:)?\s*\$?\s*(\d+\.\d{1,2})(?!\d)/g;
  var MACRO_DEF_RE = /\\(?:newcommand|renewcommand|providecommand|DeclareRobustCommand|def|pgfmathsetmacro|SI|num)\b/;
  var CITE_RE = /\\(?:no)?cite[a-zA-Z]*\*?(?:\[[^\]]*\]){0,2}\{([^}]*)\}/g;
  var REF_RE = /\\(?:ref|eqref|cref|Cref|autoref|pageref|vref|subref)\*?\{([^}]*)\}/g;
  var LABEL_RE = /\\label\{([^}]+)\}/g;
  var PATH_RE = /(\/Users\/[^\s\/{}]+|\/home\/[^\s\/{}]+|[A-Za-z]:\\{1,2}Users\\{1,2}[^\s\\{}]+|\/Volumes\/[^\s\/{}]+|\/mnt\/[^\s\/{}]+)/;
  var SEED_RE = /\bseed(?:s|ed)?\b/i;
  var RANDOM_RE = /\brandom(?:ly)?\s+(?:split|shuffled|initiali[sz]ed|sampled|permuted|selected|partitioned)\b/i;
  var DOI_TYPES = { article: 1, inproceedings: 1, incollection: 1, conference: 1, book: 1, inbook: 1 };
  var PREPRINT_RE = /arxiv|biorxiv|medrxiv|chemrxiv|ssrn|research\s*square|10\.48550|10\.1101\//i;

  function now() {
    if (typeof performance !== 'undefined' && performance && typeof performance.now === 'function') {
      return performance.now();
    }
    return Date.now();
  }

  function maskComment(line) {
    for (var i = 0; i < line.length; i++) {
      if (line.charAt(i) === '%') {
        var bs = 0;
        var j = i - 1;
        while (j >= 0 && line.charAt(j) === '\\') {
          bs++;
          j--;
        }
        if (bs % 2 === 0) {
          return line.slice(0, i);
        }
      }
    }
    return line;
  }

  function clip(s) {
    s = String(s).replace(/\s+/g, ' ').trim();
    return s.length > 110 ? s.slice(0, 107) + '...' : s;
  }

  function detectKind(text) {
    var hasEntries = /^\s*@[A-Za-z]+\s*[{(]\s*[^,\s]+\s*,/m.test(text);
    var hasTex = /\\(?:begin\{document\}|documentclass|section|cite|begin\{abstract\}|input|include)\b/.test(text);
    if (hasEntries && !hasTex) {
      return 'bib';
    }
    return 'tex';
  }

  function grimConsistent(meanStr, n) {
    var decimals = meanStr.split('.')[1].length;
    var mean = parseFloat(meanStr);
    var scale = Math.pow(10, decimals);
    if (!(n > 0) || n > scale) {
      return true;
    }
    var k0 = Math.round(mean * n);
    for (var k = k0 - 1; k <= k0 + 1; k++) {
      if (Math.abs(Math.round((k / n) * scale) / scale - mean) < 1e-9) {
        return true;
      }
    }
    return false;
  }

  function stripLatexForCount(src) {
    var lines = src.split('\n');
    var out = [];
    for (var i = 0; i < lines.length; i++) {
      out.push(maskComment(lines[i]));
    }
    var s = out.join(' ');
    s = s.replace(/\\(?:no)?cite[a-zA-Z]*\*?(?:\[[^\]]*\]){0,2}\{[^}]*\}/g, ' ');
    s = s.replace(/\\(?:label|ref|eqref|cref)\{[^}]*\}/g, ' ');
    s = s.replace(/\$[^$]*\$/g, ' X ');
    s = s.replace(/\\[a-zA-Z]+\*?(?:\[[^\]]*\])?/g, ' ');
    s = s.replace(/\\./g, ' ');
    s = s.replace(/[{}~]/g, ' ');
    return s;
  }

  function countWords(src) {
    var tokens = stripLatexForCount(src).split(/\s+/);
    var n = 0;
    for (var i = 0; i < tokens.length; i++) {
      if (/[A-Za-z0-9\u00C0-\u024F]/.test(tokens[i])) {
        n++;
      }
    }
    return n;
  }

  function findAbstract(text) {
    var m = /\\begin\{abstract\}([\s\S]*?)\\end\{abstract\}/.exec(text);
    if (m) {
      return { body: m[1], index: m.index };
    }
    var idx = text.search(/\\abstract\s*\{/);
    if (idx >= 0) {
      var start = text.indexOf('{', idx);
      var depth = 0;
      for (var i = start; i < text.length; i++) {
        var c = text.charAt(i);
        if (c === '{') {
          depth++;
        } else if (c === '}') {
          depth--;
          if (depth === 0) {
            return { body: text.slice(start + 1, i), index: idx };
          }
        }
      }
    }
    return null;
  }

  function lineOfIndex(text, index) {
    var n = 1;
    for (var i = 0; i < index && i < text.length; i++) {
      if (text.charCodeAt(i) === 10) {
        n++;
      }
    }
    return n;
  }

  function parseBibEntries(text) {
    var entries = [];
    var re = /@([A-Za-z]+)\s*([{(])\s*([^,\s]+)\s*,/g;
    var m;
    while ((m = re.exec(text)) !== null) {
      var type = m[1].toLowerCase();
      if (type === 'comment' || type === 'string' || type === 'preamble') {
        continue;
      }
      var open = m[2];
      var close = open === '{' ? '}' : ')';
      var start = m.index + m[0].indexOf(open);
      var depth = 0;
      var end = text.length;
      for (var i = start; i < text.length; i++) {
        var c = text.charAt(i);
        if (c === open) {
          depth++;
        } else if (c === close) {
          depth--;
          if (depth === 0) {
            end = i + 1;
            break;
          }
        }
      }
      entries.push({ type: type, key: m[3], body: text.slice(start, end), index: m.index });
      re.lastIndex = Math.max(re.lastIndex, end);
    }
    return entries;
  }

  function scanBib(text, push, opts) {
    var entries = parseBibEntries(text);
    var seen = {};
    for (var i = 0; i < entries.length; i++) {
      var e = entries[i];
      var line = lineOfIndex(text, e.index);
      var lower = e.key.toLowerCase();
      if (seen[lower]) {
        push('citations', 'high', line, 'Duplicate BibTeX key "' + e.key + '" (first defined on line ' + seen[lower] + ')', '@' + e.type + '{' + e.key + ',', 'bib-duplicate-key');
      } else {
        seen[lower] = line;
      }
      var hasDoi = /(^|[,\s{])doi\s*=/i.test(e.body);
      if (DOI_TYPES[e.type] && !hasDoi) {
        push('citations', 'medium', line, 'BibTeX @' + e.type + ' "' + e.key + '" is missing a doi = {...} field', '@' + e.type + '{' + e.key + ',', 'bib-missing-doi');
      }
      if (PREPRINT_RE.test(e.body)) {
        var ym = /(^|[,\s{])year\s*=\s*[{"]?\s*(\d{4})/i.exec(e.body);
        var year = ym ? parseInt(ym[2], 10) : null;
        if (year !== null && opts.year - year >= opts.stalePreprintYears) {
          push('citations', 'medium', line, 'Stale preprint "' + e.key + '" (' + year + '): check arXiv/bioRxiv for a published version of record', '@' + e.type + '{' + e.key + ',', 'bib-stale-preprint');
        }
      }
    }
    return entries.length;
  }

  function scanTex(text, push, opts) {
    var lines = text.split('\n');
    var labels = {};
    var labelCount = 0;
    var lm;
    var masked = [];
    for (var i = 0; i < lines.length; i++) {
      masked.push(maskComment(lines[i]));
      LABEL_RE.lastIndex = 0;
      while ((lm = LABEL_RE.exec(masked[i])) !== null) {
        labels[lm[1].trim()] = true;
        labelCount++;
      }
    }
    var lastN = null;
    var lastNLine = -99;
    var seedPinned = false;
    var randomLine = 0;
    var randomText = '';
    for (var li = 0; li < masked.length; li++) {
      var raw = lines[li];
      var line = masked[li];
      var ln = li + 1;
      var m;

      var pm = PATH_RE.exec(raw);
      if (pm) {
        var inComment = line.indexOf(pm[1]) < 0;
        push('leaks', 'high', ln, 'Local filesystem path leak "' + pm[1] + '"' + (inComment ? ' inside a % comment (still shipped in arXiv source)' : '') + ': de-anonymizes the author', raw, 'path-leak');
      }

      if (!line.trim()) {
        continue;
      }
      var isMacroDef = MACRO_DEF_RE.test(line);

      if (!isMacroDef) {
        P_RE.lastIndex = 0;
        while ((m = P_RE.exec(line)) !== null) {
          var op = m[2];
          var pv = parseFloat(m[3]);
          if (op === '=' && pv >= 0.04 && pv <= 0.05) {
            push('numbers', 'high', ln, 'Borderline p = ' + m[3] + ' (0.04x zone): fragile result, Referee #2 p-hacking flag; trace it to a numbers.tex macro', line, 'p-borderline');
          } else if ((op === '<' || op === '\\lt') && Math.abs(pv - 0.05) < 1e-12) {
            push('numbers', 'medium', ln, 'Thresholded "p < .05": report the exact p-value from a traced numbers.tex macro', line, 'p-threshold');
          } else {
            push('numbers', 'medium', ln, 'Hardcoded p-value (p ' + op + ' ' + m[3] + ') not wrapped in a numbers.tex macro', line, 'p-hardcoded');
          }
        }
        R_RE.lastIndex = 0;
        while ((m = R_RE.exec(line)) !== null) {
          push('numbers', 'medium', ln, 'Hardcoded correlation r = ' + (m[2] ? '-' : '') + m[3] + ' not traced to a numbers.tex macro', line, 'r-hardcoded');
        }
        PM_RE.lastIndex = 0;
        while ((m = PM_RE.exec(line)) !== null) {
          push('numbers', 'medium', ln, 'Hardcoded mean \u00B1 SD (' + m[1] + ' \u00B1 ' + m[3] + ') not traced to a numbers.tex macro', line, 'pm-hardcoded');
        }
        PCT_RE.lastIndex = 0;
        while ((m = PCT_RE.exec(line)) !== null) {
          push('numbers', 'low', ln, 'Hardcoded percentage ' + m[1] + '% not traced to a numbers.tex macro', line, 'pct-hardcoded');
        }
        N_RE.lastIndex = 0;
        while ((m = N_RE.exec(line)) !== null) {
          lastN = parseInt(m[3].replace(/,/g, ''), 10);
          lastNLine = ln;
          push('numbers', 'low', ln, 'Hardcoded sample size ' + m[2] + ' = ' + m[3] + ' not traced to a numbers.tex macro', line, 'n-hardcoded');
        }
        MEAN_RE.lastIndex = 0;
        while ((m = MEAN_RE.exec(line)) !== null) {
          if (lastN !== null && ln - lastNLine <= 3 && !grimConsistent(m[1], lastN)) {
            push('numbers', 'high', ln, 'GRIM trigger: mean ' + m[1] + ' is impossible for integer data with N = ' + lastN + ' (line ' + lastNLine + ')', line, 'grim');
          }
        }
      }

      CITE_RE.lastIndex = 0;
      while ((m = CITE_RE.exec(line)) !== null) {
        var keys = m[1].split(',');
        if (!m[1].trim()) {
          push('citations', 'high', ln, 'Empty citation ' + m[0] + ' renders as [?]', line, 'cite-empty');
          continue;
        }
        for (var k = 0; k < keys.length; k++) {
          var key = keys[k].trim();
          if (!key || key.indexOf('?') >= 0 || /^(todo|tbd|xxx|fixme|citation[ _-]?needed)$/i.test(key)) {
            push('citations', 'high', ln, 'Placeholder citation key "' + (key || '(blank)') + '" in ' + m[0], line, 'cite-placeholder');
          }
        }
      }
      if (/\[\?\]|\[citation needed\]/i.test(line)) {
        push('citations', 'high', ln, 'Literal [?] / [citation needed] marker in prose', line, 'cite-marker');
      }

      REF_RE.lastIndex = 0;
      while ((m = REF_RE.exec(line)) !== null) {
        var rkeys = m[1].split(',');
        for (var r = 0; r < rkeys.length; r++) {
          var rk = rkeys[r].trim();
          if (!rk) {
            push('leaks', 'high', ln, 'Empty ' + m[0] + ' renders as ??', line, 'ref-empty');
          } else if (!labels[rk]) {
            if (labelCount > 0) {
              push('leaks', 'medium', ln, 'Unresolved reference \\ref{' + rk + '}: no matching \\label in this buffer (renders as ??)', line, 'ref-unresolved');
            } else {
              push('leaks', 'low', ln, '\\ref{' + rk + '} has no \\label in this buffer (verify it exists in another file)', line, 'ref-external');
            }
          }
        }
      }
      if (/(^|[^?])\?\?([^?]|$)/.test(line) && !/\\(?:url|href)/.test(line)) {
        push('leaks', 'high', ln, 'Literal "??" in source: unresolved figure/table/equation reference', line, 'ref-marker');
      }

      if (SEED_RE.test(line)) {
        if (/\d/.test(line)) {
          seedPinned = true;
        } else {
          push('leaks', 'medium', ln, 'Random seed mentioned without a pinned value (state the exact seed)', line, 'seed-unpinned');
        }
      }
      if (!randomLine && RANDOM_RE.test(line)) {
        randomLine = ln;
        randomText = line;
      }
    }
    if (randomLine && !seedPinned) {
      push('leaks', 'low', randomLine, 'Randomized procedure described but no pinned random seed reported anywhere in this buffer', randomText, 'seed-missing');
    }

    var abs = findAbstract(text);
    if (!abs) {
      return null;
    }
    var words = countWords(abs.body);
    var absLine = lineOfIndex(text, abs.index);
    var venues = {};
    for (var vk in VENUES) {
      if (Object.prototype.hasOwnProperty.call(VENUES, vk)) {
        venues[vk] = { label: VENUES[vk].label, limit: VENUES[vk].abstractWords, over: words > VENUES[vk].abstractWords };
      }
    }
    var target = VENUES[opts.venue] ? opts.venue : DEFAULT_VENUE;
    var limit = VENUES[target].abstractWords;
    if (words > limit) {
      push('wordcount', words > limit * 1.1 ? 'high' : 'medium', absLine, 'Abstract is ' + words + ' words: ' + (words - limit) + ' over the ' + target + ' limit of ' + limit, '\\begin{abstract}', 'abstract-over');
    }
    return { words: words, line: absLine, target: target, limit: limit, venues: venues };
  }

  function scan(text, options) {
    var t0 = now();
    var opts = options || {};
    var cfg = {
      venue: VENUES[opts.venue] ? opts.venue : DEFAULT_VENUE,
      year: opts.year || new Date().getFullYear(),
      stalePreprintYears: typeof opts.stalePreprintYears === 'number' ? opts.stalePreprintYears : 1,
      lineOffset: opts.lineOffset || 0
    };
    var src = String(text || '').replace(/\r\n?/g, '\n');
    var kind = opts.kind === 'bib' || opts.kind === 'tex' ? opts.kind : detectKind(src);
    var findings = [];
    function push(category, severity, line, message, snippet, rule) {
      findings.push({
        category: category,
        severity: severity,
        line: line + cfg.lineOffset,
        rule: rule,
        message: message,
        snippet: clip(snippet)
      });
    }
    var wordCount = null;
    var bibEntries = 0;
    if (kind === 'bib') {
      bibEntries = scanBib(src, push, cfg);
    } else {
      wordCount = scanTex(src, push, cfg);
    }
    findings.sort(function (a, b) {
      return a.line - b.line || (a.rule < b.rule ? -1 : a.rule > b.rule ? 1 : 0);
    });
    var penalty = 0;
    var counts = { high: 0, medium: 0, low: 0, numbers: 0, citations: 0, leaks: 0, wordcount: 0 };
    for (var i = 0; i < findings.length; i++) {
      penalty += SEVERITY_WEIGHTS[findings[i].severity];
      counts[findings[i].severity]++;
      counts[findings[i].category]++;
    }
    var score = Math.max(0, 100 - penalty);
    return {
      engine: 'limboAudit-overleaf',
      version: VERSION,
      kind: kind,
      venue: cfg.venue,
      score: score,
      grade: score >= 90 ? 'A' : score >= 75 ? 'B' : score >= 60 ? 'C' : score >= 40 ? 'D' : 'F',
      lines: src ? src.split('\n').length : 0,
      bibEntries: bibEntries,
      counts: counts,
      findings: findings,
      wordCount: wordCount,
      elapsedMs: Math.round((now() - t0) * 100) / 100
    };
  }

  function buildPiMemo(result, extra) {
    var r = result || { score: null, counts: { high: 0, medium: 0, low: 0 }, findings: [] };
    var x = extra || {};
    var amount = x.amount || '$650';
    var title = x.manuscript || '[manuscript title]';
    var venue = x.venue || r.venue || '[target journal]';
    var lines = [
      'Subject: Quote + justification: AveryCorp pre-submission manuscript audit (' + amount + ', P-Card)',
      '',
      'Hi [PI name],',
      '',
      'Before we submit "' + title + '" to ' + venue + ', I ran the free limboAudit client-side check in Overleaf.',
      'It scored ' + (r.score === null ? '[score]' : r.score + '/100') + ' with ' + r.counts.high + ' high / ' + r.counts.medium + ' medium / ' + r.counts.low + ' low findings (untraced numbers, citation/DOI gaps, reference or anonymization leaks).',
      '',
      'I would like to purchase the AveryCorp 48h Executive Audit & Referee #2 Dossier:',
      '  Vendor:   AveryCorp (https://averycorp.org/services.html)',
      '  Service:  Tier 1A Executive Manuscript Audit (fixed price, ' + amount + '; tiers range $650-$2,450)',
      '  Payment:  Departmental P-Card, single transaction, no PO or contract required',
      '',
      'Procurement justification:',
      '  - A single fixed-price purchase under ' + (x.cap || '$2,500') + ' falls within the micro-purchase method of',
      '    2 CFR \u00A7 200.320(a)(1) (Uniform Guidance), which allows award without soliciting quotes when the',
      '    price is considered reasonable; please confirm against our institution\'s P-Card and micro-purchase policy.',
      '  - Data-management relevance: the audit produces traceable numbers.tex macros and a verified, DOI-complete',
      '    bibliography that support our Data Management & Sharing Plan under the NIH Data Management and',
      '    Sharing Policy (NOT-OD-21-013), which treats reasonable data management and sharing costs as allowable.',
      '',
      'Proposed charge: [grant / cost center]. Turnaround: 48 hours.',
      '',
      'Thanks,',
      '[Your name]'
    ];
    return lines.join('\n');
  }

  var API = {
    VERSION: VERSION,
    CTA: CTA,
    VENUES: VENUES,
    CATEGORIES: CATEGORIES,
    SEVERITY_WEIGHTS: SEVERITY_WEIGHTS,
    DEFAULT_VENUE: DEFAULT_VENUE,
    scan: scan,
    detectKind: detectKind,
    countWords: countWords,
    grimConsistent: grimConsistent,
    buildPiMemo: buildPiMemo
  };

  root.LimboScanner = API;
  if (typeof module === 'object' && module && module.exports) {
    module.exports = API;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
