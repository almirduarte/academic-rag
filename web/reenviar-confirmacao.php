<?php
require_once __DIR__ . '/auth-common.php';
$error = '';
$message = '';
$email = '';
if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST') {
    $email = is_string($_POST['email'] ?? null) ? trim($_POST['email']) : '';
    if (!farol_csrf_valid()) {
        $error = 'A sessão expirou. Atualize a página e tente novamente.';
    } else {
        try {
            $response = farol_api('/auth/resend-confirmation', ['email' => $email, 'ip_address' => farol_ip()], null, 90);
            if ($response['status'] === 200) {
                $message = $response['data']['message'];
            } elseif ($response['status'] === 422) {
                $error = 'Informe um e-mail válido com até 50 caracteres.';
            } else {
                $error = farol_error($response);
            }
        } catch (Throwable $e) {
            error_log('Aplicação: falha ao reenviar confirmação (' . get_class($e) . ').');
            $error = 'Não foi possível solicitar o envio agora. Tente novamente mais tarde.';
        }
    }
}
$csrf = $_SESSION['csrf'];
$appName = farol_app_name(true);
session_write_close();
?>
<!doctype html><html lang="pt-BR"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reenviar confirmação — <?= farol_h($appName) ?></title>
<style>body{max-width:540px;margin:40px auto;padding:0 20px;font:16px Arial,sans-serif;color:#222}img{width:100%;max-height:170px;object-fit:cover}label{display:block;margin-top:16px}input{box-sizing:border-box;width:100%;font:inherit;padding:10px;margin-top:5px}button{font:inherit;padding:10px 18px;margin-top:22px;cursor:pointer}.error{padding:12px;border:1px solid #b00;color:#900}.notice{padding:12px;background:#eef7ef}a{color:#10425f}</style>
</head><body>
<img src="farolete-villegagnon.png" alt="Farolete da Ilha de Villegagnon">
<h1><?= farol_h($appName) ?></h1><h2>Reenviar confirmação</h2>
<?php if ($error !== ''): ?><p class="error" role="alert"><?= farol_h($error) ?></p><?php endif; ?>
<?php if ($message !== ''): ?><p class="notice" role="status"><?= farol_h($message) ?></p><?php endif; ?>
<form method="post" action="reenviar-confirmacao.php">
<input type="hidden" name="csrf" value="<?= farol_h($csrf) ?>">
<label for="email">E-mail do cadastro</label>
<input id="email" name="email" type="email" maxlength="50" autocomplete="email" value="<?= farol_h($email) ?>" required>
<button type="submit">Reenviar confirmação</button>
</form><p><a href="login.php">Voltar para o login</a></p>
</body></html>
