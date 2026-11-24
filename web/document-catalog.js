/* Atualização localizada: mantém os próprios elementos dos formulários em edição. */
'use strict';
window.FarolCatalog = {
  create(container, emptyMessage) {
    let latest = new Map();
    container.addEventListener('input', markDirty);
    container.addEventListener('change', markDirty);
    function markDirty(event) {
      const card = event.target.closest('article[data-document-id]');
      if (card && event.target.closest('form')) card.dataset.dirty = '1';
    }
    function parseCard(item) {
      const template = document.createElement('template');
      template.innerHTML = item.html; // HTML do próprio servidor, com campos escapados no PHP.
      const card = template.content.firstElementChild;
      if (!card || card.tagName !== 'ARTICLE' || card.dataset.documentId !== String(item.id)) {
        throw new Error('Cartão documental inválido');
      }
      return card;
    }
    function replaceClean(old, next) {
      const open = [...old.querySelectorAll('details')].map(d => d.open);
      next.querySelectorAll('details').forEach((d,i) => {d.open = open[i] || false;});
      old.replaceWith(next);
    }
    function conflict(old, removed) {
      old.dataset.stale = '1';
      // Impede submeter uma substituição preparada para uma versão que já mudou.
      old.querySelectorAll('form button, form input').forEach(el => {el.disabled = true;});
      let notice = old.querySelector('.catalog-conflict');
      if (!notice) {
        notice = document.createElement('div'); notice.className = 'catalog-conflict';
        notice.setAttribute('role','status');
        const text = document.createElement('p'); notice.append(text);
        const button = document.createElement('button'); button.type = 'button';
        button.textContent = 'Descartar preenchimento e atualizar este item';
        button.addEventListener('click', () => {
          const next = latest.get(old.dataset.documentId);
          if (next) replaceClean(old, parseCard(next)); else old.remove();
        });
        notice.append(button); old.prepend(notice);
      }
      notice.querySelector('p').textContent = removed
        ? 'Este documento foi removido do catálogo. O preenchimento foi preservado para conferência; o envio está desabilitado.'
        : 'Este documento foi atualizado. O preenchimento foi preservado para conferência; atualize este item antes de enviar.';
    }
    return {
      update(items) {
        // Valida toda a resposta antes de alterar a tela.
        const incoming = new Map(); const parsed = new Map();
        for (const item of items) {
          const key = String(item.id);
          if (incoming.has(key)) throw new Error('Documento duplicado');
          incoming.set(key,item); parsed.set(key,parseCard(item));
        }
        latest = incoming;
        for (const old of [...container.querySelectorAll('article[data-document-id]')]) {
          const key = old.dataset.documentId; const next = parsed.get(key);
          if (!next) {
            if (old.dataset.dirty === '1') conflict(old,true); else old.remove();
          } else if (old.dataset.stale === '1' || old.dataset.version !== next.dataset.version) {
            if (old.dataset.dirty === '1') conflict(old,false); else replaceClean(old,next);
          }
          parsed.delete(key);
        }
        for (const next of parsed.values()) container.append(next);
        emptyMessage.hidden = items.length !== 0;
      }
    };
  }
};
