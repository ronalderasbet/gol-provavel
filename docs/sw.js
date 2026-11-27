// FootPrevia — funciona offline e sempre tenta buscar a versão mais nova primeiro.
const CACHE = "gol-provavel-v6";
const SHELL = ["./", "index.html", "privacidade.html", "manifest.webmanifest", "footprevia-192.png", "footprevia-512.png", "footprevia-maskable-192.png", "footprevia-maskable-512.png", "footprevia-apple-180.png"];
self.addEventListener("install", e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL))); self.skipWaiting(); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE && k !== "escudos-v1").map(k => caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method === "GET" && url.hostname === "media.api-sports.io") {
    // escudos dos times: guardados no aparelho depois da primeira vez
    e.respondWith(caches.open("escudos-v1").then(c => c.match(e.request).then(hit => hit || fetch(e.request).then(r => { if (r.ok || r.type === "opaque") c.put(e.request, r.clone()); return r; }))));
    return;
  }
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  const key = url.origin + url.pathname;
  e.respondWith(
    fetch(e.request).then(r => {
      if (r.ok) { const copy = r.clone(); caches.open(CACHE).then(c => c.put(key, copy)); }
      return r;
    }).catch(() => caches.match(key).then(r => r || caches.match("index.html")))
  );
});

// Notificações dos times seguidos (enviadas pelo serviço ao vivo)
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) { d = { title: "FootPrevia", body: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.title || "FootPrevia", {
    body: d.body || "", icon: "footprevia-192.png", tag: d.tag || undefined, renotify: !!d.tag,
    data: { url: d.url || "./#hoje" }
  }));
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = new URL((e.notification.data && e.notification.data.url) || "./#hoje", self.registration.scope).href;
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(list => {
    for (const c of list) { if (c.url.startsWith(self.registration.scope) && "focus" in c) { c.navigate(url).catch(() => {}); return c.focus(); } }
    return self.clients.openWindow(url);
  }));
});
