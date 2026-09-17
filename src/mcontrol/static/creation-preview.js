// Keep native help popovers beside their buttons, including near viewport edges.
(() => {
  const buttons = document.querySelectorAll('.new-server [popovertarget]');
  function position(button, popup) {
    const edge = 12, gap = 8;
    popup.style.maxHeight = `${Math.max(80, innerHeight - edge * 2)}px`;
    const anchor = button.getBoundingClientRect();
    const rect = popup.getBoundingClientRect();
    const left = Math.max(edge, Math.min(anchor.right - rect.width, innerWidth - rect.width - edge));
    const below = anchor.bottom + gap;
    const top = below + rect.height <= innerHeight - edge
      ? below : Math.max(edge, anchor.top - gap - rect.height);
    popup.style.left = `${left}px`;
    popup.style.top = `${top}px`;
  }
  for (const button of buttons) {
    const popup = document.getElementById(button.getAttribute('popovertarget'));
    if (!popup) continue;
    popup.addEventListener('toggle', event => {
      if (event.newState === 'open') position(button, popup);
    });
  }
  function reposition() {
    for (const button of buttons) {
      const popup = document.getElementById(button.getAttribute('popovertarget'));
      if (popup?.matches(':popover-open')) position(button, popup);
    }
  }
  window.addEventListener('resize', reposition);
  document.addEventListener('scroll', reposition, true);
})();

(() => {
  const form = document.querySelector('.new-server__form');
  const panel = document.querySelector('.setup-preview');
  if (!form || !panel) return;
  const status = panel.querySelector('[data-preview-status]');
  const files = panel.querySelector('[data-preview-files]');
  const code = panel.querySelector('[data-preview-code]');
  const upload = panel.querySelector('[data-preview-upload]');
  let selected = 'docker-compose.yml', available = [], timer, pending, revision = 0;
  function showFile(file) {
    selected = file.path;
    files.value = file.path;
    code.textContent = file.content.trimEnd();
  }
  files.addEventListener('change', () => {
    const file = available.find(item => item.path === files.value);
    if (file) showFile(file);
  });
  async function refresh(version) {
    const controller = new AbortController();
    pending = controller;
    status.hidden = false;
    status.textContent = 'Updating preview...';
    panel.setAttribute('aria-busy', 'true');
    try {
      const data = new FormData(form);
      data.delete('accept_eula');
      const response = await fetch('/servers/new/preview', {
        method: 'POST', body: data, signal: controller.signal,
      });
      if (version !== revision) return;
      if (!response.ok) throw new Error('Preview unavailable');
      const result = await response.json();
      if (version !== revision) return;
      files.replaceChildren();
      available = []; files.disabled = true; code.textContent = ''; upload.textContent = '';
      const errors = Object.values(result.errors || {});
      if (errors.length) {
        status.textContent = errors.join(' ');
        return;
      }
      available = result.files;
      for (const file of available) files.add(new Option(file.path, file.path));
      files.disabled = !available.length;
      if (result.files.length) showFile(result.files.find(file => file.path === selected) || result.files[0]);
      const custom = String(data.get('custom_start_script') || '').trim();
      const jar = String(data.get('server_jar') || '').trim() || 'paper.jar';
      upload.textContent = custom
        ? `Upload ${custom} and the modpack files into server/ after creation.`
        : `Upload ${jar} into server/ after creation.`;
      status.hidden = true;
    } catch (error) {
      if (error.name !== 'AbortError' && version === revision) {
        status.textContent = 'Preview unavailable. Change a field to retry.';
        available = []; files.replaceChildren(); files.disabled = true;
        code.textContent = ''; upload.textContent = '';
      }
    } finally {
      if (version === revision) panel.removeAttribute('aria-busy');
    }
  }
  form.addEventListener('input', event => {
    if (event.target.name === 'accept_eula') return;
    clearTimeout(timer); pending?.abort();
    const version = ++revision;
    panel.setAttribute('aria-busy', 'true');
    status.hidden = false; status.textContent = 'Updating preview...';
    timer = setTimeout(() => refresh(version), 250);
  });
  refresh(++revision);
})();
