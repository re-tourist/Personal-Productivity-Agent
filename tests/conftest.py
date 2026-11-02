"""Keep pytest's destructive basetemp cleanup inside a fresh, private directory."""

import tempfile
from pathlib import Path

import pytest


def pytest_configure(config):
    if config.option.basetemp is not None:
        return  # Preserve pytest's explicit CLI override semantics.
    root = Path(config.rootpath).resolve()
    parent = root / '.pytest_cache' / 'ppa-tmp'
    # Refuse redirected caches before creating anything outside the checkout.
    if parent.resolve() != parent or not parent.resolve().is_relative_to(root):
        raise pytest.UsageError('PPA test cache must stay inside the project root')
    parent.mkdir(parents=True, exist_ok=True)
    # Exclusive allocation: no existing directory (or other concurrent run) is cleared.
    config.option.basetemp = tempfile.mkdtemp(prefix='session-', dir=parent)
