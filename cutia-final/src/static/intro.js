// Robotul 3D care te salută când intri în Cutia Clasei.
// Construit din forme simple cu Three.js (inclus local în /vendor, fără CDN).
// Textele vin din app.js deja traduse; aici doar le afișăm cu textContent.

import * as THREE from "three";
import { RoundedBoxGeometry } from "./vendor/RoundedBoxGeometry.js";
import { RoomEnvironment } from "./vendor/RoomEnvironment.js";

const ease = {
  outBack: (x) => 1 + 2.2 * Math.pow(x - 1, 3) + 1.2 * Math.pow(x - 1, 2),
  inCubic: (x) => x * x * x,
};
const clamp01 = (x) => Math.min(1, Math.max(0, x));

function buildRobot() {
  const shell = new THREE.MeshPhysicalMaterial({ color: 0xf5f3ff, roughness: 0.28, metalness: 0, clearcoat: 1, clearcoatRoughness: 0.12, sheen: 0.4, sheenColor: 0xd8ccff });
  const visorMat = new THREE.MeshPhysicalMaterial({ color: 0x0d0c18, roughness: 0.08, metalness: 0.3, clearcoat: 1, clearcoatRoughness: 0.05 });
  const eyeMat = new THREE.MeshBasicMaterial({ color: 0xcfe6ff, toneMapped: false });
  const glowMat = new THREE.MeshBasicMaterial({ color: 0xc9bfff, toneMapped: false });
  const roseMat = new THREE.MeshBasicMaterial({ color: 0xff9fcf, transparent: true, opacity: 0.9, toneMapped: false });
  const accent = new THREE.MeshPhysicalMaterial({ color: 0xb4a5ff, roughness: 0.25, clearcoat: 1, emissive: 0x6b5bd6, emissiveIntensity: 0.35 });

  const robot = new THREE.Group();
  const head = new THREE.Group();
  head.position.y = 1.5;
  robot.add(head);

  head.add(new THREE.Mesh(new RoundedBoxGeometry(1.62, 1.2, 1.25, 8, 0.42), shell));
  const visor = new THREE.Mesh(new RoundedBoxGeometry(1.34, 0.8, 0.12, 8, 0.32), visorMat);
  visor.position.set(0, -0.02, 0.6);
  head.add(visor);

  const eyes = [];
  for (const x of [-0.3, 0.3]) {
    const eye = new THREE.Mesh(new THREE.CapsuleGeometry(0.085, 0.13, 8, 20), eyeMat);
    eye.position.set(x, 0.06, 0.675);
    head.add(eye);
    eyes.push(eye);
    const cheek = new THREE.Mesh(new THREE.CircleGeometry(0.075, 24), roseMat);
    cheek.position.set(x * 1.55, -0.2, 0.668);
    head.add(cheek);
  }
  const smile = new THREE.Mesh(new THREE.TorusGeometry(0.12, 0.022, 10, 40, Math.PI), eyeMat);
  smile.rotation.z = Math.PI;
  smile.position.set(0, -0.14, 0.675);
  head.add(smile);

  for (const x of [-0.86, 0.86]) {
    const ear = new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.17, 0.12, 40), accent);
    ear.rotation.z = Math.PI / 2;
    ear.position.x = x;
    head.add(ear);
  }
  const stalk = new THREE.Mesh(new THREE.CylinderGeometry(0.022, 0.022, 0.36, 16), shell);
  stalk.position.y = 0.78;
  head.add(stalk);
  const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.085, 32, 32), glowMat);
  bulb.position.y = 0.99;
  head.add(bulb);
  const halo = new THREE.Mesh(new THREE.SphereGeometry(0.16, 32, 32), new THREE.MeshBasicMaterial({ color: 0xc9bfff, transparent: true, opacity: 0.18, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false }));
  halo.position.y = 0.99;
  head.add(halo);

  const neck = new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.22, 0.16, 32), visorMat);
  neck.position.y = 0.82;
  robot.add(neck);

  const body = new THREE.Mesh(new RoundedBoxGeometry(1.12, 1.0, 0.88, 8, 0.42), shell);
  body.position.y = 0.2;
  robot.add(body);
  const ring = new THREE.Mesh(new THREE.TorusGeometry(0.17, 0.028, 16, 64), glowMat);
  ring.position.set(0, 0.26, 0.45);
  robot.add(ring);
  const core = new THREE.Mesh(new THREE.SphereGeometry(0.07, 24, 24), roseMat.clone());
  core.material.opacity = 0.9;
  core.position.set(0, 0.26, 0.44);
  robot.add(core);

  const arms = [];
  for (const side of [-1, 1]) {
    const pivot = new THREE.Group();
    pivot.position.set(side * 0.7, 0.5, 0);
    const arm = new THREE.Mesh(new THREE.CapsuleGeometry(0.12, 0.46, 8, 20), shell);
    arm.position.y = -0.32;
    const hand = new THREE.Mesh(new THREE.SphereGeometry(0.15, 32, 32), accent);
    hand.position.y = -0.68;
    pivot.add(arm, hand);
    pivot.rotation.z = side * 0.18;
    robot.add(pivot);
    arms.push(pivot);
  }

  // Lumina de levitație de sub robot
  const glowTex = (() => {
    const c = document.createElement("canvas");
    c.width = c.height = 128;
    const g = c.getContext("2d");
    const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    grad.addColorStop(0, "rgba(201,191,255,0.9)");
    grad.addColorStop(0.35, "rgba(255,173,210,0.35)");
    grad.addColorStop(1, "rgba(0,0,0,0)");
    g.fillStyle = grad;
    g.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
  })();
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(2.6, 2.6), new THREE.MeshBasicMaterial({ map: glowTex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -0.85;

  return { robot, head, eyes, arms, bulb, halo, ring, core, floor };
}

function sparkles() {
  const n = 140;
  const pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const r = 2.5 + Math.random() * 3.5, a = Math.random() * Math.PI * 2, y = (Math.random() - 0.3) * 5;
    pos.set([Math.cos(a) * r, y, Math.sin(a) * r - 1.5], i * 3);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  return new THREE.Points(geo, new THREE.PointsMaterial({ color: 0xd9d0ff, size: 0.035, transparent: true, opacity: 0.8, depthWrite: false }));
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

export function play({ hello, name, line, skipLabel, durationMs = 7000 }) {
  return new Promise((resolve) => {
    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch (_) {
      resolve(false); // fără WebGL: intrăm direct în aplicație
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    renderer.outputColorSpace = THREE.SRGBColorSpace;

    const overlay = el("div", "intro");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-label", `${hello} ${name}`);
    overlay.style.setProperty("--intro-ms", `${durationMs}ms`);
    overlay.append(el("div", "aurora-i"), renderer.domElement);
    const speech = el("div", "speech");
    const title = el("h2");
    title.append(document.createTextNode(`${hello} `), el("span", "grad", name), document.createTextNode(" 👋"));
    const sub = el("p");
    speech.append(title, sub);
    title.style.opacity = "0";
    title.style.transform = "translateY(12px)";
    title.style.transition = "opacity .8s ease, transform .8s ease";
    const skip = el("button", "intro-skip", skipLabel);
    skip.type = "button";
    const bar = el("div", "intro-bar");
    bar.append(el("i"));
    overlay.append(speech, skip, bar);
    document.body.append(overlay);

    const scene = new THREE.Scene();
    const pmrem = new THREE.PMREMGenerator(renderer);
    scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(-3, 5, 6);
    const rimA = new THREE.PointLight(0xb4a5ff, 30, 12);
    rimA.position.set(-3.5, 2.5, -2.5);
    const rimB = new THREE.PointLight(0xffadd2, 24, 12);
    rimB.position.set(3.5, 1.5, -2);
    scene.add(key, rimA, rimB, new THREE.AmbientLight(0xffffff, 0.25));

    const R = buildRobot();
    const stage = new THREE.Group();
    stage.add(R.robot, R.floor);
    scene.add(stage);
    const dust = sparkles();
    scene.add(dust);

    const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
    function resize() {
      const w = window.innerWidth, h = window.innerHeight;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      // Pe telefon (portret) dăm camera înapoi, ca robotul să încapă deasupra textului
      // Robotul stă în treimea de sus, cu antena vizibilă; textul rămâne dedesubt
      const portrait = h / w > 1.2;
      camera.position.set(0, 0.4, portrait ? 15 : 10.5);
      camera.lookAt(0, portrait ? -0.35 : 0.02, 0);
      camera.updateProjectionMatrix();
    }
    resize();
    window.addEventListener("resize", resize);

    const pointer = { x: 0, y: 0 };
    const onMove = (e) => {
      pointer.x = (e.clientX / window.innerWidth) * 2 - 1;
      pointer.y = (e.clientY / window.innerHeight) * 2 - 1;
    };
    window.addEventListener("pointermove", onMove);

    // Textul apare literă cu literă
    let typed = 0, typeTimer = null;
    setTimeout(() => { title.style.opacity = "1"; title.style.transform = "none"; }, 650);
    setTimeout(() => {
      typeTimer = setInterval(() => {
        typed += 1;
        sub.textContent = line.slice(0, typed);
        if (typed >= line.length) clearInterval(typeTimer);
      }, 28);
    }, 1300);

    const t0 = performance.now();
    let leaving = 0, done = false, raf = 0;

    function frame(now) {
      const t = (now - t0) / 1000;
      // Intrare: robotul urcă din jos și se rotește spre tine
      const k = ease.outBack(clamp01(t / 1.4));
      const base = -3.2 + 3.2 * k;
      const leave = leaving ? ease.inCubic(clamp01((now - leaving) / 900)) : 0;
      R.robot.position.y = base + Math.sin(t * 1.6) * 0.08 + leave * 6;
      R.robot.rotation.y = (1 - k) * -0.7 + Math.sin(t * 0.6) * 0.08;
      R.robot.scale.setScalar(0.7 + 0.3 * k - leave * 0.3);
      R.floor.material.opacity = (0.55 + Math.sin(t * 1.6) * 0.15) * clamp01(t / 1.2) * (1 - leave);

      // Capul te urmărește cu privirea
      R.head.rotation.y += ((pointer.x * 0.35) - R.head.rotation.y) * 0.06;
      R.head.rotation.x += ((pointer.y * 0.18) - R.head.rotation.x) * 0.06;
      R.head.rotation.z = Math.sin(t * 1.2) * 0.04;

      // Mâna dreaptă face cu mâna, cea stângă stă relaxată
      const waving = clamp01((t - 0.9) / 0.4) * (1 - leave);
      R.arms[1].rotation.z = 0.18 + waving * (2.25 + Math.sin(t * 7.5) * 0.32);
      R.arms[0].rotation.z = -0.18 - Math.sin(t * 1.4) * 0.05;

      // Clipit, antenă și lumina din piept
      const blink = (t % 3.2) > 3.05 ? 0.12 : 1;
      R.eyes.forEach((e) => (e.scale.y += (blink - e.scale.y) * 0.5));
      const pulse = 0.5 + 0.5 * Math.sin(t * 3);
      R.halo.scale.setScalar(1 + pulse * 0.6);
      R.halo.material.opacity = 0.1 + pulse * 0.2;
      R.ring.rotation.z = t * 0.8;
      R.core.material.opacity = 0.6 + pulse * 0.4;

      dust.rotation.y = t * 0.05;
      renderer.render(scene, camera);
      if (!done) raf = requestAnimationFrame(frame);
    }
    raf = requestAnimationFrame(frame);

    function finish() {
      if (leaving) return;
      leaving = performance.now();
      overlay.classList.add("leaving");
      clearInterval(typeTimer);
      setTimeout(() => {
        done = true;
        cancelAnimationFrame(raf);
        window.removeEventListener("resize", resize);
        window.removeEventListener("pointermove", onMove);
        document.removeEventListener("keydown", onKey);
        scene.traverse((o) => {
          if (o.geometry) o.geometry.dispose();
          if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => { if (m.map) m.map.dispose(); m.dispose(); });
        });
        pmrem.dispose();
        renderer.dispose();
        overlay.remove();
        resolve(true);
      }, 950);
    }
    const onKey = (e) => { if (["Escape", "Enter", " "].includes(e.key)) { e.preventDefault(); finish(); } };
    document.addEventListener("keydown", onKey);
    skip.addEventListener("click", finish);
    setTimeout(finish, durationMs);
    skip.focus();
  });
}

window.CutiaIntro = { play };
