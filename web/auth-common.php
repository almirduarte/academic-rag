<?php
declare(strict_types=1);
require_once __DIR__ . '/sectors.php';

header('Cache-Control: no-store');
header('Referrer-Policy: same-origin');
header('X-Content-Type-Options: nosniff');
ini_set('session.use_strict_mode', '1');
ini_set('session.use_only_cookies', '1');
session_name('farol_session');
session_set_cookie_params([
    'lifetime' => 0,
    'path' => '/',
    'secure' => true,
    'httponly' => true,
    'samesite' => 'Lax',
]);
session_start();
if (($_SESSION['auth']['expires_at'] ?? PHP_INT_MAX) <= time()) {
    unset($_SESSION['auth']);
}
if (!isset($_SESSION['csrf'])) {
    $_SESSION['csrf'] = bin2hex(random_bytes(32));
}

function farol_h(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function farol_csrf_valid(): bool
{
    return is_string($_POST['csrf'] ?? null)
        && hash_equals($_SESSION['csrf'], $_POST['csrf']);
}

function farol_ip(): string
{
    $ip = $_SERVER['REMOTE_ADDR'] ?? '';
    if (!filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4)) {
        throw new RuntimeException('Endereço IPv4 indisponível.');
    }
    return $ip;
}

function farol_api(string $route, array $payload, ?string $token = null, int $timeout = 30): array
{
    // Configuração fora do DocumentRoot: /home/USUARIO/farol-config.json.
    $root = realpath($_SERVER['DOCUMENT_ROOT'] ?? '');
    if ($root === false) {
        throw new RuntimeException('Diretório público indisponível.');
    }
    $path = getenv('FAROL_CONFIG_PATH') ?: dirname($root) . '/farol-config.json';
    if (!is_readable($path)) {
        throw new RuntimeException('Configuração indisponível.');
    }
    $config = json_decode(file_get_contents($path), true, 512, JSON_THROW_ON_ERROR);
    $key = $config['api_token'] ?? '';
    $url = rtrim($config['api_url'] ?? 'http://192.168.2.210:8000', '/');
    if (!is_string($key) || $key === '' || preg_match('/[\r\n]/', $key)) {
        throw new RuntimeException('Chave da API inválida.');
    }
    $headers = ['Content-Type: application/json', 'X-API-Key: ' . $key];
    if ($token !== null) {
        if (!preg_match('/^[A-Za-z0-9_-]{43}$/D', $token)) {
            throw new RuntimeException('Sessão inválida.');
        }
        $headers[] = 'Authorization: Bearer ' . $token;
    }
    $curl = curl_init($url . $route);
    if ($curl === false) {
        throw new RuntimeException('Não foi possível iniciar a conexão.');
    }
    curl_setopt_array($curl, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => json_encode($payload, JSON_THROW_ON_ERROR | JSON_UNESCAPED_UNICODE),
        CURLOPT_HTTPHEADER => $headers,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => min(10, $timeout),
        CURLOPT_TIMEOUT => $timeout,
        CURLOPT_FOLLOWLOCATION => false,
    ]);
    $body = curl_exec($curl);
    $errno = curl_errno($curl);
    $status = (int) curl_getinfo($curl, CURLINFO_HTTP_CODE);
    unset($curl);
    if ($body === false) {
        return ['status' => $errno === CURLE_OPERATION_TIMEDOUT ? 504 : 502,
            'data' => ['detail' => $errno === CURLE_OPERATION_TIMEDOUT
                ? 'O tempo de espera terminou. O servidor ainda pode estar processando a consulta.'
                : 'Não foi possível acessar a API. Tente novamente mais tarde.']];
    }
    $data = json_decode($body, true, 512, JSON_THROW_ON_ERROR);
    if (!is_array($data)) {
        throw new RuntimeException('Resposta inválida da API.');
    }
    return ['status' => $status, 'data' => $data];
}

function farol_error(array $response): string
{
    $status = $response['status'];
    if ($status === 422) {
        return 'Confira os campos: nome completo, e-mail válido (até 50 caracteres), CPF válido, setor e senha de 8 a 128 caracteres para cadastro.';
    }
    if (in_array($status, [400, 401, 403, 409, 429, 502, 504], true)
        && is_string($response['data']['detail'] ?? null)) {
        return $response['data']['detail'];
    }
    return 'Não foi possível concluir a operação (HTTP ' . $status . ').';
}


function farol_app_name(bool $refresh = true): string
{
    static $resolved = null;
    if ($resolved !== null) return $resolved;
    $cache = $_SESSION['app_identity'] ?? [];
    $name = is_string($cache['name'] ?? null) ? $cache['name'] : 'Farol Acadêmico';
    if (!$refresh || (int)($cache['checked_at'] ?? 0) > time() - 60) {
        return $resolved = $name;
    }
    try {
        $response = farol_api('/app/config', [], null, 2);
        $candidate = $response['data']['app_name'] ?? null;
        if ($response['status'] !== 200 || !is_string($candidate)
            || trim($candidate) === '' || strlen($candidate) > 480
            || preg_match('/[\x00-\x1F\x7F]/', $candidate)) {
            throw new RuntimeException('Nome da aplicação indisponível.');
        }
        $name = $candidate;
    } catch (Throwable $exception) {
        // Mantém o último nome conhecido ou o padrão; não bloqueia login.
        error_log('Aplicação: falha ao consultar identificação (' . get_class($exception) . ').');
    }
    if (session_status() === PHP_SESSION_ACTIVE) {
        $_SESSION['app_identity'] = ['name' => $name, 'checked_at' => time()];
    }
    return $resolved = $name;
}
