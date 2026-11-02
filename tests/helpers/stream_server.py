"""Test-only loopback server; no provider or user database is opened."""
import asyncio
import socket
import sys
from pathlib import Path

import uvicorn

from productivity_agent.api.app import create_app

directory = Path(sys.argv[1])


class SlowStream:
    async def astream(self, *args, **kwargs):
        try:
            yield {'agent': {'messages': []}}
            await asyncio.sleep(30)
        finally:
            (directory / 'closed').write_text('closed', encoding='utf-8')


app = create_app(approval_graph=object(), calendar_graph=object(), store=object(),
                 live_agent=SlowStream(), api_token='')
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    sock.listen(128)
    (directory / 'port').write_text(str(sock.getsockname()[1]), encoding='utf-8')
    uvicorn.Server(uvicorn.Config(app, log_level='warning')).run(sockets=[sock])
