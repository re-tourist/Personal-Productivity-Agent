"""SSE error contracts with real ToolNode; real TCP disconnect cancellation."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool

from productivity_agent.api.app import create_app
from productivity_agent.tools.productivity import MockProductivityBackend
from productivity_agent.workflows.tool_agent import build_tool_agent

QUERY = {'message': 'offline test', 'reference_now': '2026-11-02T12:00:00+08:00'}


class ScriptedModel:
    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        if any(isinstance(m, ToolMessage) for m in messages):
            return AIMessage(content='observed local tool result')
        return AIMessage(content='', tool_calls=[{
            'name': 'probe', 'args': {}, 'id': 'offline-1', 'type': 'tool_call',
        }])


@pytest.mark.parametrize('fail', [False, True])
def test_real_toolnode_sse_done_or_sanitized_error(fail):
    @tool
    def probe() -> str:
        """Read a synthetic value for offline stream verification."""
        if fail:
            raise RuntimeError('synthetic-private-marker')
        return 'local result'

    graph = build_tool_agent(ScriptedModel(), MockProductivityBackend(), extra_tools=[probe])
    app = create_app(approval_graph=object(), calendar_graph=object(), store=object(),
                     live_agent=graph, api_token='')
    with TestClient(app) as api:
        r = api.post('/v1/agent/stream', json=QUERY)
    assert r.status_code == 200
    assert r.headers['content-type'].startswith('text/event-stream')
    frames = [frame.splitlines() for frame in r.text.strip().split('\n\n')]
    events = [lines[0].removeprefix('event: ') for lines in frames]
    data = [json.loads(lines[1].removeprefix('data: ')) for lines in frames]
    assert events[0] == 'progress'
    assert 'synthetic-private-marker' not in r.text
    if fail:
        assert events[-1] == 'error'
        assert 'done' not in events
        assert data[-1] == {'message': 'agent execution failed'}
    else:
        assert events.count('done') == 1
        assert events[-1] == 'done'
        assert 'error' not in events
        assert any(d.get('node') == 'tools' for d in data)
        assert data[-1]['answer'] == 'observed local tool result'


def test_tcp_disconnect_closes_upstream_stream(tmp_path):
    worker = Path(__file__).parent / 'helpers' / 'stream_server.py'
    env = dict(os.environ, PPA_ENABLE_LIVE_QWEN='0', DASHSCOPE_API_KEY='',
               LANGSMITH_TRACING='false')
    with (tmp_path / 'server.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, str(worker), str(tmp_path)],
                                   env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 15
            while True:
                assert process.poll() is None, (tmp_path / 'server.log').read_text()
                if (tmp_path / 'port').exists():
                    port = (tmp_path / 'port').read_text()
                    try:
                        if httpx.get(f'http://127.0.0.1:{port}/health', timeout=0.3,
                                     trust_env=False).status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                assert time.monotonic() < deadline, 'server readiness timeout'
                time.sleep(0.05)
            with httpx.stream('POST', f'http://127.0.0.1:{port}/v1/agent/stream',
                              json=QUERY, timeout=5, trust_env=False) as response:
                assert response.status_code == 200
                assert next(response.iter_lines()) == 'event: progress'
                # Close TCP before the 30s producer delay completes.
            deadline = time.monotonic() + 5
            while not (tmp_path / 'closed').exists():
                assert time.monotonic() < deadline, 'producer was not cancelled on disconnect'
                time.sleep(0.05)
            assert process.poll() is None  # Cancellation did not crash the server.
            assert httpx.get(f'http://127.0.0.1:{port}/health', trust_env=False).status_code == 200
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
