<?php
declare(strict_types=1);
require_once __DIR__ . '/auth-common.php';

if (!isset($_SESSION['auth'])) {
    header('Location: login.php', true, 303);
    exit;
}

function end_account_session(string $message): void
{
    unset($_SESSION['auth']);
    session_regenerate_id(true);
    $_SESSION['csrf'] = bin2hex(random_bytes(32));
    $_SESSION['account_notice'] = $message;
    header('Location: login.php', true, 303);
    exit;
}

function posted_text(string $field): string
{
    return is_string($_POST[$field] ?? null) ? $_POST[$field] : '';
}

$error = '';
$message = is_string($_SESSION['profile_notice'] ?? null) ? $_SESSION['profile_notice'] : '';
unset($_SESSION['profile_notice']);
$profile = null;
$submitted = null;
$auth = $_SESSION['auth'];

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST') {
    $action = posted_text('action');
    if ($action === 'profile') {
        $submitted = [
            'full_name' => trim(posted_text('full_name')),
            'email' => trim(posted_text('email')),
            'cpf' => trim(posted_text('cpf')),
            'sector' => (int) posted_text('sector'),
        ];
    }
    if (!farol_csrf_valid()) {
        $error = 'A sessão do formulário expirou. Confira os dados e tente novamente.';
        http_response_code(403);
    } elseif (!in_array($action, ['profile', 'password'], true)) {
        $error = 'Operação inválida.';
        http_response_code(400);
    } elseif ($action === 'password' && posted_text('new_password') !== posted_text('password_confirmation')) {
        $error = 'A confirmação da nova senha não confere.';
    } else {
        try {
            $payload = ['current_password' => posted_text('current_password'), 'ip_address' => farol_ip()];
            if ($action === 'profile') {
                $payload += $submitted;
                $route = '/auth/update-profile';
            } else {
                $payload += ['new_password' => posted_text('new_password'),
                             'password_confirmation' => posted_text('password_confirmation')];
                $route = '/auth/change-password';
            }
            $response = farol_api($route, $payload, $auth['token'], 60);
            if ($response['status'] === 401) {
                end_account_session('Sua sessão expirou. Entre novamente.');
            }
            if ($response['status'] === 200) {
                $notice = is_string($response['data']['message'] ?? null)
                    ? $response['data']['message'] : 'Alteração concluída.';
                if (($response['data']['reauthenticate'] ?? false) === true) {
                    end_account_session($notice);
                }
                $_SESSION['profile_notice'] = $notice;
                $_SESSION['csrf'] = bin2hex(random_bytes(32));
                header('Location: meu-cadastro.php', true, 303);
                exit;
            }
            $error = $response['status'] === 422
                ? ($action === 'password'
                    ? 'Informe a senha atual e uma nova senha diferente, de 8 a 128 caracteres, com confirmação igual.'
                    : 'Confira nome e sobrenome, CPF, e-mail de até 50 caracteres, setor e senha atual.')
                : farol_error($response);
        } catch (Throwable $exception) {
            error_log('Aplicação: falha ao alterar cadastro (' . get_class($exception) . ').');
            $error = 'Não foi possível confirmar a alteração. Consulte seus dados ou tente entrar novamente antes de repetir.';
        } finally {
            unset($payload, $response);
        }
    }
}

try {
    $response = farol_api('/auth/profile', [], $auth['token']);
    if ($response['status'] === 401) {
        end_account_session('Sua sessão expirou. Entre novamente.');
    }
    $data = $response['data']['user'] ?? null;
    if ($response['status'] !== 200 || !is_array($data)
        || !is_string($data['full_name'] ?? null) || !is_string($data['email'] ?? null)
        || !is_string($data['cpf'] ?? null) || !is_int($data['sector'] ?? null)
        || !is_int($data['id'] ?? null)) {
        throw new RuntimeException('Resposta de cadastro inválida.');
    }
    $_SESSION['auth']['user'] = ['id' => $data['id'], 'full_name' => $data['full_name']];
    $profile = $submitted ?? $data;
} catch (Throwable $exception) {
    error_log('Aplicação: falha ao consultar cadastro (' . get_class($exception) . ').');
    $error = 'Não foi possível consultar seu cadastro. Tente novamente mais tarde.';
    http_response_code(503);
}
unset($response, $data);
$csrf = $_SESSION['csrf'];
$appName = farol_app_name(true);
session_write_close();
?>
<!doctype html>
<html lang="pt-BR"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Meu cadastro — <?= farol_h($appName) ?></title>
<style>
body{max-width:700px;margin:40px auto;padding:0 20px;font:16px Arial,sans-serif;color:#222}
a{color:#10425f}label{display:block;margin-top:16px}
input,select{box-sizing:border-box;width:100%;font:inherit;padding:10px;margin-top:5px}
button{font:inherit;padding:10px 18px;margin-top:22px;cursor:pointer}
section{border:1px solid #ccc;border-radius:6px;padding:22px;margin-top:24px}
.error{padding:12px;border:1px solid #b00;color:#900}.notice{padding:12px;background:#eef7ef}
small{display:block;margin-top:6px;color:#444}h2{margin-top:0}
</style></head><body>
<h1><?= farol_h($appName) ?></h1>
<nav><a href="index.php">Voltar às consultas</a></nav>
<h2 style="margin-top:28px">Meu cadastro</h2>
<?php if ($error !== ''): ?><p class="error" role="alert"><?= farol_h($error) ?></p><?php endif; ?>
<?php if ($message !== ''): ?><p class="notice" role="status"><?= farol_h($message) ?></p><?php endif; ?>
<?php if ($profile !== null): ?>
<section aria-labelledby="profile-title"><h2 id="profile-title">Dados pessoais</h2>
<form method="post" action="meu-cadastro.php">
<input type="hidden" name="csrf" value="<?= farol_h($csrf) ?>">
<input type="hidden" name="action" value="profile">
<label for="full_name">Nome completo</label>
<input id="full_name" name="full_name" maxlength="200" autocomplete="name" value="<?= farol_h($profile['full_name']) ?>" required>
<label for="cpf">CPF</label>
<input id="cpf" name="cpf" maxlength="14" inputmode="numeric" value="<?= farol_h($profile['cpf']) ?>" required>
<label for="sector">Setor</label>
<select id="sector" name="sector" required><option value="">Selecione</option>
<?php foreach (farol_sectors() as $id => $label): ?>
<option value="<?= $id ?>" <?= $profile['sector'] === $id ? 'selected' : '' ?>><?= farol_h($label) ?></option>
<?php endforeach; ?></select>
<label for="email">E-mail</label>
<input id="email" name="email" type="email" maxlength="50" autocomplete="username" value="<?= farol_h($profile['email']) ?>" required>
<small>Ao alterar o e-mail, todas as sessões serão encerradas. Será necessário confirmar o novo endereço antes de entrar novamente. Confira a digitação.</small>
<label for="profile-password">Senha atual</label>
<input id="profile-password" name="current_password" type="password" maxlength="128" autocomplete="current-password" required>
<button type="submit">Salvar dados</button>
</form></section>
<section aria-labelledby="password-title"><h2 id="password-title">Alterar senha</h2>
<p>Após a alteração, todas as sessões serão encerradas. Entre novamente com a nova senha.</p>
<form method="post" action="meu-cadastro.php">
<input type="hidden" name="csrf" value="<?= farol_h($csrf) ?>">
<input type="hidden" name="action" value="password">
<label for="current-password">Senha atual</label>
<input id="current-password" name="current_password" type="password" maxlength="128" autocomplete="current-password" required>
<label for="new-password">Nova senha</label>
<input id="new-password" name="new_password" type="password" minlength="8" maxlength="128" autocomplete="new-password" required>
<small>Use de 8 a 128 caracteres. Espaços são permitidos.</small>
<label for="password-confirmation">Confirme a nova senha</label>
<input id="password-confirmation" name="password_confirmation" type="password" minlength="8" maxlength="128" autocomplete="new-password" required>
<button type="submit">Alterar senha</button>
</form></section>
<?php endif; ?>
</body></html>
