"""Regression for fresh basetemp allocation: never reuse/delete an existing run."""
import subprocess
import sys
from pathlib import Path


def test_default_temp_is_fresh_and_preserves_existing_directory(tmp_path):
    root = Path(__file__).resolve().parents[1]
    probe = tmp_path / 'test_probe.py'
    result = tmp_path / 'result.txt'
    # Load the real hook into an isolated tiny pytest checkout to avoid recursion.
    (tmp_path / 'conftest.py').write_bytes((root / 'tests/conftest.py').read_bytes())
    probe.write_text(
        'from pathlib import Path\n'
        'def test_probe(tmp_path):\n'
        f'    Path({str(result)!r}).write_text(str(tmp_path))\n', encoding='utf-8')
    locations = []
    for _ in range(2):
        child = subprocess.run([sys.executable, '-m', 'pytest', '-q', str(probe),
                                '--rootdir', str(tmp_path)], check=False, capture_output=True,
                               text=True, timeout=30, cwd=tmp_path)
        assert child.returncode == 0, child.stdout + child.stderr
        location = Path(result.read_text())
        assert location.is_relative_to(tmp_path / '.pytest_cache/ppa-tmp')
        locations.append(location)
        (location / 'sentinel').write_text('keep')
    assert locations[0].parent != locations[1].parent
    assert (locations[0] / 'sentinel').read_text() == 'keep'
