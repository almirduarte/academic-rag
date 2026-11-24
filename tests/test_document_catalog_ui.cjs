// Requer Node.js, playwright e Chromium. Não acessa servidores ou banco reais.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
(async () => {
 const browser = await chromium.launch({headless:true, ...(process.env.CHROMIUM_PATH ? {executablePath:process.env.CHROMIUM_PATH} : {})});
 try {
  const page = await browser.newPage();
  await page.setContent('<form id="include"><input id="new-title"></form><div id="catalog"></div><p id="empty" hidden>Vazio</p>');
  await page.addScriptTag({path:path.join(__dirname,'../web/document-catalog.js')});
  await page.evaluate(() => {
   window.card = (id,version,title) => ({id,html:`<article data-document-id="${id}" data-version="${version}"><h3>${title}</h3><details><summary>Substituir</summary><form><input name="title" value="${title}"><input name="pdf" type="file"><button>Enviar</button></form></details></article>`});
   window.catalog=FarolCatalog.create(document.querySelector('#catalog'),document.querySelector('#empty'));
   catalog.update([card(1,'a','Um')]);
  });
  assert.equal(await page.locator('article').count(),1);
  await page.evaluate(() => catalog.update([card(1,'a','Um'),card(2,'b','Dois')]));
  assert.equal(await page.locator('article').count(),2); console.log('OK inclusão automática');
  await page.locator('[data-document-id="1"] summary').click();
  await page.evaluate(() => catalog.update([card(1,'c','Novo'),card(2,'b','Dois')]));
  assert.equal(await page.locator('[data-document-id="1"] h3').textContent(),'Novo');
  assert.equal(await page.locator('[data-document-id="1"] details').evaluate(e=>e.open),true);
  console.log('OK substituição e preservação de seção aberta');
  await page.locator('[data-document-id="1"] input[name="title"]').fill('Minha edição');
  await page.locator('[data-document-id="1"] input[type="file"]').setInputFiles({name:'teste.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF-teste')});
  await page.locator('#new-title').fill('Inclusão em andamento');
  await page.evaluate(() => {window.originalInput=document.querySelector('[data-document-id="1"] input[name="title"]');catalog.update([card(1,'c','Novo')]);});
  assert.equal(await page.locator('article').count(),1);
  assert.equal(await page.locator('[data-document-id="1"] input[name="title"]').inputValue(),'Minha edição');
  assert.equal(await page.evaluate(()=>originalInput===document.querySelector('[data-document-id="1"] input[name="title"]')),true);
  assert.equal(await page.locator('input[type="file"]').evaluate(e=>e.files[0].name),'teste.pdf');
  assert.equal(await page.locator('#new-title').inputValue(),'Inclusão em andamento');
  console.log('OK exclusão automática; texto, arquivo selecionado e inclusão preservados');
  await page.evaluate(() => catalog.update([card(1,'d','Outra versão')]));
  assert.equal(await page.locator('.catalog-conflict').count(),1);
  assert.equal(await page.locator('article form button').isDisabled(),true);
  assert.equal(await page.locator('article input[name="title"]').inputValue(),'Minha edição');
  console.log('OK conflito de versão bloqueia envio sem apagar edição');
  await page.locator('.catalog-conflict button').click();
  assert.equal(await page.locator('article h3').textContent(),'Outra versão');
  assert.equal(await page.locator('article form button').isDisabled(),false);
  console.log('OK descarte explícito atualiza somente o item');
  await page.locator('article input[name="title"]').fill('Edição antes da exclusão');
  await page.evaluate(() => catalog.update([]));
  assert.match(await page.locator('.catalog-conflict').textContent(),/removido/);
  assert.equal(await page.locator('#empty').isVisible(),true);
  await page.locator('.catalog-conflict button').click();
  assert.equal(await page.locator('article').count(),0);
  console.log('OK exclusão durante edição preserva e identifica formulário obsoleto');
  await page.evaluate(() => {catalog.update([card(3,'a','Três')]);window.invalidRejected=false;try{catalog.update([{id:4,html:'<p>Inválido</p>'}]);}catch{window.invalidRejected=true;}});
  assert.equal(await page.evaluate(()=>invalidRejected),true);
  assert.equal(await page.locator('article h3').textContent(),'Três');
  console.log('OK resposta inválida não apaga catálogo');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
