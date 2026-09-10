$ErrorActionPreference = 'Stop'
python "$PSScriptRoot\assistant.py" configure-key
exit $LASTEXITCODE
