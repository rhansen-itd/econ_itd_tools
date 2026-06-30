// ==UserScript==
// @name         EOS Front-Panel Capture
// @namespace    econ-itd-tools
// @version      1.0
// @description  Record Econolite EOS front-panel WebSocket traffic — your key presses AND the controller's screen frames — then download it as a text file. Saves copy-pasting frames out of DevTools.
// @match        https://10.37.23.200:8443/*
// @match        http://10.37.23.200:8081/*
// @run-at       document-start
// @grant        none
// ==/UserScript==
//
// SETUP
// -----
// 1. Install a userscript manager: Tampermonkey or Violentmonkey (Chrome/Edge/Firefox).
// 2. Add this file as a new userscript (or drag it onto the extension's dashboard).
// 3. Edit the two @match lines above if your controller's IP/port differs.
// 4. Open the controller's front panel in your browser. A small black/green box
//    appears bottom-right. Navigate around; press keys; then click "Download".
//
// WHY A USERSCRIPT (and not a console paste): the page opens its WebSocket the
// moment it loads, so the wrapper below must be installed BEFORE that happens.
// @run-at document-start guarantees that. A console paste or bookmarklet runs
// too late to catch the already-open socket.
//
// OUTPUT FORMAT — one record per line, tab-separated:
//     <iso-timestamp>\t<DIR>\t<payload>
//   DIR is one of:
//     SEND  – a key press your browser sent to the controller (e.g. "key13")
//     RECV  – a screen frame the controller sent back (hex prefix + blob + text)
//     OPEN  / CLOSE – socket lifecycle markers
// RECV payloads are passed through verbatim (only CR/LF/TAB collapsed to spaces),
// so byte offsets like SCREEN_TEXT_OFFSET line up with eos_set_time.py.

(function () {
  'use strict';

  // ── capture buffer ──────────────────────────────────────────────────────
  const records = [];                 // "ISO-timestamp\tDIR\tpayload"
  const counts  = { SEND: 0, RECV: 0 };

  function sanitize(text) {
    // Keep exactly one record per line: collapse any CR/LF/TAB in the payload.
    // Frames are normally a single flat string, so this rarely changes anything.
    return String(text).replace(/[\r\n\t]+/g, ' ');
  }

  function push(ts, dir, text) {
    records.push(ts.toISOString() + '\t' + dir + '\t' + sanitize(text));
    if (dir in counts) counts[dir]++;
    updateBadge();
  }

  function record(dir, data) {
    const ts = new Date();            // stamp at arrival so async Blob stays ordered
    if (typeof data === 'string') {
      push(ts, dir, data);
    } else if (data instanceof ArrayBuffer) {
      push(ts, dir, new TextDecoder().decode(data));
    } else if (data && typeof data.text === 'function') {
      data.text().then(t => push(ts, dir, t));   // Blob (binary frame)
    } else {
      push(ts, dir, data);
    }
  }

  // ── wrap the WebSocket constructor (installed before the page opens it) ──
  const OrigWS = window.WebSocket;
  function WrappedWS(url, protocols) {
    const ws = protocols !== undefined ? new OrigWS(url, protocols) : new OrigWS(url);
    push(new Date(), 'OPEN', url + (protocols ? ' [' + protocols + ']' : ''));

    const origSend = ws.send;
    ws.send = function (data) {
      record('SEND', data);           // <-- your key presses land here
      return origSend.call(this, data);
    };
    ws.addEventListener('message', ev => record('RECV', ev.data));
    ws.addEventListener('close', () => push(new Date(), 'CLOSE', ''));
    return ws;
  }
  WrappedWS.prototype = OrigWS.prototype;
  ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED'].forEach(k => { WrappedWS[k] = OrigWS[k]; });
  window.WebSocket = WrappedWS;

  // ── download / clear ────────────────────────────────────────────────────
  function download() {
    const header =
      '# EOS front-panel capture\n' +
      '# url:   ' + location.href + '\n' +
      '# saved: ' + new Date().toISOString() + '\n' +
      '# cols:  <iso-timestamp>\\t<DIR>\\t<payload>   ' +
      '(DIR = SEND key press | RECV frame | OPEN | CLOSE)\n';
    const blob = new Blob([header + records.join('\n') + '\n'], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'eos_capture_' + new Date().toISOString().replace(/[:.]/g, '-') + '.txt';
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function clearAll() {
    records.length = 0;
    counts.SEND = counts.RECV = 0;
    updateBadge();
  }

  // ── floating UI — buttons only (no key shortcuts, so we never inject a key) ─
  let badge;
  function updateBadge() {
    if (badge) badge.textContent = 'SEND ' + counts.SEND + ' · RECV ' + counts.RECV;
  }

  function buildUI() {
    const box = document.createElement('div');
    box.style.cssText =
      'position:fixed;bottom:10px;right:10px;z-index:2147483647;' +
      'font:12px/1.4 monospace;background:#111;color:#0f0;padding:8px;' +
      'border:1px solid #0f0;border-radius:6px;opacity:0.9;';

    badge = document.createElement('div');
    badge.style.marginBottom = '6px';
    box.appendChild(badge);
    updateBadge();

    const dl = document.createElement('button');
    dl.textContent = '⬇ Download';
    dl.onclick = download;

    const cl = document.createElement('button');
    cl.textContent = '✕ Clear';
    cl.style.marginLeft = '6px';
    cl.onclick = clearAll;

    [dl, cl].forEach(b => { b.style.cssText = 'font:11px monospace;cursor:pointer;'; });
    box.appendChild(dl);
    box.appendChild(cl);
    document.body.appendChild(box);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', buildUI);
  } else {
    buildUI();
  }
})();
