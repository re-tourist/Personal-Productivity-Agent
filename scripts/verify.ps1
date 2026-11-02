$ErrorActionPreference = "Stop"
Write-Host "[1/3] Compile" -ForegroundColor Cyan
python -m compileall -q src tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "[2/3] Full pytest" -ForegroundColor Cyan
python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "[3/3] M7 offline acceptance" -ForegroundColor Cyan
python -m productivity_agent.evaluation --out reports/m7-offline-evaluation.json
exit $LASTEXITCODE
