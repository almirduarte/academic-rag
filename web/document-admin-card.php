<?php
declare(strict_types=1);
// Inclusão interna; os dados e a autorização vêm de document-admin.php.
function farol_admin_card(array $doc, string $csrf): string
{
    ob_start();
?>
<article data-document-id="<?= (int)$doc['id'] ?>" data-version="<?= farol_h(hash('sha256', json_encode($doc, JSON_THROW_ON_ERROR))) ?>"><h3><?= farol_h($doc['title']) ?></h3><p><?= farol_h($doc['source_file']) ?></p>
<details><summary>Substituir documento</summary><p>O documento atual continua disponível até a nova publicação. O ID será preservado.</p>
<form method="post" enctype="multipart/form-data"><input type="hidden" name="csrf" value="<?= farol_h($csrf) ?>"><input type="hidden" name="action" value="replace"><input type="hidden" name="document_id" value="<?= (int)$doc['id'] ?>">
<label>Título <input type="text" name="title" maxlength="300" value="<?= farol_h($doc['title']) ?>" required></label>
<label>Novo PDF <input type="file" name="pdf" accept="application/pdf,.pdf" required></label><button>Preparar substituição</button></form></details>
<details><summary>Remover documento</summary><p>A exclusão remove o PDF, os trechos e o resumo da base. Não há desfazer pela interface.</p>
<form method="post"><input type="hidden" name="csrf" value="<?= farol_h($csrf) ?>"><input type="hidden" name="action" value="delete"><input type="hidden" name="document_id" value="<?= (int)$doc['id'] ?>">
<label>Digite o nome completo do arquivo acima para confirmar <input type="text" name="confirmation" required autocomplete="off"></label><button class="danger">Confirmar exclusão</button></form></details>
</article>
<?php
    return (string)ob_get_clean();
}
