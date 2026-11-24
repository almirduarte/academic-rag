<?php
declare(strict_types=1);
// Função interna; não cria endpoint de upload público.
function farol_upload_document(array $file, array $metadata, string $token): array
{
    if (($file['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_OK
        || !is_string($file['tmp_name'] ?? null) || !is_uploaded_file($file['tmp_name'])) {
        throw new RuntimeException('Selecione um PDF de até 50 MiB. Confira também os limites de upload do PHP.');
    }
    $size = filesize($file['tmp_name']);
    if ($size === false || $size <= 0 || $size > 50 * 1024 * 1024) {
        throw new RuntimeException('O PDF deve ter até 50 MiB.');
    }
    $root = realpath($_SERVER['DOCUMENT_ROOT'] ?? '');
    if ($root === false) { throw new RuntimeException('Configuração indisponível.'); }
    $configPath = getenv('FAROL_CONFIG_PATH') ?: dirname($root) . '/farol-config.json';
    $config = json_decode(file_get_contents($configPath), true, 512, JSON_THROW_ON_ERROR);
    $key = $config['api_token'] ?? '';
    if (!is_string($key) || $key === '' || preg_match('/[\r\n]/', $key)
        || !preg_match('/^[A-Za-z0-9_-]{43}$/D', $token)) {
        throw new RuntimeException('Configuração de autenticação inválida.');
    }
    $url = rtrim($config['api_url'] ?? 'http://192.168.2.210:8000', '/');
    $handle = fopen($file['tmp_name'], 'rb');
    if ($handle === false) { throw new RuntimeException('Não foi possível ler o upload.'); }
    try {
        $curl = curl_init($url . '/documents/admin/upload?' . http_build_query($metadata, '', '&', PHP_QUERY_RFC3986));
        if ($curl === false) { throw new RuntimeException('cURL indisponível.'); }
        curl_setopt_array($curl, [
            CURLOPT_UPLOAD => true,
            CURLOPT_CUSTOMREQUEST => 'POST',
            CURLOPT_INFILE => $handle,
            CURLOPT_INFILESIZE => $size,
            CURLOPT_HTTPHEADER => ['Content-Type: application/pdf', 'X-API-Key: ' . $key, 'Authorization: Bearer ' . $token, 'Expect:'],
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_CONNECTTIMEOUT => 10,
            CURLOPT_TIMEOUT => 120,
        ]);
        $body = curl_exec($curl);
        $status = (int)curl_getinfo($curl, CURLINFO_HTTP_CODE);
        unset($curl);
        if ($body === false) { throw new RuntimeException('A transferência não foi confirmada. Atualize a lista de tarefas antes de repetir.'); }
        $data = json_decode($body, true, 512, JSON_THROW_ON_ERROR);
        return ['status' => $status, 'data' => $data];
    } finally { fclose($handle); }
}
