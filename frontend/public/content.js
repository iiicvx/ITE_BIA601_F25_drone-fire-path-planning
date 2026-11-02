// نصوص الواجهة من content/ar.json، تُحمَّل مرة واحدة.
// المفتاح المفقود يظهر بالشكل ⟦key⟧ ليسهل اكتشافه.
// النص المنسق عبر data-i18n-html لا يقبل إلا الوسوم strong وspan وsub.
let catalog = null;
const missing = new Set();
let failed = false;

async function load() {
  if (catalog) return catalog;
  const r = await fetch('/content/ar.json?v=viewport-20261018');
  if (!r.ok) throw new Error(`content ${r.status}`);
  catalog = await r.json();
  for (const k of ['meta', 'navigation', 'hero', 'story', 'mission', 'results', 'statuses']) {
    if (!catalog[k]) throw new Error(`content missing section ${k}`);
  }
  return catalog;
}

/** بحث متداخل: t('story.hud.city') مع تعويض {name}. */
export function t(key, params) {
  if (!catalog) { missing.add(key); return `⟦${key}⟧`; }
  let v = catalog;
  for (const part of key.split('.')) {
    v = v?.[part];
    if (v === undefined) break;
  }
  if (typeof v !== 'string') {
    if (!missing.has(key)) { missing.add(key); console.warn(`[content] missing key: ${key}`); }
    return `⟦${key}⟧`;
  }
  if (params) for (const [k, val] of Object.entries(params)) v = v.replaceAll(`{${k}}`, String(val));
  return v;
}

export function missingKeys() { return [...missing]; }

/** وصول مباشر إلى الفهرس للمدخلات المركبة (مصفوفات وكائنات). يعيد Null عند الفقد. */
export function raw(key) {
  if (!catalog) return null;
  let v = catalog;
  for (const part of key.split('.')) {
    v = v?.[part];
    if (v === undefined) break;
  }
  if (v === undefined) {
    if (!missing.has(key)) { missing.add(key); console.warn(`[content] missing key: ${key}`); }
    return null;
  }
  return v;
}

/** تطبيق الفهرس على DOM الثابت: النصوص، وHTML الغني الموثوق، وخصائص aria والعناوين. */
export function applyBindings(scope = document) {
  scope.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
  scope.querySelectorAll('[data-i18n-html]').forEach((el) => { el.innerHTML = t(el.dataset.i18nHtml); });
  scope.querySelectorAll('[data-i18n-aria-label]').forEach((el) => { el.setAttribute('aria-label', t(el.dataset.i18nAriaLabel)); });
  scope.querySelectorAll('[data-i18n-title]').forEach((el) => { el.setAttribute('title', t(el.dataset.i18nTitle)); });
  scope.querySelectorAll('[data-i18n-placeholder]').forEach((el) => { el.setAttribute('placeholder', t(el.dataset.i18nPlaceholder)); });
  const title = scope.querySelector('title');
  if (title) title.textContent = t('meta.title');
  const desc = scope.querySelector('meta[name="description"]');
  if (desc) desc.setAttribute('content', t('meta.description'));
}

/** تحميل الفهرس ثم الربط؛ وعند الفشل يظهر شريط خطأ واضح. */
export const ready = load()
  .then(() => { applyBindings(); return catalog; })
  .catch((err) => {
    failed = true;
    console.error('[content]', err);
    const bar = document.createElement('div');
    bar.setAttribute('role', 'alert');
    bar.style.cssText = 'position:fixed;top:0;right:0;left:0;z-index:999;background:#B42318;color:#fff;padding:10px 16px;font-size:14px;text-align:center';
    bar.textContent = 'تعذر تحميل نصوص الواجهة. / Failed to load interface content.';
    document.body.prepend(bar);
    throw err;
  });

export function loadFailed() { return failed; }
