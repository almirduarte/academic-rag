<?php

require_once __DIR__ . '/auth-common.php';

$isPost = ($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST';
$isAjax = $isPost && ($_POST['ajax'] ?? '') === '1';

function farol_json(array $data, int $status = 200): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE);
    exit;
}

if (!isset($_SESSION['auth'])) {
    if ($isAjax) {
        farol_json(['error' => 'Sua sessão expirou. Atualize a página para entrar novamente.'], 401);
    }
    header('Location: login.php', true, 303);
    exit;
}

header('Cache-Control: no-store');
if (session_status() !== PHP_SESSION_ACTIVE) {
    session_start();
}
if (empty($_SESSION['csrf'])) {
    $_SESSION['csrf'] = bin2hex(random_bytes(32));
}
$csrf = $_SESSION['csrf'];
$auth = $_SESSION['auth'];
// Libera o bloqueio da sessão antes da chamada demorada à API.
$appName = farol_app_name(!$isAjax);
session_write_close();

function h(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

$question = '';
$result = null;
$error = null;
$status = 200;
$title = $appName;
$queryLength = 2000;
$outputLimitWarning = 'A resposta atingiu o limite de saída do modelo e pode estar incompleta. Itens ou explicações podem ter sido omitidos.';

if ($isPost) {
    $question = is_string($_POST['question'] ?? null) ? trim($_POST['question']) : '';
    $submittedCsrf = is_string($_POST['csrf'] ?? null) ? $_POST['csrf'] : '';

    if (!hash_equals($csrf, $submittedCsrf)) {
        $error = 'A sessão expirou. Atualize a página e tente novamente.';
        $status = 403;
    } elseif ($question === '' || mb_strlen($question, 'UTF-8') > $queryLength) {
        $error = 'Digite uma pergunta com até ' . strval($queryLength) . ' caracteres.';
        $status = 422;
    } elseif (!function_exists('curl_init')) {
        $error = 'A extensão cURL não está disponível no PHP.';
        $status = 500;
    } else {
        try {
            $response = farol_api('/ask', [
                'question' => $question,
                'ip_address' => farol_ip(),
            ], $auth['token'], 360);
            if ($response['status'] >= 200 && $response['status'] < 300
                && is_string($response['data']['answer'] ?? null)) {
                $result = $response['data'];
            } else {
                $status = $response['status'] >= 400 ? $response['status'] : 502;
                $error = $status === 401
                    ? 'Sua sessão expirou. Atualize a página e entre novamente.'
                    : farol_error($response);
                if ($status === 401) {
                    session_start();
                    unset($_SESSION['auth']);
                    session_write_close();
                }
            }
        } catch (Throwable $exception) {
            $status = 500;
            $error = 'Não foi possível preparar a consulta. Verifique a configuração e os dados do usuário no servidor.';
            error_log('Aplicação: falha na preparação da consulta (' . get_class($exception) . ').');
        }
    }
    if ($isAjax) {
        farol_json($error !== null ? ['error' => $error] : $result, $status);
    }
}
?>
<!doctype html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title><?= h($title) ?></title>
    <style>
        body { max-width: 900px; margin: 40px auto; padding: 0 20px; font: 16px Arial, sans-serif; color: #222; }
        textarea { box-sizing: border-box; width: 100%; min-height: 100px; padding: 10px; font: inherit; }
        button { margin-top: 10px; padding: 10px 18px; font: inherit; cursor: pointer; }
        button:disabled { cursor: wait; opacity: .6; }
        #interrupt { border: 1px solid #a33; color: #922; background: #fff; }
        .answer, .error { margin-top: 24px; padding: 16px; border: 1px solid #ccc; border-radius: 6px; }
        .warning { margin-bottom: 16px; padding: 12px; border: 1px solid #9c6b00; border-radius: 6px; background: #fff8df; color: #624300; }
        .error { border-color: #b00; color: #900; }
        .sources, .timings, #status { color: #555; font-size: 14px; }
        .answer-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
        #copy-answer { margin: 0; padding: 8px; background: #fff; color: #15516e; border: 1px solid #15516e; border-radius: 4px; }
        #copy-answer svg { display: block; }
        #copy-status { color: #555; font-size: 14px; }
        #answer-text { white-space: pre-wrap; overflow-wrap: anywhere; }
        .lighthouse { position: relative; }
        .lighthouse img { display: block; width: 100%; max-height: 280px; object-fit: cover; object-position: center; }
        .lighthouse.is-loading img { opacity: .3; }
        .loading-overlay { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; background: rgba(255, 255, 255, .25); }
        .spinner { width: 56px; height: 56px; border: 6px solid rgba(16, 66, 95, .2); border-top-color: #10425f; border-radius: 50%; animation: spin 1s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }
        @media (prefers-reduced-motion: reduce) { .spinner { animation: none; } }
        .character-count { margin: 4px 0 0; text-align: right; color: #555; font-size: 14px; }
        [hidden] { display: none !important; }
    </style>
</head>
<body>
    <div id="lighthouse" class="lighthouse">
        <img src="farolete-villegagnon.png" alt="Farolete da Ilha de Villegagnon, na Baía de Guanabara">
        <div id="loading-overlay" class="loading-overlay" aria-hidden="true" hidden>
            <span class="spinner"></span>
        </div>
    </div>
    <h1><?= h($title) ?></h1>
    <nav aria-label="Documentos de referência" style="margin:20px 0;padding:16px;border:1px solid #ccc;border-radius:6px;">
        <a href="documents.php" target="_blank" rel="noopener" style="display:inline-block;padding:10px 16px;border:1px solid #15516e;border-radius:4px;color:#15516e;">Consultar documentos disponíveis</a>
        <p style="margin:10px 0 0;font-size:14px;">Veja quais documentos estão carregados, abra ou baixe os PDFs. Abre em outra aba, preservando sua pergunta.</p>
    </nav>
    <p>Olá, <?= h($auth['user']['full_name']) ?>.</p>
    <p><a href="meu-cadastro.php">Meu cadastro e senha</a></p>
    <form method="post" action="logout.php" style="margin-bottom: 30px;">
        <input type="hidden" name="csrf" value="<?= h($csrf) ?>">
        <button type="submit">Sair</button>
    </form>
    <form id="question-form" method="post">
        <input type="hidden" name="csrf" value="<?= h($csrf) ?>">
        <label for="question">Sua pergunta</label>
        <textarea id="question" name="question" maxlength="<?php echo strval($queryLength)?>" aria-describedby="character-count" required><?= h($question) ?></textarea>
        <p id="character-count" class="character-count"><span id="characters-remaining"><?= max(0, $queryLength - mb_strlen($question, 'UTF-8')) ?></span> caracteres disponíveis</p>
        <button id="consult" type="submit">Consultar</button>
        <button id="interrupt" type="button" hidden>Interromper consulta</button>
    </form>
    <p id="status" role="status" aria-live="polite"></p>
    <noscript>Ative o JavaScript para interromper a espera sem sair da página.</noscript>
    <div id="error" class="error" role="alert" <?= $error === null ? 'hidden' : '' ?>><?= h($error ?? '') ?></div>
    <section id="answer" class="answer" aria-labelledby="answer-heading" <?= !is_array($result) ? 'hidden' : '' ?>>
        <div class="answer-header">
            <h2 id="answer-heading">Resposta</h2>
            <button id="copy-answer" type="button" title="Copiar resposta" aria-label="Copiar resposta" aria-describedby="copy-status" hidden>
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true" focusable="false">
                    <rect x="8" y="8" width="12" height="13" rx="2"/>
                    <path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>
                </svg>
            </button>
        </div>
        <p id="copy-status" role="status" aria-live="polite"></p>
        <div id="output-limit-warning" class="warning" role="status" <?= ($result['output_limit_reached'] ?? false) === true ? '' : 'hidden' ?>><?= h($outputLimitWarning) ?></div>
        <div id="answer-text"><?= h($result['answer'] ?? '') ?></div>
        <h3 id="sources-heading">Fontes</h3>
        <ul id="sources" class="sources">
            <?php foreach (($result['sources'] ?? []) as $source): ?>
                <li><?= h((string)($source['file'] ?? '')) ?>, trecho <?= h((string)($source['chunk'] ?? '')) ?></li>
            <?php endforeach; ?>
        </ul>
        <p id="timings" class="timings"><?php if (isset($result['timings_seconds']['total'])): ?>Tempo total: <?= h((string)$result['timings_seconds']['total']) ?> s<?php endif; ?></p>
    </section>
    <script src="answer-copy.js?v=1" defer></script>
    <script>
    (() => {
        'use strict';
        const form = document.getElementById('question-form');
        const question = document.getElementById('question');
        const consult = document.getElementById('consult');
        const interrupt = document.getElementById('interrupt');
        const status = document.getElementById('status');
        const error = document.getElementById('error');
        const answer = document.getElementById('answer');
        const outputLimitWarning = document.getElementById('output-limit-warning');
        const lighthouse = document.getElementById('lighthouse');
        const loadingOverlay = document.getElementById('loading-overlay');
        const remaining = document.getElementById('characters-remaining');
        let active = null;

        function updateCharacterCount() {
            remaining.textContent = String(Math.max(0, question.maxLength - question.value.length));
        }
        question.addEventListener('keyup', updateCharacterCount);
        question.addEventListener('input', updateCharacterCount);
        updateCharacterCount();

        function busy(value) {
            lighthouse.classList.toggle('is-loading', value);
            loadingOverlay.hidden = !value;
            consult.disabled = value;
            consult.textContent = value ? 'Consultando…' : 'Consultar';
            interrupt.hidden = !value;
            question.readOnly = value;
            form.setAttribute('aria-busy', String(value));
        }

        function render(data) {
            if (!data || typeof data.answer !== 'string') {
                throw new Error('O servidor retornou uma resposta inválida.');
            }
            document.getElementById('answer-text').textContent = data.answer;
            outputLimitWarning.hidden = data.output_limit_reached !== true;
            const sources = document.getElementById('sources');
            sources.replaceChildren();
            for (const source of (Array.isArray(data.sources) ? data.sources : [])) {
                if (!source || typeof source !== 'object') continue;
                const li = document.createElement('li');
                li.textContent = `${source.file ?? ''}, trecho ${source.chunk ?? ''}`;
                sources.append(li);
            }
            document.getElementById('sources-heading').hidden = sources.childElementCount === 0;
            const total = data.timings_seconds?.total;
            document.getElementById('timings').textContent =
                total === undefined || total === null ? '' : `Tempo total: ${total} s`;
            answer.hidden = false;
        }

        interrupt.addEventListener('click', () => {
            if (!active) return;
            const cancelled = active;
            active = null; // Impede que uma resposta antiga altere a próxima consulta.
            cancelled.abort();
            busy(false);
            status.textContent = 'Espera interrompida. O servidor ainda pode estar processando a consulta anterior.';
            question.focus();
        });

        form.addEventListener('submit', async event => {
            event.preventDefault();
            updateCharacterCount();
            if (active || !form.reportValidity()) return;
            if (question.value.length > question.maxLength) {
                error.textContent = 'Digite uma pergunta com até ' + question.maxLength + ' caracteres.';
                error.hidden = false;
                question.focus();
                return;
            }
            if (!question.value.trim()) {
                error.textContent = 'Digite uma pergunta.';
                error.hidden = false;
                question.focus();
                return;
            }
            const controller = new AbortController();
            active = controller;
            const body = new FormData(form);
            body.set('ajax', '1');
            error.hidden = true;
            answer.hidden = true;
            outputLimitWarning.hidden = true;
            busy(true);
            status.textContent = 'Consultando os documentos. Aguarde…';
            try {
                const response = await fetch(window.location.pathname, {
                    method: 'POST', body, signal: controller.signal,
                    credentials: 'same-origin', cache: 'no-store',
                    headers: { 'Accept': 'application/json' },
                });
                if (active !== controller) return;
                if (response.redirected) {
                    throw new Error('Sua sessão pode ter expirado. Atualize a página para entrar novamente.');
                }
                if (!(response.headers.get('Content-Type') || '').includes('application/json')) {
                    throw new Error(response.status === 504
                        ? 'O servidor web excedeu o tempo de espera. A consulta ainda pode estar em processamento.'
                        : 'O servidor não retornou a resposta esperada. Atualize a página e verifique sua sessão.');
                }
                const data = await response.json();
                if (active !== controller) return;
                if (!response.ok || data?.error) {
                    throw new Error(typeof data?.error === 'string' ? data.error : `Falha na consulta (HTTP ${response.status}).`);
                }
                render(data);
                status.textContent = data.output_limit_reached === true
                    ? 'Consulta concluída com aviso de resposta possivelmente incompleta.'
                    : 'Consulta concluída.';
            } catch (exception) {
                if (active !== controller) return;
                status.textContent = '';
                error.textContent = exception instanceof TypeError
                    ? 'Não foi possível concluir a comunicação com o servidor.'
                    : (exception.message || 'Não foi possível concluir a consulta.');
                error.hidden = false;
            } finally {
                if (active === controller) {
                    active = null;
                    busy(false);
                }
            }
        });
    })();
    </script>
</body>
</html>
