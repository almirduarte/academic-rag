<?php
require_once __DIR__ . '/auth-common.php';
if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST' || !farol_csrf_valid()) {
    http_response_code(403);
    exit('Solicitação inválida.');
}
try {
    if (isset($_SESSION['auth']['token'])) {
        $response = farol_api('/auth/logout', [], $_SESSION['auth']['token']);
        if ($response['status'] !== 200) {
            throw new RuntimeException('Não foi possível revogar a sessão.');
        }
    }
} catch (Throwable $e) {
    http_response_code(503);
    exit('Não foi possível encerrar a sessão no servidor. Volte à página e tente novamente.');
}
$_SESSION = [];
setcookie(session_name(), '', ['expires'=>time()-3600, 'path'=>'/', 'secure'=>true,
    'httponly'=>true, 'samesite'=>'Lax']);
session_destroy();
header('Location: login.php', true, 303);
exit;
