<?php
declare(strict_types=1);
require_once __DIR__ . '/auth-common.php';
if (!isset($_SESSION['auth'])) {
    header('Location: login.php', true, 303);
    exit;
}
$auth = $_SESSION['auth'];
$appName = farol_app_name(true);
session_write_close();
$documents = [];
$isAdmin = false;
$error = null;
try {
    $response = farol_api('/documents/list', [], $auth['token']);
    if ($response['status'] === 401) {
        header('Location: login.php', true, 303);
        exit;
    }
    if ($response['status'] !== 200) {
        $error = farol_error($response);
        http_response_code(503);
    } elseif (!is_array($response['data']['documents'] ?? null)) {
        throw new RuntimeException('Catálogo inválido.');
    } else {
        $documents = $response['data']['documents'];
        $isAdmin = ($response['data']['is_admin'] ?? false) === true;
    }
} catch (Throwable $exception) {
    error_log('Aplicação: falha ao consultar documentos (' . get_class($exception) . ').');
    $error = 'Não foi possível consultar os documentos. Tente novamente mais tarde.';
    http_response_code(503);
}
?>
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Documentos — <?= farol_h($appName) ?></title>
<style>
body {max-width:900px;margin:40px auto;padding:0 20px;font:16px Arial,sans-serif;color:#222;}
a {color:#15516e;}
.document {border:1px solid #ccc;border-radius:6px;padding:20px;margin:20px 0;overflow-wrap:anywhere;}
h2 {font-size:21px;margin:0 0 12px;}
dl {display:grid;grid-template-columns:150px 1fr;gap:8px;margin:16px 0;}
dt {font-weight:bold;} dd {margin:0;}
.actions {display:flex;gap:12px;flex-wrap:wrap;margin-top:20px;}
.actions a {border:1px solid #15516e;padding:10px 16px;border-radius:4px;text-decoration:none;}
.error {padding:16px;border:1px solid #b00;color:#900;}
.muted {color:#555;font-size:14px;}
@media(max-width:550px) {dl {grid-template-columns:1fr;gap:5px;}dd {margin-bottom:10px;}}
</style>
</head>
<body>
<h1><?= farol_h($appName) ?></h1>
<nav><a href="index.php">Voltar às consultas</a></nav>
<?php if ($isAdmin): ?><p><a href="document-admin.php">Administrar documentos</a></p><?php endif; ?>
<h2 style="margin-top:28px">Documentos disponíveis</h2>
<p>Veja os documentos carregados na base e consulte os PDFs originais utilizados como fonte das respostas. Este acesso está disponível a todos os usuários autenticados.</p>
<?php if ($error !== null): ?>
<p class="error" role="alert"><?= farol_h($error) ?></p>
<?php elseif (!$documents): ?>
<p>Nenhum documento foi cadastrado para consulta aos originais.</p>
<?php else: ?>
<?php foreach ($documents as $doc): ?>
<article class="document">
<h2><?= farol_h((string)$doc['title']) ?></h2>
<dl>
<dt>Arquivo</dt><dd><?= farol_h((string)$doc['source_file']) ?></dd>
<dt>Situação</dt><dd><?= farol_h((string)$doc['status']) ?></dd>
<dt>Tamanho</dt><dd><?= farol_h(number_format((float)$doc['size_bytes'] / 1048576, 2, ',', '.')) ?> MiB</dd>
<dt>Cadastro</dt><dd><?= farol_h((new DateTimeImmutable($doc['registered_at']))->setTimezone(new DateTimeZone('America/Sao_Paulo'))->format('d/m/Y H:i')) ?> (Brasília)</dd>
</dl>
<?php if ($doc['can_download']): ?>
<div class="actions">
<a href="document-file.php?id=<?= (int)$doc['id'] ?>&amp;mode=inline" target="_blank" rel="noopener">Abrir PDF</a>
<a href="document-file.php?id=<?= (int)$doc['id'] ?>&amp;mode=attachment">Baixar PDF</a>
</div>
<?php else: ?>
<p class="muted">O arquivo precisa ser conferido pelo administrador.</p>
<?php endif; ?>
</article>
<?php endforeach; ?>
<?php endif; ?>
</body>
</html>
