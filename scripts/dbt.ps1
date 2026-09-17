param(
    [ValidateSet("build", "debug", "run", "test")]
    [string]$Command = "build",
    [string]$EnvFile = ".env.postgres"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $root $EnvFile
if (-not (Test-Path -LiteralPath $envPath)) {
    throw "Missing $envPath. Copy .env.example to .env.postgres and configure it."
}

foreach ($line in Get-Content -LiteralPath $envPath) {
    if ($line -match '^([^#=]+)=(.*)$') {
        [Environment]::SetEnvironmentVariable(
            $matches[1], $matches[2].Trim('"').Trim("'"), "Process"
        )
    }
}

$dbt = Join-Path $root ".venv\Scripts\dbt.exe"
if (-not (Test-Path -LiteralPath $dbt)) {
    throw "dbt is not installed. Run: python -m pip install -r requirements.txt"
}

& $dbt $Command --project-dir $root --profiles-dir $root
exit $LASTEXITCODE
