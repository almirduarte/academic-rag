"""Testes isolados: não conectam ao PostgreSQL, Ollama ou SMTP."""
import importlib
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch, MagicMock

from app.retrieval_sections import rebuild_sections, build_section_context
from app.diagnostico_busca import budget_pack, estimate, fuse
from app.document_text import make_chunks


def rows(text, size=220, overlap=80, source='teste.pdf'):
    return [dict(c, source_file=source) for c in make_chunks(text, size, overlap)]


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.section = ('5.4. MILITARES ESTRANGEIROS a) Regras gerais. '
            'f) Em função de dificuldades de língua, poderão ser aplicadas condições especiais. '
            + ''.join(f'I) Avaliação {n}: tempo adicional condicionado ao pedido. ' for n in range(12))
            + ''.join(f'II) Situação {n}: repetência em anos distintos. ' for n in range(10)))
        self.document = '3.11. CLASSIFICAÇÃO a) Ordem por países. ' + self.section + '5.5. OUTRAS FORÇAS a) Outra regra.'

    def test_roundtrip_preserves_condition_and_continuation(self):
        sections, warnings = rebuild_sections(rows(self.document))
        foreign = next(s for s in sections if s['section'] == '5.4')
        self.assertEqual(foreign['content'], self.section.strip())
        self.assertEqual(warnings, [])
        self.assertGreater(len(foreign['source_chunks']), 2)
        self.assertNotIn('OUTRAS FORÇAS', foreign['content'])

    def test_budget_excludes_whole_section_instead_of_truncating(self):
        sections, _ = rebuild_sections(rows(self.document))
        selected, excluded = budget_pack(sections, build_section_context, 'pergunta', 'instruções',
            220, 40, 20, 3, 20)
        self.assertFalse(any(s['section'] == '5.4' for s in selected))
        self.assertTrue(any(s['section'] == '5.4' for s in excluded))
        self.assertLessEqual(estimate('pergunta', build_section_context(selected), 'instruções', 3) + 60, 220)

    def test_gap_marks_unclosed_section(self):
        chunks = rows(self.document)
        del chunks[3]
        sections, warnings = rebuild_sections(chunks)
        self.assertTrue(warnings)
        self.assertTrue(any(not s['complete_boundary'] for s in sections))

    def test_no_overlap_does_not_join_arbitrary_text(self):
        chunks = [dict(source_file='a', chunk_index=0, content='1. INTRODUÇÃO a) Texto inicial.'),
                  dict(source_file='a', chunk_index=1, content='2. REGRAS a) Texto seguinte.')]
        sections, warnings = rebuild_sections(chunks)
        self.assertFalse(sections[0]['complete_boundary'])
        self.assertTrue(warnings)

    def test_same_indexes_in_different_documents_are_independent(self):
        sections, _ = rebuild_sections(rows(self.document, source='a.pdf') + rows(self.document, source='b.pdf'))
        self.assertEqual(len([s for s in sections if s['section'] == '5.4']), 2)
        ranked = fuse(sections, [])
        self.assertEqual(len(ranked), len(sections))

    def test_titles_missing_is_reported(self):
        sections, warnings = rebuild_sections(rows('Texto sem títulos numerados. ' * 30))
        self.assertEqual(sections, [])
        self.assertTrue(warnings)

    def test_ambiguous_overlap_is_not_guessed(self):
        sections, warnings = rebuild_sections(rows('1. REGRAS a) ' + 'Texto repetido sem variação. ' * 30))
        self.assertTrue(any('ambígua' in w for w in warnings))

    def test_subsections_and_references(self):
        text = '5.3. REGRAS a) Conforme art. 4.6, alínea y. 5.3.1. ASPIRANTES a) Regra. 5.4. ESTRANGEIROS a) Regra.'
        sections, _ = rebuild_sections(rows(text))
        self.assertEqual([s['section'] for s in sections], ['5.3', '5.3.1', '5.4'])


class IdentityTests(unittest.TestCase):
    def test_name_normalization_default_and_limit(self):
        from app.config import configured_app_name
        for value, expected in [('  ', 'Farol Acadêmico'), (' Acervo  Naval ', 'Acervo Naval'), ('Pesquisa & Ensino <EN>', 'Pesquisa & Ensino <EN>')]:
            with patch.dict(os.environ, APP_NAME=value):
                self.assertEqual(configured_app_name(), expected)
        with patch.dict(os.environ, APP_NAME='x' * 121):
            with self.assertRaises(ValueError):
                configured_app_name()

    def test_confirmation_uses_name_without_sending(self):
        stub = types.ModuleType('app.db')
        stub.get_conn = MagicMock(side_effect=AssertionError('Banco não deve ser acessado'))
        with patch.dict(sys.modules, {'app.db': stub}):
            sys.modules.pop('app.email_verification', None)
            mod = importlib.import_module('app.email_verification')
        config = types.SimpleNamespace(app_name='Acervo & Pesquisa', public_url='https://example.test',
            smtp_host='smtp.example.test', smtp_from='no-reply@example.test', smtp_security='starttls',
            smtp_port=587, smtp_user='', smtp_password='')
        with patch.object(mod, 'settings', config), patch.object(mod.smtplib, 'SMTP') as smtp:
            mod.send_confirmation('test@example.test', 'dummy-token')
            msg = smtp.return_value.send_message.call_args.args[0]
            self.assertEqual(str(msg['Subject']), 'Acervo & Pesquisa — confirme seu e-mail')
            self.assertIn('Acervo & Pesquisa', msg.get_content())
            self.assertNotIn('Farol Acadêmico', msg.get_content())


if __name__ == '__main__':
    unittest.main()
