// Testes isolados da API de clipboard e do DOM: sem navegador ou dependências npm.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const code = fs.readFileSync(path.join(__dirname, '../web/answer-copy.js'), 'utf8');
function fixture(writeText) {
    let listener, observer, selected = false;
    const button = {hidden:true, disabled:false, addEventListener:(_, fn) => {listener = fn;}};
    const text = {textContent:'Resposta **literal**\nSegunda linha & <texto>.'};
    const status = {textContent:''};
    const elements = {'copy-answer':button, 'answer-text':text, 'copy-status':status};
    vm.runInNewContext(code, {
        document: {getElementById:id => elements[id], createRange:() => ({selectNodeContents:node => {selected = node === text;}})},
        window: {getSelection:() => ({removeAllRanges(){}, addRange(){}})},
        navigator: {clipboard:writeText ? {writeText} : undefined},
        MutationObserver: class { constructor(fn){observer=fn;} observe(){} },
    });
    return {button, text, status, click:() => listener(), change:value => {text.textContent=value;observer();}, selected:() => selected};
}
(async () => {
    let copied;
    const ok = fixture(async value => {copied=value;});
    await ok.click();
    assert.equal(copied, ok.text.textContent);
    assert.equal(ok.status.textContent,'Resposta copiada.');
    assert.equal(ok.button.disabled,false);
    console.log('OK cópia exata, quebras de linha e confirmação');
    ok.change('Resposta nova');
    assert.equal(ok.status.textContent,'');
    await ok.click(); assert.equal(copied,'Resposta nova');
    console.log('OK atualização da resposta');
    ok.change('   ');assert.equal(ok.button.disabled,true);
    console.log('OK resposta vazia');
    for (const write of [undefined, async () => {throw new Error('Permissão negada');}]) {
        const failure = fixture(write); await failure.click();
        assert.equal(failure.selected(),true);
        assert.match(failure.status.textContent,/Ctrl\+C/);
        assert.equal(failure.button.disabled,false);
    }
    console.log('OK clipboard ausente e permissão negada');
    let resolve;
    const delayed = fixture(() => new Promise(r => {resolve=r;}));
    const pending = delayed.click();
    assert.equal(delayed.button.disabled,true);
    delayed.change('Nova resposta durante a cópia');resolve();await pending;
    assert.equal(delayed.status.textContent,'');
    assert.equal(delayed.button.disabled,false);
    console.log('OK cópia pendente não confirma uma resposta nova');
})().catch(error => {console.error(error);process.exitCode=1;});
