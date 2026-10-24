# Format, lint, and test the Rust workspace on Windows.
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..\..\rust')

function Run([scriptblock]$Step) {
    & $Step
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Run { cargo fmt --check }
Run { cargo clippy --all-targets -- -D warnings }
Run { cargo test }
