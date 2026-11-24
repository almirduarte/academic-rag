<?php
declare(strict_types=1);
require_once __DIR__ . '/auth-common.php';
if (!isset($_SESSION['auth'])) {
    header('Location: login.php', true, 303);
    exit;
}
$auth = $_SESSION['auth'];
session_write_close();
$id = filter_var($_GET['id'] ?? null, FILTER_VALIDATE_INT, ['options' => ['min_range' => 1]]);
$mode = $_GET['mode'] ?? 'attachment';
if ($id === false || !in_array($mode, ['inline', 'attachment'], true)) {
    http_response_code(400);
    exit('Documento inválido.');
}
$temp = null;
try {
    // Mesmo arquivo privado de configuração utilizado por auth-common.php.
    $root = realpath($_SERVER['DOCUMENT_ROOT'] ?? '');
    if ($root === false) {
        throw new RuntimeException('Configuração indisponível.');
    }
    $configPath = getenv('FAROL_CONFIG_PATH') ?: dirname($root) . '/farol-config.json';
    $config = json_decode(file_get_contents($configPath), true, 512, JSON_THROW_ON_ERROR);
    $key = $config['api_token'] ?? '';
    $url = rtrim($config['api_url'] ?? 'http://192.168.2.210:8000', '/');
    $token = $auth['token'] ?? '';
    if (!is_string($key) || $key === '' || preg_match('/[\r\n]/', $key)
        || !is_string($token) || !preg_match('/^[A-Za-z0-9_-]{43}$/D', $token)) {
        throw new RuntimeException('Credenciais inválidas.');
    }
    $temp = tmpfile();
    if ($temp === false) {
        throw new RuntimeException('Arquivo temporário indisponível.');
    }
    $bytes = 0;
    $dispositionHeader = null;
    $curl = curl_init($url . '/documents/download');
    if ($curl === false) {
        throw new RuntimeException('cURL indisponível.');
    }
    curl_setopt_array($curl, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => json_encode(['id' => $id, 'disposition' => $mode], JSON_THROW_ON_ERROR),
        CURLOPT_HTTPHEADER => ['Content-Type: application/json', 'X-API-Key: ' . $key, 'Authorization: Bearer ' . $token],
        CURLOPT_FOLLOWLOCATION => false,
        CURLOPT_CONNECTTIMEOUT => 10,
        CURLOPT_TIMEOUT => 120,
        CURLOPT_HEADERFUNCTION => static function ($handle, string $line) use (&$dispositionHeader): int {
            if (stripos($line, 'Content-Disposition:') === 0) {
                $value = trim(substr($line, strlen('Content-Disposition:')));
                if (!preg_match('/[\r\n]/', $value)
                    && preg_match('/^(inline|attachment);/i', $value)) {
                    $dispositionHeader = $value;
                }
            }
            return strlen($line);
        },
        CURLOPT_WRITEFUNCTION => static function ($handle, string $data) use ($temp, &$bytes): int {
            $bytes += strlen($data);
            if ($bytes > 50 * 1024 * 1024) {
                return 0;
            }
            $written = fwrite($temp, $data);
            return $written === false ? 0 : $written;
        },
    ]);
    $ok = curl_exec($curl);
    $status = (int)curl_getinfo($curl, CURLINFO_HTTP_CODE);
    $contentType = (string)curl_getinfo($curl, CURLINFO_CONTENT_TYPE);
    unset($curl);
    if ($ok === false) {
        throw new RuntimeException('Falha na transferência.');
    }
    if ($status === 401) {
        header('Location: login.php', true, 303);
        exit;
    }
    if (in_array($status, [404, 409], true)) {
        http_response_code($status);
        header('Content-Type: text/plain; charset=utf-8');
        exit('Documento indisponível ou alterado. Solicite a conferência ao administrador.');
    }
    if ($status !== 200 || strtolower(explode(';', $contentType)[0]) !== 'application/pdf') {
        throw new RuntimeException('Resposta documental inválida.');
    }
    rewind($temp);
    if (fread($temp, 5) !== '%PDF-') {
        throw new RuntimeException('Resposta não contém PDF.');
    }
    rewind($temp);
    header('Content-Type: application/pdf');
    header('Content-Disposition: ' . ($dispositionHeader ?? ($mode . '; filename="documento-' . $id . '.pdf"')));
    header('Content-Length: ' . $bytes);
    header('Cache-Control: no-store');
    header('X-Content-Type-Options: nosniff');
    fpassthru($temp);
} catch (Throwable $exception) {
    error_log('Farol: falha ao acessar original (' . get_class($exception) . ').');
    http_response_code(502);
    header('Content-Type: text/plain; charset=utf-8');
    echo 'Não foi possível acessar o documento. Tente novamente mais tarde.';
} finally {
    if (is_resource($temp)) {
        fclose($temp);
    }
}
