"""Local acceptance harness. Temporary SQLite, InMemory repository, loopback only.
Run: .venv/bin/python -m integration_tests.thoma_local
Never uses a remote repository; restarting discards all test data.
"""
import json
import os
from pathlib import Path
import tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Lock
from urllib.parse import urlparse, parse_qs, unquote
import secrets
import argparse
from dataclasses import replace
from unittest.mock import patch

work = tempfile.TemporaryDirectory()
os.environ['DATABASE_URL'] = f'sqlite:///{work.name}/browser.sqlite3'
os.environ['COOKIE_SECURE'] = 'false'
from backend.auth.service import create_user
from backend.database import Base, SessionLocal, engine
from backend.main import create_app
from backend.models import ModuleAccess
from backend.github.repository import InMemoryGitRepository
from backend.records.module_index import make_index, dump_index
from backend.modules import get_module
from fastapi.testclient import TestClient
module = get_module('sammlung_thoma')
app=create_app()
repo=InMemoryGitRepository({module.storage['state']['path']:json.dumps({'next_record_id':1,'next_signature_number':{'A':1}}), module.storage['index']['path']:dump_index(make_index(module,[]))})
app.state.data_repository=repo
test_modules=[get_module(key) for key in ('sammlung_thoma','autographen_9_6','foto_papierabzuege')]
for definition in test_modules:
    repo.files.setdefault(definition.storage['state']['path'], json.dumps({'next_record_id':1,'next_signature_number':{key:1 for key in definition.signature_strategy['partitions']}}))
    if definition.storage.get('index'):
        repo.files.setdefault(definition.storage['index']['path'],dump_index(make_index(definition,[])))
app.state.generic_write_modules={definition.access_key for definition in test_modules}
Base.metadata.create_all(bind=engine)
test_password=secrets.token_urlsafe(24)
with SessionLocal() as db:
    user=create_user(db,username='local-test',display_name='Local Test',email='local@example.test',role='redaktion',ui_profile='redaktion',modules=['foto_papierabzuege'],password=test_password)
    user.module_access.clear();db.flush();user.module_access.extend(ModuleAccess(module_key=definition.access_key) for definition in test_modules);db.commit()
client=TestClient(app)
client.post('/api/auth/login',json={'login':'local-test','password':test_password})

csrf_name=client.get('/api/auth/me').json()['csrf_cookie_name']
ROOT=str(Path(__file__).resolve().parents[1])
hold_next=False
release=Event()
control_lock=Lock()
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=ROOT,**kwargs)
    def api(self):
        global hold_next
        if self.path.startswith('/test-control'):
            query=parse_qs(urlparse(self.path).query)
            with control_lock:
                if query.get('hold') == ['1']:
                    hold_next=True
                    release.clear()
                if query.get('release') == ['1']:
                    release.set()
            self.send_response(200);self.end_headers();self.wfile.write(b'OK');return
        delayed=False
        if self.command in ('POST','PUT') and '/records' in self.path:
            with control_lock:
                delayed=hold_next
                hold_next=False

        if self.path == '/test-state':
            data={'contents':dict(repo.files),'state':json.loads(repo.files[module.storage['state']['path']]),'files':list(repo.files),'commits':len(repo.commits)}
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(data).encode());return
        body=self.rfile.read(int(self.headers.get('Content-Length','0')))
        headers={}
        if 'X-CSRF-Token' in self.headers:headers['X-CSRF-Token']=self.headers['X-CSRF-Token']
        response=client.request(self.command,self.path,content=body,headers={**headers,'Content-Type':'application/json'})
        if delayed: release.wait(300)
        self.send_response(response.status_code);self.send_header('Content-Type','application/json')
        self.send_header('Set-Cookie',f'{csrf_name}={client.cookies.get(csrf_name)}; Path=/')
        self.end_headers();self.wfile.write(response.content)
    def do_GET(self):
        if self.path.startswith('/api/') or self.path=='/test-state' or self.path.startswith('/test-control'):self.api()
        elif (Path(ROOT) / unquote(urlparse(self.path).path).lstrip('/')).resolve().is_relative_to(Path(ROOT) / 'app'):
            super().do_GET()
        else:
            self.send_error(404)
    def do_POST(self):self.api()
    def do_PUT(self):self.api()
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port', type=int, default=8798)
port=parser.parse_args().port
print(f'Thoma-Testmaske: http://127.0.0.1:{port}/app/module/?module=sammlung_thoma&new=1', flush=True)
ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()
