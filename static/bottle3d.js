// غرشة سمن ثلاثية الأبعاد: بلاستيك شفاف، سمن ذهبي، غطاء نصف شفاف، وملصق المتجر ملفوف حولها.
// تُحمَّل فقط لما يقترب القسم من الشاشة، وتوقف الرسم لما يختفي.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const canvas = document.getElementById('bottle3d');
const stage = canvas.parentElement;
const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.75));
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 50);
camera.position.set(0, 0.7, 3.3);

// إضاءة دافئة مثل ضوء السراج + إضاءة حافة من الخلف
scene.add(new THREE.HemisphereLight(0xfff1d6, 0x2a1508, 0.6));
const key = new THREE.DirectionalLight(0xffd9a0, 2.2); key.position.set(2.5, 3, 2.5); scene.add(key);
const rim = new THREE.DirectionalLight(0xffb45a, 2.6); rim.position.set(-2.5, 1.5, -2.5); scene.add(rim);
const fill = new THREE.PointLight(0xffa040, 1.4, 6); fill.position.set(0, 0.4, 1.6); scene.add(fill);

// شكل الغرشة من صورة المنتج: طويلة ونحيفة، جسم شبه مستقيم ثم انحدار طويل لرقبة قصيرة
const BODY_R = 0.214, TOP = 1.15;
const outline = [
  [0.0, 0.0], [0.17, 0.0], [0.2, 0.01], [0.212, 0.04], [0.216, 0.1], [0.214, 0.5],
  [0.206, 0.6], [0.188, 0.72], [0.162, 0.84], [0.136, 0.95], [0.113, 1.04], [0.101, 1.08],
  [0.101, 1.13], [0.109, 1.135], [0.109, TOP], [0.0, TOP],
];
const pts = outline.map(([r, y]) => new THREE.Vector2(r, y));
const bottleGeo = new THREE.LatheGeometry(pts, 96);
bottleGeo.computeVertexNormals();

const bottle = new THREE.Group();
scene.add(bottle);

// البلاستيك الشفاف: طبقة لامعة خفيفة فوق السمن بدل الانكسار الكامل، عشان يبان اللون الذهبي صافي
const plastic = new THREE.MeshPhysicalMaterial({
  color: 0xfff6e0, metalness: 0, roughness: 0.04, clearcoat: 1, clearcoatRoughness: 0.03,
  transparent: true, opacity: 0.16, depthWrite: false, envMapIntensity: 1.8, side: THREE.DoubleSide,
});
const shell = new THREE.Mesh(bottleGeo, plastic);
shell.renderOrder = 2;
bottle.add(shell);

// السمن داخل الغرشة (أصغر قليلاً، يمتلئ لين بداية الرقبة)
const FILL = 0.97;
const fillPts = outline.filter(([, y]) => y <= FILL).map(([r, y]) => new THREE.Vector2(Math.max(0, r - 0.008), Math.max(0.008, y)));
fillPts.push(new THREE.Vector2(0.128, FILL), new THREE.Vector2(0.0, FILL));
const ghee = new THREE.Mesh(new THREE.LatheGeometry(fillPts, 96), new THREE.MeshPhysicalMaterial({
  color: 0xf29400, roughness: 0.22, metalness: 0, emissive: 0xd35f00, emissiveIntensity: 0.5, envMapIntensity: 0.55,
  sheen: 0.6, sheenColor: 0xffd27a, clearcoat: 0.5, clearcoatRoughness: 0.2,
}));
ghee.renderOrder = 1;
bottle.add(ghee);

// الغطاء: أبيض نصف شفاف بحزوز عمودية
const capGeo = new THREE.CylinderGeometry(0.114, 0.117, 0.12, 72, 1, false);
const pos = capGeo.attributes.position;
for (let i = 0; i < pos.count; i++) {
  const x = pos.getX(i), z = pos.getZ(i), a = Math.atan2(z, x), r = Math.hypot(x, z);
  if (r > 0.08) { const k = 1 + 0.02 * Math.max(0, Math.cos(a * 30)); pos.setX(i, x * k); pos.setZ(i, z * k); }
}
capGeo.computeVertexNormals();
const cap = new THREE.Mesh(capGeo, new THREE.MeshPhysicalMaterial({
  color: 0xf4f1ea, roughness: 0.3, clearcoat: 0.7, transparent: true, opacity: 0.9,
}));
cap.position.y = TOP + 0.06;
bottle.add(cap);

// الملصق: نفس تصميم ملصق المتجر مرسوم على كانفس وملفوف حول الغرشة
function labelTexture() {
  const c = document.createElement('canvas'); c.width = 640; c.height = 900;
  const g = c.getContext('2d');
  g.fillStyle = '#5a2a12'; g.fillRect(0, 0, 640, 900);
  g.fillStyle = '#f7efdc'; roundRect(g, 14, 14, 612, 872, 40); g.fill();
  g.strokeStyle = '#8a4a1c'; g.lineWidth = 6; roundRect(g, 34, 34, 572, 832, 30); g.stroke();
  // علم عُمان
  const fx = 260, fy = 90;
  g.fillStyle = '#fff'; g.fillRect(fx, fy, 120, 78); g.fillStyle = '#007a3d'; g.fillRect(fx, fy + 52, 120, 26);
  g.fillStyle = '#c8102e'; g.fillRect(fx, fy, 36, 78); g.fillRect(fx + 36, fy + 26, 84, 26);
  g.direction = 'rtl'; g.textAlign = 'center'; g.fillStyle = '#4a1f0c';
  g.font = '700 150px "Aref Ruqaa", serif'; g.fillText('سمن', 320, 360);
  g.font = '700 150px "Aref Ruqaa", serif'; g.fillText('عُماني', 320, 520);
  g.fillStyle = '#a3202a'; roundRect(g, 120, 575, 400, 110, 55); g.fill();
  g.fillStyle = '#fff'; g.font = '700 70px "Readex Pro", Tahoma, sans-serif'; g.fillText('أصلي ١٠٠%', 320, 652);
  g.fillStyle = '#1f5a37'; g.font = '600 48px "Readex Pro", sans-serif'; g.fillText('من أرض عُمان', 320, 800);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 8;
  return tex;
}
function roundRect(g, x, y, w, h, r) {
  g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath();
}
const labelArc = 1.7;                                          // عرض الملصق حول الغرشة (بالراديان)، مقابل الكاميرا
const label = new THREE.Mesh(
  new THREE.CylinderGeometry(BODY_R + 0.003, BODY_R + 0.003, 0.3, 64, 1, true, -labelArc / 2, labelArc),
  new THREE.MeshStandardMaterial({ roughness: 0.55, metalness: 0, side: THREE.FrontSide }),
);
label.position.y = 0.29;
label.renderOrder = 3;
bottle.add(label);
Promise.all([document.fonts.load('700 40px "Aref Ruqaa"'), document.fonts.load('700 40px "Readex Pro"')]).finally(() => { label.material.map = labelTexture(); label.material.needsUpdate = true; });

// ظل ناعم تحت الغرشة
const shadowTex = (() => {
  const c = document.createElement('canvas'); c.width = c.height = 256; const g = c.getContext('2d');
  const r = g.createRadialGradient(128, 128, 0, 128, 128, 128);
  r.addColorStop(0, 'rgba(0,0,0,.55)'); r.addColorStop(1, 'rgba(0,0,0,0)'); g.fillStyle = r; g.fillRect(0, 0, 256, 256);
  return new THREE.CanvasTexture(c);
})();
const shadow = new THREE.Mesh(new THREE.PlaneGeometry(0.95, 0.95), new THREE.MeshBasicMaterial({ map: shadowTex, transparent: true, depthWrite: false }));
shadow.rotation.x = -Math.PI / 2; shadow.position.y = 0.001;
scene.add(shadow);

bottle.position.y = -0.05;

// التحكم: سحب للتدوير، دوران تلقائي هادئ
const controls = new OrbitControls(camera, canvas);
controls.target.set(0, 0.6, 0);
controls.enableZoom = false; controls.enablePan = false;
controls.minPolarAngle = Math.PI * 0.32; controls.maxPolarAngle = Math.PI * 0.58;
controls.enableDamping = true; controls.dampingFactor = 0.08;
controls.autoRotate = !reduce; controls.autoRotateSpeed = 1.6;
controls.addEventListener('start', () => { controls.autoRotate = false; stage.classList.add('touched'); });
controls.addEventListener('end', () => { clearTimeout(controls.t); controls.t = setTimeout(() => { controls.autoRotate = !reduce; }, 2500); });

// تبديل الحجم: الكبيرة والصغيرة
let targetScale = 1;
document.querySelectorAll('[data-b3-size]').forEach((b) => b.addEventListener('click', () => {
  targetScale = +b.dataset.b3Size;
  document.querySelectorAll('[data-b3-size]').forEach((x) => x.setAttribute('aria-pressed', x === b));
}));

function resize() {
  const w = stage.clientWidth, h = stage.clientHeight;
  renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(stage);
resize();

let visible = true;
new IntersectionObserver((e) => { visible = e[0].isIntersecting; }).observe(stage);
const clock = new THREE.Clock();
renderer.setAnimationLoop(() => {
  if (!visible) return;
  const t = clock.getElapsedTime();
  const s = bottle.scale.x + (targetScale - bottle.scale.x) * 0.08;
  bottle.scale.setScalar(s); shadow.scale.setScalar(s);
  if (!reduce) bottle.position.y = -0.05 + Math.sin(t * 1.2) * 0.012;
  fill.intensity = 1.3 + Math.sin(t * 2.3) * 0.12 + Math.sin(t * 5.1) * 0.06;   // وميض خفيف مثل السراج
  controls.update();
  renderer.render(scene, camera);
});
stage.classList.add('ready');
