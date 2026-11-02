"""New acceptance boundaries: OS process restart and real HTTP decision replay."""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from productivity_agent.api.app import create_app

WORKER = Path(__file__).parent / 'helpers' / 'approval_worker.py'


@pytest.mark.parametrize('approved', [True, False])
def test_http_checkpoint_survives_three_os_processes(tmp_path, approved):
    def run(mode, *args):
        env = dict(os.environ, PPA_ENABLE_LIVE_QWEN='0', DASHSCOPE_API_KEY='',
                   LANGSMITH_TRACING='false')
        child = subprocess.run([sys.executable, str(WORKER), str(tmp_path), mode, *args],
                               env=env, check=False, capture_output=True, text=True, timeout=30)
        assert child.returncode == 0, child.stderr
        return json.loads(child.stdout)

    first = run('create')
    tid = first['thread_id']
    assert first['tasks']['count'] == 0
    assert first['approval']['operation_id'] != tid
    second = run('approve' if approved else 'reject', tid)
    assert second['before']['status'] == 'awaiting_approval'
    expected = 'created' if approved else 'cancelled'
    assert second['decision']['status'] == expected
    third = run('verify', tid)
    assert third['before']['status'] == expected
    assert third['replay_status'] == 409
    assert third['unknown_thread'] == 404
    assert third['tasks']['count'] == int(approved)
    assert third['tasks'] == second['tasks']
    assert all(r['pid'] != os.getpid() for r in [first, second, third])
    if approved:
        assert third['tasks']['items'][0]['id'] == second['decision']['task']['id']


def test_real_http_concurrent_decisions_and_distinct_drafts(tmp_path, monkeypatch):
    monkeypatch.setenv('PPA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('PPA_ENABLE_LIVE_QWEN', '0')
    with TestClient(create_app(api_token='')) as api:
        payload = {'title': 'same payload', 'due_at': '2026-12-10T15:00:00+08:00'}
        drafts = [api.post('/v1/tasks/drafts', json=payload) for _ in range(2)]
        assert [r.status_code for r in drafts] == [201, 201]
        a, b = [r.json() for r in drafts]
        assert a['thread_id'] != b['thread_id']
        assert a['approval']['operation_id'] != b['approval']['operation_id']
        assert api.get('/v1/tasks').json()['count'] == 0

        def approve(_):
            return api.post(f"/v1/tasks/drafts/{a['thread_id']}/decision",
                            json={'approved': True})

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(approve, range(2)))
        assert sorted(r.status_code for r in responses) == [200, 409]
        assert api.get('/v1/tasks').json()['count'] == 1
        assert api.get(f"/v1/tasks/drafts/{b['thread_id']}").json()['status'] == 'awaiting_approval'
        assert api.post(f"/v1/tasks/drafts/{b['thread_id']}/decision",
                        json={'approved': False}).json()['status'] == 'cancelled'
        assert api.get('/v1/tasks').json()['count'] == 1
