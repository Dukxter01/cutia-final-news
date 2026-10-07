// Cutia Clasei · interfața platformei (fără framework).
// Tot textul vine din i18n/<limbă>.js; totul se construiește cu el(), fără innerHTML.

const $ = (sel) => document.querySelector(sel);
// Răspunsurile la întrebările AI despre problemă, funcții, date și mărime se adaugă la descriere
const TARGET_FIELD = { problem: "description", features: "description", data: "description", size: "description" };
const THEMES = [
  ["dark", "linear-gradient(135deg,#b4a5ff,#ffadd2)"], ["light", "linear-gradient(135deg,#f7f5f1,#d9d2ff)"],
  ["sunset", "linear-gradient(135deg,#ff9a8b,#ffc48a)"], ["ocean", "linear-gradient(135deg,#8fb4ff,#7fe0e8)"],
  ["contrast", "#ffd400"],
];
const INTRO_MS = 7000;
const CHECKLIST = ["features", "privacy", "ai_consent", "github_readme", "no_keys", "trainer_access"];
const BADGES = {
  first_question: "❓", first_homework: "📚", five_homework: "🔥", first_idea: "💡",
  crowd_favorite: "🎉", chosen: "🏆", perfectionist: "💎", century: "💯", demo_day: "🎬", streak_7: "📆", quest_master: "🗺",
};
const NEWS_HUE = { launch: 330, tools: 190, models: 265, research: 150, industry: 35 };

let auth = null;
try { auth = JSON.parse(localStorage.getItem("cutia-auth")); } catch (_) { auth = null; }

let lang = LANGS.some((l) => l.code === document.documentElement.lang) ? document.documentElement.lang : "ro";
let cfg = { ai: false, topics: Object.keys(TOPIC_META) };
let questions = [], proposals = [], submissions = [], assignments = [], announcements = [];
let threads = [], chat = [], activeThread = null, unread = 0;
let myPoints = null, board = [], students = [];
let newsData = null, newsLoading = false, newsCat = "all";
let lastMissing = [], lastStats = {};
let currentView = "home", selectedTopic = "prompting", selectedKind = "homework", pendingFiles = [];
let authMode = "in";
let drafts = [], currentDraftId = null, draftTimer = null, draftSavedAt = null;
const aiPending = new Set();

// ================================================================ i18n

function strings(code) { return (I18N[code] && I18N[code].strings) || {}; }

function t(key, ...args) {
  let s = strings(lang)[key] ?? strings("en")[key] ?? key;
  for (const a of args) s = typeof s === "string" ? s.replace("{}", a) : s;
  return s;
}

function topic(key) {
  const meta = TOPIC_META[key];
  const text = (I18N[lang] && I18N[lang].topics[key]) || (I18N.en && I18N.en.topics[key]);
  if (!meta || !text) return { key, icon: "✨", hue: 50, title: key, summary: "", tips: [], prompt: "", pitfall: "" };
  return { key, ...meta, ...text };
}

function loadLang(code) {
  if (I18N[code]) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = `i18n/${code}.js`;
    s.onload = resolve;
    s.onerror = reject;
    document.head.append(s);
  });
}

function applyI18n() {
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach((n) => (n.textContent = t(n.dataset.i18n)));
  document.querySelectorAll("[data-i18n-placeholder]").forEach((n) => (n.placeholder = t(n.dataset.i18nPlaceholder)));
  document.querySelectorAll("[data-i18n-title]").forEach((n) => {
    n.title = t(n.dataset.i18nTitle);
    n.setAttribute("aria-label", n.title);
  });
  const current = LANGS.find((l) => l.code === lang);
  $("#lang-btn").replaceChildren(current.flag, " ", el("span", { class: "mono" }, current.code.toUpperCase()));
  $("#lang-menu").replaceChildren(...LANGS.map((l) =>
    el("button", { class: l.code === lang ? "on" : "", role: "menuitem", onclick: () => { closeMenus(); setLang(l.code); } },
      l.flag, " ", l.name)));
}

async function setLang(next) {
  if (next === lang || !LANGS.some((l) => l.code === next)) return;
  try { await loadLang(next); } catch (_) { return; }
  lang = next;
  try { localStorage.setItem("cutia-lang", lang); } catch (_) {}
  applyI18n();
  if (isLoggedIn()) {
    api("/api/me", { method: "PATCH", body: { lang } }).catch(() => {});
    renderAll();
    if (newsData) loadNews(); // știrile sunt alese și explicate în limba ta
    if (digestData) loadDigest();
  } else {
    renderLogin();
  }
}

// ================================================================ helpers

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Lang": lang,
      ...(auth ? { Authorization: `Bearer ${auth.token}` } : {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && auth) logout(true);
  if (!res.ok) {
    const detail = Array.isArray(data.detail) ? t("err.check") : data.detail;
    throw Object.assign(new Error(detail || t("err.generic")), { status: res.status });
  }
  return data;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "style") node.style.cssText = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) node.setAttribute(k, v === true ? "" : v);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(child));
  }
  return node;
}

const motionOff = () =>
  window.matchMedia("(prefers-reduced-motion: reduce)").matches || document.documentElement.dataset.motion === "off";
const sleep = (ms) => new Promise((r) => setTimeout(r, motionOff() ? 0 : ms));
const isTrainer = () => auth && auth.role === "trainer";
const isLoggedIn = () => auth && !$("#app-view").classList.contains("hidden");
const safeLink = (url) => /^https?:\/\//i.test(url || "");
const trunc = (s, n = 60) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
const norm = (s) => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

function locale() {
  return { ro: "ro-RO", en: "en-GB", fr: "fr-FR", it: "it-IT", es: "es-ES", de: "de-DE" }[lang];
}

function timeAgo(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return t("time.now");
  if (s < 3600) return t("time.min", Math.floor(s / 60));
  if (s < 86400) return t("time.h", Math.floor(s / 3600));
  return new Date(iso).toLocaleDateString(locale(), { day: "numeric", month: "short" });
}

function countdown(iso) {
  const ms = new Date(iso).getTime() - Date.now();
  if (ms < 0) return { text: t("time.overdue"), late: true };
  const d = Math.floor(ms / 86400000), h = Math.floor((ms % 86400000) / 3600000), m = Math.floor((ms % 3600000) / 60000);
  const parts = d ? [t("time.d", d), t("time.hh", h)] : h ? [t("time.hh", h), t("time.mm", m)] : [t("time.mm", m)];
  return { text: t("time.left", parts.join(" ")), late: false };
}

function hue(name) {
  let h = 0;
  for (const c of name || "") h = (h * 31 + c.charCodeAt(0)) % 360;
  return h;
}

function avatar(name, small = true) {
  if (!name || name === "Anonim") return el("span", { class: `avatar anon ${small ? "sm" : ""}` }, "?");
  const initials = name.trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  return el("span", { class: `avatar ${small ? "sm" : ""}`, style: `--h:${hue(name)}` }, initials);
}

let toastTimer;
function toast(msg) {
  const box = $("#toast");
  box.textContent = msg;
  box.classList.remove("hidden");
  box.style.animation = "none"; void box.offsetWidth; box.style.animation = "";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => box.classList.add("hidden"), 2800);
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast(t("g.copied")); } catch (_) {}
}

// Markdown minimal și sigur (doar noduri text): paragrafe, liste, cod, `cod`, **bold**
function inlineMd(text) {
  const out = [];
  const re = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    out.push(tok.startsWith("`") ? el("code", {}, tok.slice(1, -1)) : el("strong", {}, tok.slice(2, -2)));
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function renderMd(src) {
  const root = el("div", { class: "md" });
  src.split(/```[^\n]*\n?/).forEach((part, i) => {
    if (i % 2 === 1) {
      const code = part.replace(/\n$/, "");
      root.append(el("pre", {}, el("code", {}, code),
        el("button", { class: "copy-btn small", type: "button", onclick: () => copy(code) }, t("g.copy"))));
      return;
    }
    let list = null;
    for (const line of part.split("\n")) {
      const item = line.match(/^\s*(?:[-*]|\d+\.)\s+(.*)/);
      if (item) {
        if (!list) { list = el(/^\s*\d/.test(line) ? "ol" : "ul"); root.append(list); }
        list.append(el("li", {}, inlineMd(item[1])));
      } else {
        list = null;
        if (line.trim()) root.append(el("p", {}, inlineMd(line.replace(/^#+\s*/, ""))));
      }
    }
  });
  return root;
}

function richText(src) {
  // Pașii de predare au <b>…</b>; îi transformăm în noduri, fără innerHTML
  return src.split(/(<b>.*?<\/b>)/).filter(Boolean).map((part) =>
    part.startsWith("<b>") ? el("b", {}, part.slice(3, -4)) : part);
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function confetti() {
  if (motionOff()) return;
  const canvas = $("#confetti");
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  canvas.width = innerWidth * dpr;
  canvas.height = innerHeight * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const colors = ["#8b5cf6", "#22d3ee", "#f472b6", "#34d399", "#fbbf24"];
  const parts = Array.from({ length: 150 }, () => ({
    x: innerWidth / 2 + (Math.random() - .5) * 120, y: innerHeight * .35,
    vx: (Math.random() - .5) * 14, vy: Math.random() * -13 - 4,
    r: Math.random() * 6 + 4, rot: Math.random() * 6, vr: (Math.random() - .5) * .3,
    c: colors[Math.floor(Math.random() * colors.length)],
  }));
  const start = performance.now();
  (function frame(now) {
    ctx.clearRect(0, 0, innerWidth, innerHeight);
    for (const p of parts) {
      p.vy += .35; p.vx *= .99; p.x += p.vx; p.y += p.vy; p.rot += p.vr;
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rot);
      ctx.fillStyle = p.c; ctx.fillRect(-p.r / 2, -p.r / 4, p.r, p.r / 2);
      ctx.restore();
    }
    if (now - start < 2600) requestAnimationFrame(frame);
    else ctx.clearRect(0, 0, innerWidth, innerHeight);
  })(start);
}

function setPref(name, value) {
  document.documentElement.dataset[name] = value;
  try { localStorage.setItem(`cutia-${name}`, value); } catch (_) {}
}

// ================================================================ login

let terminalRunning = false;
async function runTerminal() {
  if (terminalRunning) return;
  terminalRunning = true;
  const body = $("#term-body");
  while (!$("#login-view").classList.contains("hidden")) {
    body.replaceChildren();
    for (const [prefix, text, typed] of t("term")) {
      const cls = prefix === "$ " ? "t-prompt" : prefix === "? " ? "t-q" : prefix === "✓ " ? "t-ok" : "t-ai";
      const span = el("span", { class: typed ? "" : cls });
      const cursor = el("span", { class: "cursor" });
      body.append(el("div", {}, el("span", { class: cls }, prefix), span, cursor));
      if (typed && !motionOff()) {
        for (let i = 1; i <= text.length; i++) { span.textContent = text.slice(0, i); await sleep(28 + Math.random() * 40); }
      } else {
        span.textContent = text;
      }
      await sleep(typed ? 350 : 550);
      cursor.remove();
    }
    body.lastChild.append(el("span", { class: "cursor" }));
    if (motionOff()) break;
    await sleep(3500);
  }
  terminalRunning = false;
}

function renderMarquee() {
  const chips = cfg.topics.map((k) => {
    const tp = topic(k);
    return el("span", { class: "chip", style: `--h:${tp.hue}` }, tp.icon, " ", tp.title);
  });
  $("#topic-marquee .marquee-track").replaceChildren(...chips, ...chips.map((c) => c.cloneNode(true)));
}

function lastUser() {
  try { return JSON.parse(localStorage.getItem("cutia-last")); } catch (_) { return null; }
}

function rememberUser(name, email) {
  try { localStorage.setItem("cutia-last", JSON.stringify({ name, email })); } catch (_) {}
}

function renderLogin() {
  const last = lastUser();
  const first = last && last.name ? last.name.split(/\s+/)[0] : null;
  const up = authMode === "up";
  // „reset” = parolă nouă din linkul de pe email; „code” = lipsește codul clasei după Google / confirmare
  const special = authMode === "reset" || authMode === "code";
  // Numele tău apare automat data viitoare: „Bine ai revenit, Madalina!”
  $("#login-title").textContent = special ? t(authMode === "reset" ? "login.resetTitle" : "login.codeTitle")
    : first && !up ? t("login.welcomeBack", first) : t("login.title");
  $("#not-you").classList.toggle("hidden", !first || up || special);
  $(".auth-tabs").classList.toggle("hidden", special);
  $("#email-field").classList.toggle("hidden", special);
  $("#password-field").classList.toggle("hidden", authMode === "code");
  if (first) {
    $("#not-you-btn").textContent = t("login.notYou", first);
    if (!$("#login-email").value && last.email) $("#login-email").value = last.email;
  }
  document.querySelectorAll(".auth-tabs button").forEach((b) => {
    b.classList.toggle("on", b.dataset.auth === authMode);
    b.setAttribute("aria-selected", String(b.dataset.auth === authMode));
  });
  $("#name-field").classList.toggle("hidden", !up);
  $("#class-field").classList.toggle("hidden", !(up && cfg.class_code_required) && authMode !== "code");
  $("#trainer-field").classList.toggle("hidden", !up);
  const newPass = up || authMode === "reset";
  $("#login-password").placeholder = t(newPass ? "login.passwordNewPh" : "login.passwordPh");
  $("#login-password").autocomplete = newPass ? "new-password" : "current-password";
  $("#auth-hint").textContent = up ? t(cfg.supabase ? "login.hintSupabase" : "login.hintNew") : "";
  $("#auth-submit").textContent = t({ up: "login.create", reset: "login.resetSave", code: "login.codeSave" }[authMode] || "login.submit");
  $("#forgot").classList.toggle("hidden", up || special || !!cfg.supabase);
  // Mod demo: conturile de test, la un click
  $("#demo-box").classList.toggle("hidden", !cfg.demo || special);
  if (cfg.demo) {
    $("#demo-lead").textContent = t("login.demoLead", cfg.demo.password);
    $("#demo-accounts").replaceChildren(...cfg.demo.accounts.map((d) => el("button", { type: "button", class: "small ghost", onclick: () => {
      authMode = "in"; renderLogin();
      $("#login-email").value = d.email; $("#login-password").value = cfg.demo.password; $("#login-password").focus();
    } }, `${d.name} · ${t("role." + d.role)}`)));
  }
  $("#forgot-supa").classList.toggle("hidden", up || special || !cfg.supabase);
  $("#secured-by").classList.toggle("hidden", !cfg.supabase);
  renderMarquee();
  setupGoogle();
}

function loginInfo(text) {
  $("#login-info").textContent = text || "";
  $("#login-info").classList.toggle("hidden", !text);
}

document.querySelectorAll(".auth-tabs button").forEach((b) => b.addEventListener("click", () => {
  authMode = b.dataset.auth;
  $("#login-error").textContent = "";
  loginInfo("");
  renderLogin();
  (authMode === "up" ? $("#login-name") : $("#login-email")).focus();
}));

$("#not-you-btn").addEventListener("click", () => {
  try { localStorage.removeItem("cutia-last"); } catch (_) {}
  $("#login-email").value = "";
  renderLogin();
  $("#login-email").focus();
});

async function finishLogin(data) {
  auth = data;
  try { localStorage.setItem("cutia-auth", JSON.stringify(auth)); } catch (_) {}
  ["#login-password", "#login-code", "#login-class"].forEach((id) => ($(id).value = ""));
  await start(true);
}

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-error").textContent = "";
  loginInfo("");
  const email = $("#login-email").value.trim();
  try {
    if (authMode === "reset" || authMode === "code") {
      const data = authMode === "reset"
        ? await api("/api/auth/supabase/new-password", { method: "POST", body: { access_token: supaToken, password: $("#login-password").value } })
        : await api("/api/auth/supabase", { method: "POST", body: { access_token: supaToken, class_code: $("#login-class").value } });
      supaToken = null;
      authMode = "in";
      rememberUser(data.name, "");
      await finishLogin(data);
      return;
    }
    const data = authMode === "up"
      ? await api("/api/register", {
          method: "POST",
          body: {
            name: $("#login-name").value, email, password: $("#login-password").value,
            class_code: $("#login-class").value, trainer_code: $("#login-code").value,
          },
        })
      : await api("/api/login", { method: "POST", body: { email, password: $("#login-password").value } });
    if (data.confirm_email) {
      // Supabase a trimis emailul de confirmare: contul se activează din link
      $("#login-password").value = "";
      authMode = "in";
      renderLogin();
      loginInfo(t("login.confirmSent", email));
      return;
    }
    rememberUser(data.name, email);
    await finishLogin(data);
  } catch (err) {
    $("#login-error").textContent = err.message;
  }
});

// ---------------------------------------------------------------- Supabase (dacă serverul are SUPABASE_URL)
// Tokenul primit înapoi de la Supabase (linkul din email sau Google) stă doar în memorie
// până îl verifică serverul; din bara de adrese îl ștergem imediat.
let supaToken = null;

$("#forgot-btn").addEventListener("click", async () => {
  $("#login-error").textContent = "";
  const email = $("#login-email").value.trim();
  if (!email) {
    $("#login-error").textContent = t("login.needEmail");
    $("#login-email").focus();
    return;
  }
  try {
    await api("/api/auth/supabase/recover", { method: "POST", body: { email } });
    loginInfo(t("login.resetSent", email));
  } catch (err) { $("#login-error").textContent = err.message; }
});

$("#supa-google").addEventListener("click", () => {
  // Codul clasei (dacă l-ai scris) te așteaptă până te întorci de la Google
  try { sessionStorage.setItem("cutia-class", $("#login-class").value); } catch (_) {}
  const back = location.origin + location.pathname;
  location.href = `${cfg.supabase.url}/auth/v1/authorize?provider=google&redirect_to=${encodeURIComponent(back)}`;
});

async function handleSupabaseReturn() {
  const hash = new URLSearchParams(location.hash.slice(1));
  if (!hash.has("access_token") && !hash.has("error")) return false;
  history.replaceState(null, "", location.pathname + location.search);
  if (!cfg.supabase) return false;
  loginInfo("");
  $("#login-error").textContent = "";
  if (hash.has("error")) {
    $("#login-error").textContent = t("login.linkError");
    return true;
  }
  supaToken = hash.get("access_token");
  if (hash.get("type") === "recovery") {
    authMode = "reset";
    renderLogin();
    $("#login-password").focus();
    return true;
  }
  let classCode = "";
  try { classCode = sessionStorage.getItem("cutia-class") || ""; sessionStorage.removeItem("cutia-class"); } catch (_) {}
  try {
    const data = await api("/api/auth/supabase", { method: "POST", body: { access_token: supaToken, class_code: classCode } });
    supaToken = null;
    rememberUser(data.name, "");
    await finishLogin(data);
  } catch (err) {
    if (err.status === 403 && cfg.class_code_required) {
      authMode = "code";
      renderLogin();
      $("#login-class").focus();
      if (!classCode) return true;  // titlul „Încă un pas: codul clasei” spune deja ce lipsește
    }
    $("#login-error").textContent = err.message;
  }
  return true;
}

// Linkul deschis în același tab (doar se schimbă #...) ajunge tot aici
window.addEventListener("hashchange", () => {
  const view = location.hash.slice(1);
  if (isLoggedIn() && Object.prototype.hasOwnProperty.call(VIEW_SPACE, view)) showView(view);
  else handleSupabaseReturn();
});

// ---------------------------------------------------------------- Google (doar dacă serverul are GOOGLE_CLIENT_ID)
let googleReady = false;
function setupGoogle() {
  const wrap = $("#google-wrap");
  const special = authMode === "reset" || authMode === "code";
  if (cfg.supabase) {
    wrap.classList.toggle("hidden", !cfg.supabase.google || special);
    $("#supa-google").classList.remove("hidden");
    $("#google-btn").classList.add("hidden");
    return;
  }
  wrap.classList.toggle("hidden", !cfg.google_client_id);
  if (!cfg.google_client_id) return;
  const render = () => {
    google.accounts.id.initialize({ client_id: cfg.google_client_id, callback: onGoogle });
    $("#google-btn").replaceChildren();
    google.accounts.id.renderButton($("#google-btn"), {
      theme: document.documentElement.dataset.theme === "light" ? "outline" : "filled_black",
      shape: "pill", size: "large", text: "continue_with", locale: lang, width: 300,
    });
  };
  if (googleReady) { render(); return; }
  if (document.getElementById("gsi-script")) return;
  const s = document.createElement("script");
  s.id = "gsi-script";
  s.src = "https://accounts.google.com/gsi/client";
  s.async = true;
  s.onload = () => { googleReady = true; render(); };
  s.onerror = () => wrap.classList.add("hidden");
  document.head.append(s);
}

async function onGoogle(response) {
  $("#login-error").textContent = "";
  try {
    const data = await api("/api/auth/google", {
      method: "POST", body: { credential: response.credential, class_code: $("#login-class").value },
    });
    rememberUser(data.name, "");
    await finishLogin(data);
  } catch (err) {
    $("#login-error").textContent = err.message;
    // Primul cont cu Google, când clasa cere cod: arătăm câmpul pentru cod
    if (cfg.class_code_required && authMode !== "up") { authMode = "up"; renderLogin(); }
  }
}

$("#logout-btn").addEventListener("click", () => logout());

function logout(expired = false) {
  if (auth && !expired) fetch("/api/logout", { method: "POST", headers: { Authorization: `Bearer ${auth.token}` } }).catch(() => {});
  auth = null;
  supaToken = null;
  digestData = null; digestDate = null;
  live = null;
  quests = null;
  recap = null;
  clearTimeout(livePollTimer);
  clearTimeout(digestPoll);
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  speaking = false;
  try { localStorage.removeItem("cutia-auth"); } catch (_) {}
  // Pe un calculator comun, textul nescris al cuiva nu rămâne pe ecran pentru următorul
  [...LOCAL_DRAFTS, "#p-title", "#p-description", "#p-audience", "#f-title", "#f-description", "#f-audience"].forEach((sel) => ($(sel).value = ""));
  clearTimeout(draftTimer);
  drafts = []; currentDraftId = null; draftSavedAt = null;
  closeDrawer();
  closeMenus();
  $("#app-view").classList.add("hidden");
  $("#user-box").classList.add("hidden");
  $("#points-chip").classList.add("hidden");
  document.querySelectorAll(".app-only").forEach((n) => n.classList.add("hidden"));
  $("#login-view").classList.remove("hidden");
  renderLogin();
  runTerminal();
}

// ================================================================ shell

const VIEW_SPACE = {
  home: null, messages: "private", questions: "private", submissions: "private", workshop: "private",
  live: "public", box: "public", showcase: "public", news: "public", points: "public", guide: "public",
};

function showView(name) {
  currentView = name;
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("hidden", v.id !== `view-${name}`));
  $("#sidebar").classList.remove("open");
  updateStatusSpace();
  if (name === "messages") loadChat();
  if (name === "news" && !newsData && !newsLoading) loadNews();
  if (name === "news" && !digestData) loadDigest();
  if (name === "points") { loadPoints(); loadQuests(); }
  if (name === "workshop") showWs(wsTab);
  if (name === "live") { loadLive(); scheduleLive(); }
  if (name === "showcase") loadShowcase();
  if (name === "guide") { loadHall(); loadFaq(); }
  window.scrollTo({ top: 0, behavior: motionOff() ? "auto" : "smooth" });
}

function updateStatusSpace() {
  const space = VIEW_SPACE[currentView];
  $("#sb-space").textContent = space ? t(space === "public" ? "space.public" : "space.private") : "⌂ " + t("nav.home");
}

document.querySelectorAll(".nav-item").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));
document.querySelectorAll("[data-goto]").forEach((b) => b.addEventListener("click", () => showView(b.dataset.goto)));
$("#more-btn").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
$("#points-chip").addEventListener("click", () => showView("points"));

function renderHeader() {
  const h = new Date().getHours();
  const hello = h < 11 ? t("greet.morning") : h < 18 ? t("greet.day") : t("greet.evening");
  const first = auth.name.split(/\s+/)[0];
  const T = isTrainer();
  $("#user-role").textContent = t(T ? "role.trainer" : "role.student");
  $("#greet-eyebrow").textContent = t(T ? "greet.trainer" : "greet.student");
  $("#greet-title").textContent = `${hello}, ${first} 👋`;
  $("#home-lead").textContent = t(T ? "home.leadT" : "home.lead");
  $("#home-recent-title").textContent = t(T ? "home.recentT" : "home.recent");
  $("#questions-title").textContent = t(T ? "q.class" : "q.mine");
  $("#submissions-title").textContent = t(T ? "s.all" : "s.mine");
  $("#nav-private-label").textContent = t(T ? "nav.privateT" : "nav.private");
  $("#q-lead").textContent = t(T ? "q.leadT" : "q.lead");
  $("#s-lead").textContent = t(T ? "s.viewLeadT" : "s.viewLead");
  $("#m-lead").textContent = t(T ? "m.leadT" : "m.lead");
  $("#pt-lead").textContent = t(T ? "pt.leadT" : "pt.lead");
  document.querySelectorAll("[data-space]").forEach((n) => {
    n.textContent = n.dataset.space === "public" ? t("space.public") : t(T ? "space.privateT" : "space.private");
  });
  const ai = t(cfg.ai ? "status.aiOn" : "status.aiOff");
  $("#ai-status").textContent = (cfg.ai ? "● " : "○ ") + ai;
  $("#sb-ai").textContent = ai;
  $("#sb-online").textContent = t("status.online");
  $("#sb-lang").textContent = `${lang.toUpperCase()} · vibe coding · ${auth.name}`;
  updateStatusSpace();
}

// ---------------------------------------------------------------- robotul de bun venit
function introEnabled() {
  try { return localStorage.getItem("cutia-intro") !== "off"; } catch (_) { return true; }
}

async function playIntro() {
  // intro.js e modul și se încarcă separat; îl așteptăm puțin, apoi renunțăm
  for (let i = 0; i < 25 && !window.CutiaIntro; i++) await new Promise((r) => setTimeout(r, 100));
  if (!window.CutiaIntro) return;
  try { sessionStorage.setItem("cutia-intro-done", "1"); } catch (_) {}
  await window.CutiaIntro.play({
    hello: t("intro.hi"), name: auth.name.split(/\s+/)[0], line: t("intro.line"),
    skipLabel: t("intro.skip"), durationMs: INTRO_MS,
  });
}

async function start(fromLogin = false) {
  let me;
  try {
    me = await api("/api/me");
  } catch (err) {
    // Doar o sesiune expirată te scoate din cont; fără internet, aplicația se deschide cu ce știe
    if (err.status === 401 || !auth) { logout(true); return; }
    me = { name: auth.name, role: auth.role, email: auth.email, prefs: auth.prefs || {}, has_password: auth.has_password };
    toast(t("app.offline"));
  }
  // Setările serverului (AI, notificări) pot lipsi dacă pagina s-a deschis fără internet
  api("/api/config").then((c) => { cfg = c; }).catch(() => {});
  // Limba aleasă pe alt dispozitiv te urmează, dacă aici n-ai ales alta
  let localLang = null;
  try { localLang = localStorage.getItem("cutia-lang"); } catch (_) {}
  if (me.prefs && me.prefs.lang && !localLang && me.prefs.lang !== lang) await setLang(me.prefs.lang);
  auth.prefs = me.prefs || {};
  auth.email = me.email;
  auth.has_password = me.has_password;

  $("#login-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  $("#user-box").classList.remove("hidden");
  document.querySelectorAll(".app-only").forEach((n) => n.classList.remove("hidden"));
  $("#points-chip").classList.toggle("hidden", isTrainer());
  $("#user-name").textContent = auth.name;
  const av = avatar(auth.name, false);
  av.id = "user-avatar";
  $("#user-avatar").replaceWith(av);
  document.querySelectorAll(".student-only").forEach((n) => n.classList.toggle("hidden", isTrainer()));
  document.querySelectorAll(".trainer-only").forEach((n) => n.classList.toggle("hidden", !isTrainer()));
  $("#chat-layout").classList.toggle("trainer", isTrainer());
  $("#thread-list").classList.toggle("hidden", !isTrainer());
  lastStats = {};
  myPoints = null;
  renderHeader();
  renderChips();
  renderTopicFilter();
  renderSubmissionForm();
  renderMessages();
  restoreLocalDrafts();
  // Linkurile din notificări deschid direct ecranul potrivit (#live, #questions, …)
  const fromLink = location.hash.slice(1);
  showView(Object.prototype.hasOwnProperty.call(VIEW_SPACE, fromLink) ? fromLink : "home");
  let seenThisSession = false;
  try { seenThisSession = Boolean(sessionStorage.getItem("cutia-intro-done")); } catch (_) {}
  const intro = introEnabled() && !motionOff() && (fromLogin || !seenThisSession) ? playIntro() : Promise.resolve();
  await Promise.all([refresh(), intro]);
  loadNews();
  loadDigest();
  loadLive();
  scheduleLive();
  loadQuests();
  loadRecap();
  maybeOnboard();
}

function renderAll() {
  renderHeader();
  renderChips();
  renderTopicFilter();
  renderSubmissionForm();
  renderAssignments();
  renderQuestions();
  renderSubmissions();
  renderProposals();
  renderDrafts();
  renderMessages();
  renderGuide();
  renderPoints();
  renderNews();
  renderByte();
  renderHome(true);
  renderNotifications();
  if (!$("#drawer").classList.contains("hidden")) {
    if ($("#drawer").dataset.mode === "settings") openSettings();
    else openTopic($("#drawer").dataset.topic);
  }
}

// ================================================================ keyboard

document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k" && isLoggedIn()) {
    e.preventDefault();
    openPalette();
    return;
  }
  if (e.key === "Escape") { closeDrawer(); closeMenus(); closePalette(); $("#sidebar").classList.remove("open"); }
  const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
  if (e.key === "/" && !typing && isLoggedIn()) {
    const search = document.querySelector('.view:not(.hidden) input[type="search"]');
    if (search) { e.preventDefault(); search.focus(); }
  }
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && typing) {
    const form = document.activeElement.closest("form");
    if (form) { e.preventDefault(); form.requestSubmit(); }
  }
});

// ================================================================ menus (limbă, notificări)

function closeMenus() {
  document.querySelectorAll(".menu").forEach((m) => m.classList.add("hidden"));
  document.querySelectorAll("[aria-expanded]").forEach((b) => b.setAttribute("aria-expanded", "false"));
}

function toggleMenu(btn, menu) {
  const open = menu.classList.contains("hidden");
  closeMenus();
  if (open) { menu.classList.remove("hidden"); btn.setAttribute("aria-expanded", "true"); }
  return open;
}

$("#lang-btn").addEventListener("click", (e) => { e.stopPropagation(); toggleMenu($("#lang-btn"), $("#lang-menu")); });
$("#bell-btn").addEventListener("click", (e) => {
  e.stopPropagation();
  if (toggleMenu($("#bell-btn"), $("#notif-menu"))) {
    renderNotifications();
    markSeen();
  }
});
document.addEventListener("click", (e) => { if (!e.target.closest(".menu-wrap")) closeMenus(); });

// ================================================================ notifications

function seenKey() { return `cutia-seen-${auth.role}-${auth.name.toLowerCase()}`; }
function lastSeen() { try { return localStorage.getItem(seenKey()) || ""; } catch (_) { return ""; } }
function markSeen() {
  try { localStorage.setItem(seenKey(), new Date().toISOString()); } catch (_) {}
  setTimeout(renderBell, 1500);
}

function notifications() {
  const items = [];
  const nowIso = new Date().toISOString();
  if (isTrainer()) {
    if (unread) items.push({ at: nowIso, icon: "✉", text: t("notif.dmT", unread), view: "messages" });
    questions.filter((q) => !q.answer).forEach((q) =>
      items.push({ at: q.created_at, icon: "?", text: t("notif.question", q.anonymous ? t("q.anonTag") : q.author), sub: trunc(q.text), view: "questions" }));
    submissions.filter((x) => x.status === "sent").forEach((x) =>
      items.push({ at: x.created_at, icon: "⇪", text: t("notif.submission", x.author), sub: trunc(x.title), view: "submissions" }));
  } else {
    if (unread) items.push({ at: nowIso, icon: "✉", text: t("notif.dm", unread), view: "messages" });
    questions.filter((q) => q.answer).forEach((q) =>
      items.push({ at: q.answered_at, icon: "🧑‍🏫", text: t("notif.answer", trunc(q.text, 40)), view: "questions" }));
    submissions.filter((x) => x.reviewed_at).forEach((x) =>
      items.push({ at: x.reviewed_at, icon: "💬", text: t("notif.feedback", trunc(x.title, 40)), view: "submissions" }));
    proposals.filter((p) => p.mine && p.chosen).forEach((p) =>
      items.push({ at: p.chosen_at || p.created_at, icon: "🏆", text: t("notif.chosen", trunc(p.title, 40)), view: "box" }));
  }
  if (digestData && digestData.digest && !digestDate) items.push({ at: digestData.digest.created_at, icon: "📰", text: t("byte.notif"), sub: digestData.digest.title || "", view: "news" });
  announcements.forEach((a) => items.push({ at: a.created_at, icon: "📣", text: t("notif.announcement", trunc(a.text, 50)), view: "home" }));
  assignments.forEach((a) => items.push({ at: a.created_at, icon: "📌", text: t("notif.assignment", trunc(a.title, 50)), view: "submissions" }));
  return items.filter((i) => i.at).sort((a, b) => (a.at < b.at ? 1 : -1)).slice(0, 15);
}

function renderBell() {
  if (!auth) return;
  const seen = lastSeen();
  const n = notifications().filter((i) => i.at > seen).length;
  $("#bell-dot").textContent = n > 9 ? "9+" : n;
  $("#bell-dot").classList.toggle("hidden", n === 0);
}

function renderNotifications() {
  if (!auth) return;
  renderBell();
  const seen = lastSeen();
  const items = notifications();
  $("#notif-menu").replaceChildren(
    el("div", { class: "notif-head" }, t("notif.title"),
      el("button", { class: "link-btn", style: "width:auto", onclick: () => { markSeen(); closeMenus(); } }, t("notif.markRead"))),
    ...(items.length ? items.map((i) => el("button", {
      class: `notif-item ${i.at > seen ? "unread" : ""}`,
      onclick: () => { closeMenus(); showView(i.view); },
    }, el("span", { class: "ni" }, i.icon), el("span", { class: "nt" }, i.text, i.sub ? el("small", {}, i.sub) : null, el("small", {}, timeAgo(i.at)))))
      : [el("div", { class: "empty" }, t("notif.empty"))]));
}

// ================================================================ home

function renderStats(instant = false) {
  const answered = questions.filter((q) => q.answer).length;
  const stats = isTrainer()
    ? [
        ["open", questions.length - answered, "stat.open", true],
        ["toReview", submissions.filter((x) => x.status === "sent").length, "act.reviewT", true],
        ["unread", unread, "stat.unread", true],
        ["proposals", proposals.length, "stat.proposalsT"],
      ]
    : [
        ["points", myPoints ? myPoints.total : 0, "stat.points", true],
        ["mine", questions.length, "stat.mine"],
        ["subs", submissions.length, "nav.submissions"],
        ["proposals", proposals.length, "stat.proposals"],
      ];
  $("#stats").replaceChildren(...stats.map(([key, value, label, hl]) => {
    const from = instant ? value : lastStats[key] ?? 0;
    const b = el("b", {}, String(from));
    countUp(b, from, value);
    lastStats[key] = value;
    return el("div", { class: `stat ${hl && value ? "hl" : ""}` }, b, el("span", {}, t(label)));
  }));
}

function countUp(node, from, to) {
  if (from === to || motionOff()) { node.textContent = to; return; }
  const t0 = performance.now();
  (function step(now) {
    const k = Math.min(1, (now - t0) / 600);
    node.textContent = Math.round(from + (to - from) * (1 - Math.pow(1 - k, 3)));
    if (k < 1) requestAnimationFrame(step);
  })(t0);
}

function levelProgress(p) {
  const lvl = p.level;
  if (!lvl.next_min) return { pct: 100, text: t("home.maxLevel") };
  return {
    pct: Math.round(((p.total - lvl.min) / (lvl.next_min - lvl.min)) * 100),
    text: t("home.toNext", lvl.next_min - p.total, t("lvl." + lvl.next_key)),
  };
}

function renderLevelCard() {
  const card = $("#level-card");
  card.classList.toggle("hidden", isTrainer() || !myPoints);
  if (isTrainer() || !myPoints) return;
  const prog = levelProgress(myPoints);
  card.replaceChildren(
    el("div", { class: "level-badge" }, String(myPoints.level.index)),
    el("div", {},
      el("b", {}, `${t("pt.level", myPoints.level.index)} · ${t("lvl." + myPoints.level.key)}`),
      el("div", { class: "xp" }, el("i", { style: `width:${prog.pct}%` })),
      el("small", {}, prog.text)),
    quests && quests.streak.current ? el("div", { class: "streak-chip", title: t("qs.streakTitle") }, "🔥 ", el("b", {}, String(quests.streak.current)), " ", t(quests.streak.current === 1 ? "qs.day1" : "qs.days")) : null,
    el("button", { class: "ghost big-btn", onclick: () => showView("points") }, el("span", { class: "big" }, `⚡ ${myPoints.total}`)));
}

function renderAnnouncements() {
  const box = $("#announce-box");
  const list = announcements.slice(0, 3);
  box.classList.toggle("hidden", !isTrainer() && list.length === 0);
  const rows = list.map((a) => el("div", { class: "ann" },
    el("span", { class: "pin" }, a.pinned ? "📌" : "📣"),
    el("div", { class: "md-wrap", style: "flex:1;min-width:0" }, renderMd(a.text), el("small", { class: "muted" }, `${a.author} · ${timeAgo(a.created_at)}`)),
    isTrainer() ? el("button", { class: "ghost small", title: t("a.delete"), onclick: async () => {
      try { await api(`/api/announcements/${a.id}`, { method: "DELETE" }); loadAnnouncements(); } catch (err) { toast(err.message); }
    } }, "✕") : null));
  const children = [el("div", { class: "panel-head" }, el("h3", {}, t("home.announcements")))];
  if (isTrainer()) {
    const area = el("textarea", { rows: 2, maxlength: 2000, placeholder: t("home.announcePh") });
    const pin = el("input", { type: "checkbox" });
    const form = el("form", { class: "ann-form" }, area,
      el("div", { class: "row" }, el("label", { class: "check" }, pin, " ", t("home.pin")),
        el("button", { type: "submit", class: "primary small" }, t("home.post"))));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!area.value.trim()) return;
      try {
        await api("/api/announcements", { method: "POST", body: { text: area.value, pinned: pin.checked } });
        toast(t("home.posted"));
        loadAnnouncements();
      } catch (err) { toast(err.message); }
    });
    children.push(form);
  }
  box.replaceChildren(...children, ...rows);
}

function actionCard(view, h, top, title, desc, after) {
  const card = el("button", {
    class: "action-card", style: `--h:${h}`,
    onclick: () => { showView(view); if (after) setTimeout(after, 60); },
  }, top, el("b", {}, title), el("span", { class: "d" }, desc));
  return card;
}

function renderHome(instant = false) {
  if (!auth) return;
  renderStats(instant);
  renderLevelCard();
  renderAnnouncements();
  const open = questions.filter((q) => !q.answer).length;
  const toReview = submissions.filter((x) => x.status === "sent").length;
  const num = (n) => el("span", { class: "big-num" }, String(n));
  const ico = (s) => el("span", { class: "ico mono" }, s);
  const cards = isTrainer()
    ? [
        actionCard("questions", 330, num(open), t("nav.questions"), t("act.answerT")),
        actionCard("submissions", 190, num(toReview), t("nav.submissions"), t("act.reviewT")),
        actionCard("messages", 20, num(unread), t("nav.messages"), t("act.unreadT")),
        actionCard("box", 265, num(proposals.length), t("nav.box"), t("act.ideasT")),
        actionCard("news", 210, ico("◉"), t("act.news"), t("act.newsD")),
        actionCard("points", 45, ico("⚡"), t("nav.points"), t("pt.bonusTitle")),
      ]
    : [
        actionCard("questions", 330, ico("?"), t("act.ask"), t("act.askD"), () => $("#question-text").focus()),
        actionCard("submissions", 190, ico("⇪"), t("act.submit"), t("act.submitD"), () => $("#s-title").focus()),
        actionCard("box", 265, ico("✦"), t("act.idea"), t("act.ideaD"), () => $("#p-description").focus()),
        actionCard("messages", 20, ico("✉"), t("act.msg"), t("act.msgD"), () => $("#chat-input").focus()),
        actionCard("news", 210, ico("◉"), t("act.news"), t("act.newsD")),
        actionCard("guide", 150, ico("#"), t("act.learn"), t("act.learnD")),
      ];
  cards.forEach((c, i) => (c.style.animationDelay = `${i * 50}ms`));
  $("#actions").replaceChildren(...cards);

  // Teme cu termen
  const upcoming = assignments
    .filter((a) => a.due_at)
    .sort((a, b) => (a.due_at < b.due_at ? -1 : 1))
    .filter((a) => isTrainer() || !a.submitted || new Date(a.due_at) > new Date())
    .slice(0, 4);
  $("#home-deadlines").replaceChildren(...(upcoming.length ? upcoming.map((a) => {
    const cd = countdown(a.due_at);
    const badge = !isTrainer() && a.submitted
      ? el("span", { class: "countdown done" }, t("a.done"))
      : el("span", { class: `countdown ${cd.late ? "late" : ""}` }, cd.text);
    return el("button", { class: "mini", onclick: () => showView("submissions") },
      el("span", { class: "k" }, "📌"), el("span", { class: "t" }, a.title), badge);
  }) : [el("div", { class: "empty" }, t("home.noDeadlines"))]));

  // Știrea zilei din AI News
  const insight = $("#home-insight");
  const brief = digestData && digestData.digest;
  if (brief && (brief.tldr || brief.stories.length)) {
    insight.replaceChildren(el("div", { class: "insight" },
      el("div", { class: "meta mono muted small" }, `🤖 Byte · ${t("byte.eyebrow")}`),
      el("h4", {}, brief.title || brief.stories[0].headline || brief.stories[0].title),
      el("p", {}, brief.tldr || brief.stories[0].why || trunc(brief.stories[0].summary || "", 200)),
      el("button", { class: "link-btn", onclick: () => showView("news") }, t("byte.open"))));
  }
  const top = newsData && newsData.items && newsData.items.length ? (newsData.items.find((i) => i.top) || newsData.items[0]) : null;
  if (brief && (brief.tldr || brief.stories.length)) {
    // briefing-ul lui Byte e deja afișat mai sus
  } else if (top) {
    insight.replaceChildren(el("div", { class: "insight" },
      el("div", { class: "meta mono muted small" }, `${top.source} · ${timeAgo(top.published)}`),
      el("h4", {}, top.headline || top.title),
      el("p", {}, top.why || top.summary),
      safeLink(top.link) ? el("a", { class: "link-btn", href: top.link, target: "_blank", rel: "noopener noreferrer" }, t("n.read")) : null));
  } else {
    insight.replaceChildren(el("div", { class: "empty" }, newsLoading || !newsData ? el("span", {}, t("n.loading"), el("span", { class: "dots" })) : t("n.empty")));
  }

  const recent = [
    ...questions.map((q) => ({ at: q.created_at, view: "questions", k: topic(q.category).icon, text: q.text,
      status: el("span", { class: `status ${q.answer ? "ok" : "open"}` }, t(q.answer ? "q.statusOk" : "q.statusOpen")) })),
    ...submissions.map((x) => ({ at: x.created_at, view: "submissions", k: t("kind." + x.kind).split(" ")[0], text: x.title,
      status: el("span", { class: `status ${x.status}` }, t("st." + x.status)) })),
  ].sort((a, b) => (a.at < b.at ? 1 : -1)).slice(0, 5);
  $("#home-recent").replaceChildren(...(recent.length ? recent.map((it) =>
    el("button", { class: "mini", onclick: () => showView(it.view) },
      el("span", { class: "k" }, it.k), el("span", { class: "t" }, it.text), it.status))
    : [el("div", { class: "empty" }, t("home.nothing"))]));

  const best = proposals.filter((p) => p.status !== "withdrawn").sort((a, b) => b.votes - a.votes || b.id - a.id).slice(0, 5);
  $("#home-top").replaceChildren(...(best.length ? best.map((p) =>
    el("button", { class: "mini", onclick: () => showView("box") },
      el("span", { class: "k" }, p.chosen ? "★" : "✦"), el("span", { class: "t" }, p.title),
      el("span", { class: "votes" }, `▲ ${p.votes}`)))
    : [el("div", { class: "empty" }, t("home.nothing"))]));
}

// ================================================================ direct messages

async function loadUnread() {
  try { unread = (await api("/api/dm/unread")).unread; } catch (_) { return; }
  $("#m-badge").textContent = unread;
  $("#m-badge").classList.toggle("hidden", unread === 0);
}

async function loadChat() {
  if (!auth) return;
  try {
    if (isTrainer()) {
      // Întâi conversația deschisă (o marchează citită), apoi lista cu numărul de necitite
      if (activeThread) chat = (await api(`/api/dm/${encodeURIComponent(activeThread)}`)).messages;
      threads = (await api("/api/dm")).threads;
    } else {
      chat = (await api("/api/dm")).messages;
    }
  } catch (err) { toast(err.message); return; }
  renderMessages();
  loadUnread();
}

function renderMessages() {
  if (!auth) return;
  const layout = $("#chat-layout");
  layout.classList.toggle("has-thread", Boolean(activeThread));
  if (isTrainer()) {
    const q = norm($("#thread-search").value);
    const shown = threads.filter((th) => !q || norm(th.name).includes(q));
    $("#threads").replaceChildren(...(shown.length ? shown.map((th) =>
      el("button", { class: `thread ${th.student_key === activeThread ? "on" : ""}`, onclick: () => { activeThread = th.student_key; chat = []; loadChat(); } },
        avatar(th.name), el("span", { class: "tt" }, th.name, el("small", {}, th.last || "…")),
        th.unread ? el("span", { class: "badge" }, String(th.unread)) : null))
      : [el("div", { class: "empty" }, t("m.noStudents"))]));
  }
  const active = threads.find((th) => th.student_key === activeThread);
  const head = $("#chat-head");
  if (isTrainer()) {
    head.replaceChildren(...(active
      ? [el("button", { class: "ghost small back-btn", onclick: () => { activeThread = null; renderMessages(); } }, t("m.back")), avatar(active.name), active.name]
      : [el("span", { class: "muted" }, t("m.pick"))]));
  } else {
    head.replaceChildren(el("span", { class: "avatar sm", style: "--h:160" }, "🧑‍🏫"), t("m.trainer"),
      el("span", { class: "space private", style: "margin-left:auto" }, t("space.private")));
  }
  const canWrite = !isTrainer() || Boolean(activeThread);
  $("#chat-form").classList.toggle("hidden", !canWrite);
  const log = $("#chat-log");
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 60;
  if (!canWrite) {
    log.replaceChildren();
  } else if (!chat.length) {
    log.replaceChildren(el("div", { class: "empty" }, t("m.empty")));
  } else {
    log.replaceChildren(...chat.map((m) => el("div", { class: `bubble ${m.mine ? "mine" : ""}` },
      el("div", { class: "who" }, `${m.mine ? t("m.you") : m.from_role === "trainer" ? m.from_name + " · " + t("m.trainer") : m.from_name} · ${timeAgo(m.created_at)}`),
      renderMd(m.text))));
  }
  if (atBottom || !log.dataset.ready) { log.scrollTop = log.scrollHeight; log.dataset.ready = "1"; }
}

$("#thread-search").addEventListener("input", renderMessages);

const chatInput = $("#chat-input");
chatInput.addEventListener("input", () => {
  chatInput.style.height = "auto";
  chatInput.style.height = Math.min(chatInput.scrollHeight, 160) + "px";
});
chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.metaKey) { e.preventDefault(); $("#chat-form").requestSubmit(); }
});

$("#chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = chatInput.value.trim();
  if (!text) return;
  try {
    const path = isTrainer() ? `/api/dm/${encodeURIComponent(activeThread)}` : "/api/dm";
    const m = await api(path, { method: "POST", body: { text } });
    chat.push(m);
    chatInput.value = "";
    clearLocalDraft("#chat-input");
    chatInput.style.height = "auto";
    $("#chat-log").dataset.ready = "";
    renderMessages();
  } catch (err) { toast(err.message); }
});

function prefillMessage(text) {
  showView("messages");
  chatInput.value = text;
  chatInput.dispatchEvent(new Event("input"));
  chatInput.focus();
}

// ================================================================ questions

function renderChips() {
  $("#topic-chips").replaceChildren(...cfg.topics.map((k) => {
    const tp = topic(k);
    return el("button", {
      type: "button", role: "radio", "aria-checked": String(k === selectedTopic),
      class: `chip ${k === selectedTopic ? "on" : ""}`, style: `--h:${tp.hue}`,
      onclick: () => { selectedTopic = k; renderChips(); },
    }, tp.icon, " ", tp.title);
  }));
  const tp = topic(selectedTopic);
  $("#topic-hint").replaceChildren(t("q.tryFirst"), el("code", { title: t("g.copy"), onclick: () => copy(tp.prompt) }, tp.prompt));
}

function renderTopicFilter() {
  const select = $("#question-topic");
  const current = select.value || "all";
  select.replaceChildren(el("option", { value: "all" }, t("q.allTopics")),
    ...cfg.topics.map((k) => el("option", { value: k }, `${topic(k).icon} ${topic(k).title}`)));
  select.value = current;
}

$("#question-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const q = await api("/api/questions", {
      method: "POST",
      body: { text: $("#question-text").value, category: selectedTopic, anonymous: $("#question-anon").checked, faq_ok: $("#question-faq").checked },
    });
    $("#question-text").value = "";
    $("#question-faq").checked = false;
    clearLocalDraft("#question-text");
    toast(t("q.sent"));
    await loadQuestions();
    loadPoints();
    if (cfg.ai) requestAiAnswer(q.id);
  } catch (err) { toast(err.message); }
});

async function requestAiAnswer(id) {
  aiPending.add(id);
  renderQuestions();
  try {
    const updated = await api(`/api/questions/${id}/ai-answer`, { method: "POST" });
    questions = questions.map((q) => (q.id === id ? updated : q));
  } catch (err) {
    toast(err.message);
  } finally {
    aiPending.delete(id);
    renderQuestions();
  }
}

$("#question-search").addEventListener("input", renderQuestions);
$("#question-filter").addEventListener("change", renderQuestions);
$("#question-topic").addEventListener("change", renderQuestions);

async function loadQuestions() {
  questions = await api("/api/questions");
  renderQuestions();
  renderGuide();
  renderHome();
  renderBell();
}

function renderQuestions() {
  const term = norm($("#question-search").value.trim());
  const filter = $("#question-filter").value;
  const topicFilter = $("#question-topic").value || "all";
  const shown = questions.filter((q) => {
    if (filter === "open" && q.answer) return false;
    if (filter === "answered" && !q.answer) return false;
    if (topicFilter !== "all" && q.category !== topicFilter) return false;
    return !term || norm(`${q.text} ${q.answer || ""} ${q.ai_answer || ""} ${q.author}`).includes(term);
  });
  const open = questions.filter((q) => !q.answer).length;
  $("#q-badge").textContent = open;
  $("#q-badge").classList.toggle("hidden", !isTrainer() || open === 0);
  const list = $("#questions-list");
  if (!shown.length) {
    list.replaceChildren(el("div", { class: "empty" },
      t(questions.length ? "q.emptyFilter" : isTrainer() ? "q.emptyTrainer" : "q.emptyStudent")));
    return;
  }
  list.replaceChildren(...shown.map((q, i) => {
    const card = questionCard(q);
    card.style.animationDelay = `${Math.min(i, 8) * 40}ms`;
    return card;
  }));
}

function topicChip(key) {
  const tp = topic(key);
  return el("button", { type: "button", class: "topic-chip", style: `--h:${tp.hue}`, onclick: () => openTopic(key) },
    tp.icon, " ", tp.title);
}

function questionCard(q) {
  const head = el("div", { class: "item-head" },
    isTrainer() ? avatar(q.author) : null,
    isTrainer() ? el("strong", {}, q.anonymous ? t("q.anonTag") : q.author) : null,
    topicChip(q.category),
    !isTrainer() && q.anonymous ? el("span", { class: "tag" }, t("q.anonTag")) : null,
    q.faq_ok ? el("span", { class: "tag faq-tag" }, t("q.faqTag")) : null,
    el("span", {}, timeAgo(q.created_at)),
    el("span", { class: `right status ${q.answer ? "ok" : "open"}` }, t(q.answer ? "q.statusOk" : "q.statusOpen")));
  const card = el("article", { class: "item" }, head, el("p", { class: "item-text" }, q.text));

  // Răspunsul oficial al trainerului vine primul
  if (q.answer) {
    card.append(el("div", { class: "answer" },
      el("div", { class: "label" }, t("q.trainer"), el("span", { class: "muted" }, ` · ${timeAgo(q.answered_at)}`)),
      renderMd(q.answer)));
  }
  if (q.ai_answer) {
    card.append(el("div", { class: "ai-answer" }, el("div", { class: "label" }, t("q.ai")), renderMd(q.ai_answer)));
  } else if (aiPending.has(q.id)) {
    card.append(el("div", { class: "ai-loading" }, "› ", t("q.aiThinking"), el("span", { class: "dots" })));
  }

  // Acordul pentru FAQ îl dă (sau îl retrage) doar autorul
  if (!isTrainer() && q.mine) {
    card.append(el("div", { class: "actions" }, el("button", { type: "button", class: "small ghost", onclick: async () => {
      try {
        await api(`/api/questions/${q.id}/faq-consent`, { method: "POST", body: { faq_ok: !q.faq_ok } });
        toast(t(q.faq_ok ? "q.faqRevoked" : "q.faqAllowed"));
        loadQuestions();
      } catch (err) { toast(err.message); }
    } }, t(q.faq_ok ? "q.faqRevoke" : "q.faqAllow"))));
  }

  if (!isTrainer() && !q.answer) {
    card.append(el("div", { class: "waiting" }, t("q.waiting")));
    if (!q.ai_answer && !aiPending.has(q.id)) {
      if (cfg.ai) {
        card.append(el("div", { class: "actions" },
          el("button", { class: "small glow", onclick: () => requestAiAnswer(q.id) }, t("q.aiAsk"))));
      } else {
        const tp = topic(q.category);
        card.append(el("div", { class: "guide-peek" },
          el("strong", {}, `${t("q.fromGuide")} · ${tp.icon} ${tp.title}`),
          el("ul", {}, tp.tips.slice(0, 2).map((tip) => el("li", {}, tip))),
          el("button", { class: "link-btn", type: "button", onclick: () => openTopic(q.category) }, t("q.openGuide"))));
      }
    }
  }

  if (isTrainer()) {
    const area = el("textarea", { rows: 3, placeholder: t("q.replyPh") });
    area.value = q.answer || "";
    const buttons = el("div", { class: "row end" });
    if (q.ai_answer) {
      buttons.append(el("button", { type: "button", class: "ghost small", onclick: () => { area.value = q.ai_answer; area.focus(); } }, t("q.useAi")));
    }
    buttons.append(el("button", { type: "submit", class: "primary small" }, t("q.sendReply")));
    const form = el("form", { class: "answer-form hidden" }, area, buttons);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await api(`/api/questions/${q.id}/answer`, { method: "POST", body: { text: area.value } });
        toast(t("q.replied"));
        loadQuestions();
      } catch (err) { toast(err.message); }
    });
    const actions = el("div", { class: "actions" },
      el("button", { class: "small", onclick: () => { form.classList.toggle("hidden"); area.focus(); } }, t(q.answer ? "q.edit" : "q.reply")));
    if (cfg.ai && !q.ai_answer && !aiPending.has(q.id)) {
      actions.append(el("button", { class: "small ghost", onclick: () => requestAiAnswer(q.id) }, "✨ ", t("q.aiDraft")));
    }
    if (q.faq_ok && q.answer) {
      actions.append(el("button", { class: "small ghost", onclick: async () => {
        try { await api(`/api/questions/${q.id}/to-faq`, { method: "POST" }); toast(t("q.toFaqDone")); loadFaq(); }
        catch (err) { toast(err.message); }
      } }, "? ", t("q.toFaq")));
    }
    card.append(actions, form);
  }
  return card;
}

// ================================================================ homework & projects

async function loadAssignments() {
  assignments = await api("/api/assignments");
  renderAssignments();
  renderSubmissionForm();
  renderHome();
  renderBell();
}

function renderAssignments() {
  const box = $("#assignments");
  if (!assignments.length) {
    box.replaceChildren(el("div", { class: "empty" }, t("a.empty")));
    return;
  }
  box.replaceChildren(...assignments.map((a) => {
    const cd = a.due_at ? countdown(a.due_at) : null;
    const right = [];
    if (isTrainer()) {
      right.push(el("span", { class: "countdown" }, t("a.submittedN", a.submitted)));
      right.push(el("button", { class: "ghost small", title: t("a.delete"), onclick: async (e) => {
        e.stopPropagation();
        if (!confirm(t("a.confirmDelete", a.title))) return;
        try { await api(`/api/assignments/${a.id}`, { method: "DELETE" }); loadAssignments(); } catch (err) { toast(err.message); }
      } }, "✕"));
    } else if (a.submitted) {
      right.push(el("span", { class: "countdown done" }, t("a.done")));
    } else {
      if (cd) right.push(el("span", { class: `countdown ${cd.late ? "late" : ""}` }, cd.text));
      right.push(el("button", { class: "small primary", onclick: () => handInFor(a) }, t("a.handIn")));
    }
    return el("div", { class: "mini" },
      el("span", { class: "k" }, "📌"),
      el("span", { class: "t" }, el("b", {}, a.title), " ",
        el("small", { class: "muted" }, [t("a.points", a.points), a.due_at ? t("a.onTime") : null].filter(Boolean).join(" · ")),
        a.description ? el("small", { class: "muted", style: "display:block;white-space:normal" }, a.description) : null),
      ...right);
  }));
}

function handInFor(a) {
  selectedKind = "homework";
  renderSubmissionForm();
  $("#s-assignment").value = String(a.id);
  if (!$("#s-title").value) $("#s-title").value = a.title;
  $("#submission-form").scrollIntoView({ behavior: motionOff() ? "auto" : "smooth", block: "start" });
  setTimeout(() => $("#s-link").focus(), 300);
}

$("#assignment-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const due = $("#a-due").value;
  try {
    await api("/api/assignments", {
      method: "POST",
      body: {
        title: $("#a-title").value,
        description: $("#a-desc").value,
        due_at: due ? new Date(due).toISOString() : null,
        points: Number($("#a-points").value) || 0,
      },
    });
    ["#a-title", "#a-desc", "#a-due"].forEach((id) => ($(id).value = ""));
    toast(t("a.created"));
    loadAssignments();
  } catch (err) { toast(err.message); }
});

function renderSubmissionForm() {
  $("#kind-chips").replaceChildren(...["homework", "project", "other"].map((k, i) =>
    el("button", {
      type: "button", class: `chip ${k === selectedKind ? "on" : ""}`, style: `--h:${[190, 265, 330][i]}`,
      onclick: () => { selectedKind = k; renderSubmissionForm(); },
    }, t("kind." + k))));
  const sel = $("#s-assignment");
  const current = sel.value;
  sel.replaceChildren(el("option", { value: "" }, t("s.noAssignment")),
    ...assignments.map((a) => el("option", { value: String(a.id) }, a.title)));
  sel.value = assignments.some((a) => String(a.id) === current) ? current : "";
  const ticked = new Set([...document.querySelectorAll("#checklist input:checked")].map((c) => c.value));
  $("#checklist").replaceChildren(...CHECKLIST.map((key) => {
    const box = el("input", { type: "checkbox", value: key });
    box.checked = ticked.has(key);
    return el("label", { class: "ck" }, box, el("span", {}, t("s.ck." + key)));
  }));
  $("#checklist-box").classList.toggle("hidden", selectedKind === "other");
  $("#howto-steps").replaceChildren(...[1, 2, 3, 4, 5].map((n) => el("li", {}, richText(t("s.step" + n)))));
  renderPendingFiles();
  renderStatusFilter();
}

function renderPendingFiles() {
  $("#file-list").replaceChildren(...pendingFiles.map((f, i) =>
    el("span", { class: "file-chip" }, "📄 ", el("span", { class: "n" }, f.name), el("span", { class: "sz" }, formatSize(f.size)),
      el("button", { type: "button", class: "ghost", title: t("s.remove"), onclick: () => { pendingFiles.splice(i, 1); renderPendingFiles(); } }, "✕"))));
}

function addFiles(list) {
  for (const f of list) {
    if (pendingFiles.length >= 5) break;
    if (!pendingFiles.some((p) => p.name === f.name && p.size === f.size)) pendingFiles.push(f);
  }
  renderPendingFiles();
}

const dz = $("#dropzone");
dz.addEventListener("click", () => $("#s-files").click());
dz.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#s-files").click(); } });
$("#s-files").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });
["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
dz.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));

// XHR în loc de fetch, ca să avem bară de progres la încărcare
function uploadForm(form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/submissions");
    xhr.setRequestHeader("Authorization", `Bearer ${auth.token}`);
    xhr.setRequestHeader("X-Lang", lang);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch (_) {}
      if (xhr.status === 401) logout(true);
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new Error(Array.isArray(data.detail) ? t("err.check") : data.detail || t("err.generic")));
    };
    xhr.onerror = () => reject(new Error(t("err.generic")));
    xhr.send(form);
  });
}

$("#submission-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#submission-error").textContent = "";
  const form = new FormData();
  form.append("kind", selectedKind);
  form.append("title", $("#s-title").value);
  form.append("link", $("#s-link").value);
  form.append("note", $("#s-note").value);
  if ($("#s-assignment").value) form.append("assignment_id", $("#s-assignment").value);
  if (selectedKind !== "other") {
    document.querySelectorAll("#checklist input:checked").forEach((c) => form.append("checklist", c.value));
  }
  pendingFiles.forEach((f) => form.append("files", f, f.name));

  const btn = $("#s-send");
  const bar = $("#upload-progress");
  btn.disabled = true;
  btn.textContent = t("s.uploading");
  bar.classList.remove("hidden");
  bar.firstElementChild.style.width = "0";
  try {
    await uploadForm(form, (k) => (bar.firstElementChild.style.width = `${Math.round(k * 100)}%`));
    ["#s-title", "#s-link", "#s-note"].forEach((id) => ($(id).value = ""));
    clearLocalDraft("#s-title", "#s-link", "#s-note");
    $("#s-assignment").value = "";
    pendingFiles = [];
    document.querySelectorAll("#checklist input").forEach((c) => (c.checked = false));
    renderPendingFiles();
    confetti();
    toast(t("s.sent"));
    loadSubmissions();
    loadAssignments();
    loadPoints();
  } catch (err) {
    $("#submission-error").textContent = err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = t("s.send");
    setTimeout(() => bar.classList.add("hidden"), 600);
  }
});

async function downloadFile(sub, file) {
  try {
    const res = await fetch(`/api/submissions/${sub.id}/files/${file.id}`, {
      headers: { Authorization: `Bearer ${auth.token}`, "X-Lang": lang },
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || t("err.generic"));
    const url = URL.createObjectURL(await res.blob());
    const a = el("a", { href: url, download: file.name });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (err) { toast(err.message); }
}

function renderStatusFilter() {
  const select = $("#submission-status");
  const current = select.value || "all";
  select.replaceChildren(el("option", { value: "all" }, t("s.allStatus")),
    ...["sent", "received", "reviewed", "redo"].map((st) => el("option", { value: st }, t("st." + st))));
  select.value = current;
}

$("#submission-search").addEventListener("input", renderSubmissions);
$("#submission-status").addEventListener("change", renderSubmissions);

async function loadSubmissions() {
  submissions = await api("/api/submissions");
  renderSubmissions();
  renderHome();
  renderBell();
}

function renderSubmissions() {
  const term = norm($("#submission-search").value.trim());
  const status = $("#submission-status").value || "all";
  const shown = submissions.filter((x) =>
    (status === "all" || x.status === status) &&
    (!term || norm(`${x.title} ${x.note} ${x.link} ${x.author}`).includes(term)));
  const pending = submissions.filter((x) => x.status === "sent").length;
  $("#s-badge").textContent = pending;
  $("#s-badge").classList.toggle("hidden", !isTrainer() || pending === 0);
  const list = $("#submissions-list");
  if (!shown.length) {
    list.replaceChildren(el("div", { class: "empty" }, t(submissions.length ? "q.emptyFilter" : isTrainer() ? "s.emptyT" : "s.empty")));
    return;
  }
  list.replaceChildren(...shown.map((x, i) => {
    const card = submissionCard(x);
    card.style.animationDelay = `${Math.min(i, 8) * 40}ms`;
    return card;
  }));
}

function submissionCard(x) {
  const forA = assignments.find((a) => a.id === x.assignment_id);
  const card = el("article", { class: "item" },
    el("div", { class: "item-head" },
      isTrainer() ? avatar(x.author) : null,
      isTrainer() ? el("strong", {}, x.author) : null,
      el("span", { class: "tag" }, t("kind." + x.kind)),
      forA ? el("span", { class: "tag" }, `📌 ${forA.title}`) : null,
      el("span", {}, timeAgo(x.created_at)),
      x.kind !== "other" ? el("span", { class: "ck-meter" }, `${t("s.check")} `, el("b", {}, `${x.checklist.length}/${CHECKLIST.length}`)) : null,
      el("span", { class: `right status ${x.status}` }, t("st." + x.status))),
    el("h3", {}, x.title));
  if (x.note) card.append(el("p", { class: "item-text" }, x.note));
  // Serverul acceptă doar linkuri http(s); verificăm și aici înainte să-l facem clicabil
  if (safeLink(x.link)) card.append(el("div", { class: "row" },
    el("a", { class: "sub-link", href: x.link, target: "_blank", rel: "noopener noreferrer" }, "↗ ", x.link),
    /github\.com\//.test(x.link) ? el("button", { type: "button", class: "small ghost", onclick: () => checkRepoFrom(x.link) }, t("rc.checkBtn")) : null));
  if (x.files.length) {
    card.append(el("div", { class: "file-list" }, x.files.map((f) =>
      el("span", { class: "file-chip" }, "📄 ", el("span", { class: "n" }, f.name), el("span", { class: "sz" }, formatSize(f.size)),
        el("button", { type: "button", class: "small", onclick: () => downloadFile(x, f) }, "↓ ", t("s.download"))))));
  }
  if (x.feedback) {
    card.append(el("div", { class: "answer" },
      el("div", { class: "label" }, t("s.feedback"), el("span", { class: "muted" }, ` · ${timeAgo(x.reviewed_at)}`)),
      renderMd(x.feedback)));
  }
  if (isTrainer()) {
    let chosen = x.status === "sent" ? "received" : x.status;
    const area = el("textarea", { rows: 3, placeholder: t("s.feedbackPh") });
    area.value = x.feedback || "";
    const seg = el("div", { class: "seg" });
    const drawSeg = () => seg.replaceChildren(...["received", "reviewed", "redo"].map((st) =>
      el("button", { type: "button", class: `small ${st === chosen ? "on" : ""}`, onclick: () => { chosen = st; drawSeg(); } }, t("st." + st))));
    drawSeg();
    const form = el("form", { class: "review-form hidden" }, seg, area,
      el("div", { class: "row end" }, el("button", { type: "submit", class: "primary small" }, t("s.saveReview"))));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await api(`/api/submissions/${x.id}/review`, { method: "POST", body: { status: chosen, feedback: area.value } });
        toast(t("s.reviewed"));
        loadSubmissions();
        loadBoard();
      } catch (err) { toast(err.message); }
    });
    card.append(el("div", { class: "actions" },
      el("button", { class: "small", onclick: () => { form.classList.toggle("hidden"); area.focus(); } }, "✎ ", t("s.review"))), form);
  }
  return card;
}

// ================================================================ idea box (wizard)

function setStep(n) {
  document.querySelectorAll("#pipeline li").forEach((li) => {
    const s = Number(li.dataset.step);
    li.classList.toggle("active", s === n);
    li.classList.toggle("dark", s === n && (s === 2 || s === 5));
    li.classList.toggle("done", s < n);
  });
}

function showStage(id) {
  ["#proposal-form", "#ai-thinking", "#refine-result"].forEach((s) => $(s).classList.toggle("hidden", s !== id));
}

let refineSource = "";

async function runRefine(body) {
  refineSource = body.description || "";
  $("#proposal-error").textContent = "";
  showStage("#ai-thinking");
  setStep(2);
  const log = $("#ai-log");
  log.replaceChildren(el("div", {}, el("span", { class: "t-prompt" }, "$ "), "claude refine proposal.json"));
  let done = false;
  const request = api("/api/proposals/refine", { method: "POST", body }).finally(() => { done = true; });
  request.catch(() => {}); // eroarea e tratată mai jos, după animație
  for (const line of t("p.log")) {
    log.append(el("div", { class: "t-ai" }, "› " + line));
    await sleep(380);
  }
  const cursor = el("span", { class: "cursor" });
  if (!done) log.append(el("div", { class: "t-dim" }, "› " + t("p.waitClaude"), cursor));
  try {
    const r = await request;
    cursor.remove();
    const n = (r.missing || []).length;
    log.append(el("div", { class: "t-ok" }, t("p.done") + (n ? n + t(n === 1 ? "p.oneQ" : "p.manyQ") : t("p.allClear"))));
    await sleep(500);
    showRefined(r);
  } catch (err) {
    showStage("#proposal-form");
    setStep(1);
    $("#proposal-error").textContent = err.message;
  }
}

async function typewrite(node, text) {
  node.textContent = "";
  if (motionOff()) { node.textContent = text; return; }
  for (let i = 0; i < text.length; i += 2) {
    node.textContent = text.slice(0, i + 2);
    await new Promise((r) => setTimeout(r, 12));
  }
}

function showRefined(r) {
  showStage("#refine-result");
  typewrite($("#understood-text"), r.understood || t("p.understoodEmpty"));
  $("#refine-notes").textContent = t(r.engine === "claude" ? "p.engineClaude" : "p.engineLocal") + (r.notes || "")
    + (r.refines_left != null ? " · " + t("p.refinesLeft", r.refines_left) : "");
  renderDiff(refineSource, r.description || "");
  $("#f-title").value = r.title || "";
  $("#f-description").value = r.description || "";
  $("#f-audience").value = r.audience || "";
  $("#approve").checked = false;
  $("#submit-proposal").disabled = true;
  lastMissing = r.missing || [];
  $("#missing-box").classList.toggle("hidden", lastMissing.length === 0);
  $("#missing-list").replaceChildren(...lastMissing.map((m, i) => {
    const ta = el("textarea", { rows: 2, "data-missing": i, placeholder: t("p.answerPh"), "aria-label": m.question });
    ta.addEventListener("input", () => setStep(4), { once: true });
    return el("div", { class: "q-bubble" },
      el("div", { class: "q" }, el("small", {}, `🤖 ${t("field." + m.field)}`), m.question), ta);
  }));
  setStep(lastMissing.length ? 3 : 4);
}

// Diff pe cuvinte între ce a scris studentul și varianta AI (LCS); doar noduri text, fără HTML
function wordDiff(a, b) {
  const A = a.split(/(\s+)/).filter(Boolean), B = b.split(/(\s+)/).filter(Boolean);
  if (A.length * B.length > 600000) return [{ op: "same", text: b }];
  const L = Array.from({ length: A.length + 1 }, () => new Uint16Array(B.length + 1));
  for (let i = A.length - 1; i >= 0; i--)
    for (let j = B.length - 1; j >= 0; j--)
      L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out = [];
  const push = (op, text) => { const last = out[out.length - 1]; if (last && last.op === op) last.text += text; else out.push({ op, text }); };
  let i = 0, j = 0;
  while (i < A.length && j < B.length) {
    if (A[i] === B[j]) { push("same", A[i]); i++; j++; }
    else if (L[i + 1][j] >= L[i][j + 1]) push("del", A[i++]);
    else push("ins", B[j++]);
  }
  while (i < A.length) push("del", A[i++]);
  while (j < B.length) push("ins", B[j++]);
  return out;
}

function renderDiff(before, after) {
  const box = $("#diff-box");
  box.classList.toggle("hidden", !before.trim());
  if (!before.trim()) return;
  if (before.trim() === after.trim()) { $("#diff-text").replaceChildren(el("span", { class: "muted" }, t("p.diffNone"))); return; }
  $("#diff-text").replaceChildren(...wordDiff(before, after).map((p) =>
    p.op === "same" ? document.createTextNode(p.text) : el(p.op === "ins" ? "ins" : "del", {}, p.text)));
}

$("#proposal-form").addEventListener("submit", (e) => {
  e.preventDefault();
  runRefine({ title: $("#p-title").value, description: $("#p-description").value, audience: $("#p-audience").value });
});

$("#apply-answers").addEventListener("click", (e) => {
  e.preventDefault();
  // Pornim de la varianta retușată și adăugăm răspunsurile la câmpurile cerute
  const body = { title: $("#f-title").value, description: $("#f-description").value, audience: $("#f-audience").value };
  document.querySelectorAll("[data-missing]").forEach((ta) => {
    const answer = ta.value.trim();
    if (!answer) return;
    const asked = lastMissing[Number(ta.dataset.missing)].field;
    const field = TARGET_FIELD[asked] || asked;
    body[field] = body[field] ? `${body[field]} ${answer}` : answer;
  });
  // Ținem ciorna sincronizată, ca „Înapoi” să nu piardă detaliile
  $("#p-title").value = body.title;
  $("#p-description").value = body.description;
  $("#p-audience").value = body.audience;
  runRefine(body);
});

$("#approve").addEventListener("change", () => {
  $("#submit-proposal").disabled = !$("#approve").checked;
  setStep($("#approve").checked ? 5 : 4);
});

["#f-title", "#f-description", "#f-audience"].forEach((id) =>
  $(id).addEventListener("input", () => {
    // Orice modificare cere o nouă aprobare
    $("#approve").checked = false;
    $("#submit-proposal").disabled = true;
    setStep(4);
    scheduleDraftSave();
  }));

$("#back-edit").addEventListener("click", (e) => {
  e.preventDefault();
  showStage("#proposal-form");
  setStep(1);
});

$("#submit-proposal").addEventListener("click", async (e) => {
  e.preventDefault();
  $("#proposal-error").textContent = "";
  try {
    await api("/api/proposals", {
      method: "POST",
      body: { title: $("#f-title").value, description: $("#f-description").value, audience: $("#f-audience").value, approved: $("#approve").checked },
    });
    ["#p-title", "#p-description", "#p-audience"].forEach((id) => ($(id).value = ""));
    showStage("#proposal-form");
    setStep(1);
    if (currentDraftId) {
      api(`/api/drafts/${currentDraftId}`, { method: "DELETE" }).catch(() => {}).finally(loadDrafts);
      currentDraftId = null;
    }
    clearTimeout(draftTimer);
    draftSavedAt = null;
    renderDrafts();
    confetti();
    toast(t("p.submitted"));
    loadProposals();
    loadPoints();
  } catch (err) {
    $("#proposal-error").textContent = err.message;
  }
});

// Mod proiector: o propunere pe ecran, mare, pentru discuția din clasă
let projIndex = 0;
function projectorList() {
  return proposals.filter((p) => p.status !== "withdrawn").sort((a, b) => b.votes - a.votes || b.id - a.id);
}
function renderProjector() {
  const list = projectorList();
  const box = $("#projector");
  const close = el("button", { type: "button", class: "small ghost proj-close", onclick: closeProjector }, t("p.projClose"));
  if (!list.length) { box.replaceChildren(close, el("p", { class: "proj-empty" }, t("p.projEmpty"))); return; }
  projIndex = (projIndex + list.length) % list.length;
  const p = list[projIndex];
  box.replaceChildren(...[
    el("div", { class: "proj-top" }, el("span", { class: "mono muted" }, t("p.projCount", projIndex + 1, list.length)), decisionBadge(p), close),
    el("h1", { id: "proj-title" }, p.title),
    el("p", { class: "proj-line" }, el("b", {}, t("p.what")), p.description),
    el("p", { class: "proj-line" }, el("b", {}, t("p.for")), p.audience),
    p.trainer_note ? el("p", { class: "trainer-note" }, el("b", {}, t("p.trainerNote") + ": "), p.trainer_note) : null,
    el("div", { class: "proj-foot" },
      el("span", { class: "proj-votes mono" }, `▲ ${p.votes}`),
      el("span", { class: "muted" }, p.author),
      el("div", { class: "row" },
        el("button", { type: "button", class: "small", onclick: () => { projIndex--; renderProjector(); }, "aria-label": "←" }, "←"),
        el("button", { type: "button", class: "small", onclick: () => { projIndex++; renderProjector(); }, "aria-label": "→" }, "→"))),
    el("p", { class: "muted small proj-hint" }, t("p.projHint"))].filter(Boolean));
}
function openProjector() {
  projIndex = 0;
  $("#projector").classList.remove("hidden");
  document.body.classList.add("proj-open");
  renderProjector();
  $("#projector").requestFullscreen?.().catch(() => {});
}
function closeProjector() {
  $("#projector").classList.add("hidden");
  document.body.classList.remove("proj-open");
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
}
document.addEventListener("keydown", (e) => {
  if ($("#projector").classList.contains("hidden")) return;
  if (e.key === "Escape") closeProjector();
  else if (e.key === "ArrowRight") { projIndex++; renderProjector(); }
  else if (e.key === "ArrowLeft") { projIndex--; renderProjector(); }
});
$("#projector-btn").addEventListener("click", openProjector);

$("#export-btn").addEventListener("click", async () => {
  try {
    const res = await fetch("/api/proposals/export.csv", { headers: { "X-Lang": lang, Authorization: `Bearer ${auth.token}` } });
    if (!res.ok) throw new Error(t("err.generic"));
    const url = URL.createObjectURL(await res.blob());
    const a = el("a", { href: url, download: "propuneri.csv" });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (err) { toast(err.message); }
});

$("#proposal-search").addEventListener("input", renderProposals);
$("#proposal-sort").addEventListener("change", renderProposals);

async function loadProposals() {
  proposals = await api("/api/proposals");
  renderProposals();
  if (!$("#projector").classList.contains("hidden")) renderProjector();
  renderHome();
  renderBell();
}

function renderProposals() {
  const term = norm($("#proposal-search").value.trim());
  const sort = $("#proposal-sort").value;
  const shown = proposals
    .filter((p) => isTrainer() || p.status !== "withdrawn")
    .filter((p) => !term || norm(`${p.title} ${p.description} ${p.audience} ${p.author}`).includes(term))
    .sort((a, b) => {
      if (sort === "votes") return b.votes - a.votes || b.id - a.id;
      if (sort === "chosen") return b.chosen - a.chosen || b.votes - a.votes || b.id - a.id;
      return b.id - a.id;
    });
  const active = proposals.filter((p) => p.status !== "withdrawn").length;
  $("#p-badge").textContent = active;
  $("#p-badge").classList.toggle("hidden", active === 0);
  renderMyProposals();
  const list = $("#proposals-list");
  if (!shown.length) {
    list.replaceChildren(el("div", { class: "empty" }, t(proposals.length ? "q.emptyFilter" : "p.empty")));
    return;
  }
  list.replaceChildren(...shown.map((p, i) => {
    const card = proposalCard(p, sort === "votes" && !term ? i + 1 : null);
    card.style.animationDelay = `${Math.min(i, 8) * 40}ms`;
    return card;
  }));
}

const DECISIONS = ["new", "discussing", "chosen", "rejected"];

function decisionBadge(p) {
  if (p.decision === "chosen") return el("span", { class: "right chosen-badge" }, t("p.chosen"));
  if (p.decision === "discussing" || p.decision === "rejected") return el("span", { class: `right status dec-${p.decision}` }, t("p.dec." + p.decision));
  return null;
}

async function setDecision(p, decision, note) {
  try {
    await api(`/api/proposals/${p.id}/decision`, { method: "POST", body: { decision, note } });
    if (decision === "chosen" && p.decision !== "chosen") confetti();
    toast(t("p.decSaved"));
    await loadProposals();
    loadBoard();
  } catch (err) { toast(err.message); }
}

function decisionControls(p) {
  const note = el("input", { maxlength: 500, placeholder: t("p.notePh"), value: p.trainer_note || "" });
  const seg = el("div", { class: "seg dec-seg", role: "group" }, ...DECISIONS.map((d) =>
    el("button", { type: "button", class: `small ${p.decision === d ? "on" : ""}`, disabled: p.status === "withdrawn" && d !== p.decision,
      onclick: () => setDecision(p, d, note.value) }, t("p.dec." + d))));
  const form = el("div", { class: "dec-note" }, note,
    el("button", { type: "button", class: "small ghost", onclick: () => setDecision(p, p.decision, note.value) }, t("p.noteSave")));
  return el("div", { class: "dec-wrap" }, seg, form);
}

function proposalCard(p, rank) {
  const actions = el("div", { class: "actions" });
  if (isTrainer()) {
    actions.append(decisionControls(p));
    actions.append(el("span", { class: "muted small mono" }, `▲ ${p.votes} ${t(p.votes === 1 ? "p.vote1" : "p.votes")}`));
  } else {
    actions.append(el("button", {
      class: `small vote ${p.voted ? "on" : ""}`, disabled: p.mine,
      title: t(p.voted ? "p.unvote" : "p.vote"),
      onclick: () => act(`/api/proposals/${p.id}/vote`),
    }, `▲ ${p.votes}`));
  }
  if (p.chosen && p.status !== "withdrawn") actions.append(el("button", { class: "small kick", onclick: () => openKickstart(p) }, t("kick.open")));
  if (p.mine && p.status !== "withdrawn") actions.append(withdrawControls(p));
  return el("article", { class: `item ${p.chosen ? "chosen" : ""} ${p.status === "withdrawn" ? "withdrawn" : ""}` },
    el("div", { class: "item-head" },
      rank && p.votes > 0 ? el("span", { class: `rank ${rank <= 3 ? "top" : ""}` }, `#${rank}`) : null,
      avatar(p.author),
      el("strong", {}, p.mine ? p.author + t("p.you") : p.author),
      el("span", {}, timeAgo(p.created_at)),
      p.status === "withdrawn" ? el("span", { class: "right status withdrawn" }, t(p.withdrawn_reason === "resolved" ? "p.withdrawnResolved" : "p.withdrawn"))
        : decisionBadge(p)),
    el("h3", {}, p.title),
    el("p", { class: "meta-line" }, el("b", {}, t("p.what")), p.description),
    el("p", { class: "meta-line" }, el("b", {}, t("p.for")), p.audience),
    p.trainer_note ? el("p", { class: "trainer-note" }, el("b", {}, t("p.trainerNote") + ": "), p.trainer_note) : null,
    actions);
}

async function act(path) {
  try {
    await api(path, { method: "POST" });
    await loadProposals();
    loadBoard();
    return true;
  } catch (err) {
    toast(err.message);
    return false;
  }
}

// ================================================================ drafts (ciorne pe server) & propunerile mele

function wizardValues() {
  // Dacă AI-ul a retușat deja textul, salvăm varianta finală la care lucrezi
  const refined = !$("#refine-result").classList.contains("hidden");
  const pick = (a, b) => $(refined ? a : b).value;
  return {
    title: pick("#f-title", "#p-title"),
    description: pick("#f-description", "#p-description"),
    audience: pick("#f-audience", "#p-audience"),
  };
}

async function loadDrafts() {
  if (!auth || isTrainer()) return;
  try { drafts = await api("/api/drafts"); } catch (_) { return; }
  renderDrafts();
}

function renderDrafts() {
  $("#drafts-title").textContent = `${t("p.drafts")} · ${drafts.length}`;
  $("#draft-status").textContent = draftSavedAt ? t("p.draftSaved", timeAgo(draftSavedAt)) : "";
  $("#drafts-list").replaceChildren(...drafts.map((d) =>
    el("span", { class: `draft-chip ${d.id === currentDraftId ? "on" : ""}` },
      el("span", { class: "dt", title: t("p.continue"), onclick: () => openDraft(d) }, "✎ ", d.title || trunc(d.description || "", 30) || t("p.untitled")),
      el("small", {}, timeAgo(d.updated_at)),
      el("button", { type: "button", class: "ghost", title: t("p.delete"), onclick: () => deleteDraft(d) }, "✕"))));
}

function scheduleDraftSave() {
  if (!auth || isTrainer()) return;
  clearTimeout(draftTimer);
  draftTimer = setTimeout(() => saveDraft(true), 1500);
}

async function saveDraft(silent = false) {
  clearTimeout(draftTimer);
  const data = wizardValues();
  if (!data.title.trim() && !data.description.trim() && !data.audience.trim()) return;
  try {
    const d = currentDraftId
      ? await api(`/api/drafts/${currentDraftId}`, { method: "PUT", body: data })
      : await api("/api/drafts", { method: "POST", body: data });
    currentDraftId = d.id;
    draftSavedAt = d.updated_at;
    drafts = [d, ...drafts.filter((x) => x.id !== d.id)];
    renderDrafts();
    if (!silent) toast(t("p.draftSavedToast"));
  } catch (err) {
    // Ciorna a fost ștearsă între timp: începem una nouă la următoarea salvare
    if (currentDraftId && /404|nu există|not found/i.test(err.message)) currentDraftId = null;
    if (!silent) toast(err.message);
  }
}

function openDraft(d) {
  clearTimeout(draftTimer);
  currentDraftId = d.id;
  draftSavedAt = d.updated_at;
  $("#p-title").value = d.title || "";
  $("#p-description").value = d.description || "";
  $("#p-audience").value = d.audience || "";
  showStage("#proposal-form");
  setStep(1);
  renderDrafts();
  $("#proposal-wizard").scrollIntoView({ behavior: motionOff() ? "auto" : "smooth", block: "start" });
  $("#p-description").focus();
}

async function deleteDraft(d) {
  if (!confirm(t("p.confirmDeleteDraft"))) return;
  try {
    await api(`/api/drafts/${d.id}`, { method: "DELETE" });
    drafts = drafts.filter((x) => x.id !== d.id);
    if (currentDraftId === d.id) { currentDraftId = null; draftSavedAt = null; }
    renderDrafts();
  } catch (err) { toast(err.message); }
}

function newDraft() {
  clearTimeout(draftTimer);
  currentDraftId = null;
  draftSavedAt = null;
  ["#p-title", "#p-description", "#p-audience"].forEach((id) => ($(id).value = ""));
  showStage("#proposal-form");
  setStep(1);
  renderDrafts();
  $("#p-title").focus();
}

["#p-title", "#p-description", "#p-audience"].forEach((id) => $(id).addEventListener("input", scheduleDraftSave));
document.querySelectorAll(".save-draft").forEach((b) => b.addEventListener("click", () => saveDraft(false)));
$("#new-draft").addEventListener("click", newDraft);

function withdrawControls(p) {
  const wrap = el("span", { style: "display:contents" });
  let reason = "resolved";
  const note = el("input", { maxlength: 300, placeholder: t("p.withdrawNote") });
  const seg = el("div", { class: "seg" });
  const drawSeg = () => seg.replaceChildren(...[["resolved", t("p.reasonResolved")], ["other", t("p.reasonOther")]].map(([v, label]) =>
    el("button", { type: "button", class: `small ${v === reason ? "on" : ""}`, onclick: () => { reason = v; drawSeg(); } }, label)));
  drawSeg();
  const form = el("div", { class: "withdraw-form hidden" },
    el("b", {}, t("p.withdrawTitle")), seg, note,
    el("div", { class: "row end" },
      el("button", { type: "button", class: "small ghost", onclick: () => form.classList.add("hidden") }, t("p.cancel")),
      el("button", { type: "button", class: "small primary", onclick: async () => {
        try {
          await api(`/api/proposals/${p.id}/withdraw`, { method: "POST", body: { reason, note: note.value } });
          toast(t("p.withdrawDone"));
          await loadProposals();
          loadPoints();
        } catch (err) { toast(err.message); }
      } }, t("p.withdraw"))));
  wrap.append(el("button", { type: "button", class: "small ghost", onclick: () => { form.classList.toggle("hidden"); note.focus(); } }, "⤺ ", t("p.withdraw")), form);
  return wrap;
}

function renderMyProposals() {
  if (!auth || isTrainer()) return;
  const mine = proposals.filter((p) => p.mine);
  $("#my-count").textContent = t("p.myCount", mine.length);
  $("#my-proposals-list").replaceChildren(...(mine.length ? mine.map((p) => {
    const withdrawn = p.status === "withdrawn";
    const status = withdrawn
      ? el("span", { class: `status ${p.withdrawn_reason === "resolved" ? "resolved" : "withdrawn"}` }, t(p.withdrawn_reason === "resolved" ? "p.withdrawnResolved" : "p.withdrawn"))
      : p.chosen ? el("span", { class: "chosen-badge" }, t("p.chosen"))
      : p.decision === "discussing" || p.decision === "rejected" ? el("span", { class: `status dec-${p.decision}` }, t("p.dec." + p.decision))
      : el("span", { class: "status ok" }, t("p.active"));
    const row = el("div", { class: `mine-row ${withdrawn ? "withdrawn" : ""}` },
      el("span", { class: "t" }, p.title), status,
      el("span", { class: "votes mono small" }, `▲ ${p.votes}`),
      el("span", { class: "muted small" }, timeAgo(p.created_at)));
    if (withdrawn) {
      if (p.withdrawn_note) row.append(el("span", { class: "muted small", style: "flex-basis:100%" }, `“${p.withdrawn_note}”`));
      row.append(el("button", { type: "button", class: "small", onclick: async () => {
        try { await api(`/api/proposals/${p.id}/restore`, { method: "POST" }); toast(t("p.restored")); await loadProposals(); loadPoints(); }
        catch (err) { toast(err.message); }
      } }, t("p.restore")));
    } else {
      row.append(withdrawControls(p));
    }
    return row;
  }) : [el("div", { class: "empty" }, t("p.mineEmpty"))]));
}

// ================================================================ ciorne locale (întrebări, mesaje, teme)
// Textul pe care-l scrii nu se pierde dacă închizi pagina: îl ținem în browser până îl trimiți.

const LOCAL_DRAFTS = ["#question-text", "#chat-input", "#s-title", "#s-link", "#s-note"];

function localDraftKey(sel) { return `cutia-draft-${(auth && auth.name || "").toLowerCase()}-${sel.slice(1)}`; }

function restoreLocalDrafts() {
  LOCAL_DRAFTS.forEach((sel) => {
    try {
      const v = localStorage.getItem(localDraftKey(sel));
      if (v && !$(sel).value) { $(sel).value = v; $(sel).dispatchEvent(new Event("input")); }
    } catch (_) {}
  });
}

function clearLocalDraft(...sels) {
  sels.forEach((sel) => { try { localStorage.removeItem(localDraftKey(sel)); } catch (_) {} });
}

LOCAL_DRAFTS.forEach((sel) => $(sel).addEventListener("input", () => {
  if (!auth) return;
  try {
    const v = $(sel).value;
    if (v.trim()) localStorage.setItem(localDraftKey(sel), v);
    else localStorage.removeItem(localDraftKey(sel));
  } catch (_) {}
}));

// ================================================================ AI news

async function loadNews(refresh = false) {
  if (!auth) return;
  newsLoading = true;
  renderNews();
  try {
    newsData = await api(`/api/news${refresh ? "?refresh=true" : ""}`);
  } catch (err) {
    newsData = { items: [], sources: [], errors: [err.message] };
  } finally {
    newsLoading = false;
  }
  renderNews();
  renderHome();
}

$("#news-refresh").addEventListener("click", () => loadNews(true));

function renderNews() {
  if (!auth) return;
  const list = $("#news-list");
  const items = (newsData && newsData.items) || [];
  const cats = ["all", ...Object.keys(NEWS_HUE).filter((c) => items.some((i) => i.category === c))];
  if (!cats.includes(newsCat)) newsCat = "all";
  $("#news-cats").replaceChildren(...cats.map((c) => el("button", {
    type: "button", class: `chip ${c === newsCat ? "on" : ""}`, style: `--h:${NEWS_HUE[c] || 260}`,
    onclick: () => { newsCat = c; renderNews(); },
  }, c === "all" ? t("n.all") : t("cat." + c))));
  $("#news-meta").textContent = newsData && newsData.updated_at
    ? `${t(newsData.curated ? "n.curated" : "n.filtered")} · ${t("n.updated", timeAgo(newsData.updated_at))}` : "";

  if (newsLoading && !items.length) {
    list.replaceChildren(...Array.from({ length: 4 }, () => el("div", { class: "skeleton" })));
    return;
  }
  if (!items.length) {
    list.replaceChildren(el("div", { class: "empty", style: "grid-column:1/-1" },
      el("p", {}, t("n.empty")), el("p", { class: "small" }, t("n.emptyHint"), " ", ((newsData && newsData.sources) || []).join(" · "))));
    return;
  }
  const shown = items.filter((i) => newsCat === "all" || i.category === newsCat);
  const topIndex = Math.max(0, shown.findIndex((i) => i.top));
  list.replaceChildren(...shown.map((it, idx) => newsCard(it, idx === topIndex && newsCat === "all", idx)));
}

function newsCard(it, isTop, idx) {
  const title = it.headline || it.title;
  const card = el("article", { class: `news-card ${isTop ? "top" : ""}`, style: `--h:${NEWS_HUE[it.category] || 260}; animation-delay:${Math.min(idx, 10) * 40}ms` },
    el("div", { class: "meta" },
      isTop ? el("span", { class: "countdown" }, t("n.top")) : null,
      el("span", {}, t("cat." + it.category)), el("span", {}, "·"), el("span", {}, it.source),
      it.published ? el("span", {}, `· ${timeAgo(it.published)}`) : null),
    el("h3", {}, title));
  if (it.why) card.append(el("div", { class: "why" }, el("b", {}, t("n.why")), it.why));
  else if (it.summary) card.append(el("p", { class: "sum" }, trunc(it.summary, 220)));
  const actions = el("div", { class: "actions" });
  if (safeLink(it.link)) actions.append(el("a", { class: "read", href: it.link, target: "_blank", rel: "noopener noreferrer" }, t("n.read")));
  if (!isTrainer()) {
    actions.append(el("button", { class: "small ghost", onclick: () => prefillMessage(t("n.shareMsg", title, it.link)) }, "✉ ", t("n.share")));
    actions.append(el("button", { class: "small ghost", onclick: () => {
      showView("box");
      showStage("#proposal-form");
      setStep(1);
      $("#p-description").value = t("n.inspireDesc", `${title} (${it.link})`) + "\n";
      $("#p-description").focus();
    } }, t("n.inspire")));
  }
  card.append(actions);
  return card;
}

// ================================================================ Byte: briefing-ul zilei

let digestData = null, digestDate = null, digestPoll = null, digestPolls = 0, speaking = false;
const SPEECH_LANG = { ro: "ro-RO", en: "en-US", fr: "fr-FR", it: "it-IT", es: "es-ES", de: "de-DE" };

async function loadDigest(date = digestDate) {
  if (!auth) return;
  clearTimeout(digestPoll);
  try {
    digestData = await api(`/api/digest${date ? `?date=${encodeURIComponent(date)}` : ""}`);
  } catch (_) { digestData = digestData || { digest: null, history: [] }; }
  // Cât timp Byte scrie, mai întrebăm din când în când (maxim ~3 minute)
  if (digestData.generating && digestPolls < 30) {
    digestPolls++;
    digestPoll = setTimeout(() => loadDigest(), 6000);
  } else digestPolls = 0;
  renderByte();
  renderHome();
  renderNotifications();
}

function dayLabel(iso) {
  const today = new Date().toISOString().slice(0, 10);
  const y = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  if (iso === today) return t("byte.today");
  if (iso === y) return t("byte.yesterday");
  return new Date(iso + "T12:00:00").toLocaleDateString(lang, { day: "numeric", month: "short" });
}

function countUp(node, target) {
  if (motionOff()) { node.textContent = target; return; }
  const t0 = performance.now();
  const step = (now) => {
    const k = Math.min(1, (now - t0) / 900);
    node.textContent = Math.round(target * (1 - Math.pow(1 - k, 3)));
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function typeInto(node, text) {
  node.textContent = "";
  if (motionOff() || !text) { node.textContent = text || ""; return; }
  let i = 0;
  const tick = () => {
    if (!node.isConnected) return;
    i = Math.min(text.length, i + 2);
    node.textContent = text.slice(0, i);
    if (i < text.length) setTimeout(tick, 16);
  };
  tick();
}

function renderByte() {
  const box = $("#byte");
  if (!box || !auth) return;
  const data = digestData;
  const d = data && data.digest;
  box.classList.toggle("scanning", Boolean(data && data.generating) || !data);
  box.classList.toggle("talking", speaking);
  $("#byte-eyebrow").textContent = `Byte · ${t("byte.eyebrow")}` + (d ? ` · ${new Date(d.date + "T12:00:00").toLocaleDateString(lang, { weekday: "long", day: "numeric", month: "long" })}` : "");
  const body = $("#byte-body");
  if (!d) {
    $("#byte-title").textContent = t(data && data.generating ? "byte.generating" : "byte.none");
    $("#byte-say").textContent = data ? t("byte.next", new Date(data.next_run).toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" })) : "";
    $("#byte-pulse").replaceChildren();
    body.replaceChildren(data && data.generating ? el("div", { class: "byte-loading" }, ...Array.from({ length: 3 }, () => el("div", { class: "skeleton" }))) : el("span"));
    return;
  }
  $("#byte-title").textContent = d.title || t("byte.eyebrow");
  const say = $("#byte-say");
  const line = d.line || t("byte.localLine");
  if (say.dataset.shown !== d.date + lang) { say.dataset.shown = d.date + lang; typeInto(say, line); } else say.textContent = line;
  $("#byte-pulse").replaceChildren(el("span", { class: "mono" }, t("byte.pulse")),
    el("span", { class: "bars" }, ...Array.from({ length: 5 }, (_, i) => el("i", { class: i < d.pulse ? "on" : "" }))));

  // Statistici: câte surse, câte știri citite, câte alese
  const stat = (n, label) => { const b = el("b", {}, "0"); countUp(b, n); return el("div", { class: "byte-stat" }, b, el("span", {}, label)); };
  const stats = el("div", { class: "byte-stats" },
    stat(d.stats.sources, t("byte.statSources")), stat(d.stats.scanned, t("byte.statScanned")),
    stat(d.stats.fresh, d.window_hours ? t("byte.statFresh", d.window_hours) : t("byte.statRecent")), stat(d.stories.length, t("byte.statPicked")));

  const actions = el("div", { class: "byte-actions" },
    "speechSynthesis" in window ? el("button", { type: "button", class: "small", onclick: () => toggleListen(d) }, t(speaking ? "byte.stop" : "byte.listen")) : null,
    el("button", { type: "button", class: "small ghost", onclick: () => copy(digestText(d)) }, t("byte.copy")),
    isTrainer() ? el("button", { type: "button", class: "small ghost", onclick: rerunDigest }, t("byte.rerun")) : null,
    el("span", { class: "muted small mono byte-next" }, t("byte.next", new Date(data.next_run).toLocaleString(lang, { weekday: "short", hour: "2-digit", minute: "2-digit" }))));

  const history = data.history.length > 1 ? el("div", { class: "chips byte-history" },
    el("span", { class: "muted small" }, t("byte.history")),
    ...data.history.slice(0, 7).map((day) => el("button", {
      type: "button", class: `chip ${day === d.date ? "on" : ""}`,
      onclick: () => { digestDate = day === data.history[0] ? null : day; loadDigest(); },
    }, dayLabel(day)))) : null;

  const stories = el("ol", { class: "byte-stories" }, ...d.stories.map((s, i) => el("li", { style: `--h:${NEWS_HUE[s.category] || 260}; animation-delay:${i * 70}ms` },
    el("span", { class: "num mono" }, String(i + 1).padStart(2, "0")),
    el("div", {},
      el("div", { class: "meta mono muted small" }, `${s.source}${s.published ? " · " + timeAgo(s.published) : ""}`),
      el("h3", {}, safeLink(s.link) ? el("a", { href: s.link, target: "_blank", rel: "noopener noreferrer" }, s.headline || s.title) : (s.headline || s.title)),
      s.why ? el("p", {}, s.why) : (s.summary ? el("p", { class: "muted" }, trunc(s.summary, 200)) : null),
      s.for_you ? el("p", { class: "for-you" }, el("b", {}, t("byte.forYou")), " ", s.for_you) : null))));

  const side = el("aside", { class: "byte-side" });
  if (d.tool) {
    side.append(el("div", { class: "byte-card" }, el("h4", {}, t("byte.tool")),
      el("b", {}, d.tool.name), el("p", { class: "muted small" }, d.tool.what),
      d.tool.try_prompt ? el("div", { class: "prompt-box" }, el("span", { class: "mono small muted" }, t("byte.tryPrompt")), el("p", {}, d.tool.try_prompt),
        el("button", { type: "button", class: "small", onclick: () => copy(d.tool.try_prompt) }, t("byte.copyPrompt"))) : null,
      safeLink(d.tool.link) ? el("a", { class: "link-btn", href: d.tool.link, target: "_blank", rel: "noopener noreferrer" }, t("n.read")) : null));
  }
  side.append(challengeCard(d));
  if (d.word) side.append(el("div", { class: "byte-card" }, el("h4", {}, t("byte.word")), el("b", { class: "word" }, d.word.term), el("p", { class: "small" }, d.word.explain)));
  if (!d.ai) side.append(el("p", { class: "muted small" }, t("byte.localHint")));

  const tldr = d.tldr ? el("p", { class: "byte-tldr" }) : null;
  body.replaceChildren(stats, ...(tldr ? [tldr] : []), actions, ...(history ? [history] : []), el("div", { class: "byte-grid" }, stories, side));
  if (tldr) tldr.textContent = d.tldr;
}

function challengeCard(d) {
  // Fără AI: provocarea zilei e promptul unui topic din ghid (altul în fiecare zi)
  let title = d.challenge && d.challenge.title, steps = d.challenge ? d.challenge.steps : null;
  if (!steps) {
    const keys = cfg.topics.filter((k) => k !== "other");
    const tp = topic(keys[Number(d.date.replaceAll("-", "")) % keys.length]);
    title = `${tp.icon} ${tp.title}`;
    steps = [t("byte.guideStep1", tp.title), tp.prompt, t("byte.guideStep3")];
  }
  const key = `cutia-challenge-${d.date}`;
  let done = [];
  try { done = JSON.parse(localStorage.getItem(key)) || []; } catch (_) {}
  const card = el("div", { class: "byte-card challenge" }, el("h4", {}, t("byte.challenge")), el("b", {}, title));
  const list = el("ul", { class: "steps" });
  steps.forEach((step, i) => {
    const box = el("input", { type: "checkbox" });
    box.checked = done.includes(i);
    box.addEventListener("change", () => {
      done = box.checked ? [...done, i] : done.filter((x) => x !== i);
      try { localStorage.setItem(key, JSON.stringify(done)); } catch (_) {}
      if (done.length === steps.length) {
        toast(t("byte.challengeDone"));
        confetti();
        // Se numără la misiunea săptămânii „Provocarea lui Byte”
        if (!isTrainer()) api("/api/challenge", { method: "POST", body: { date: d.date } }).then(loadQuests).catch(() => {});
      }
    });
    list.append(el("li", {}, el("label", {}, box, el("span", {}, step))));
  });
  card.append(list);
  return card;
}

function digestText(d) {
  const lines = [`Byte · ${d.title || t("byte.eyebrow")} (${d.date})`, ""];
  if (d.tldr) lines.push(d.tldr, "");
  d.stories.forEach((s, i) => lines.push(`${i + 1}. ${s.headline || s.title}`, ...(s.why ? [`   ${s.why}`] : []), `   ${s.link}`));
  if (d.tool) lines.push("", `${t("byte.tool")}: ${d.tool.name}`);
  return lines.join("\n");
}

function toggleListen(d) {
  const synth = window.speechSynthesis;
  if (speaking) { synth.cancel(); speaking = false; renderByte(); return; }
  const text = [d.title, d.tldr, ...d.stories.map((s) => `${s.headline || s.title}. ${s.why || ""}`)].filter(Boolean).join(" … ");
  const u = new SpeechSynthesisUtterance(text);
  u.lang = SPEECH_LANG[lang] || "en-US";
  const voice = synth.getVoices().find((v) => v.lang && v.lang.toLowerCase().startsWith(lang));
  if (voice) u.voice = voice;
  u.rate = 1.02;
  u.onend = u.onerror = () => { speaking = false; renderByte(); };
  synth.cancel();
  synth.speak(u);
  speaking = true;
  renderByte();
}

async function rerunDigest() {
  try {
    await api("/api/digest/run", { method: "POST" });
    toast(t("byte.rerunStarted"));
    digestDate = null;
    digestPolls = 0;
    digestData = { ...(digestData || {}), generating: true };
    renderByte();
    digestPoll = setTimeout(() => loadDigest(), 4000);
  } catch (err) { toast(err.message); }
}


// ================================================================ Atelier (privat): repo, Error Doctor, Prompt Lab

let wsTab = "repo", repoResult = null;

function showWs(tab) {
  wsTab = tab;
  document.querySelectorAll(".ws-tabs button").forEach((b) => {
    b.classList.toggle("on", b.dataset.ws === tab);
    b.setAttribute("aria-selected", String(b.dataset.ws === tab));
  });
  ["repo", "doctor", "prompt"].forEach((k) => $(`#ws-${k}`).classList.toggle("hidden", k !== tab));
  if (tab === "doctor") loadDoctorHistory();
}
document.querySelectorAll(".ws-tabs button").forEach((b) => b.addEventListener("click", () => showWs(b.dataset.ws)));
$("#s-link-check").addEventListener("click", () => {
  const url = $("#s-link").value.trim();
  if (url) checkRepoFrom(url);
  else $("#s-link").focus();
});

function checkRepoFrom(url) {
  showView("workshop");
  showWs("repo");
  $("#repo-url").value = url;
  runRepoCheck(url);
}

$("#repo-form").addEventListener("submit", (e) => {
  e.preventDefault();
  runRepoCheck($("#repo-url").value.trim());
});

function scanning(text) {
  return el("div", { class: "card panel scan-card" }, el("span", { class: "scan-line" }), el("span", {}, text, el("span", { class: "dots" })));
}

async function runRepoCheck(url) {
  const box = $("#repo-result");
  box.replaceChildren(scanning(t("rc.checking")));
  try {
    repoResult = await api("/api/repo-check", { method: "POST", body: { url } });
    renderRepoResult();
    if (repoResult.passed === repoResult.total) confetti();
  } catch (err) {
    box.replaceChildren(el("p", { class: "error" }, err.message));
  }
}

function renderRepoResult() {
  const r = repoResult;
  if (!r) return;
  const ICON = { ok: "✓", warn: "!", fail: "✕", manual: "☐" };
  const pct = Math.round((r.passed / Math.max(1, r.total)) * 100);
  const details = (c) => {
    const lines = [];
    if (c.key === "live_link" && safeLink(c.detail)) lines.push(el("a", { href: c.detail, target: "_blank", rel: "noopener noreferrer", class: "small" }, c.detail));
    if (c.key === "no_env_file") (c.detail || []).forEach((f) => lines.push(el("code", {}, f)));
    if (c.key === "no_keys_now") (c.detail || []).forEach((d) => lines.push(el("code", {}, `${d.file} · ${d.kind} · ${d.masked}`)));
    if (c.key === "no_keys_history") {
      (c.detail || []).forEach((d) => lines.push(el("code", {}, `${d.commit} · ${d.file} · ${d.kind} · ${d.masked}`)));
      lines.push(el("span", { class: "muted small" }, t("rc.scanned", c.scanned)));
    }
    return lines;
  };
  const alarm = r.checks.some((c) => c.key.startsWith("no_keys") && c.status === "fail");
  $("#repo-result").replaceChildren(el("div", { class: "card panel rc" },
    el("div", { class: "rc-head" },
      el("div", { class: `score-ring ${pct === 100 ? "full" : ""}`, style: `--p:${pct}` }, el("b", {}, `${r.passed}/${r.total}`)),
      el("div", {},
        el("h3", {}, el("a", { href: r.url, target: "_blank", rel: "noopener noreferrer" }, r.repo)),
        el("p", { class: "muted small mono" }, `${r.head} · ${timeAgo(r.checked_at)}`),
        el("p", {}, r.passed === r.total ? t("rc.allGood") : t("rc.score", r.passed, r.total)))),
    alarm ? el("div", { class: "alarm" }, t("rc.keyAlarm")) : null,
    el("ul", { class: "rc-list" }, ...r.checks.map((c, i) => el("li", { class: `rc-row ${c.status}`, style: `animation-delay:${i * 50}ms` },
      el("span", { class: "rc-ico" }, ICON[c.status]),
      el("div", {}, el("b", {}, t("rc.k." + c.key)),
        c.status !== "ok" ? el("p", { class: "muted small" }, t("rc.f." + c.key)) : null,
        ...details(c))))),
    isTrainer() ? null : el("div", { class: "row end" }, el("button", { type: "button", class: "small", onclick: () => {
      showView("submissions");
      $("#s-link").value = r.url;
      $("#s-link").dispatchEvent(new Event("input"));
    } }, t("rc.useInSubmit")))));
}


// ---------------------------------------------------------------- Error Doctor

let doctorHistory = [], doctorLoaded = false;

$("#doc-image").addEventListener("change", () => {
  const f = $("#doc-image").files[0];
  $("#doc-image-name").textContent = f ? f.name : "";
});

// Lipești o captură direct din clipboard (Ctrl+V) în câmpul de eroare
$("#doc-text").addEventListener("paste", (e) => {
  const item = [...(e.clipboardData ? e.clipboardData.items : [])].find((i) => i.type.startsWith("image/"));
  if (!item) return;
  const file = item.getAsFile();
  const dt = new DataTransfer();
  dt.items.add(new File([file], "screenshot.png", { type: file.type }));
  $("#doc-image").files = dt.files;
  $("#doc-image-name").textContent = "📷 screenshot.png";
});

$("#doctor-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = new FormData();
  form.append("text", $("#doc-text").value);
  if ($("#doc-image").files[0]) form.append("image", $("#doc-image").files[0]);
  $("#doc-result").replaceChildren(scanning(t("doc.thinking")));
  try {
    const res = await fetch("/api/doctor", { method: "POST", body: form, headers: { "X-Lang": lang, Authorization: `Bearer ${auth.token}` } });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || t("err.generic"));
    $("#doc-image").value = "";
    $("#doc-image-name").textContent = "";
    doctorHistory.unshift(data);
    renderDoctorResult(data);
    renderDoctorHistory();
  } catch (err) {
    $("#doc-result").replaceChildren(el("p", { class: "error" }, err.message));
  }
});

function doctorCard(d) {
  const r = d.result;
  const title = r ? r.title : t(`doc.l.${d.local}.t`);
  const prompt = r ? r.prompt : t("doc.localPrompt", d.excerpt || "…");
  const steps = r ? r.steps : t(`doc.l.${d.local}.s`).split(" | ");
  const sev = r ? r.severity : null;
  return el("div", { class: "card panel doctor-card" },
    el("div", { class: "doctor-head" },
      el("span", { class: "doctor-ico" }, "🩺"),
      el("div", {}, el("h3", {}, title),
        el("p", { class: "muted small mono" }, `${timeAgo(d.created_at)}${d.image ? " · 📷" : ""} · ${r ? "AI" : t("doc.localTag")}`)),
      sev ? el("span", { class: `sev ${sev}` }, t("doc.sev." + sev)) : null),
    d.had_key ? el("div", { class: "alarm" }, t("doc.keyFound")) : null,
    r ? el("p", {}, r.explain) : el("p", {}, t(`doc.l.${d.local}.e`)),
    r && r.cause ? el("p", { class: "muted" }, el("b", {}, t("doc.cause")), " ", r.cause) : null,
    el("h4", {}, t("doc.steps")),
    el("ol", { class: "doctor-steps" }, ...steps.map((s) => el("li", {}, s))),
    el("div", { class: "prompt-box" }, el("span", { class: "mono small muted" }, t("doc.promptLabel")), el("p", {}, prompt),
      el("button", { type: "button", class: "small", onclick: () => copy(prompt) }, t("byte.copyPrompt"))),
    r ? null : el("p", { class: "muted small" }, t("doc.localHint")));
}

function renderDoctorResult(d) {
  $("#doc-result").replaceChildren(doctorCard(d));
}

async function loadDoctorHistory() {
  if (doctorLoaded || !auth) return;
  try { doctorHistory = await api("/api/doctor"); doctorLoaded = true; } catch (_) {}
  renderDoctorHistory();
}

function renderDoctorHistory() {
  $("#doc-history").replaceChildren(...(doctorHistory.length ? doctorHistory.map((d) => el("div", { class: "mini" },
    el("button", { type: "button", class: "mini-main", onclick: () => renderDoctorResult(d) },
      el("span", { class: "k" }, "🩺"), el("span", { class: "t" }, d.result ? d.result.title : t(`doc.l.${d.local}.t`)),
      el("span", { class: "muted small" }, timeAgo(d.created_at))),
    el("button", { type: "button", class: "icon-btn", "aria-label": t("doc.delete"), onclick: async () => {
      try {
        await api(`/api/doctor/${d.id}`, { method: "DELETE" });
        doctorHistory = doctorHistory.filter((x) => x.id !== d.id);
        renderDoctorHistory();
      } catch (err) { toast(err.message); }
    } }, "✕"))) : [el("div", { class: "empty" }, t("doc.noHistory"))]));
}

// ---------------------------------------------------------------- Prompt Lab

let lastLab = null;

$("#prompt-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const prompt = $("#pl-text").value.trim();
  $("#pl-result").replaceChildren(scanning(t("pl.thinking")));
  try {
    lastLab = { prompt, ...(await api("/api/prompt-lab", { method: "POST", body: { prompt } })) };
    renderLab();
  } catch (err) { $("#pl-result").replaceChildren(el("p", { class: "error" }, err.message)); }
});

function renderLab() {
  const r = lastLab;
  const total = Object.values(r.scores).reduce((a, b) => a + b, 0);
  const improved = r.improved || t("pl.skeleton", r.prompt);
  const tips = r.ai ? r.tips : r.tips.map((c) => t("pl.tip." + c));
  const bars = el("div", { class: "lab-bars" }, ...Object.entries(r.scores).map(([k, v]) => el("div", { class: "lab-bar" },
    el("span", {}, t("pl.c." + k)), el("span", { class: "track" }, el("i", { style: `width:${v * 20}%` })), el("b", { class: "mono" }, `${v}/5`))));
  const shareTitle = el("input", { maxlength: 80, placeholder: t("hall.titlePh") });
  const share = el("div", { class: "row" }, shareTitle, el("button", { type: "button", class: "small", onclick: async () => {
    try {
      await api("/api/hall", { method: "POST", body: { title: shareTitle.value || t("hall.untitled"), prompt: improved } });
      toast(t("hall.shared"));
      loadHall();
    } catch (err) { toast(err.message); }
  } }, t("hall.share")));
  $("#pl-result").replaceChildren(el("div", { class: "card panel lab" },
    el("div", { class: "rc-head" },
      el("div", { class: `score-ring ${total >= 16 ? "full" : ""}`, style: `--p:${total * 5}` }, el("b", {}, `${total}/20`)),
      el("div", {}, el("h3", {}, t(total >= 16 ? "pl.great" : total >= 10 ? "pl.good" : "pl.weak")), r.verdict ? el("p", {}, r.verdict) : null)),
    r.had_key ? el("div", { class: "alarm" }, t("doc.keyFound")) : null,
    bars,
    tips.length ? el("ul", { class: "lab-tips" }, ...tips.map((x) => el("li", {}, x))) : null,
    el("div", { class: "prompt-box" }, el("span", { class: "mono small muted" }, t(r.ai ? "pl.improved" : "pl.template")), el("p", {}, improved),
      el("div", { class: "row" },
        el("button", { type: "button", class: "small", onclick: () => copy(improved) }, t("byte.copyPrompt")),
        el("button", { type: "button", class: "small ghost", onclick: () => { $("#pl-text").value = improved; $("#pl-text").focus(); } }, t("pl.useIt")))),
    el("h4", {}, t("hall.shareTitle")), share));
}

// ---------------------------------------------------------------- Întrebări frecvente (public, în Ghid)

let faq = [];

async function loadFaq() {
  if (!auth) return;
  try { faq = await api("/api/faq"); } catch (_) { faq = []; }
  renderFaq();
}

function faqEditor(item, onDone) {
  const q = el("input", { maxlength: 300, value: item ? item.q : "", placeholder: t("faq.qPh") });
  const a = el("textarea", { rows: 3, maxlength: 3000, placeholder: t("faq.aPh") });
  a.value = item ? item.a : "";
  return el("form", { class: "card composer faq-form", onsubmit: async (e) => {
    e.preventDefault();
    try {
      await api(item && item.id ? `/api/faq/${item.id}` : "/api/faq", { method: item && item.id ? "PUT" : "POST", body: { q: q.value, a: a.value, ...(item && !item.id && item.question_id ? { question_id: item.question_id } : {}) } });
      toast(t("faq.saved"));
      if (onDone) onDone();
      loadFaq();
    } catch (err) { toast(err.message); }
  } }, q, a, el("div", { class: "row end" }, el("button", { type: "submit", class: "small primary" }, t(item && item.id ? "faq.save" : "faq.add"))));
}

function renderFaq() {
  $("#faq-trainer").replaceChildren(...(isTrainer() ? [faqEditor(null)] : []));
  $("#faq-list").replaceChildren(...(faq.length ? faq.map((f) => {
    const item = el("details", { class: "faq-item" }, el("summary", {}, f.q), el("div", { class: "md-wrap" }, renderMd(f.a)));
    if (isTrainer()) item.append(el("div", { class: "row" },
      el("button", { type: "button", class: "small ghost", onclick: () => item.replaceWith(faqEditor(f)) }, t("faq.edit")),
      el("button", { type: "button", class: "small ghost", onclick: async () => {
        if (!confirm(t("faq.deleteConfirm"))) return;
        try { await api(`/api/faq/${f.id}`, { method: "DELETE" }); loadFaq(); } catch (err) { toast(err.message); }
      } }, "✕")));
    return item;
  }) : [el("div", { class: "empty" }, t("faq.empty"))]));
}

// ---------------------------------------------------------------- Serii și misiuni săptămânale (student)

let quests = null;

async function loadQuests() {
  if (!auth || isTrainer()) return;
  try { quests = await api("/api/quests"); } catch (_) { return; }
  renderLevelCard();
  if (currentView === "points") renderPoints();
}

function questsCard() {
  if (!quests) return el("span");
  const s = quests.streak;
  const end = new Date(quests.week_end + "T23:59:59");
  const daysLeft = Math.max(0, Math.ceil((end - Date.now()) / 86400000));
  return el("div", { class: "card panel quests" },
    el("div", { class: "quests-head" },
      el("div", { class: `flame ${s.today ? "lit" : ""}` }, el("span", {}, "🔥"), el("b", {}, String(s.current))),
      el("div", {}, el("h3", {}, t(s.current === 1 ? "qs.streak1" : "qs.streak", s.current)), el("p", { class: "muted small" },
        s.today ? t("qs.todayDone") : s.current ? t("qs.keepGoing") : t("qs.start"), " · ", t("qs.best", s.best)))),
    el("div", { class: "panel-head" }, el("h3", {}, t("qs.title")), el("span", { class: "muted small mono" }, t("qs.left", daysLeft))),
    el("div", { class: "quest-list" }, ...quests.quests.map((q) => el("div", { class: `quest ${q.done ? "done" : ""}` },
      el("span", { class: "q-ico" }, q.done ? "✓" : QUEST_ICON[q.key]),
      el("div", {}, el("b", {}, t("qs.q." + q.key, q.target)),
        el("div", { class: "xp" }, el("i", { style: `width:${Math.round((q.progress / q.target) * 100)}%` }))),
      el("span", { class: "mono small" }, q.done ? `+${quests.reward}` : `${q.progress}/${q.target}`)))));
}
const QUEST_ICON = { ask: "?", homework: "⇪", byte: "⏱", lab: "🧪", live: "●", idea: "✦", showcase: "★", doctor: "🩺" };

// ---------------------------------------------------------------- Recap săptămânal (trainer, pe Acasă)

let recap = null;

async function loadRecap(refresh = false) {
  if (!auth || !isTrainer()) return;
  if (refresh) $("#recap-card").replaceChildren(scanning(t("rec.loading")));
  try { recap = await api(`/api/recap${refresh ? "?refresh=true" : ""}`); } catch (err) { if (refresh) toast(err.message); }
  renderRecap();
}

function renderRecap() {
  const card = $("#recap-card");
  card.classList.toggle("hidden", !isTrainer() || !recap);
  if (!recap || !isTrainer()) return;
  const st = recap.stats;
  const stat = (n, label, view) => el("button", { type: "button", class: "recap-stat", onclick: view ? () => showView(view) : null }, el("b", {}, String(n)), el("span", {}, label));
  const publish = (s) => {
    const box = el("div", { class: "faq-suggest" }, el("b", {}, s.q), el("p", { class: "small muted" }, trunc(s.a, 220)),
      el("button", { type: "button", class: "small", onclick: () => box.replaceWith(faqEditor({ q: s.q, a: s.a, question_id: s.question_id }, () => loadRecap())) }, t("rec.toFaq")));
    return box;
  };
  card.replaceChildren(
    el("div", { class: "panel-head" }, el("h3", {}, t("rec.title")),
      el("button", { type: "button", class: "link-btn", onclick: () => loadRecap(true) }, t(cfg.ai ? "rec.refreshAi" : "rec.refresh"))),
    el("div", { class: "recap-stats" },
      stat(st.active + "/" + st.students, t("rec.active")), stat(st.questions_new, t("rec.qNew"), "questions"),
      stat(st.questions_open, t("rec.qOpen"), "questions"), stat(st.to_review, t("rec.review"), "submissions"),
      stat(st.ideas_new, t("rec.ideas"), "box"), stat(st.projects_new, t("rec.projects"), "showcase"),
      stat(st.live_classes, t("rec.live"), "live"), stat(st.stuck_peak, t("rec.stuck"))),
    recap.topics.length ? el("div", { class: "chips" }, el("span", { class: "muted small" }, t("rec.topics")),
      ...recap.topics.map((x) => { const tp = topic(x.key); return el("span", { class: "chip", style: `--h:${tp.hue}` }, `${tp.icon} ${tp.title} · ${x.count}`); })) : null,
    recap.ai ? el("div", { class: "recap-ai" }, el("p", {}, recap.ai.summary),
      el("h4", {}, t("rec.focus")), el("ul", {}, ...recap.ai.focus.map((f) => el("li", {}, f)))) : null,
    recap.inactive.length ? el("p", { class: "small" }, el("b", {}, t("rec.inactive")), " ", recap.inactive.join(", ")) : null,
    recap.faq_suggestions.length ? el("div", {}, el("h4", {}, t("rec.faq")), el("div", { class: "faq-suggests" }, ...recap.faq_suggestions.map(publish))) : null);
}

// ---------------------------------------------------------------- Hall of Prompts (public, în Ghid)

let hall = [];

async function loadHall() {
  if (!auth) return;
  try { hall = await api("/api/hall"); } catch (_) { hall = []; }
  renderHall();
}

function renderHall() {
  $("#hall-list").replaceChildren(...(hall.length ? hall.map((h) => el("article", { class: "hall-card" },
    el("div", { class: "meta mono muted small" }, `${h.author} · ${timeAgo(h.created_at)}`),
    el("h3", {}, h.title),
    el("p", { class: "mono small hall-prompt" }, h.prompt),
    el("div", { class: "row" },
      el("button", { type: "button", class: `small ${h.liked ? "on" : "ghost"}`, disabled: h.mine, onclick: async () => {
        try { Object.assign(h, await api(`/api/hall/${h.id}/like`, { method: "POST" })); renderHall(); } catch (err) { toast(err.message); }
      } }, `♥ ${h.likes}`),
      el("button", { type: "button", class: "small ghost", onclick: () => copy(h.prompt) }, t("byte.copyPrompt")),
      h.mine || isTrainer() ? el("button", { type: "button", class: "small ghost", onclick: async () => {
        if (!confirm(t("hall.deleteConfirm"))) return;
        try { await api(`/api/hall/${h.id}`, { method: "DELETE" }); loadHall(); } catch (err) { toast(err.message); }
      } }, "✕") : null))) : [el("div", { class: "empty" }, t("hall.empty"))]));
}


// ================================================================ Ora live (public, cât ține ora)

let live = null, livePollTimer = null;

async function loadLive() {
  if (!auth) return;
  const wasActive = live && live.active;
  try { live = await api("/api/live"); } catch (_) { return; }
  if (live.active && wasActive === false && !isTrainer()) toast(t("live.startedToast"));
  renderLive();
}

function scheduleLive() {
  clearTimeout(livePollTimer);
  livePollTimer = setTimeout(async () => {
    await loadLive();
    if (auth) scheduleLive();
  }, currentView === "live" ? 3000 : 20000);
}

async function liveAction(path, body = {}) {
  try {
    live = await api(path, { method: "POST", body });
    renderLive();
    return true;
  } catch (err) { toast(err.message); return false; }
}

function renderLive() {
  if (!auth) return;
  const on = Boolean(live && live.active);
  $("#live-badge").classList.toggle("hidden", !on);
  const nav = document.querySelector('.nav-item[data-view="live"]');
  if (nav) nav.classList.toggle("on-air", on);
  $("#live-lead").textContent = t(on ? "live.leadOn" : "live.leadOff");
  if (!live) return;
  // Nu redesenăm cât timp cineva scrie în ecranul live (altfel pierde textul)
  const active = document.activeElement;
  if (active && $("#live-body").contains(active) && /INPUT|TEXTAREA/.test(active.tagName) && active.value) return;
  $("#live-body").replaceChildren(on ? liveRoom() : liveOff());
}

function liveOff() {
  if (isTrainer()) {
    const title = el("input", { maxlength: 120, placeholder: t("live.titlePh") });
    return el("form", { class: "card composer live-start", onsubmit: (e) => { e.preventDefault(); liveAction("/api/live/start", { title: title.value }); } },
      el("div", { class: "composer-head" }, el("span", { class: "prompt mono live-dot" }, "●"), el("h2", {}, t("live.startTitle"))),
      title, el("div", { class: "row end" }, el("button", { type: "submit", class: "primary glow" }, t("live.start"))));
  }
  const recent = live.last_ended_at && Date.now() - new Date(live.last_ended_at) < 3 * 3600 * 1000;
  return el("div", { class: "card empty live-off" },
    el("div", { class: "live-orb" }), el("h3", {}, t("live.offTitle")), el("p", { class: "muted" }, t("live.offText")),
    recent ? el("div", { class: "live-after" }, el("p", {}, t("live.ended")),
      el("button", { type: "button", class: "primary", onclick: () => showView("box") }, t("live.toBox"))) : null);
}

function liveRoom() {
  const T = isTrainer();
  const head = el("div", { class: "card live-head" },
    el("span", { class: "on-air-pill mono" }, el("i"), "LIVE"),
    el("div", {}, el("h2", {}, live.title || t("live.title")), el("p", { class: "muted small mono" }, t("live.started", timeAgo(live.started_at)))),
    T ? el("button", { type: "button", class: "small ghost", onclick: () => { if (confirm(t("live.endConfirm"))) liveAction("/api/live/end"); } }, t("live.end")) : null);

  // „M-am blocat”: studentul apasă, trainerul vede doar numărul
  const stuck = T
    ? el("div", { class: "card live-stuck trainer" },
        el("b", { class: `stuck-num ${live.stuck ? "hot" : ""}` }, String(live.stuck)),
        el("p", {}, t("live.stuckCount", live.stuck)), el("p", { class: "muted small" }, t("live.stuckPeak", live.stuck_peak)),
        el("button", { type: "button", class: "small", onclick: () => liveAction("/api/live/stuck/reset") }, t("live.stuckReset")))
    : el("div", { class: "card live-stuck" },
        el("button", { type: "button", class: `stuck-btn ${live.me_stuck ? "on" : ""}`, onclick: () => liveAction("/api/live/stuck") },
          t(live.me_stuck ? "live.unstuckBtn" : "live.stuckBtn")),
        el("p", { class: "muted small" }, t("live.stuckAnon")),
        live.stuck ? el("p", { class: "small" }, t("live.stuckCount", live.stuck)) : null);

  const poll = el("div", { class: "card panel live-poll" }, el("div", { class: "panel-head" }, el("h3", {}, t("live.pollTitle"))));
  if (T) {
    const q = el("input", { maxlength: 200, placeholder: t("live.pollQ") });
    const opts = [1, 2, 3, 4].map((i) => el("input", { maxlength: 80, placeholder: t("live.pollOpt", i) }));
    poll.append(el("form", { class: "poll-form", onsubmit: async (e) => {
      e.preventDefault();
      if (await liveAction("/api/live/polls", { question: q.value, options: opts.map((o) => o.value) })) { q.value = ""; opts.forEach((o) => (o.value = "")); }
    } }, q, el("div", { class: "poll-opts" }, ...opts), el("div", { class: "row end" }, el("button", { type: "submit", class: "small primary" }, t("live.pollStart")))));
  }
  if (!live.polls.length) poll.append(el("p", { class: "muted small" }, t("live.pollNone")));
  live.polls.slice(0, 3).forEach((p) => {
    const total = Math.max(1, p.total);
    poll.append(el("div", { class: `poll ${p.open ? "open" : ""}` },
      el("b", {}, p.question),
      ...p.options.map((o, i) => p.results
        ? el("div", { class: `poll-res ${p.my_vote === i ? "mine" : ""}` }, el("span", { class: "fill", style: `width:${Math.round((p.results[i] / total) * 100)}%` }),
            el("span", { class: "lbl" }, o), el("span", { class: "mono" }, `${Math.round((p.results[i] / total) * 100)}%`))
        : el("button", { type: "button", class: "poll-opt", onclick: () => liveAction(`/api/live/polls/${p.id}/vote`, { option: i }) }, o)),
      el("div", { class: "row" }, el("span", { class: "muted small mono" }, t("live.pollVotes", p.total)),
        T && p.open ? el("button", { type: "button", class: "small ghost", onclick: () => liveAction(`/api/live/polls/${p.id}/close`) }, t("live.pollClose")) : null,
        !T && p.open && p.my_vote != null ? el("span", { class: "muted small" }, t("live.voteChange")) : null)));
    if (!T && p.open && p.results) {
      // poți schimba votul: butoanele rămân sub rezultate
      poll.lastChild.append(el("div", { class: "chips" }, ...p.options.map((o, i) =>
        el("button", { type: "button", class: `chip ${p.my_vote === i ? "on" : ""}`, onclick: () => liveAction(`/api/live/polls/${p.id}/vote`, { option: i }) }, o))));
    }
  });

  const ticketCard = el("div", { class: "card panel live-ticket" }, el("div", { class: "panel-head" }, el("h3", {}, t("live.ticketTitle"))));
  if (T) {
    const q = el("input", { maxlength: 300, placeholder: t("live.ticketPh"), value: live.ticket ? live.ticket.question : "" });
    ticketCard.append(el("form", { class: "row", onsubmit: (e) => { e.preventDefault(); liveAction("/api/live/ticket", { question: q.value }); } },
      q, el("button", { type: "submit", class: "small" }, t("live.ticketSet"))));
    if (live.ticket) {
      ticketCard.append(el("p", { class: "muted small mono" }, t("live.ticketAnswers", live.ticket.count)),
        el("div", { class: "ticket-answers" }, ...live.ticket.answers.map((a) => el("div", { class: "ticket-a" }, avatar(a.name), el("div", {}, el("b", {}, a.name), el("p", {}, a.text))))));
    }
  } else if (!live.ticket) {
    ticketCard.append(el("p", { class: "muted small" }, t("live.ticketWait")));
  } else {
    const a = el("textarea", { rows: 2, maxlength: 1000 });
    a.value = live.ticket.my_answer || "";
    ticketCard.append(el("p", {}, el("b", {}, live.ticket.question)),
      el("form", { onsubmit: (e) => { e.preventDefault(); liveAction("/api/live/ticket/answer", { text: a.value }).then((ok) => ok && toast(t("live.ticketSent"))); } },
        a, el("div", { class: "row end" }, el("button", { type: "submit", class: "small primary" }, t("live.ticketSend")))));
    if (live.ticket.my_answer) ticketCard.append(el("p", { class: "muted small" }, t("live.ticketSent")));
  }

  const text = el("input", { maxlength: 500, placeholder: t("live.queuePh") });
  const anon = el("input", { type: "checkbox" });
  const queue = el("div", { class: "card panel live-queue" },
    el("div", { class: "panel-head" }, el("h3", {}, t("live.queueTitle")), el("span", { class: "muted small mono" }, String(live.queue.length))),
    el("form", { class: "queue-form", onsubmit: async (e) => {
      e.preventDefault();
      if (await liveAction("/api/live/questions", { text: text.value, anonymous: anon.checked })) text.value = "";
    } }, text, el("label", { class: "check small" }, anon, t("live.anon")), el("button", { type: "submit", class: "small primary" }, t("live.ask"))),
    ...(live.queue.length ? live.queue.map((q) => el("div", { class: `queue-item ${q.answered ? "done" : ""}` },
      el("button", { type: "button", class: `upvote ${q.upvoted ? "on" : ""}`, disabled: q.mine, onclick: () => liveAction(`/api/live/questions/${q.id}/upvote`) },
        el("span", {}, "▲"), el("b", {}, String(q.upvotes))),
      el("div", {}, el("p", {}, q.text), el("span", { class: "muted small" }, q.author || t("live.anon"), " · ", timeAgo(q.created_at))),
      q.answered ? el("span", { class: "tag" }, t("live.answered")) : null,
      T ? el("button", { type: "button", class: "small ghost", onclick: () => liveAction(`/api/live/questions/${q.id}/answered`) }, q.answered ? "↺" : t("live.markAnswered")) : null))
      : [el("p", { class: "muted small" }, t("live.queueEmpty"))]));

  return el("div", {}, head, el("div", { class: "live-grid" }, el("div", { class: "live-col" }, stuck, poll, ticketCard), queue));
}


// ================================================================ Kickstart kit (idei alese)

async function openKickstart(p) {
  const list = (items) => el("ol", { class: "doctor-steps" }, ...items.map((x) => el("li", {}, x)));
  openDrawer("kickstart", 280, [el("div", { class: "ico" }, "🚀"), el("h2", { id: "drawer-title" }, p.title), scanning(t("kick.loading"))]);
  let kit;
  try { kit = await api(`/api/proposals/${p.id}/kickstart`); } catch (err) { kit = { ai: false }; }
  // Fără AI: un plan simplu construit din ce a scris studentul în propunere
  const firstPrompt = kit.ai ? kit.first_prompt : t("kick.localPrompt", p.title, p.description, p.audience);
  const firstHour = kit.ai ? kit.first_hour : t("kick.localHour").split(" | ");
  const later = kit.ai ? kit.later : t("kick.localLater").split(" | ");
  openDrawer("kickstart", 280, [
    el("div", { class: "ico" }, "🚀"),
    el("h2", { id: "drawer-title" }, p.title),
    el("p", { class: "muted" }, t("kick.lead", p.author)),
    el("h4", {}, t("kick.first")),
    el("div", { class: "prompt-box" }, el("p", {}, firstPrompt), el("button", { type: "button", class: "small", onclick: () => copy(firstPrompt) }, t("byte.copyPrompt"))),
    el("h4", {}, t("kick.hour")), list(firstHour),
    el("h4", {}, t("kick.later")), list(later),
    kit.ai ? el("p", {}, el("b", {}, t("kick.stack")), " ", kit.stack) : null,
    kit.ai ? el("div", { class: "alarm soft" }, el("b", {}, t("kick.risk")), " ", kit.risk) : null,
    el("h4", {}, t("kick.done")),
    el("ul", { class: "doctor-steps" }, ...CHECKLIST.map((k) => el("li", {}, t("s.ck." + k)))),
    el("div", { class: "row" }, el("button", { type: "button", class: "small", onclick: () => { closeDrawer(); showView("workshop"); showWs("repo"); } }, t("rc.checkBtn"))),
  ]);
}

// ================================================================ Demo Day (public)

let showcase = [];
const imageUrls = {};

async function loadShowcase() {
  if (!auth) return;
  try { showcase = await api("/api/showcase"); } catch (_) { return; }
  renderShowcase();
}

// Imaginile cer autentificare: le luăm cu fetch și le punem ca blob local
async function showcaseImage(item, img) {
  if (imageUrls[item.id]) { img.src = imageUrls[item.id]; return; }
  try {
    const res = await fetch(`/api/showcase/${item.id}/image`, { headers: { Authorization: `Bearer ${auth.token}` } });
    if (!res.ok) return;
    imageUrls[item.id] = URL.createObjectURL(await res.blob());
    img.src = imageUrls[item.id];
  } catch (_) {}
}

function showcaseCard(item, big = false) {
  const img = el("img", { alt: item.title, loading: "lazy" });
  if (item.has_image) showcaseImage(item, img);
  const react = (e) => el("button", { type: "button", class: `react ${item.my_reactions.includes(e) ? "on" : ""}`, disabled: item.mine, onclick: async () => {
    try { Object.assign(item, await api(`/api/showcase/${item.id}/react`, { method: "POST", body: { emoji: e } })); renderShowcase(); } catch (err) { toast(err.message); }
  } }, e, " ", el("b", {}, String(item.reactions[e])));
  return el("article", { class: `show-card ${big ? "big" : ""} ${item.spotlight ? "spot" : ""}` },
    el("div", { class: `shot ${item.has_image ? "" : "empty"}` }, item.has_image ? img : el("span", {}, "★"),
      item.spotlight ? el("span", { class: "spot-pill" }, t("sc.spotlight")) : null),
    el("div", { class: "show-body" },
      el("div", { class: "meta mono muted small" }, `${item.author} · ${timeAgo(item.created_at)}`),
      el("h3", {}, item.title),
      item.description ? el("p", {}, item.description) : null,
      el("div", { class: "row" },
        safeLink(item.live_url) ? el("a", { class: "btn-link primary", href: item.live_url, target: "_blank", rel: "noopener noreferrer" }, t("sc.open")) : null,
        safeLink(item.repo_url) ? el("a", { class: "btn-link", href: item.repo_url, target: "_blank", rel: "noopener noreferrer" }, "GitHub ↗") : null),
      el("div", { class: "row reacts" }, ...["🔥", "👏", "💡", "🤯"].map(react),
        isTrainer() ? el("button", { type: "button", class: `small ${item.spotlight ? "on" : "ghost"}`, onclick: async () => {
          try { await api(`/api/showcase/${item.id}/spotlight`, { method: "POST" }); loadShowcase(); confetti(); } catch (err) { toast(err.message); }
        } }, t(item.spotlight ? "sc.unspot" : "sc.spot")) : null,
        item.mine || isTrainer() ? el("button", { type: "button", class: "small ghost", onclick: async () => {
          if (!confirm(t("sc.deleteConfirm"))) return;
          try { await api(`/api/showcase/${item.id}`, { method: "DELETE" }); loadShowcase(); } catch (err) { toast(err.message); }
        } }, "✕") : null)));
}

function renderShowcase() {
  const spot = showcase.find((x) => x.spotlight);
  $("#spotlight").replaceChildren(...(spot ? [el("p", { class: "eyebrow mono" }, t("sc.weekTitle")), showcaseCard(spot, true)] : []));
  const rest = showcase.filter((x) => !x.spotlight);
  $("#showcase-list").replaceChildren(...(rest.length ? rest.map((x) => showcaseCard(x)) : spot ? [] : [el("div", { class: "empty" }, t("sc.empty"))]));
}

$("#sc-image").addEventListener("change", () => { const f = $("#sc-image").files[0]; $("#sc-image-name").textContent = f ? f.name : ""; });

$("#showcase-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = new FormData();
  [["title", "#sc-title"], ["description", "#sc-desc"], ["live_url", "#sc-live"], ["repo_url", "#sc-repo"]].forEach(([k, sel]) => form.append(k, $(sel).value));
  if ($("#sc-image").files[0]) form.append("image", $("#sc-image").files[0]);
  try {
    const res = await fetch("/api/showcase", { method: "POST", body: form, headers: { "X-Lang": lang, Authorization: `Bearer ${auth.token}` } });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(Array.isArray(data.detail) ? t("err.check") : data.detail || t("err.generic"));
    ["#sc-title", "#sc-desc", "#sc-live", "#sc-repo", "#sc-image"].forEach((sel) => ($(sel).value = ""));
    $("#sc-image-name").textContent = "";
    toast(t("sc.published"));
    confetti();
    loadShowcase();
    loadPoints();
  } catch (err) { toast(err.message); }
});

// ================================================================ points & leaderboard

async function loadPoints() {
  if (!auth) return;
  try {
    if (isTrainer()) {
      students = await api("/api/students");
    } else {
      const before = myPoints ? myPoints.total : null;
      myPoints = await api("/api/points/me");
      $("#points-chip-n").textContent = myPoints.total;
      $("#points-chip").title = `${t("pt.level", myPoints.level.index)} · ${t("lvl." + myPoints.level.key)}`;
      if (before !== null && myPoints.total > before) {
        const chip = $("#points-chip");
        chip.classList.remove("bump"); void chip.offsetWidth; chip.classList.add("bump");
        toast(`⚡ +${myPoints.total - before} ${t("pt.total")}`);
      }
    }
  } catch (_) { return; }
  await loadBoard();
  renderPoints();
  renderHome();
}

async function loadBoard() {
  try { board = await api("/api/leaderboard"); } catch (_) { board = []; }
  renderBoard();
}

function renderPoints() {
  if (!auth) return;
  if (isTrainer()) {
    const sel = $("#bonus-student");
    const current = sel.value;
    sel.replaceChildren(...students.map((s) => el("option", { value: s.key }, `${s.name} · ⚡${s.total}`)));
    if (students.some((s) => s.key === current)) sel.value = current;
    $("#reset-result").textContent = "";
    $("#bonus-quick").replaceChildren(...[5, 10, 20, -5].map((n) =>
      el("button", { type: "button", class: "small", onclick: () => ($("#bonus-points").value = n) }, n > 0 ? `+${n}` : String(n))));
  } else if (myPoints) {
    const prog = levelProgress(myPoints);
    const got = new Set(myPoints.badges);
    $("#my-points").replaceChildren(
      el("div", { class: "card points-hero" },
        el("div", { class: "ring", style: `--p:${prog.pct}` }, el("div", {}, el("div", {}, el("b", {}, String(myPoints.total)), el("small", {}, t("pt.total"))))),
        el("div", {},
          el("p", { class: "eyebrow mono" }, t("pt.level", myPoints.level.index)),
          el("h2", {}, t("lvl." + myPoints.level.key)),
          el("div", { class: "xp" }, el("i", { style: `width:${prog.pct}%` })),
          el("p", {}, prog.text))),
      questsCard(),
      el("div", { class: "card panel", style: "margin-bottom:1rem" },
        el("div", { class: "panel-head" }, el("h3", {}, t("pt.badges"))),
        el("div", { class: "badges" }, Object.entries(BADGES).map(([k, icon]) =>
          el("div", { class: `badge-card ${got.has(k) ? "got" : "locked"}` },
            el("span", { class: "bi" }, icon), el("b", {}, t("b." + k)), el("small", {}, t(`b.${k}.d`)))))),
      el("div", { class: "pts-cols" },
        el("div", { class: "card panel" },
          el("div", { class: "panel-head" }, el("h3", {}, t("pt.how"))),
          ...Object.entries(myPoints.rules).map(([k, v]) => el("div", { class: "rule" }, el("span", {}, t("rule." + k)), el("b", {}, `+${v}`))),
          el("div", { class: "rule" }, el("span", {}, t("rule.bonus")), el("b", {}, "±"))),
        el("div", { class: "card panel" },
          el("div", { class: "panel-head" }, el("h3", {}, t("pt.history"))),
          ...(myPoints.events.length ? myPoints.events.map((ev) => el("div", { class: "event" },
            el("span", { title: ev.ref || "" }, `${t("rule." + ev.kind)}${ev.ref ? " · " + (ev.kind === "quest" ? t("qs.n." + ev.ref) : ev.ref) : ""}`),
            el("b", { class: ev.points < 0 ? "neg" : "" }, `${ev.points > 0 ? "+" : ""}${ev.points}`)))
            : [el("div", { class: "empty" }, t("pt.noHistory"))]))));
  }
  renderBoard();
}

function renderBoard() {
  const medals = ["🥇", "🥈", "🥉"];
  const top = board.slice(0, 3);
  const order = [top[1], top[0], top[2]];
  $("#podium").replaceChildren(...(top.length >= 3 ? order.map((r, i) => el("div", { class: `p${[2, 1, 3][i]}` },
    el("span", { class: "medal" }, medals[[1, 0, 2][i]]), avatar(r.name, false), el("b", {}, r.name), el("small", {}, `⚡ ${r.total}`))) : []));
  $("#board").replaceChildren(...board.map((r) => el("div", { class: `board-row ${r.me ? "me" : ""}` },
    el("span", { class: "rk" }, `#${r.rank}`), avatar(r.name),
    el("span", { class: "nm" }, r.name, r.me ? ` (${t("pt.you")})` : "", r.hidden ? el("span", { class: "tag", style: "margin-left:.4rem" }, t("pt.hidden")) : null,
      el("small", { class: "muted mono", style: "margin-left:.5rem" }, `L${r.level}`)),
    el("span", { class: "sc" }, `⚡ ${r.total}`))));
}

$("#reset-pass").addEventListener("click", async () => {
  const key = $("#bonus-student").value;
  const student = students.find((x) => x.key === key);
  if (!student || !confirm(t(cfg.supabase ? "pt.resetConfirmEmail" : "pt.resetConfirm", student.name))) return;
  try {
    const r = await api(`/api/students/${encodeURIComponent(key)}/reset-password`, { method: "POST" });
    $("#reset-result").textContent = r.email_sent ? t("pt.resetEmailSent", student.name)
      : t("pt.resetDone", student.name, r.temporary_password);
  } catch (err) { toast(err.message); }
});

$("#bonus-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/points/bonus", {
      method: "POST",
      body: { student_key: $("#bonus-student").value, points: Number($("#bonus-points").value), reason: $("#bonus-reason").value },
    });
    $("#bonus-reason").value = "";
    toast(t("pt.given"));
    confetti();
    loadPoints();
  } catch (err) { toast(err.message); }
});

// ================================================================ guide

function renderGuide() {
  const counts = {};
  for (const q of questions) counts[q.category] = (counts[q.category] || 0) + 1;
  $("#topic-grid").replaceChildren(...cfg.topics.map((k, i) => {
    const tp = topic(k);
    const n = counts[k] || 0;
    const card = el("button", { type: "button", class: "topic-card", style: `--h:${tp.hue}; animation-delay:${i * 30}ms`, onclick: () => openTopic(k) },
      el("span", { class: "ico" }, tp.icon),
      n ? el("span", { class: "count" }, `${n} ${t(n === 1 ? "g.qcount1" : "g.qcount")}`) : null,
      el("h3", {}, tp.title),
      el("p", {}, tp.summary));
    card.addEventListener("pointermove", (e) => {
      const r = card.getBoundingClientRect();
      card.style.setProperty("--mx", `${e.clientX - r.left}px`);
      card.style.setProperty("--my", `${e.clientY - r.top}px`);
    });
    return card;
  }));
  const ranked = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 6);
  const heat = $("#heat");
  heat.classList.toggle("hidden", ranked.length === 0);
  if (!ranked.length) return;
  const max = ranked[0][1];
  heat.replaceChildren(el("h3", {}, t(isTrainer() ? "g.heatT" : "g.heatS")),
    ...ranked.map(([k, n]) => {
      const tp = topic(k);
      return el("div", { class: "heat-row", style: `--h:${tp.hue}` },
        el("span", { class: "name" }, `${tp.icon} ${tp.title}`),
        el("div", { class: "heat-bar" }, el("i", { style: `width:${(n / max) * 100}%` })),
        el("b", {}, String(n)));
    }));
}

// ================================================================ drawer: topic & settings

function openDrawer(mode, hueValue, body) {
  const drawer = $("#drawer");
  drawer.dataset.mode = mode;
  drawer.style.setProperty("--h", hueValue);
  $("#drawer-body").replaceChildren(...body);
  drawer.classList.remove("hidden");
  $("#drawer-backdrop").classList.remove("hidden");
  document.body.classList.add("no-scroll");
}

function closeDrawer() {
  $("#drawer").classList.add("hidden");
  $("#drawer-backdrop").classList.add("hidden");
  document.body.classList.remove("no-scroll");
}

$("#drawer-close").addEventListener("click", closeDrawer);
$("#drawer-backdrop").addEventListener("click", closeDrawer);

function openTopic(key) {
  const tp = topic(key);
  $("#drawer").dataset.topic = key;
  const body = [
    el("div", { class: "ico" }, tp.icon),
    el("h2", { id: "drawer-title" }, tp.title),
    el("p", { class: "muted" }, tp.summary),
    el("h4", {}, t("g.tips")),
    el("ol", {}, tp.tips.map((tip) => el("li", {}, tip))),
    el("h4", {}, t("g.prompt")),
    el("div", { class: "md" }, el("pre", {}, el("code", {}, tp.prompt),
      el("button", { class: "copy-btn small", type: "button", onclick: () => copy(tp.prompt) }, t("g.copy")))),
    el("h4", {}, t("g.pitfall")),
    el("p", { class: "pitfall" }, "⚠️ ", tp.pitfall),
  ];
  if (auth && !isTrainer()) {
    body.push(el("button", {
      class: "primary glow", type: "button",
      onclick: () => {
        selectedTopic = cfg.topics.includes(key) ? key : "other";
        renderChips();
        closeDrawer();
        showView("questions");
        $("#question-text").focus();
      },
    }, t("g.ask")));
  }
  openDrawer("topic", tp.hue, body);
  $("#drawer-close").focus();
}

function segment(options, current, onPick) {
  return el("div", { class: "seg" }, options.map(([value, label]) =>
    el("button", { type: "button", class: `small ${value === current ? "on" : ""}`, onclick: () => onPick(value) }, label)));
}

function openSettings() {
  const d = document.documentElement.dataset;
  const body = [
    el("div", { class: "ico" }, "⚙"),
    el("h2", { id: "drawer-title" }, t("settings")),
    el("div", { class: "set-group" }, el("h4", {}, t("set.lang")),
      el("div", { class: "lang-grid" }, LANGS.map((l) =>
        el("button", { type: "button", class: l.code === lang ? "on" : "", onclick: async () => { await setLang(l.code); openSettings(); } }, l.flag, " ", l.name)))),
    el("div", { class: "set-group" }, el("h4", {}, t("set.style")),
      el("div", { class: "theme-grid" }, THEMES.map(([name, color]) =>
        el("button", { type: "button", class: d.theme === name ? "on" : "", onclick: () => { setPref("theme", name); openSettings(); } },
          el("span", { class: "swatch", style: `background:${color}` }), t("theme." + name))))),
    el("div", { class: "set-group" }, el("h4", {}, t("set.motion")),
      segment([["on", t("set.on")], ["off", t("set.off")]], d.motion || "on", (v) => { setPref("motion", v); openSettings(); })),
    el("div", { class: "set-group" }, el("h4", {}, t("set.size")),
      segment([["normal", t("set.normal")], ["large", t("set.large")]], d.size || "normal", (v) => { setPref("size", v); openSettings(); })),
    el("div", { class: "set-group" }, el("h4", {}, t("set.intro")),
      segment([["on", t("set.on")], ["off", t("set.off")]], introEnabled() ? "on" : "off", (v) => {
        try { localStorage.setItem("cutia-intro", v); } catch (_) {}
        openSettings();
      })),
  ];
  if (auth) body.push(appGroup());
  if (auth) body.push(passwordForm());
  if (auth && !isTrainer()) {
    const box = el("input", { type: "checkbox" });
    box.checked = !(auth.prefs && auth.prefs.hide_from_leaderboard);
    box.addEventListener("change", async () => {
      try {
        const r = await api("/api/me", { method: "PATCH", body: { hide_from_leaderboard: !box.checked } });
        auth.prefs = r.prefs;
        loadBoard();
      } catch (err) { toast(err.message); }
    });
    body.push(el("div", { class: "set-group" },
      el("label", { class: "switch" }, el("span", {}, t("set.leaderboard")), box),
      el("p", { class: "muted small" }, t("set.leaderboardHint"))));
  }
  body.push(el("div", { class: "set-group" }, el("h4", {}, t("set.shortcuts")),
    el("div", { class: "kbd-list" },
      el("div", {}, el("span", { class: "kbd" }, "Ctrl K"), t("set.k1")),
      el("div", {}, el("span", { class: "kbd" }, "/"), t("set.k2")),
      el("div", {}, el("span", { class: "kbd" }, "Ctrl ↵"), t("set.k3")))));
  openDrawer("settings", 200, body);
}

$("#settings-btn").addEventListener("click", openSettings);

function passwordForm() {
  // Cont Google prin Supabase: parola se pune din linkul primit pe email
  if (cfg.supabase && auth.has_password === false) {
    const send = el("button", { type: "button", class: "ghost small" }, t("set.sendLink"));
    send.addEventListener("click", async () => {
      try {
        await api("/api/auth/supabase/recover", { method: "POST", body: { email: auth.email } });
        send.disabled = true;
        toast(t("set.linkSent"));
      } catch (err) { toast(err.message); }
    });
    return el("div", { class: "set-group" }, el("h4", {}, t("set.password")),
      el("p", { class: "muted small" }, t("set.passwordByEmail")), el("div", { class: "row end" }, send));
  }
  const current = el("input", { type: "password", autocomplete: "current-password", maxlength: 200 });
  const next = el("input", { type: "password", autocomplete: "new-password", maxlength: 200, placeholder: t("login.passwordNewPh") });
  const error = el("p", { class: "error" });
  const form = el("form", { class: "set-group" }, el("h4", {}, t("set.password")),
    auth.has_password === false ? null : el("label", {}, t("set.current"), current),
    el("label", {}, t("set.new"), next),
    el("div", { class: "row end" }, el("button", { type: "submit", class: "primary small" }, t("set.save"))), error);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    error.textContent = "";
    try {
      await api("/api/me/password", { method: "POST", body: { current: current.value, new: next.value } });
      current.value = next.value = "";
      auth.has_password = true;
      toast(t("set.saved"));
    } catch (err) { error.textContent = err.message; }
  });
  return form;
}


// ================================================================ Aplicație instalabilă (PWA) + notificări push

let installPrompt = null, swReg = null;

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").then((reg) => { swReg = reg; }).catch(() => {});
  // Click pe o notificare când aplicația e deja deschisă
  navigator.serviceWorker.addEventListener("message", (e) => {
    if (e.data && e.data.view && isLoggedIn() && Object.prototype.hasOwnProperty.call(VIEW_SPACE, e.data.view)) showView(e.data.view);
  });
}
// Revine internetul: reîncărcăm setările serverului și datele
window.addEventListener("online", () => {
  api("/api/config").then((c) => { cfg = c; }).catch(() => {});
  if (isLoggedIn()) refresh().catch(() => {});
});
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); installPrompt = e; });
window.addEventListener("appinstalled", () => { installPrompt = null; toast(t("app.installed")); });

const isStandalone = () => window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent);
const pushSupported = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

async function pushSubscription() {
  if (!pushSupported()) return null;
  const reg = swReg || await navigator.serviceWorker.ready;
  return reg.pushManager.getSubscription();
}

function keyBytes(b64) {
  const raw = atob((b64 + "=".repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

async function enablePush() {
  if (await Notification.requestPermission() !== "granted") { toast(t("app.denied")); return false; }
  const reg = swReg || await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(cfg.push_key) });
  await api("/api/push/subscribe", { method: "POST", body: sub.toJSON() });
  toast(t("app.pushOn"));
  return true;
}

async function disablePush() {
  const sub = await pushSubscription();
  if (sub) {
    await api("/api/push/unsubscribe", { method: "POST", body: { endpoint: sub.endpoint } }).catch(() => {});
    await sub.unsubscribe();
  }
  toast(t("app.pushOff"));
}

function appGroup() {
  const status = el("p", { class: "muted small" });
  const group = el("div", { class: "set-group" }, el("h4", {}, t("app.title")));
  // Instalare: Android/Chrome au buton; pe iPhone se face din Safari → Partajează
  if (isStandalone()) group.append(el("p", { class: "small" }, t("app.isInstalled")));
  else if (installPrompt) group.append(el("button", { type: "button", class: "primary small", onclick: async () => {
    installPrompt.prompt();
    await installPrompt.userChoice;
    installPrompt = null;
    openSettings();
  } }, t("app.install")));
  else group.append(el("p", { class: "small" }, t(isIOS() ? "app.iosHint" : "app.browserHint")));
  if (!cfg.push_key || !pushSupported()) {
    group.append(el("p", { class: "muted small" }, t(cfg.push_key ? (isIOS() && !isStandalone() ? "app.iosPush" : "app.noPush") : "app.pushOffServer")));
    return group;
  }
  const btn = el("button", { type: "button", class: "small" });
  const refresh = async () => {
    const on = Boolean(await pushSubscription()) && Notification.permission === "granted";
    btn.textContent = t(on ? "app.disable" : "app.enable");
    btn.dataset.on = on ? "1" : "";
    status.textContent = t(Notification.permission === "denied" ? "app.blocked" : on ? "app.onText" : "app.offText");
  };
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try { if (btn.dataset.on) await disablePush(); else await enablePush(); } catch (err) { toast(err.message || t("err.generic")); }
    btn.disabled = false;
    refresh();
  });
  refresh();
  group.append(el("div", { class: "row" }, btn), status);
  return group;
}

// ================================================================ command palette (Ctrl+K)

let paletteItems = [], paletteIndex = 0;

function paletteActions() {
  const views = ["home", "messages", "questions", "submissions", "workshop", "live", "box", "showcase", "news", "points", "guide"];
  const icons = { home: "⌂", messages: "✉", questions: "?", submissions: "⇪", workshop: "⚒", live: "●", box: "✦", showcase: "★", news: "◉", points: "⚡", guide: "#" };
  const items = views.map((v) => ({ icon: icons[v], label: t("k.go", t("nav." + v)), run: () => showView(v) }));
  items.push({ icon: "🤖", label: t("byte.palette"), run: () => showView("news") });
  if (!isTrainer()) {
    items.push(
      { icon: "?", label: t("k.ask"), run: () => { showView("questions"); setTimeout(() => $("#question-text").focus(), 60); } },
      { icon: "⇪", label: t("k.submit"), run: () => { showView("submissions"); setTimeout(() => $("#s-title").focus(), 60); } },
      { icon: "✦", label: t("k.idea"), run: () => { showView("box"); setTimeout(() => $("#p-description").focus(), 60); } },
      { icon: "✉", label: t("k.msg"), run: () => { showView("messages"); setTimeout(() => $("#chat-input").focus(), 60); } });
  }
  items.push({ icon: "⚙", label: t("k.settings"), run: openSettings });
  LANGS.forEach((l) => items.push({ icon: l.flag, label: t("k.lang", l.name), run: () => setLang(l.code) }));
  THEMES.forEach(([name]) => items.push({ icon: "◐", label: t("k.theme", t("theme." + name)), run: () => setPref("theme", name) }));
  cfg.topics.forEach((k) => items.push({ icon: topic(k).icon, label: t("k.topic", topic(k).title), run: () => openTopic(k) }));
  items.push({ icon: "⎋", label: t("k.logout"), run: () => logout() });
  return items;
}

function openPalette() {
  $("#palette").classList.remove("hidden");
  $("#palette-input").value = "";
  renderPalette();
  $("#palette-input").focus();
}

function closePalette() { $("#palette").classList.add("hidden"); }

function renderPalette() {
  const q = norm($("#palette-input").value.trim());
  paletteItems = paletteActions().filter((it) => !q || norm(it.label).includes(q)).slice(0, 12);
  paletteIndex = Math.min(paletteIndex, Math.max(0, paletteItems.length - 1));
  $("#palette-list").replaceChildren(...(paletteItems.length ? paletteItems.map((it, i) =>
    el("button", { class: `pal-item ${i === paletteIndex ? "on" : ""}`, role: "option", onclick: () => runPalette(i) },
      el("span", { class: "pi" }, it.icon), it.label, i === paletteIndex ? el("small", {}, "↵") : null))
    : [el("div", { class: "empty" }, t("k.empty"))]));
}

function runPalette(i) {
  const it = paletteItems[i];
  closePalette();
  if (it) it.run();
}

$("#palette-input").addEventListener("input", () => { paletteIndex = 0; renderPalette(); });
$("#palette-input").addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") { e.preventDefault(); paletteIndex = Math.min(paletteIndex + 1, paletteItems.length - 1); renderPalette(); }
  if (e.key === "ArrowUp") { e.preventDefault(); paletteIndex = Math.max(paletteIndex - 1, 0); renderPalette(); }
  if (e.key === "Enter") { e.preventDefault(); runPalette(paletteIndex); }
});
$("#palette").addEventListener("click", (e) => { if (e.target.id === "palette") closePalette(); });
$("#palette-btn").addEventListener("click", () => (isLoggedIn() ? openPalette() : null));

// ================================================================ onboarding

function maybeOnboard() {
  const key = `cutia-ob-${auth.role}-${auth.name.toLowerCase()}`;
  let seen = false;
  try { seen = Boolean(localStorage.getItem(key)); } catch (_) {}
  if (seen) return;
  $("#ob-title").textContent = t("ob.title", auth.name.split(/\s+/)[0]);
  $("#onboarding").classList.remove("hidden");
  $("#ob-go").onclick = () => {
    try { localStorage.setItem(key, "1"); } catch (_) {}
    $("#onboarding").classList.add("hidden");
    confetti();
  };
  $("#ob-go").focus();
}

// ================================================================ data & boot

async function loadAnnouncements() {
  announcements = await api("/api/announcements");
  renderAnnouncements();
  renderBell();
}

async function refresh() {
  try {
    await Promise.all([loadQuestions(), loadProposals(), loadSubmissions(), loadAssignments(), loadAnnouncements(), loadUnread(), loadDrafts()]);
    await loadPoints();
    renderNotifications();
  } catch (err) { toast(err.message); }
}

// Reîmprospătare periodică: mesajele des, restul la 20 de secunde
setInterval(() => {
  if (!isLoggedIn() || document.hidden) return;
  loadUnread().then(() => { renderBell(); if (currentView === "home") renderHome(); });
  if (currentView === "messages") loadChat();
}, 6000);

setInterval(() => {
  if (!isLoggedIn() || document.hidden) return;
  // Nu redesenăm cât timp cineva scrie un răspuns, un feedback sau așteaptă AI-ul
  if (!document.querySelector(".answer-form:not(.hidden)") && aiPending.size === 0) loadQuestions().catch(() => {});
  if (!document.querySelector(".review-form:not(.hidden)")) loadSubmissions().catch(() => {});
  loadProposals().catch(() => {});
  loadQuests();
  loadAssignments().catch(() => {});
  loadAnnouncements().catch(() => {});
  loadPoints();
}, 20000);

setStep(1);

(async function boot() {
  try { await Promise.all([loadLang("en"), loadLang(lang)]); } catch (_) { lang = "en"; }
  applyI18n();
  try { cfg = await api("/api/config"); } catch (_) {}
  if (cfg.supabase) $("#reset-pass").dataset.i18n = "pt.resetEmail";
  applyI18n();
  renderLogin();
  await handleSupabaseReturn();
  if (!$("#app-view").classList.contains("hidden")) return;  // a intrat din linkul Supabase
  if (auth && !supaToken) start();
  else runTerminal();
})();
