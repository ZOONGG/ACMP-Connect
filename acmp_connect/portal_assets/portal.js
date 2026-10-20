'use strict';
const forms = [...document.querySelectorAll('form[data-loading]')];
let submitting = false;
forms.forEach(form => {
  form.addEventListener('submit', event => {
    if (submitting) {
      event.preventDefault();
      return;
    }
    submitting = true;
    form.classList.add('is-loading');
    form.setAttribute('aria-busy', 'true');
    const status = form.querySelector('[role="status"]');
    if (status) status.textContent = form.dataset.loading;
    // Disable buttons only: credentials and CSRF must remain successful controls.
    forms.forEach(item => item.querySelectorAll('button[type="submit"]').forEach(button => {
      button.disabled = true;
    }));
    const button = event.submitter;
    if (button) {
      button.dataset.original = button.innerHTML;
      const label = button.querySelector('span');
      if (label) label.textContent = form.dataset.loading;
      else button.textContent = form.dataset.loading;
    }
  });
});
window.addEventListener('pageshow', () => {
  submitting = false;
  forms.forEach(form => {
    form.classList.remove('is-loading');
    form.removeAttribute('aria-busy');
    const status = form.querySelector('[role="status"]');
    if (status) status.textContent = '';
    form.querySelectorAll('button[type="submit"]').forEach(button => {
      button.disabled = false;
      if (button.dataset.original) button.innerHTML = button.dataset.original;
    });
  });
  const password = document.getElementById('password');
  if (password) password.type = 'password';
  const reveal = document.querySelector('.reveal');
  if (reveal) { reveal.textContent = 'Показать'; reveal.setAttribute('aria-pressed', 'false'); reveal.setAttribute('aria-label', 'Показать пароль'); }
});
const reveal = document.querySelector('.reveal');
if (reveal) reveal.addEventListener('click', () => {
  const password = document.getElementById('password');
  const visible = password.type === 'password';
  password.type = visible ? 'text' : 'password';
  reveal.textContent = visible ? 'Скрыть' : 'Показать';
  reveal.setAttribute('aria-pressed', String(visible));
  reveal.setAttribute('aria-label', visible ? 'Скрыть пароль' : 'Показать пароль');
});

const deleteDialog = document.getElementById('delete-dialog');
const openDelete = document.querySelector('[data-open-delete]');
if (deleteDialog && openDelete) {
  openDelete.addEventListener('click', () => {
    deleteDialog.querySelector('form').reset();
    deleteDialog.showModal();
  });
  document.querySelector('[data-close-delete]').addEventListener('click', () => deleteDialog.close());
}
