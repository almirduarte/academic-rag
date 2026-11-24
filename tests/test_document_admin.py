"""Testes isolados: HTTP real em TestClient; PostgreSQL/embeddings simulados.
Execute: python -m unittest discover -s tests -p test_document_admin.py -v
"""
import ast
from contextlib import contextmanager
import hashlib
import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]

def functions(file,names,namespace):
    tree=ast.parse((ROOT/'app'/file).read_text())
    nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
    for n in nodes:
        if n.name!='require_admin': n.decorator_list=[]
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),file,'exec'),namespace)
    return namespace

class UploadTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.user={'use_id':1,'use_admin':True}
        def current_user(): return self.user
        ns={'Depends':Depends,'current_user':current_user,'HTTPException':HTTPException}
        functions('auth.py',{'require_admin'},ns)
        class UniqueViolation(Exception): pass
        def file_info(path):
            data=path.read_bytes()
            if not data.startswith(b'%PDF-'): raise ValueError('PDF inválido')
            return len(data),hashlib.sha256(data).hexdigest()
        self.calls=[]
        ns.update(Path=Path,uuid=uuid,re=re,JOBS_DIR=Path(self.temp.name),MAX_BYTES=100,
            Request=Request,Query=Query,UniqueViolation=UniqueViolation,file_info=file_info,
            add_job=lambda *a:self.calls.append(a))
        functions('document_admin.py',{'valid_source','job_path','upload'},ns)
        self.ns=ns
        app=FastAPI();app.post('/upload',status_code=202)(ns['upload'])
        self.client=TestClient(app);self.addCleanup(self.client.close)
    def send(self,**params):
        values=dict(operation='include',source_file='teste.pdf',title='Teste');values.update(params)
        return self.client.post('/upload',params=values,content=b'%PDF-teste')
    def test_admin_upload_queues_without_publishing(self):
        self.assertEqual(self.send().status_code,202); self.assertEqual(len(self.calls),1)
        self.assertEqual(len(list(Path(self.temp.name).glob('*.pdf'))),1)
    def test_regular_user_rejected_before_file_creation(self):
        self.user['use_admin']=False
        self.assertEqual(self.send().status_code,403);self.assertFalse(list(Path(self.temp.name).iterdir()))
    def test_permission_revocation_applies_next_request(self):
        self.assertEqual(self.send().status_code,202);self.user['use_admin']=False
        self.assertEqual(self.send().status_code,403);self.assertEqual(len(self.calls),1)
    def test_path_traversal_rejected(self):
        self.assertEqual(self.send(source_file='../teste.pdf').status_code,422);self.assertFalse(self.calls)
    def test_replace_requires_document(self):
        self.assertEqual(self.send(operation='replace').status_code,422)
    def test_invalid_pdf_removed(self):
        r=self.client.post('/upload',params=dict(operation='include',source_file='a.pdf',title='A'),content=b'invalid')
        self.assertEqual(r.status_code,422);self.assertFalse(list(Path(self.temp.name).iterdir()))
    def test_oversize_removed(self):
        self.ns['MAX_BYTES']=3
        self.assertEqual(self.send().status_code,413);self.assertFalse(list(Path(self.temp.name).iterdir()))

class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.old=self.root/'old.pdf';self.old.write_bytes(b'%PDF-old')
        self.ident=uuid.uuid4(); self.pdf=self.root/(self.ident.hex+'.pdf');self.pdf.write_bytes(b'%PDF-new')
        prepared={'replacement':{'source_file':'new.pdf','chunks':[{'chunk_index':0,'content':'new','embedding':[1]}],
                   'summaries':[{'summary_type':'work','book_number':None,'content':'new','embedding':[1]}]},
                   'metadata':{'embedding_model':'test'}}
        blob=json.dumps(prepared).encode();(self.root/(self.ident.hex+'.json')).write_bytes(blob)
        self.job=dict(job_id=self.ident,operation='replace',prepared_sha256=hashlib.sha256(blob).hexdigest(),
            upload_sha256=hashlib.sha256(self.pdf.read_bytes()).hexdigest(),source_file='new.pdf',title='New',
            document_id=1,expected_source='old.pdf',expected_revision=1,expected_fingerprint='same',requested_by=1)
        self.sql=[];self.admin=True;self.state='publishing';self.revision=1;self.fail_insert=False;self.fail_commit=False
        self.committed=False;self.rolled=False
        owner=self
        class Cursor:
            def __enter__(self): return self
            def __exit__(self,*a): pass
            def execute(self,sql,args=None): owner.sql.append(sql);self.last=sql
            def fetchone(self):
                if 'SELECT state' in self.last:return (owner.state,)
                if '.users WHERE' in self.last:return (1,) if owner.admin else None
                if 'SELECT source_file,revision' in self.last:return ('old.pdf',owner.revision,'old.pdf')
                return None
        class Conn:
            def cursor(self):return Cursor()
            def commit(self):
                if owner.fail_commit: raise OSError('lost acknowledgement')
                owner.committed=True
            def rollback(self):owner.rolled=True
        @contextmanager
        def get_conn(): yield Conn()
        def insert(*a,**kw):
            if owner.fail_insert:raise RuntimeError('insert failed')
        def file_info(p):return p.stat().st_size,hashlib.sha256(p.read_bytes()).hexdigest()
        ns=dict(hashlib=hashlib,json=json,uuid=uuid,shutil=shutil,os=__import__('os'),
            DATA_DIR=self.root,job_path=lambda ident,s:self.root/(uuid.UUID(str(ident)).hex+s),
            settings=SimpleNamespace(embedding_model='test',embedding_dimensions=1),validate=lambda *a:None,
            file_info=file_info,get_conn=get_conn,CATALOG_LOCK=1,snapshot=lambda *a:None,fingerprint=lambda x:'same',
            original_path=lambda x:self.old,execute_values=insert,_vector_literal=str,log=logging.getLogger('tests'))
        self.ns=functions('document_worker.py',{'authorized','publish'},ns)
    def run_publish(self):self.ns['publish'](self.job)
    def test_success_replaces_then_removes_old_file(self):
        self.run_publish();self.assertTrue(self.committed);self.assertFalse(self.old.exists())
        self.assertTrue((self.root/'_managed'/f'{self.ident.hex}.pdf').exists())
        self.assertEqual(self.job['document_id'],1)
    def test_insert_failure_keeps_original(self):
        self.fail_insert=True
        with self.assertRaises(RuntimeError):self.run_publish()
        self.assertTrue(self.rolled);self.assertTrue(self.old.exists());self.assertFalse(self.committed)
    def test_unknown_commit_outcome_preserves_both_files(self):
        self.fail_commit=True
        with self.assertRaises(OSError):self.run_publish()
        self.assertTrue(self.old.exists());self.assertTrue((self.root/'_managed'/f'{self.ident.hex}.pdf').exists())
    def test_revoked_permission_prevents_database_delete(self):
        self.admin=False
        with self.assertRaises(ValueError):self.run_publish()
        self.assertFalse(any(s.startswith('DELETE') for s in self.sql));self.assertTrue(self.old.exists())
    def test_changed_revision_prevents_database_delete(self):
        self.revision=2
        with self.assertRaises(ValueError):self.run_publish()
        self.assertFalse(any(s.startswith('DELETE') for s in self.sql))
    def test_cancelled_or_interrupted_job_cannot_publish(self):
        self.state='failed'
        with self.assertRaises(ValueError):self.run_publish()
        self.assertFalse(any(s.startswith('DELETE') for s in self.sql))
    def test_tampered_preparation_rejected(self):
        self.job['prepared_sha256']='wrong'
        with self.assertRaises(ValueError):self.run_publish()
        self.assertFalse(self.sql)
    def test_delete_removes_original_only_after_commit(self):
        self.job['operation']='delete';self.job['source_file']='old.pdf'
        self.run_publish();self.assertTrue(self.committed);self.assertFalse(self.old.exists())

class PatchTests(unittest.TestCase):
    def test_prompt_preserved_and_patch_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'app').mkdir()
            before='PROMPT = "meu prompt atual"\ndef run_query(question):\n    return PROMPT\n'
            p=root/'app/query.py';p.write_text(before)
            script=ROOT/'tools/patch_query_lock.py'
            subprocess.run([sys.executable,str(script)],cwd=root,check=True,capture_output=True)
            after=p.read_bytes()
            self.assertIn('PROMPT = "meu prompt atual"',p.read_text())
            self.assertEqual((root/'app/query.py.before-document-admin').read_text(),before)
            subprocess.run([sys.executable,str(script)],cwd=root,check=True,capture_output=True)
            self.assertEqual(p.read_bytes(),after)

if __name__=='__main__':unittest.main()
