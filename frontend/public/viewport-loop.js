// مالك واحد قابل للإلغاء لـ requestAnimationFrame. العمل خارج الشاشة أو المخفي يُلغى جدولته،
// لا يُتجاوز فقط داخل استدعاء حركة يعمل باستمرار.
export class ViewportLoop {
  constructor(element, { frame, ready = () => true, continuous = () => true, onResume, onSuspend, maxFPS = 0 }) {
    this.element = element; this.frame = frame; this.ready = ready; this.continuous = continuous;
    this.onResume = onResume; this.onSuspend = onSuspend; this.maxFPS = maxFPS;
    this.visible = false; this.enabled = true; this.running = false; this.request = null; this.last = null;
    this.callbacks = 0; this.frames = 0; this.resumes = 0; this.disposed = false;
    this.tick = now => {
      this.request = null;
      if (!this.active) { this.sync(); return; }
      this.callbacks++;
      if (this.maxFPS && this.last !== null && now - this.last < 1000 / this.maxFPS - 1) { this.schedule(); return; }
      const dt = this.last === null ? 0 : Math.min(.1, Math.max(0, (now - this.last) / 1000));
      this.last = now; this.frames++; this.frame(dt, now);
      if (!this.active) { this.sync(); return; }
      if (this.continuous()) this.schedule(); else this.last = null;
    };
    this.observer = new IntersectionObserver(entries => {
      const entry = entries[entries.length - 1];
      if (entry.isIntersecting && entry.intersectionRect.width > 0 && entry.intersectionRect.height > 0) this.recheck();
      else this.setVisible(false);
    }, { threshold: [0, .001, .02] });
    this.observer.observe(element);
    // ثلاث قراءات محدودة لأبعاد العناصر عند تمرير الصفحة تمنع مدخل مراقب قديمًا
    // من السماح بإطار GPU مكلف آخر أثناء التمرير السريع. لا تعمل في هذا الحارس
    // هندسة مشهد ولا فيزياء ولا مسح DOM ولا حجز خامات.
    this.recheck = () => {
      const r = element.getBoundingClientRect(), v = window.visualViewport;
      const left = v?.offsetLeft || 0, top = v?.offsetTop || 0;
      this.setVisible(r.width > 0 && r.height > 0 && r.right > left && r.left < left + (v?.width || innerWidth) &&
        r.bottom > top && r.top < top + (v?.height || innerHeight));
    };
    addEventListener('scroll', this.recheck, { passive: true }); addEventListener('resize', this.recheck, { passive: true });
    window.visualViewport?.addEventListener('scroll', this.recheck, { passive: true });
    window.visualViewport?.addEventListener('resize', this.recheck, { passive: true });
    this.visibility = () => { if (!document.hidden) this.recheck(); this.sync(); };
    this.pageHide = () => { this.pageHidden = true; this.sync(); };
    this.pageShow = () => { this.pageHidden = false; this.recheck(); this.sync(); };
    document.addEventListener('visibilitychange', this.visibility);
    document.addEventListener('fullscreenchange', this.visibility);
    addEventListener('pagehide', this.pageHide); addEventListener('pageshow', this.pageShow);
  }

  get active() {
    const fullscreen = document.fullscreenElement;
    return !this.disposed && this.enabled && this.visible && !document.hidden && !this.pageHidden &&
      (!fullscreen || fullscreen.contains(this.element)) && this.ready();
  }
  setVisible(value) { this.visible = Boolean(value); this.sync(); }
  setEnabled(value) { this.enabled = Boolean(value); this.sync(); }
  schedule() { if (this.active && this.request === null) this.request = requestAnimationFrame(this.tick); }
  invalidate() { this.sync(); }
  sync() {
    if (!this.active) {
      if (this.request !== null) cancelAnimationFrame(this.request);
      this.request = null; this.last = null;
      if (this.running) { this.running = false; this.onSuspend?.(); }
      return;
    }
    if (!this.running) { this.running = true; this.last = null; this.resumes++; this.onResume?.(); }
    this.schedule();
  }
  info() { return { active: Boolean(this.active), scheduled: this.request !== null, callbacks: this.callbacks, frames: this.frames, resumes: this.resumes, maxFPS: this.maxFPS }; }
  dispose() {
    this.disposed = true; this.sync(); this.observer.disconnect();
    document.removeEventListener('visibilitychange', this.visibility); document.removeEventListener('fullscreenchange', this.visibility);
    removeEventListener('pagehide', this.pageHide); removeEventListener('pageshow', this.pageShow);
    removeEventListener('scroll', this.recheck); removeEventListener('resize', this.recheck);
    window.visualViewport?.removeEventListener('scroll', this.recheck); window.visualViewport?.removeEventListener('resize', this.recheck);
  }
}

// لا يُبنى مشهد خارج الشاشة إلا عندما يقترب من أن يصبح مفيدًا. ينقطع المراقب
// بعد أول اقتراب، والعودة إليه تُبقي العالم نفسه.
export function deferUntilNear(element, start, margin = 400) {
  let started = false, near = false, timer = null;
  const schedule = () => {
    clearTimeout(timer);
    if (started || !near || document.hidden) return;
    timer = setTimeout(() => {
      const r = element.getBoundingClientRect();
      if (started || document.hidden || r.bottom < -margin || r.top > innerHeight + margin) return;
      started = true; cleanup(); start();
    }, element.id === 'heroCanvas' && (!location.hash || location.hash === '#intro') ? 0 : 120);
  };
  const observer = new IntersectionObserver(entries => {
    near = entries[entries.length - 1].isIntersecting; schedule();
  }, { rootMargin: `${margin}px`, threshold: 0 });
  const visibility = () => {
    if (!document.hidden) { const r = element.getBoundingClientRect(); near = r.bottom >= -margin && r.top <= innerHeight + margin; }
    schedule();
  };
  const cleanup = () => { clearTimeout(timer); observer.disconnect(); document.removeEventListener('visibilitychange', visibility); };
  document.addEventListener('visibilitychange', visibility);
  observer.observe(element);
  return cleanup;
}
