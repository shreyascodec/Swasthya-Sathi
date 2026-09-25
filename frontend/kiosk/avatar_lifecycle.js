/**
 * Swasthya Sakhi — live-avatar billing safety net (kiosk side).
 *
 * The Brenin avatar call bills per second. The kiosk only ends it cleanly on the
 * CLOSING auto-reset, so a patient who walks away mid-flow, or a tab that is
 * closed / refreshed / crashes, leaves the call billing until a server ceiling.
 * This module closes that gap with three independent guards:
 *
 *   1. HEARTBEAT   — POST /api/avatar/heartbeat every ~20s while the call is on
 *                    screen. When the pings stop, the server reaper ends the call
 *                    after SS_AVATAR_IDLE_S. (Activates the server's idle reap;
 *                    until this ships the server falls back to the max-age cap.)
 *   2. IDLE END    — if neither the avatar nor the patient has spoken/interacted
 *                    for `idleMs`, end the call locally (belt-and-braces with the
 *                    server reap; also frees the kiosk immediately).
 *   3. EXIT BEACON — on pagehide / tab-hidden, navigator.sendBeacon(/api/avatar/end)
 *                    so billing stops even when the tab is killed and no normal
 *                    end() can run. sendBeacon survives unload; fetch/SDK end do not.
 *
 * Wiring (call once, right after the session is created and the <brenin-avatar>
 * element is mounted):
 *
 *   import { attachAvatarLifecycle } from './avatar_lifecycle.js';
 *   const detach = attachAvatarLifecycle({
 *     el,                       // the <brenin-avatar> DOM element (has .client)
 *     sessionId,                // session_id from POST /api/avatar/session
 *     sessionToken,             // session_token from the same response
 *     apiOrigin: '',            // same-origin kiosk → '' ; else server origin
 *     onIdleEnd: () => kiosk.reset(),   // optional: your reset-to-IDLE handler
 *   });
 *   // Call detach() when YOU end the call (CLOSING auto-reset) so the guards for
 *   // this session stop. Then create the next session fresh.
 *
 * No dependencies. ES module (import the named export); it also attaches
 * window.attachAvatarLifecycle for plain-<script> use.
 */

var root = typeof window !== 'undefined' ? window : globalThis;

var DEFAULTS = {
  heartbeatMs: 20000, // ping cadence; must be < server SS_AVATAR_IDLE_S
  idleMs: 120000,     // no speech/interaction for this long → end locally
  apiOrigin: '',
};

export function attachAvatarLifecycle(opts) {
    opts = opts || {};
    var el = opts.el || null;
    var sessionId = opts.sessionId || '';
    var sessionToken = opts.sessionToken || '';
    var apiOrigin = (opts.apiOrigin != null ? opts.apiOrigin : DEFAULTS.apiOrigin).replace(/\/$/, '');
    var heartbeatMs = opts.heartbeatMs || DEFAULTS.heartbeatMs;
    var idleMs = opts.idleMs || DEFAULTS.idleMs;
    var onIdleEnd = typeof opts.onIdleEnd === 'function' ? opts.onIdleEnd : function () {};
    var log = opts.log === false ? function () {} : function () {
      try { console.info.apply(console, ['[avatar-lifecycle]'].concat([].slice.call(arguments))); } catch (_) {}
    };

    if (!sessionId && !sessionToken) {
      log('no session id/token — nothing to guard');
      return function () {};
    }

    var endUrl = apiOrigin + '/api/avatar/end';
    var beatUrl = apiOrigin + '/api/avatar/heartbeat';
    var body = JSON.stringify({ session_id: sessionId, session_token: sessionToken || undefined });

    var done = false;         // this session already ended — stop all guards
    var lastActivity = Date.now();
    var heartbeatTimer = null;
    var idleTimer = null;

    function markActivity() { lastActivity = Date.now(); }

    function sendHeartbeat() {
      if (done) return;
      try {
        fetch(beatUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: body,
          keepalive: true,
        }).catch(function () {});
      } catch (_) {}
    }

    // End the call for good. `viaBeacon` uses sendBeacon (survives tab unload).
    function endCall(reason, viaBeacon) {
      if (done) return;
      done = true;
      stopTimers();
      log('ending call:', reason);
      // 1) Tell OUR server to end the Brenin conversation — this is what actually
      //    stops billing (the live call talks to Brenin directly, but /end is
      //    proxied through us and clears reaper tracking too).
      if (viaBeacon && root.navigator && typeof navigator.sendBeacon === 'function') {
        try {
          navigator.sendBeacon(endUrl, new Blob([body], { type: 'application/json' }));
        } catch (_) {}
      } else {
        try {
          fetch(endUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: body,
            keepalive: true,
          }).catch(function () {});
        } catch (_) {}
      }
      // 2) Best-effort local teardown of the SDK so the video/WebRTC stops now.
      try {
        if (el && typeof el.terminate === 'function') el.terminate();
        else if (el && el.client && typeof el.client.terminate === 'function') el.client.terminate();
      } catch (_) {}
    }

    function checkIdle() {
      if (done) return;
      if (Date.now() - lastActivity >= idleMs) {
        endCall('idle (' + Math.round(idleMs / 1000) + 's no speech/interaction)', false);
        try { onIdleEnd(); } catch (_) {}
      }
    }

    function stopTimers() {
      if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null; }
      if (idleTimer) { clearInterval(idleTimer); idleTimer = null; }
    }

    // --- speech events reset the idle clock (real conversation activity) -------
    // Per the SDK, speech is emitted on the client emitter, not as DOM events.
    var client = el && el.client ? el.client : null;
    var speakingEvents = ['speaking', 'avatar-speaking'];
    function bindClient(c) {
      if (!c || typeof c.on !== 'function') return;
      speakingEvents.forEach(function (ev) {
        try { c.on(ev, markActivity); } catch (_) {}
      });
      // If the SDK signals its own end, stop guarding (avoid a double /end).
      try { c.on('end', function () { done = true; stopTimers(); }); } catch (_) {}
    }
    bindClient(client);
    // The element may attach `.client` slightly after mount; retry briefly.
    if (!client && el) {
      var tries = 0;
      var poll = setInterval(function () {
        tries++;
        if (done || tries > 25) { clearInterval(poll); return; }
        if (el.client) { clearInterval(poll); bindClient(el.client); }
      }, 200);
    }

    // --- patient interaction on the kiosk also counts as activity -------------
    var interactionEvents = ['pointerdown', 'keydown', 'touchstart'];
    interactionEvents.forEach(function (ev) {
      try { root.addEventListener(ev, markActivity, { passive: true }); } catch (_) {}
    });

    // --- exit beacon: tab closed / hidden / navigated away --------------------
    function onPageHide() { endCall('pagehide', true); }
    function onVisibility() {
      if (root.document && document.visibilityState === 'hidden') endCall('tab hidden', true);
    }
    try { root.addEventListener('pagehide', onPageHide); } catch (_) {}
    try { root.addEventListener('beforeunload', onPageHide); } catch (_) {}
    try { root.addEventListener('visibilitychange', onVisibility); } catch (_) {}

    // --- start the timers -----------------------------------------------------
    sendHeartbeat(); // one immediately so the server knows this build heartbeats
    heartbeatTimer = setInterval(sendHeartbeat, heartbeatMs);
    idleTimer = setInterval(checkIdle, Math.min(idleMs, 15000));

    // --- detach: caller ended the call normally; drop this session's guards ---
    return function detach(alsoEnd) {
      if (alsoEnd) endCall('detach', false);
      done = true;
      stopTimers();
      interactionEvents.forEach(function (ev) {
        try { root.removeEventListener(ev, markActivity); } catch (_) {}
      });
      try { root.removeEventListener('pagehide', onPageHide); } catch (_) {}
      try { root.removeEventListener('beforeunload', onPageHide); } catch (_) {}
      try { root.removeEventListener('visibilitychange', onVisibility); } catch (_) {}
  };
}

// Plain-<script> fallback: expose on the global so non-module callers can use it.
try { root.attachAvatarLifecycle = attachAvatarLifecycle; } catch (_) {}

export default attachAvatarLifecycle;
