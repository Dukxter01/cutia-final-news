// Service worker: aplicația se instalează pe telefon, se deschide și fără
// internet (ultima versiune salvată) și primește notificări push.
// Datele (/api/...) nu se salvează niciodată aici: rămân doar pe server.
const CACHE = "cutia-v2";
const SHELL = [
  "index.html", "styles.css", "app.js", "fonts.css", "intro.js", "manifest.webmanifest",
  "i18n/core.js", "i18n/ro.js", "i18n/en.js", "icons/icon-192.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

// Întâi rețeaua (ca să vezi mereu versiunea nouă), apoi copia salvată dacă nu e internet
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== location.origin || !url.pathname.startsWith("/static/")) return;
  event.respondWith(fetch(event.request).then((res) => {
    if (res.ok) {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(event.request, copy));
    }
    return res;
  }).catch(() => caches.match(event.request).then((hit) => hit || caches.match("index.html"))));
});

self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (_) {}
  event.waitUntil(self.registration.showNotification(data.title || "Cutia Clasei", {
    body: data.body || "",
    icon: "icons/icon-192.png",
    badge: "icons/icon-192.png",
    tag: data.tag || "cutia",
    data: { url: data.url || "/static/index.html" },
  }));
});

// Click pe notificare: deschide aplicația direct pe ecranul potrivit
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data.url, self.location.origin).href;
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
    const open = list.find((c) => c.url.startsWith(self.location.origin));
    if (open) {
      open.postMessage({ view: new URL(url).hash.slice(1) });
      return open.focus();
    }
    return self.clients.openWindow(url);
  }));
});
