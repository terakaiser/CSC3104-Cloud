param(
    [string]$DataDirectory = "data/deployment",
    [string]$Context = "docker-desktop"
)
$ErrorActionPreference = "Stop"
$source = (Resolve-Path -LiteralPath $DataDirectory).Path
$manifest = Join-Path $PSScriptRoot "data-loaders.yaml"
$files = @{ "coordinator" = "validation.csv"; "bank-a" = "bank_a.csv"; "bank-b" = "bank_b.csv"; "bank-c" = "bank_c.csv" }
foreach ($role in $files.Keys) {
    if (-not (Test-Path -LiteralPath (Join-Path $source "$role/$($files[$role])") -PathType Leaf)) {
        throw "Missing prepared data for $role. Run scripts/prepare_deployment_data.py first."
    }
}
kubectl --context $Context apply -f $manifest
if ($LASTEXITCODE -ne 0) { throw "Could not create data loaders" }
try {
    foreach ($role in $files.Keys) {
        kubectl --context $Context -n crossbank wait --for=condition=Ready "pod/data-loader-$role" --timeout=120s
        if ($LASTEXITCODE -ne 0) { throw "Data loader for $role is not ready" }
        kubectl --context $Context -n crossbank exec "data-loader-$role" -- python -c "from pathlib import Path; import sys; sys.exit(1 if any(Path('/data').iterdir()) else 0)"
        if ($LASTEXITCODE -ne 0) { throw "Data volume for $role is not empty. Refusing to overwrite or mix datasets." }
        # Copy only the intended CSV, never another bank's data or test.csv.
        Push-Location (Join-Path $source $role)
        try {
            kubectl --context $Context -n crossbank cp $files[$role] "data-loader-${role}:/data/$($files[$role])"
            if ($LASTEXITCODE -ne 0) { throw "Data upload failed for $role" }
            if (Test-Path -LiteralPath "SYNTHETIC_SMOKE_ONLY.txt") {
                kubectl --context $Context -n crossbank cp "SYNTHETIC_SMOKE_ONLY.txt" "data-loader-${role}:/data/SYNTHETIC_SMOKE_ONLY.txt"
                if ($LASTEXITCODE -ne 0) { throw "Marker upload failed for $role" }
            }
        } finally { Pop-Location }
    }
} finally {
    kubectl --context $Context delete -f $manifest --wait=true
}
