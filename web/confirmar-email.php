<?php
require_once __DIR__ . '/auth-common.php';
header('Referrer-Policy: no-referrer');
$error = '';
$message = '';
$token = '';
if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST') {
    $token = is_string($_POST['token'] ?? null) ? $_POST['token'] : '';
    if (!farol_csrf_valid()) {
        $error = 'A sessão expirou. Abra novamente o link recebido por e-mail.';
    } elseif (!preg_match('/^[A-Za-z0-9_-]{43}$/D', $token)) {
        $error = 'Link inválido. Abra o link completo recebido por e-mail.';
    } else {
        try {
            $response = farol_api('/auth/confirm-email', ['token' => $token, 'ip_address' => farol_ip()]);
            if ($response['status'] === 200) {
                $message = $response['data']['message'];
                $token = '';
                $_SESSION['csrf'] = bin2hex(random_bytes(32));
            } else {
                $error = farol_error($response);
            }
        } catch (Throwable $e) {
            error_log('Aplicação: falha ao confirmar e-mail (' . get_class($e) . ').');
            $error = 'Não foi possível confirmar agora. Tente novamente.';
        }
    }
}
$csrf = $_SESSION['csrf'];
$appName = farol_app_name(true);
session_write_close();
?>
<!doctype html><html lang="pt-BR"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Confirmar e-mail — <?= farol_h($appName) ?></title>
<style>body{max-width:540px;margin:40px auto;padding:0 20px;font:16px Arial,sans-serif;color:#222}img{width:100%;max-height:170px;object-fit:cover}button{font:inherit;padding:10px 18px;cursor:pointer}.error{padding:12px;border:1px solid #b00;color:#900}.notice{padding:12px;background:#eef7ef}a{color:#10425f}</style>
</head><body>
<img src="farolete-villegagnon.png" alt="Farolete da Ilha de Villegagnon">
<h1><?= farol_h($appName) ?></h1><h2>Confirmar e-mail</h2>
<?php if ($error !== ''): ?><p class="error" role="alert"><?= farol_h($error) ?></p><?php endif; ?>
<?php if ($message !== ''): ?><p class="notice" role="status"><?= farol_h($message) ?></p>
<?php else: ?>
<p>Pressione o botão para confirmar seu endereço de e-mail.</p>
<form method="post" action="confirmar-email.php">
<input type="hidden" name="csrf" value="<?= farol_h($csrf) ?>">
<input type="hidden" name="token" id="token" value="<?= farol_h($token) ?>">
<button type="submit" id="confirm">Confirmar e-mail</button>
</form>
<p id="link-error" class="error" hidden>Abra o link completo recebido por e-mail.</p>
<noscript><p>Ative o JavaScript e abra novamente o link recebido por e-mail.</p></noscript>
<script>
const fragmentToken = new URLSearchParams(location.hash.slice(1)).get('token');
const input = document.getElementById('token');
if (fragmentToken && /^[A-Za-z0-9_-]{43}$/.test(fragmentToken)) input.value = fragmentToken;
if (location.hash) history.replaceState(null, '', location.pathname);
if (!/^[A-Za-z0-9_-]{43}$/.test(input.value)) {
    document.getElementById('confirm').disabled = true;
    document.getElementById('link-error').hidden = false;
}
</script>
<?php endif; ?>
<p><a href="login.php">Entrar</a></p>
<p><a href="reenviar-confirmacao.php">Reenviar confirmação</a></p>
</body></html>
