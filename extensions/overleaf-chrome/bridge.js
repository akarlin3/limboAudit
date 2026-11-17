/*
 * limboAudit page bridge (runs in the page's MAIN world).
 * Reads the live CodeMirror 6 / Monaco / Ace document model that Overleaf keeps in page JS,
 * which an isolated-world content script cannot see. Answers same-window postMessage requests only.
 * Read-only except for moving the cursor to a finding's line when the user clicks it.
 */
(function () {
  'use strict';
  if (window.__limboReadEditor) {
    return;
  }

  function cmView() {
    var el = document.querySelector('.cm-editor .cm-content') || document.querySelector('.cm-content');
    var view = el && el.cmView && el.cmView.view;
    return view && view.state && view.state.doc ? view : null;
  }

  function aceEditor() {
    var el = document.querySelector('.ace_editor');
    return el && el.env && el.env.editor ? el.env.editor : null;
  }

  function monacoEditor() {
    var m = window.monaco;
    if (m && m.editor && typeof m.editor.getEditors === 'function') {
      var eds = m.editor.getEditors();
      return eds && eds.length ? eds[0] : null;
    }
    return null;
  }

  function activeFileName() {
    var el = document.querySelector('[role="treeitem"][aria-selected="true"] .item-name-button span') ||
      document.querySelector('[role="treeitem"][aria-selected="true"]') ||
      document.querySelector('.file-tree .selected .name');
    var name = el ? String(el.textContent || '').trim() : '';
    return name.length < 200 ? name : '';
  }

  function readEditor() {
    try {
      var view = cmView();
      if (view) {
        var st = view.state;
        var sel = st.selection && st.selection.main;
        var selected = sel && sel.to > sel.from ? st.sliceDoc(sel.from, sel.to) : '';
        return {
          text: st.doc.toString(),
          selection: selected,
          selectionLine: selected ? st.doc.lineAt(sel.from).number : 1,
          source: 'CodeMirror 6',
          fileName: activeFileName()
        };
      }
    } catch (e) {
      // fall through to the next editor
    }
    try {
      var me = monacoEditor();
      if (me && me.getModel()) {
        var model = me.getModel();
        var range = me.getSelection();
        var mSel = range && !range.isEmpty() ? model.getValueInRange(range) : '';
        return { text: model.getValue(), selection: mSel, selectionLine: mSel ? range.startLineNumber : 1, source: 'Monaco', fileName: activeFileName() };
      }
    } catch (e2) {
      // fall through
    }
    try {
      var ace = aceEditor();
      if (ace) {
        var aSel = ace.getSelectedText();
        return { text: ace.getValue(), selection: aSel, selectionLine: aSel ? ace.getSelectionRange().start.row + 1 : 1, source: 'Ace', fileName: activeFileName() };
      }
    } catch (e3) {
      // fall through
    }
    return null;
  }

  function gotoLine(line) {
    var n = parseInt(line, 10);
    if (!(n > 0)) {
      return false;
    }
    try {
      var view = cmView();
      if (view) {
        var l = view.state.doc.line(Math.min(n, view.state.doc.lines));
        view.dispatch({ selection: { anchor: l.from, head: l.to }, scrollIntoView: true });
        view.focus();
        return true;
      }
      var me = monacoEditor();
      if (me) {
        me.revealLineInCenter(n);
        me.setPosition({ lineNumber: n, column: 1 });
        me.focus();
        return true;
      }
      var ace = aceEditor();
      if (ace) {
        ace.gotoLine(n, 0, true);
        ace.focus();
        return true;
      }
    } catch (e) {
      return false;
    }
    return false;
  }

  window.__limboReadEditor = readEditor;
  window.__limboGotoLine = gotoLine;

  window.addEventListener('message', function (ev) {
    if (ev.source !== window || !ev.data || typeof ev.data.__limbo !== 'string') {
      return;
    }
    if (ev.data.__limbo === 'req') {
      window.postMessage({ __limbo: 'res', id: ev.data.id, payload: readEditor() }, window.location.origin);
    } else if (ev.data.__limbo === 'goto') {
      gotoLine(ev.data.line);
    }
  });
})();
