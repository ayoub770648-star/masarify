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
