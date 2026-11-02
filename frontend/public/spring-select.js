// EasyUI SpringSelect، مكيف لـ DOM المجرد في المشروع وللواجهة من اليمين إلى اليسار.
// المصدر: https://easyui.site/source/spring-select.json (MIT, Suraj Maurya).
// يحتفظ ببنية الزر والقائمة، والتنقل بين الخيارات النشطة، وعلامة الاختيار،
// وإعادة التركيز، ودخول النابض القصير. وتبقى عناصر select الأصلية حاملة لحالة النموذج.
import { t } from './content.js?v=viewport-20261018';

const controls = new WeakMap();
let sequence = 0, opened = null;
const chevron = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="m5 7 5 5 5-5"/></svg>';

function enhance(select) {
  if (controls.has(select)) return;
  const id = select.id || `spring-select-${++sequence}`;
  if (!select.id) select.id = id;
  const root = document.createElement('span'); root.className = 'spring-select';
  const trigger = document.createElement('button');
  trigger.type = 'button'; trigger.id = `${id}-trigger`; trigger.className = 'spring-trigger';
  // عنصر Combobox يملك ضمنيًا aria-haspopup=listbox. والإبقاء عليها ضمنية
  // يتجنب تكرار دلالات القائمة المنبثقة مع الحفاظ على رابط controls المطلوب.
  trigger.setAttribute('role', 'combobox');
  trigger.setAttribute('aria-expanded', 'false');
  const selected = document.createElement('span'); selected.className = 'spring-value';
  selected.id = `${id}-value`; trigger.append(selected); trigger.insertAdjacentHTML('beforeend', chevron);
  const label = select.closest('label');
  const caption = label?.querySelector(':scope > span');
  if (caption) {
    caption.id ||= `${id}-label`;
    trigger.setAttribute('aria-labelledby', `${caption.id} ${selected.id}`);
  } else trigger.setAttribute('aria-label', select.getAttribute('aria-label') || t('camera.drone'));
  if (label) label.htmlFor = trigger.id;
  select.after(root); root.append(trigger);
  select.hidden = true; select.tabIndex = -1; select.setAttribute('aria-hidden', 'true');
  const menu = document.createElement('div');
  menu.id = `${id}-list`; menu.className = 'spring-menu'; menu.setAttribute('role', 'listbox');
  menu.setAttribute('aria-label', caption?.textContent || select.getAttribute('aria-label') || t('camera.drone'));
  menu.setAttribute('dir', 'rtl'); menu.hidden = true;
  document.body.append(menu);
  if ('popover' in menu) menu.popover = 'manual';
  let options = [], active = -1, isOpen = false, search = '', lastSearch = 0;
  const list=document.createElement('div');list.className='spring-list-scroll';list.setAttribute('role','presentation');menu.append(list);
  const enabled = () => options.map((o, i) => !o.disabled ? i : -1).filter(i => i >= 0);
  function sync() {
    options = [...select.options];
    selected.textContent = select.selectedOptions[0]?.textContent || '—';
    trigger.disabled = select.disabled || !select.options.length;
    trigger.title = `${caption?.textContent || select.getAttribute('aria-label') || ''}: ${selected.textContent}`;
    if (isOpen && trigger.disabled) close();
    else if (isOpen) render();
  }
  function highlight(index, scroll = true) {
    active = index;
    menu.querySelectorAll('[role="option"]').forEach((node, i) => {
      node.classList.toggle('active', i === active);
      if (i === active) {
        trigger.setAttribute('aria-activedescendant', node.id);
        if (scroll) node.scrollIntoView({ block: 'nearest', behavior: 'instant' });
      }
    });
  }
  function render() {
    list.replaceChildren(); options = [...select.options];
    let group = null;
    for (const [index, option] of options.entries()) {
      if (option.parentElement.tagName === 'OPTGROUP' && group !== option.parentElement) {
        group = option.parentElement;
        const heading = document.createElement('div'); heading.className = 'spring-group'; heading.id=`${id}-group-${index}`;
        heading.textContent = group.label; heading.setAttribute('role', 'presentation'); list.append(heading);
      }
      const item = document.createElement('div'); item.id = `${id}-option-${index}`;
      item.className = 'spring-option'; item.setAttribute('role', 'option');
      item.setAttribute('aria-selected', String(option.selected));
      item.setAttribute('aria-disabled', String(option.disabled));
      const text = document.createElement('span'); text.id=`${id}-option-${index}-label`; text.textContent = option.textContent;
      item.append(text);
      if (option.selected) item.insertAdjacentHTML('beforeend', '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="m4 10 4 4 8-8"/></svg>');
      item.onpointermove = () => { if (!option.disabled) highlight(index, false); };
      item.onpointerdown = event => event.preventDefault();
      item.onclick = () => choose(index); list.append(item);
    }
    highlight(active >= 0 && options[active] && !options[active].disabled ? active : Math.max(0, select.selectedIndex), false);
  }
  function position() {
    if (!isOpen) return;
    const box = trigger.getBoundingClientRect();
    const width = Math.min(innerWidth - 24, Math.max(box.width, 240));
    const below = innerHeight - box.bottom - 16, above = box.top - 16;
    const upwards = below < 220 && above > below;
    const height = Math.min(320, Math.max(100, upwards ? above : below));
    menu.style.width = `${width}px`; menu.style.maxHeight = `${height}px`;
    menu.style.setProperty('--popup-content-max',`${height-18}px`);
    menu.style.left = `${Math.max(12, Math.min(innerWidth - width - 12, box.right - width))}px`;
    menu.style.top = `${upwards ? Math.max(12, box.top - menu.offsetHeight - 8) : box.bottom + 8}px`;
    menu.style.transformOrigin = upwards ? 'bottom center' : 'top center';
  }
  function open(index = select.selectedIndex) {
    if (trigger.disabled) return;
    if (opened && opened !== api) opened.close();
    active = index; isOpen = true; opened = api;
    (document.fullscreenElement || document.body).append(menu);
    menu.hidden = false; render();
    if (menu.showPopover) menu.showPopover();
    position(); trigger.setAttribute('aria-controls',menu.id); trigger.setAttribute('aria-expanded', 'true');
    if (!matchMedia('(prefers-reduced-motion: reduce)').matches) menu.animate([
      { opacity: 0, transform: 'translateY(-6px) scale(.98)' },
      { opacity: 1, transform: 'translateY(1px) scale(1.004)', offset: .75 },
      { opacity: 1, transform: 'translateY(0) scale(1)' },
    ], { duration: 220, easing: 'cubic-bezier(.22,1,.36,1)' });
    highlight(active);
  }
  function close(focus = false) {
    if (!isOpen) return;
    isOpen = false; if (opened === api) opened = null;
    if (menu.hidePopover && menu.matches(':popover-open')) menu.hidePopover();
    menu.hidden = true; trigger.setAttribute('aria-expanded', 'false');
    trigger.removeAttribute('aria-controls');
    trigger.removeAttribute('aria-activedescendant');
    if (focus) trigger.focus({ preventScroll: true });
  }
  function choose(index) {
    const option = options[index]; if (!option || option.disabled) return;
    select.value = option.value; sync(); close(true);
    select.dispatchEvent(new Event('input', { bubbles: true }));
    select.dispatchEvent(new Event('change', { bubbles: true }));
  }
  trigger.onclick = () => isOpen ? close() : open();
  trigger.onkeydown = event => {
    const keys = enabled();
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      if (!isOpen) { open(event.key === 'ArrowUp' ? keys.at(-1) : select.selectedIndex); return; }
      let index = keys.indexOf(active);
      if (event.key === 'Home') index = 0;
      else if (event.key === 'End') index = keys.length - 1;
      else index = (index + (event.key === 'ArrowDown' ? 1 : -1) + keys.length) % keys.length;
      highlight(keys[index]);
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault(); isOpen ? choose(active) : open();
    } else if (event.key === 'Escape' && isOpen) { event.preventDefault(); close(true); }
    else if (event.key === 'Tab') close();
    else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      const now = performance.now(); search = now - lastSearch < 700 ? search + event.key : event.key; lastSearch = now;
      if (!isOpen) open();
      const match = keys.find(i => options[i].textContent.trim().toLocaleLowerCase().startsWith(search.toLocaleLowerCase()));
      if (match !== undefined) highlight(match);
    }
  };
  document.addEventListener('pointerdown', event => { if (isOpen && !root.contains(event.target) && !menu.contains(event.target)) close(); });
  // إبقاء القائمة المنبثقة مثبتة بينما يحرك التركيز أو تمرير الصفحة زرها.
  // تمريرها الداخلي يجب ألا يغلقها قبل اختيار خيار في الأسفل.
  document.addEventListener('scroll', event => {
    if(!isOpen||menu.contains(event.target))return;
    const box=trigger.getBoundingClientRect();
    if(box.bottom<0||box.top>innerHeight)close();else position();
  }, true);
  addEventListener('resize', () => close());
  select.addEventListener('change', sync);
  new MutationObserver(sync).observe(select, { subtree: true, childList: true, attributes: true, attributeFilter: ['disabled', 'selected', 'label'] });
  const api = { sync, close, trigger }; controls.set(select, api); sync();
}

export function enhanceSelects(scope = document) {
  if (scope.matches?.('select')) enhance(scope);
  scope.querySelectorAll?.('select').forEach(enhance);
}

export function syncSelect(select) { controls.get(select)?.sync(); }

export function installSpringSelects() {
  enhanceSelects();
  new MutationObserver(entries => {
    for (const entry of entries) for (const node of entry.addedNodes) if (node.nodeType === 1) enhanceSelects(node);
  }).observe(document.body, { childList: true, subtree: true });
}
