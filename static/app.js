// أبو ميثه: السلة الجانبية، الحركة عند التمرير، وجزيئات الذهب في الواجهة
(function () {
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return [].slice.call((r || document).querySelectorAll(s)); };

  /* الهيدر يصير ثابتاً بعد أول تمرير في الرئيسية */
  var header = $('header.site');
  function onScroll() {
    if (header) header.classList.toggle('solid', window.scrollY > 40);
    var bar = $('.mbar'), trigger = $('[data-mbar-after]');
    if (bar && trigger) bar.classList.toggle('show', trigger.getBoundingClientRect().bottom < 0);
    var bg = $('.story .bg');
    if (bg && !reduce) {
      var r = bg.parentNode.getBoundingClientRect();
      bg.style.transform = 'translateY(' + ((r.top + r.height / 2 - innerHeight / 2) * -0.12) + 'px)';
    }
  }
  addEventListener('scroll', onScroll, { passive: true }); onScroll();

  /* ظهور الأقسام */
  if ('IntersectionObserver' in window && !reduce) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } });
    }, { threshold: 0.15, rootMargin: '0px 0px -40px 0px' });
    $$('.reveal, .steps').forEach(function (el) { io.observe(el); });
  } else {
    $$('.reveal, .steps').forEach(function (el) { el.classList.add('in'); });
  }

  /* أزرار الكمية */
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-step]');
    if (!b) return;
    var input = b.parentNode.querySelector('input');
    input.value = Math.max(1, Math.min(50, (+input.value || 1) + (+b.dataset.step)));
  });

  /* اسم ملف الإيصال المختار */
  document.addEventListener('change', function (e) {
    var input = e.target.closest('.drop input[type=file]');
    if (!input || !input.files.length) return;
    var drop = input.closest('.drop');
    drop.classList.add('has-file');
    drop.querySelector('[data-file-label]').textContent = '✓ ' + input.files[0].name;
  });

  /* اختيار الحجم الأول المتوفر افتراضياً */
  $$('.sizes').forEach(function (g) {
    if (!g.querySelector('input:checked')) { var o = g.querySelector('input:not(:disabled)'); if (o) o.checked = true; }
  });

  /* معرض صور المنتج */
  $$('.pgallery .thumbs button').forEach(function (b) {
    b.addEventListener('click', function () {
      var main = $('.pgallery .main img');
      main.style.opacity = 0;
      setTimeout(function () { main.src = b.dataset.src; main.alt = b.dataset.alt || ''; main.style.opacity = 1; }, 180);
      $$('.pgallery .thumbs button').forEach(function (x) { x.classList.toggle('on', x === b); });
    });
  });

  /* السلة الجانبية */
  var drawer = $('#drawer'), scrim = $('#scrim'), toast = $('#toast');
  function setCount(n) {
    $$('[data-cart-count]').forEach(function (el) {
      el.textContent = n; el.hidden = !n;
      el.classList.remove('bump'); void el.offsetWidth; el.classList.add('bump');
    });
  }
  function openDrawer() {
    if (!drawer) return;
    drawer.classList.add('open'); scrim.classList.add('open'); document.body.classList.add('lock');
    drawer.setAttribute('aria-hidden', 'false'); setTimeout(function () { var c = $('.close', drawer); if (c) c.focus(); }, 300);
  }
  function closeDrawer() {
    if (!drawer) return;
    drawer.classList.remove('open'); scrim.classList.remove('open'); document.body.classList.remove('lock');
    drawer.setAttribute('aria-hidden', 'true');
  }
  function showToast(msg) {
    if (!toast || !msg) return;
    $('span', toast).textContent = msg; toast.classList.add('show');
    clearTimeout(showToast.t); showToast.t = setTimeout(function () { toast.classList.remove('show'); }, 2200);
  }
  function render(data) {
    if (data.html !== undefined) $('.drawer-body', drawer).innerHTML = data.html;
    if (data.count !== undefined) setCount(data.count);
  }
  function send(form, submitter) {
    var fd = new FormData(form);
    if (submitter && submitter.name) fd.append(submitter.name, submitter.value);
    return fetch(form.action, { method: 'POST', body: fd, headers: { 'X-Requested-With': 'fetch' }, credentials: 'same-origin' })
      .then(function (r) { return r.json().then(function (d) { if (!r.ok) throw d; return d; }); });
  }
  document.addEventListener('submit', function (e) {
    var form = e.target, sub = e.submitter;
    if (!drawer || !form.matches('[data-ajax]')) return;
    if (sub && sub.value === 'checkout') return;              // «اطلب الحين» يكمل للطلب مباشرة
    e.preventDefault();
    if (sub) sub.disabled = true;
    send(form, sub).then(function (d) {
      render(d);
      if (form.dataset.ajax === 'add') { openDrawer(); showToast(d.message); }
    }).catch(function (err) { showToast((err && err.error) || 'تعذّر الإرسال، حاول مرة ثانية'); })
      .then(function () { if (sub) sub.disabled = false; });
  });
  $$('[data-open-cart]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      if (!drawer) return;
      e.preventDefault(); openDrawer();
      fetch(a.dataset.openCart, { headers: { 'X-Requested-With': 'fetch' }, credentials: 'same-origin' })
        .then(function (r) { return r.json(); }).then(render).catch(function () {});
    });
  });
  if (scrim) scrim.addEventListener('click', closeDrawer);
  document.addEventListener('click', function (e) { if (e.target.closest('[data-close-cart]')) closeDrawer(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeDrawer(); });

  /* جزيئات ذهبية تصعد في الواجهة مثل لمعة السمن */
  var cv = $('canvas.sparks');
  if (cv && cv.getContext) {
    var ctx = cv.getContext('2d'), W, H, parts = [], running = true;
    var size = function () {
      var dpr = Math.min(devicePixelRatio || 1, 2), r = cv.getBoundingClientRect();
      W = r.width; H = r.height; cv.width = W * dpr; cv.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      parts = [];
      for (var i = 0, n = Math.round(W * H / 14000); i < n; i++) parts.push(spawn(true));
    };
    var spawn = function (anywhere) {
      return { x: Math.random() * W, y: anywhere ? Math.random() * H : H + 10, r: Math.random() * 2.2 + .4,
               v: Math.random() * .35 + .12, s: Math.random() * 6.28, a: Math.random() * .6 + .25 };
    };
    var draw = function (t) {
      ctx.clearRect(0, 0, W, H);
      for (var i = 0; i < parts.length; i++) {
        var p = parts[i];
        if (!reduce) { p.y -= p.v; p.x += Math.sin(t / 1800 + p.s) * .25; }
        if (p.y < -10) parts[i] = p = spawn(false);
        var fade = Math.min(1, p.y / (H * .35));
        var g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r * 4);
        g.addColorStop(0, 'rgba(255,214,130,' + (p.a * fade) + ')'); g.addColorStop(1, 'rgba(255,214,130,0)');
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(p.x, p.y, p.r * 4, 0, 6.28); ctx.fill();
      }
      if (running && !reduce) requestAnimationFrame(draw);
    };
    size(); requestAnimationFrame(draw);
    addEventListener('resize', function () { clearTimeout(size.t); size.t = setTimeout(size, 200); });
    if ('IntersectionObserver' in window) new IntersectionObserver(function (es) {
      var vis = es[0].isIntersecting; if (vis && !running) { running = true; requestAnimationFrame(draw); } running = vis;
    }).observe(cv);
  }
})();

// الطابع التراثي: نجوم وشهب، دخان لبان من المبخرة، عمق مع حركة الماوس، وعدّادات
(function () {
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var hero = document.querySelector('.hero.heritage');
  if (!hero) return;

  function fit(cv) {
    var dpr = Math.min(window.devicePixelRatio || 1, 2), r = cv.getBoundingClientRect(), ctx = cv.getContext('2d');
    cv.width = r.width * dpr; cv.height = r.height * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx: ctx, w: r.width, h: r.height };
  }
  var visible = true;
  if ('IntersectionObserver' in window) new IntersectionObserver(function (e) { visible = e[0].isIntersecting; }).observe(hero);

  /* السماء: نجوم تومض وشهاب بين فترة وفترة */
  var sky = hero.querySelector('canvas.sky'), S, stars = [], meteor = null;
  function initSky() {
    S = fit(sky); stars = [];
    for (var i = 0, n = Math.round(S.w * S.h / 2600); i < n; i++)
      stars.push({ x: Math.random() * S.w, y: Math.random() * S.h * .7, r: Math.random() * 1.3 + .2, t: Math.random() * 6.3, s: Math.random() * .8 + .4 });
  }
  function drawSky(t) {
    var c = S.ctx; c.clearRect(0, 0, S.w, S.h);
    for (var i = 0; i < stars.length; i++) {
      var p = stars[i], a = .35 + .65 * Math.abs(Math.sin(p.t + t / 1000 * p.s));
      c.globalAlpha = a * (1 - p.y / (S.h * .75)); c.fillStyle = '#fff4dc';
      c.beginPath(); c.arc(p.x, p.y, p.r, 0, 6.28); c.fill();
    }
    c.globalAlpha = 1;
    if (!meteor && Math.random() < .004) meteor = { x: Math.random() * S.w * .8 + S.w * .2, y: Math.random() * S.h * .25, life: 0 };
    if (meteor) {
      meteor.life += 1; var L = meteor.life, x = meteor.x - L * 9, y = meteor.y + L * 4;
      var g = c.createLinearGradient(x, y, x + 90, y - 40); g.addColorStop(0, 'rgba(255,240,200,.9)'); g.addColorStop(1, 'rgba(255,240,200,0)');
      c.strokeStyle = g; c.lineWidth = 1.6; c.beginPath(); c.moveTo(x, y); c.lineTo(x + 90, y - 40); c.stroke();
      if (L > 40) meteor = null;
    }
  }

  /* دخان اللبان: خيوط ناعمة تتلوّى وهي تصعد من فوهة المبخرة */
  var smokeCv = hero.querySelector('canvas.smoke'), burner = hero.querySelector('.burner'), M, puffs = [];
  function initSmoke() { M = fit(smokeCv); }
  function emitter() {
    var a = smokeCv.getBoundingClientRect(), b = burner.getBoundingClientRect();
    return { x: b.left - a.left + b.width / 2, y: b.top - a.top + b.height * .48 };
  }
  function drawSmoke(t) {
    var c = M.ctx, e = emitter(); c.clearRect(0, 0, M.w, M.h);
    if (puffs.length < 70 && Math.random() < .5) puffs.push({ x: e.x + (Math.random() - .5) * 6, y: e.y, r: 4 + Math.random() * 4, life: 0, max: 160 + Math.random() * 90, seed: Math.random() * 6.3 });
    for (var i = puffs.length - 1; i >= 0; i--) {
      var p = puffs[i]; p.life++;
      var k = p.life / p.max;
      p.y -= .7 + k * .5;
      p.x += Math.sin(p.seed + p.life / 26) * (.25 + k * 1.1) + .12;
      p.r += .3;
      var a = Math.sin(Math.PI * Math.min(1, k * 1.2)) * .3;
      var g = c.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r);
      g.addColorStop(0, 'rgba(240,232,220,' + a + ')'); g.addColorStop(1, 'rgba(240,232,220,0)');
      c.fillStyle = g; c.beginPath(); c.arc(p.x, p.y, p.r, 0, 6.28); c.fill();
      if (p.life > p.max) puffs.splice(i, 1);
    }
  }

  var last = 0;
  function loop(t) {
    requestAnimationFrame(loop);
    if (!visible || t - last < 33) return;                     // ٣٠ إطاراً تكفي وتريّح الجوال
    last = t; drawSky(t); drawSmoke(t);
  }
  initSky(); initSmoke();
  if (reduce) { drawSky(0); } else { requestAnimationFrame(loop); }
  addEventListener('resize', function () { clearTimeout(initSky.t); initSky.t = setTimeout(function () { initSky(); initSmoke(); }, 200); });

  /* عمق: الطبقات تتحرك بسرعات مختلفة مع الماوس والتمرير */
  var layers = [].slice.call(hero.querySelectorAll('[data-depth]')), mx = 0, my = 0;
  function applyDepth() {
    var sy = Math.min(window.scrollY, 800);
    layers.forEach(function (el) {
      var d = +el.dataset.depth;
      el.style.transform = 'translate3d(' + (mx * d * 30).toFixed(1) + 'px,' + (my * d * 20 + sy * d * .25).toFixed(1) + 'px,0)';
    });
  }
  if (!reduce) {
    hero.addEventListener('mousemove', function (e) {
      var r = hero.getBoundingClientRect(); mx = (e.clientX - r.left) / r.width - .5; my = (e.clientY - r.top) / r.height - .5;
      requestAnimationFrame(applyDepth);
    });
    addEventListener('scroll', function () { requestAnimationFrame(applyDepth); }, { passive: true });
  }
})();

/* أرقام تعدّ لما تظهر */
(function () {
  var els = [].slice.call(document.querySelectorAll('[data-count]'));
  if (!els.length || !('IntersectionObserver' in window) || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  var fmt = function (n) { return n.toLocaleString('ar-EG'); };
  els.forEach(function (el) { el.textContent = fmt(0); });
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (!e.isIntersecting) return; io.unobserve(e.target);
      var to = +e.target.dataset.count, t0 = performance.now();
      (function tick(t) {
        var k = Math.min(1, (t - t0) / 1400); k = 1 - Math.pow(1 - k, 3);
        e.target.textContent = fmt(Math.round(to * k)); if (k < 1) requestAnimationFrame(tick);
      })(t0);
    });
  }, { threshold: .6 });
  els.forEach(function (el) { io.observe(el); });
})();
