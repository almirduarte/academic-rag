<?php
declare(strict_types=1);
require_once __DIR__ . '/auth-common.php';
require_once __DIR__ . '/document-admin-upload.php';
require_once __DIR__ . '/document-admin-card.php';
if (!isset($_SESSION['auth'])) { header('Location: login.php', true, 303); exit; }
$auth = $_SESSION['auth'];
$csrf = $_SESSION['csrf'];
$isPost = ($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST';
$csrfValid = !$isPost || farol_csrf_valid();
$appName = farol_app_name(!isset($_GET['jobs']));
session_write_close();
$authorized = false;
$error = null;
$notice = null;
$documents = [];
$jobs = [];
$preview = null;
$previewId = null;
function admin_error(array $r): string {
    return is_string($r['data']['detail'] ?? null) ? $r['data']['detail'] : 'Não foi possível concluir a operação (HTTP ' . $r['status'] . ').';
}
try {
    $listing = farol_api('/documents/list', [], $auth['token']);
    if ($listing['status'] === 401) { header('Location: login.php', true, 303); exit; }
    if ($listing['status'] !== 200) { throw new RuntimeException('Não foi possível consultar o catálogo.'); }
    if (($listing['data']['is_admin'] ?? false) !== true) { http_response_code(403); exit('Acesso permitido somente a administradores.'); }
    $authorized = true;
    $documents = $listing['data']['documents'];
    if ($isPost) {
        if (!$csrfValid) { throw new RuntimeException('A sessão expirou ou o upload excedeu o limite do PHP. Atualize a página.'); }
        $action = $_POST['action'] ?? '';
        if (in_array($action, ['include', 'replace'], true)) {
            $metadata = ['operation' => $action, 'title' => trim((string)($_POST['title'] ?? '')),
                         'source_file' => (string)($_FILES['pdf']['name'] ?? '')];
            if ($action === 'replace') { $metadata['document_id'] = (int)($_POST['document_id'] ?? 0); }
            $r = farol_upload_document($_FILES['pdf'] ?? [], $metadata, $auth['token']);
        } elseif ($action === 'delete') {
            $r = farol_api('/documents/admin/delete', ['document_id' => (int)($_POST['document_id'] ?? 0),
                'confirmation' => (string)($_POST['confirmation'] ?? '')], $auth['token']);
        } elseif (in_array($action, ['approve', 'cancel'], true)) {
            if ($action === 'approve' && ($_POST['reviewed'] ?? '') !== '1') {
                throw new RuntimeException('Confirme que conferiu o texto antes de publicar.');
            }
            $r = farol_api('/documents/admin/' . $action, ['job_id' => (string)($_POST['job_id'] ?? '')], $auth['token']);
        } else { throw new RuntimeException('Operação inválida.'); }
        if ($r['status'] < 200 || $r['status'] >= 300) { throw new RuntimeException(admin_error($r)); }
        header('Location: document-admin.php?sent=1', true, 303); exit;
    }
    if (isset($_GET['sent'])) { $notice = 'Solicitação recebida. Acompanhe a situação na lista de tarefas.'; }
    $r = farol_api('/documents/admin/jobs', [], $auth['token']);
    if ($r['status'] !== 200) { throw new RuntimeException(admin_error($r)); }
    $jobs = $r['data']['jobs'];
    if (isset($_GET['jobs'])) {
        header('Content-Type: application/json; charset=utf-8');
        // Busca após as tarefas: uma exclusão concluída já deve refletir no catálogo.
        $latest = farol_api('/documents/list', [], $auth['token']);
        if ($latest['status'] !== 200 || ($latest['data']['is_admin'] ?? false) !== true) {
            throw new RuntimeException('Catálogo indisponível ou permissão administrativa revogada.');
        }
        $cards = array_map(fn(array $doc): array => [
            'id' => (int)$doc['id'], 'html' => farol_admin_card($doc, $csrf)
        ], $latest['data']['documents']);
        header('Cache-Control: no-store');
        echo json_encode(['jobs' => $jobs, 'documents' => $cards], JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR); exit;
    }
    if (isset($_GET['review'])) {
        $previewId = (string)$_GET['review'];
        $r = farol_api('/documents/admin/preview', ['job_id' => $previewId], $auth['token']);
        if ($r['status'] !== 200) { throw new RuntimeException(admin_error($r)); }
        $preview = $r['data'];
    }
} catch (Throwable $exception) {
    $error = $exception->getMessage();
    if (isset($_GET['jobs'])) {
        http_response_code(503); header('Content-Type: application/json'); echo '{"error":"Atualização indisponível."}'; exit;
    }
}
if (!$authorized) { http_response_code(503); exit(farol_h($error ?? 'Administração indisponível.')); }
$states = ['queued'=>'Aguardando processamento','processing'=>'Processando','review'=>'Aguardando revisão',
    'approved'=>'Aguardando publicação','publishing'=>'Publicando','done'=>'Concluída','failed'=>'Falhou','cancelled'=>'Cancelada'];
$operations = ['include'=>'Inclusão','replace'=>'Substituição','delete'=>'Exclusão'];
?>
<!doctype html><html lang="pt-BR"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Administrar documentos — <?= farol_h($appName) ?></title>
<style>
body{max-width:1000px;margin:40px auto;padding:0 20px;font:16px Arial,sans-serif;color:#222}a{color:#15516e}
section,article{border:1px solid #ccc;border-radius:6px;padding:20px;margin:20px 0;overflow-wrap:anywhere}
label{display:block;margin:14px 0 6px}input[type=text],input[type=file]{box-sizing:border-box;width:100%;padding:9px;font:inherit}
button{padding:10px 16px;margin:14px 8px 0 0;font:inherit;cursor:pointer}.danger{color:#900;border:1px solid #900;background:white}
.error{border:1px solid #b00;color:#900;padding:14px}.notice{background:#eef6ef;padding:14px}
textarea{box-sizing:border-box;width:100%;height:420px;font:14px monospace;padding:12px}summary{cursor:pointer;margin:12px 0}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{text-align:left;padding:9px;border-bottom:1px solid #ddd;vertical-align:top}
[hidden]{display:none!important}.catalog-conflict{border:1px solid #9c6b00;background:#fff8df;padding:12px}.table-wrap{overflow-x:auto}.muted{font-size:14px;color:#555}
</style></head><body>
<h1><?= farol_h($appName) ?></h1><nav><a href="documents.php">Voltar aos documentos</a></nav>
<h2>Administrar documentos</h2>
<?php if ($error !== null): ?><p class="error" role="alert"><?= farol_h($error) ?></p><?php endif; ?>
<?php if ($notice !== null): ?><p class="notice" role="status"><?= farol_h($notice) ?></p><?php endif; ?>
<?php if ($preview !== null): ?>
<section><h2>Conferir texto antes de publicar</h2>
<p>Compare o texto com o PDF, especialmente fórmulas, tabelas e exceções. A extração automática pode perder formatação.</p>
<p><?= (int)$preview['metadata']['pages'] ?> páginas; <?= (int)$preview['metadata']['chunks'] ?> trechos preparados.</p>
<textarea readonly aria-label="Texto extraído completo"><?= farol_h($preview['text']) ?></textarea>
<form method="post"><input type="hidden" name="csrf" value="<?= farol_h($csrf) ?>"><input type="hidden" name="job_id" value="<?= farol_h($previewId) ?>">
<label><input type="checkbox" name="reviewed" value="1" required> Conferi o texto extraído e autorizo a publicação.</label>
<button name="action" value="approve">Publicar documento</button></form>
<form method="post"><input type="hidden" name="csrf" value="<?= farol_h($csrf) ?>"><input type="hidden" name="job_id" value="<?= farol_h($previewId) ?>"><button name="action" value="cancel">Cancelar esta tarefa</button></form>
</section>
<?php endif; ?>
<section><h2>Incluir documento</h2><p>PDF de até 50 MiB e 300 páginas. Após o processamento, será necessário conferir e autorizar a publicação.</p>
<form method="post" enctype="multipart/form-data">
<input type="hidden" name="csrf" value="<?= farol_h($csrf) ?>"><input type="hidden" name="action" value="include">
<label for="new-title">Título</label><input id="new-title" type="text" name="title" maxlength="300" required>
<label for="new-pdf">Arquivo PDF</label><input id="new-pdf" type="file" name="pdf" accept="application/pdf,.pdf" required>
<button>Enviar para processamento</button></form></section>
<section><h2>Tarefas recentes</h2><p class="muted" id="poll-status">Tarefas e documentos são atualizados a cada cinco segundos.</p>
<p><a href="document-admin.php">Atualizar a página e o catálogo</a></p>
<div class="table-wrap"><table><thead><tr><th>Documento / operação</th><th>Situação</th><th>Detalhes</th><th>Ação</th></tr></thead><tbody id="job-rows">
<?php foreach ($jobs as $job): ?><tr><td><?= farol_h($job['title']) ?><br><?= farol_h($operations[$job['operation']] ?? $job['operation']) ?></td>
<td><?= farol_h($states[$job['state']] ?? $job['state']) ?></td><td><?= farol_h($job['message']) ?></td><td>
<?php if ($job['state']==='review'): ?><a href="?review=<?= rawurlencode($job['job_id']) ?>">Conferir texto</a><?php endif; ?>
<?php if (in_array($job['state'],['queued','review','approved'],true)): ?>
<form method="post"><input type="hidden" name="csrf" value="<?= farol_h($csrf) ?>"><input type="hidden" name="job_id" value="<?= farol_h($job['job_id']) ?>"><button name="action" value="cancel">Cancelar</button></form><?php endif; ?>
</td></tr><?php endforeach; ?></tbody></table></div></section>
<section><h2>Documentos publicados</h2>
<div id="published-documents">
<?php foreach ($documents as $doc): ?><?= farol_admin_card($doc, $csrf) ?><?php endforeach; ?>
</div><p id="empty-catalog" <?= $documents ? 'hidden' : '' ?>>Nenhum documento publicado.</p></section>
<script src="document-catalog.js?v=3"></script>
<script>
const states=<?= json_encode($states,JSON_HEX_TAG|JSON_HEX_AMP|JSON_HEX_APOS|JSON_HEX_QUOT) ?>;
const operations=<?= json_encode($operations,JSON_HEX_TAG|JSON_HEX_AMP|JSON_HEX_APOS|JSON_HEX_QUOT) ?>;
const csrf=<?= json_encode($csrf,JSON_HEX_TAG|JSON_HEX_AMP|JSON_HEX_APOS|JSON_HEX_QUOT) ?>;
const catalog = FarolCatalog.create(document.getElementById('published-documents'), document.getElementById('empty-catalog'));
async function updateJobs(){
 try{
  const response=await fetch('document-admin.php?jobs=1',{cache:'no-store'});
  if(!response.ok)throw new Error('HTTP');
  const data=await response.json();if(!Array.isArray(data.jobs)||!Array.isArray(data.documents))throw new Error('JSON');
  catalog.update(data.documents);
  const rows=document.createDocumentFragment();
  for(const job of data.jobs){
   const row=document.createElement('tr');
   for(const value of [job.title+' — '+operations[job.operation],states[job.state]||job.state,job.message]){
    const cell=document.createElement('td');cell.textContent=value;row.append(cell);
   }
   const actions=document.createElement('td');
   if(job.state==='review'){const link=document.createElement('a');link.href='?review='+encodeURIComponent(job.job_id);link.textContent='Conferir texto';actions.append(link);}
   if(['queued','review','approved'].includes(job.state)){
    const form=document.createElement('form');form.method='post';
    for(const [name,value] of Object.entries({csrf,job_id:job.job_id,action:'cancel'})){const input=document.createElement('input');input.type='hidden';input.name=name;input.value=value;form.append(input);}
    const button=document.createElement('button');button.textContent='Cancelar';form.append(button);actions.append(form);
   }
   row.append(actions);rows.append(row);
  }
  document.getElementById('job-rows').replaceChildren(rows);
  document.getElementById('poll-status').textContent='Tarefas e catálogo atualizados automaticamente. Formulários em preenchimento são preservados.';
 }catch(e){document.getElementById('poll-status').textContent='Atualização indisponível. Verifique sua sessão e atualize a página.';}
 finally{setTimeout(updateJobs,5000);}
}
setTimeout(updateJobs,5000);
</script></body></html>
