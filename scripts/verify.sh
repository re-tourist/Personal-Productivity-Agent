#!/usr/bin/env bash
set -euo pipefail
python -m compileall -q src tests
python -m pytest -q
python -m productivity_agent.evaluation --out reports/m7-offline-evaluation.json
