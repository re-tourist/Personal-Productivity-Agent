"""A fresh OS process running the real FastAPI/AsyncSqliteSaver integration."""
import json
import os
import sys

from fastapi.testclient import TestClient

from productivity_agent.api.app import create_app

os.environ['PPA_ENABLE_LIVE_QWEN'] = '0'
os.environ['DASHSCOPE_API_KEY'] = ''
os.environ['PPA_DATA_DIR'] = sys.argv[1]
mode = sys.argv[2]
with TestClient(create_app(api_token='')) as api:
    if mode == 'create':
        response = api.post('/v1/tasks/drafts', json={
            'title': 'subprocess acceptance', 'due_at': '2026-12-10T15:00:00+08:00',
        })
        assert response.status_code == 201, response.text
        result = response.json()
    else:
        tid = sys.argv[3]
        before = api.get(f'/v1/tasks/drafts/{tid}')
        assert before.status_code == 200, before.text
        result = {'before': before.json()}
        if mode in {'approve', 'reject'}:
            response = api.post(f'/v1/tasks/drafts/{tid}/decision',
                                json={'approved': mode == 'approve'})
            assert response.status_code == 200, response.text
            result['decision'] = response.json()
        if mode == 'verify':
            result['replay_status'] = api.post(
                f'/v1/tasks/drafts/{tid}/decision', json={'approved': True}
            ).status_code
        result['unknown_thread'] = api.get('/v1/tasks/drafts/unknown-thread').status_code
    result['tasks'] = api.get('/v1/tasks').json()
    result['pid'] = os.getpid()
print(json.dumps(result))
