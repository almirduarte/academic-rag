/* Copia o texto recebido, preservando quebras de linha e Markdown literal. */
(() => {
    'use strict';
    const button = document.getElementById('copy-answer');
    const text = document.getElementById('answer-text');
    const status = document.getElementById('copy-status');
    if (!button || !text || !status) return;
    button.hidden = false;
    let version = 0;
    let pending = false;
    function reset() {
        version++;
        status.textContent = '';
        button.disabled = pending || !text.textContent.trim();
    }
    new MutationObserver(reset).observe(text, {childList: true, characterData: true, subtree: true});
    reset();
    button.addEventListener('click', async () => {
        const value = text.textContent;
        if (pending || !value.trim()) return;
        pending = true;
        button.disabled = true;
        const current = version;
        status.textContent = '';
        try {
            if (!navigator.clipboard?.writeText) throw new Error('Clipboard indisponível');
            await navigator.clipboard.writeText(value);
            if (current === version) status.textContent = 'Resposta copiada.';
        } catch (_) {
            if (current !== version) return;
            const selection = window.getSelection();
            if (selection) {
                const range = document.createRange();
                range.selectNodeContents(text);
                selection.removeAllRanges();
                selection.addRange(range);
            }
            status.textContent = 'Não foi possível copiar automaticamente. Selecione o texto e use Ctrl+C (ou ⌘C no Mac).';
        } finally {
            pending = false;
            button.disabled = !text.textContent.trim();
        }
    });
})();
