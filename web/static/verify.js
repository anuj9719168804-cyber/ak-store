/* Browser check used by /go and /verify (see helper/verify_web.py for what the server does with it).
 * No dependencies. Everything here runs in the visitor's browser. */
(function () {
  "use strict";

  /* ---- SHA-256 (synchronous, ASCII input): WebCrypto is async and far too slow for a hash loop ---- */
  var K = new Uint32Array([
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
  ]);
  var W = new Uint32Array(64);

  function sha256(str) {
    var len = str.length, total = ((len + 9 + 63) >> 6) << 6, buf = new Uint8Array(total), i, j;
    for (i = 0; i < len; i++) buf[i] = str.charCodeAt(i) & 0xff;
    buf[len] = 0x80;
    var bits = len * 8;
    buf[total - 4] = (bits >>> 24) & 0xff; buf[total - 3] = (bits >>> 16) & 0xff;
    buf[total - 2] = (bits >>> 8) & 0xff;  buf[total - 1] = bits & 0xff;       /* messages are tiny: high 32 bits stay 0 */
    var h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a,
        h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19;
    for (var off = 0; off < total; off += 64) {
      for (i = 0; i < 16; i++) {
        j = off + i * 4;
        W[i] = (buf[j] << 24) | (buf[j + 1] << 16) | (buf[j + 2] << 8) | buf[j + 3];
      }
      for (i = 16; i < 64; i++) {
        var x = W[i - 15], y = W[i - 2];
        var s0 = ((x >>> 7) | (x << 25)) ^ ((x >>> 18) | (x << 14)) ^ (x >>> 3);
        var s1 = ((y >>> 17) | (y << 15)) ^ ((y >>> 19) | (y << 13)) ^ (y >>> 10);
        W[i] = (W[i - 16] + s0 + W[i - 7] + s1) | 0;
      }
      var a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7;
      for (i = 0; i < 64; i++) {
        var S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
        var ch = (e & f) ^ (~e & g);
        var t1 = (h + S1 + ch + K[i] + W[i]) | 0;
        var S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
        var mj = (a & b) ^ (a & c) ^ (b & c);
        var t2 = (S0 + mj) | 0;
        h = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
      }
      h0 = (h0 + a) | 0; h1 = (h1 + b) | 0; h2 = (h2 + c) | 0; h3 = (h3 + d) | 0;
      h4 = (h4 + e) | 0; h5 = (h5 + f) | 0; h6 = (h6 + g) | 0; h7 = (h7 + h) | 0;
    }
    return [h0, h1, h2, h3, h4, h5, h6, h7];
  }

  function hex(words) {
    return words.map(function (w) { return ("00000000" + (w >>> 0).toString(16)).slice(-8); }).join("");
  }

  function leadingZeroBits(words) {
    var n = 0;
    for (var i = 0; i < 8; i++) {
      var w = words[i] >>> 0;
      if (w === 0) { n += 32; continue; }
      return n + Math.clz32(w);
    }
    return n;
  }

  /* ---- proof of work: find n so that sha256("<challenge>:<n>") starts with `bits` zero bits ---- */
  function solve(challenge, bits, onProgress) {
    return new Promise(function (resolve) {
      if (!bits || bits <= 0) { resolve("0"); return; }
      var n = 0, prefix = challenge + ":", started = Date.now();
      (function step() {
        var end = n + 3000;
        for (; n < end; n++) {
          if (leadingZeroBits(sha256(prefix + n)) >= bits) { resolve(String(n)); return; }
        }
        if (onProgress) onProgress(Date.now() - started);
        setTimeout(step, 0);                    /* let the page breathe between chunks */
      })();
    });
  }

  /* ---- what the page tells the server about itself ---- */
  var seen = { ptr: 0, t0: Date.now() };
  ["pointerdown", "pointermove", "touchstart", "mousedown", "keydown"].forEach(function (name) {
    window.addEventListener(name, function (ev) { if (ev.isTrusted) seen.ptr++; }, { passive: true, capture: true });
  });

  function signals(trusted) {
    return {
      wd: navigator.webdriver === true,
      trusted: trusted === true,
      ptr: seen.ptr,
      ms: Date.now() - seen.t0
    };
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(function (r) { return r.json().catch(function () { return { ok: false, msg: "Unexpected answer from the server." }; }); });
  }

  /* ---- Cloudflare Turnstile (optional): FSV.turnstile(el, sitekey) -> { ready: Promise, token: fn } ---- */
  function turnstile(el, sitekey) {
    var current = null, widget = null;
    var ready = new Promise(function (resolve, reject) {
      var tries = 0;
      (function mount() {
        if (window.turnstile && window.turnstile.render) {
          widget = window.turnstile.render(el, {
            sitekey: sitekey,
            callback: function (t) { current = t; resolve(t); },
            "error-callback": function () { reject(new Error("captcha")); return true; },
            "expired-callback": function () { current = null; try { window.turnstile.reset(widget); } catch (e) {} }
          });
          return;
        }
        if (++tries > 150) { reject(new Error("captcha-load")); return; }   /* ~15 s for the script to load */
        setTimeout(mount, 100);
      })();
    });
    return { ready: ready, token: function () { return current; } };
  }

  window.FSV = { turnstile: turnstile, sha256: sha256, hex: hex, leadingZeroBits: leadingZeroBits, solve: solve, signals: signals, post: post };
})();
