"""Adaptador BGE em CPU. Usa apenas pesos locais, sem download automático."""
import threading

from .core import check_lengths

MODEL = 'BAAI/bge-reranker-v2-m3'
REVISION = '953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e'
MAX_LENGTH = 4096
_lock = threading.RLock()
_model = None


def score_with_encoder(encoder, question, candidates, activation_fn, inference_context):
    pairs = [(question, c['passage']) for c in candidates]
    lengths = [len(encoder.tokenizer(q, p, truncation=False)['input_ids']) for q, p in pairs]
    # Confere TODOS os pares antes de começar; não corta alíneas silenciosamente.
    check_lengths(lengths, MAX_LENGTH)
    scores = []
    for pair in pairs:
        with inference_context():
            result = encoder.predict([pair], batch_size=1, show_progress_bar=False,
                                     activation_fn=activation_fn)
        scores.append(float(result.reshape(-1)[0]))
    return scores


def score_pairs(question, candidates):
    global _model
    # Serializa carga e inferência por processo. Cada worker mantém sua cópia.
    with _lock:
        import torch
        if _model is None:
            from sentence_transformers import CrossEncoder
            from huggingface_hub import snapshot_download
            torch.set_num_threads(2)
            try:
                path = snapshot_download(MODEL, revision=REVISION, local_files_only=True,
                    allow_patterns=['config.json', 'model.safetensors', 'tokenizer.json',
                                    'tokenizer_config.json', 'special_tokens_map.json',
                                    'sentencepiece.bpe.model', 'added_tokens.json'])
            except Exception as exc:
                raise RuntimeError(
                    'BGE na revisão testada não está disponível no cache deste usuário. '
                    'Nenhum download foi solicitado. Use o mesmo usuário/cache do teste BGE.'
                ) from exc
            _model = CrossEncoder(path, device='cpu', max_length=MAX_LENGTH,
                trust_remote_code=False, local_files_only=True,
                model_kwargs={'torch_dtype': torch.float32}, activation_fn=torch.nn.Identity())
            _model.eval()
        return score_with_encoder(_model, question, candidates, torch.nn.Identity(), torch.inference_mode)
