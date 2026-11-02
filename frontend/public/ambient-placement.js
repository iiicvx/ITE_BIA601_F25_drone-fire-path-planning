// زخرفة ثابتة مثبتة يسارًا. لا يغير تخطيطها إلا حجم نافذة العرض أو تكبيرها؛
// والتمرير لا يبحث عن مساحة ولا يغير الجانب ولا يحرك المسيّرة.
export function fixedAmbientFrame(viewport) {
  const { width: w, height: h } = viewport, narrow = w <= 700;
  const inset = Math.max(10, Math.min(36, w * .025)), header = Math.min(96, h * .25);
  const width = Math.max(1, Math.min(820, w - 2 * inset, w * (narrow ? .94 : .62), (h - header - 24) * 1.9));
  const height = width / 1.9, maxTop = Math.max(0, h - height - 16);
  const top = Math.min(maxTop, narrow ? Math.max(header, Math.min(120, h * .12)) : Math.max(header, h - height - Math.min(48, h * .05)));
  return { left: inset, top, right: inset + width, bottom: top + height, width, height, opacity: narrow ? .58 : .94 };
}

export class AmbientPlacement {
  constructor(canvas, changed) {
    this.canvas = canvas; this.layer = canvas.parentElement; this.changed = changed;
    this.stages = [...document.querySelectorAll('.hero-stage,.story-stage,#labStage')];
    this.initialized = false; this.covered = false; this.baseWidth = 1;
    this.resize = () => this.queue(); this.scroll = () => this.checkCoverage();
    addEventListener('resize', this.resize, { passive: true });
    addEventListener('scroll', this.scroll, { passive: true });
    window.visualViewport?.addEventListener('resize', this.resize, { passive: true });
    window.visualViewport?.addEventListener('scroll', this.resize, { passive: true });
    document.addEventListener('fullscreenchange', this.scroll);
    document.fonts.ready.then(this.resize); this.queue();
  }
  queue() {
    if (this.request != null || document.hidden) return;
    this.request = requestAnimationFrame(() => { this.request = null; this.sync(); });
  }
  sync() {
    const visual = window.visualViewport;
    this.viewport = { width: visual?.width || innerWidth, height: visual?.height || innerHeight, left: visual?.offsetLeft || 0, top: visual?.offsetTop || 0 };
    const frame = fixedAmbientFrame(this.viewport), resized = Math.abs(frame.width - this.baseWidth) > 1;
    this.frame = frame; this.baseWidth = frame.width; this.initialized = true; this.measuredAt = performance.now();
    this.layer.style.width = `${this.viewport.width}px`; this.layer.style.height = `${this.viewport.height}px`;
    this.layer.style.transform = `translate3d(${this.viewport.left}px,${this.viewport.top}px,0)`;
    this.canvas.style.width = `${frame.width}px`; this.canvas.style.height = `${frame.height}px`;
    this.canvas.style.transform = `translate3d(${frame.left}px,${frame.top}px,0)`;
    this.canvas.style.opacity = String(frame.opacity);
    this.canvas.dataset.layoutReady = 'true'; this.checkCoverage(false); this.changed?.(resized);
  }
  checkCoverage(notify = true) {
    if (!this.initialized || document.hidden) return;
    const f = this.frame, v = this.viewport, old = this.covered;
    this.covered = Boolean(document.fullscreenElement) || this.stages.some(stage => {
      const r = stage.getBoundingClientRect();
      return r.width > 0 && r.left <= f.left + v.left && r.right >= f.right + v.left && r.top <= f.top + v.top && r.bottom >= f.bottom + v.top;
    });
    if (notify && old !== this.covered) this.changed?.(false);
  }
  get needed() { return this.initialized && !this.covered; }
  info() { return { ...this.frame, fixed: true, anchor: 'left', covered: this.covered, viewport: this.viewport }; }
}
