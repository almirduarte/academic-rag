<?php
require_once __DIR__ . '/auth-common.php';
if (isset($_SESSION['auth'])) {
    header('Location: index.php', true, 303);
    exit;
}
$register = ($_GET['cadastro'] ?? '') === '1';
$error = '';
$message = is_string($_SESSION['account_notice'] ?? null) ? $_SESSION['account_notice'] : '';
unset($_SESSION['account_notice']);
$email = '';
$name = '';
$cpf = '';
$sector = '';
if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST') {
    $register = ($_POST['action'] ?? '') === 'register';
    $email = is_string($_POST['email'] ?? null) ? trim($_POST['email']) : '';
    $name = is_string($_POST['full_name'] ?? null) ? trim($_POST['full_name']) : '';
    $cpf = is_string($_POST['cpf'] ?? null) ? trim($_POST['cpf']) : '';
    $sector = is_string($_POST['sector'] ?? null) ? $_POST['sector'] : '';
    $password = is_string($_POST['password'] ?? null) ? $_POST['password'] : '';
    if (!farol_csrf_valid()) {
        $error = 'A sessão expirou. Atualize a página e tente novamente.';
    } elseif ($register && $password !== ($_POST['password_confirmation'] ?? null)) {
        $error = 'A confirmação da senha não confere.';
    } else {
        try {
            $payload = ['email' => $email, 'password' => $password, 'ip_address' => farol_ip()];
            if ($register) {
                $payload += ['full_name' => $name, 'cpf' => $cpf, 'sector' => (int) $sector];
            }
            $response = farol_api($register ? '/auth/register' : '/auth/login', $payload, null, 90);
            if ($response['status'] >= 200 && $response['status'] < 300) {
                if ($register) {
                    $message = $response['data']['message'] ?? 'Cadastro criado. Confira seu e-mail para confirmar o endereço.';
                    $register = false;
                    $_SESSION['csrf'] = bin2hex(random_bytes(32));
                } else {
                    $data = $response['data'];
                    if (!is_string($data['token'] ?? null) || !is_array($data['user'] ?? null)) {
                        throw new RuntimeException('Resposta inválida de autenticação.');
                    }
                    session_regenerate_id(true);
                    $_SESSION['csrf'] = bin2hex(random_bytes(32));
                    $_SESSION['auth'] = ['token' => $data['token'], 'user' => $data['user'],
                        'expires_at' => time() + (int) $data['expires_in']];
                    header('Location: index.php', true, 303);
                    exit;
                }
            } else {
                $error = farol_error($response);
            }
        } catch (Throwable $e) {
            error_log('Aplicação: falha de autenticação (' . get_class($e) . ').');
            $error = 'Não foi possível acessar o serviço de autenticação. Tente novamente mais tarde.';
        }
    }
    unset($password, $payload, $response);
}
$csrf = $_SESSION['csrf'];
$appName = farol_app_name(true);
session_write_close();
?>
<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title><?= $register ? 'Cadastro' : 'Entrar' ?> — <?= farol_h($appName) ?></title>
<style>
body {max-width:540px;margin:40px auto;padding:0 20px;font:16px Arial,sans-serif;color:#222}
img {width:100%;max-height:170px;object-fit:cover} label {display:block;margin-top:16px}
input,select {box-sizing:border-box;width:100%;font:inherit;padding:10px;margin-top:5px}
button {font:inherit;padding:10px 18px;margin-top:22px;cursor:pointer}
.error {padding:12px;border:1px solid #b00;color:#900}.notice{padding:12px;background:#eef7ef}
a{color:#10425f} small{display:block;margin-top:6px}
</style></head><body>
<img src="farolete-villegagnon.png" alt="Farolete da Ilha de Villegagnon">
<h1><?= farol_h($appName) ?></h1><h2><?= $register ? 'Criar cadastro' : 'Entrar' ?></h2>
<?php if ($error !== ''): ?><p class="error" role="alert"><?= farol_h($error) ?></p><?php endif; ?>
<?php if ($message !== ''): ?><p class="notice" role="status"><?= farol_h($message) ?></p><?php endif; ?>
<form method="post" action="login.php">
<input type="hidden" name="csrf" value="<?= farol_h($csrf) ?>">
<input type="hidden" name="action" value="<?= $register ? 'register' : 'login' ?>">
<?php if ($register): ?>
<label for="full_name">Nome completo</label><input id="full_name" name="full_name" maxlength="200" autocomplete="name" value="<?= farol_h($name) ?>" required>
<label for="cpf">CPF</label><input id="cpf" name="cpf" inputmode="numeric" maxlength="14" value="<?= farol_h($cpf) ?>" required>
<label for="sector">Setor</label><select id="sector" name="sector" required><option value="">Selecione</option>
<?php foreach (farol_sectors() as $id=>$label): ?>
<option value="<?= $id ?>" <?= $sector === (string)$id ? 'selected' : '' ?>><?= farol_h($label) ?></option>
<?php endforeach; ?></select>
<?php endif; ?>
<label for="email">E-mail</label><input id="email" name="email" type="email" maxlength="50" autocomplete="username" value="<?= farol_h($email) ?>" required>
<label for="password">Senha</label><input id="password" name="password" type="password" minlength="<?= $register ? 8 : 1 ?>" maxlength="128" autocomplete="<?= $register ? 'new-password' : 'current-password' ?>" required>
<?php if ($register): ?>
<small>Use de 12 a 128 caracteres. Espaços são permitidos.</small>
<label for="confirmation">Confirme a senha</label><input id="confirmation" name="password_confirmation" type="password" minlength="8" maxlength="128" autocomplete="new-password" required>
<?php endif; ?>
<button type="submit"><?= $register ? 'Cadastrar' : 'Entrar' ?></button>
</form>
<p><a href="<?= $register ? 'login.php' : 'login.php?cadastro=1' ?>"><?= $register ? 'Já tenho cadastro' : 'Criar meu cadastro' ?></a></p>
<p><a href="reenviar-confirmacao.php">Reenviar confirmação de e-mail</a></p>
</body></html>
