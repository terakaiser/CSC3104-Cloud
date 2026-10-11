<# Run from PowerShell: .\project.ps1 docker start (or k8s start). #>
param(
    [ValidateSet('help', 'docker', 'k8s')][string]$Target = 'help',
    [ValidateSet('help', 'setup', 'build', 'start', 'train', 'results', 'status', 'logs', 'stop')]
    [string]$Action = 'help'
)
$ErrorActionPreference = 'Stop'

function Invoke-Checked {
    param([string]$Tool, [string[]]$Arguments)
    & $Tool @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Tool failed (exit $LASTEXITCODE). Fix the error above before continuing." }
}

function Invoke-Compose {
    param([string[]]$CommandArgs)
    Invoke-Checked docker (@('compose', '-f', 'docker/compose.yaml') + $CommandArgs)
}

function Invoke-Kube {
    param([string[]]$CommandArgs)
    Invoke-Checked kubectl (@('--context', 'docker-desktop', '-n', 'crossbank') + $CommandArgs)
}

if ($Target -eq 'help' -or $Action -eq 'help') {
    Write-Host @'
Usage: .\project.ps1 <docker|k8s> <action>

setup    Docker: prepare fresh smoke data folders. Kubernetes: create storage and upload data once.
build    Build the shared Docker image (either target). Repeat after code/settings changes.
start    Start services and wait for readiness. Does not start training.
train    Submit one new experiment and show its logs.
results  Copy saved results to results/runs/<docker|kubernetes>/ and show the newest status/summary.
status   Show containers or pods.
logs     Show recent service logs.
stop     Stop services while keeping datasets, results and coordinator state.

First Docker run:     docker setup -> docker build -> docker start -> docker train -> docker results
First Kubernetes run: docker setup -> docker build -> k8s setup -> k8s start -> k8s train -> k8s results
Skip setup/build when data and the unchanged image already exist. Submit only one run at a time.
Kubernetes always targets docker-desktop. See docker/README.md and k8s/README.md for details.
'@
    return
}

Push-Location $PSScriptRoot
try {
    $tool = if ($Target -eq 'docker' -or $Action -eq 'build') { 'docker' } else { 'kubectl' }
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Install $tool and make it available in this terminal first." }
    if ($Action -eq 'build') {
        Write-Host 'Building the shared coordinator/bank image...'
        Invoke-Compose @('build', 'coordinator')
        Write-Host 'Build complete. Follow the guide to replace existing services before your next run.'
        return
    }

    switch ($Action) {
        'setup' {
            if ($Target -eq 'docker') {
                $python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
                if (-not (Test-Path $python)) { throw 'Create the Python environment first; see README.md > Environment.' }
                if (Test-Path 'data/deployment') { throw 'Deployment data already exists. Skip setup and run start. Existing data was kept.' }
                if (-not (Test-Path 'data/smoke')) {
                    Invoke-Checked $python @('scripts/testing/create_smoke_data.py')
                }
                Invoke-Checked $python @('scripts/prepare_deployment_data.py')
                Write-Host 'Artificial smoke data prepared. This is not a PaySim performance experiment.'
            } else {
                if (-not (Test-Path 'data/deployment')) { throw 'Prepare data with .\project.ps1 docker setup first.' }
                Invoke-Kube @('apply', '-f', 'k8s/storage.yaml')
                & ./k8s/load-data.ps1
                Write-Host 'Kubernetes data upload complete. Skip setup on later runs.'
            }
        }
        'start' {
            Write-Host 'Starting services; training is a separate command...'
            if ($Target -eq 'docker') {
                Invoke-Compose @('up', '-d', '--wait')
            } else {
                Invoke-Kube @('apply', '-f', 'k8s/workloads.yaml')
                foreach ($role in @('coordinator', 'bank-a', 'bank-b', 'bank-c')) {
                    Invoke-Kube @('rollout', 'status', "deployment/$role", '--timeout=180s')
                }
            }
            Write-Host "Services ready. Run .\project.ps1 $Target train to start an experiment."
        }
        'train' {
            Write-Host 'Submitting training. Keep this terminal open until the run finishes.'
            if ($Target -eq 'docker') {
                Invoke-Compose @('run', '--rm', 'submit')
            } else {
                $existing = Invoke-Kube @('get', 'job', 'training-run', '--ignore-not-found', '-o', 'json')
                if ($existing) {
                    $job = ($existing -join "`n") | ConvertFrom-Json
                    $complete = @($job.status.conditions | Where-Object { $_.type -eq 'Complete' -and $_.status -eq 'True' })
                    if ($complete.Count -eq 0) {
                        throw 'The previous submission job is active or failed. Inspect logs and saved training status before retrying; no job was removed.'
                    }
                    Invoke-Kube @('delete', 'job', 'training-run', '--wait=true')
                }
                Invoke-Kube @('create', '-f', 'k8s/training-job.yaml')
                Invoke-Kube @('logs', '-f', 'job/training-run', '--pod-running-timeout=180s')
            }
            Write-Host "Submission command finished. Run .\project.ps1 $Target results and confirm training_status.json says completed."
        }
        'results' {
            $folder = if ($Target -eq 'docker') { 'results/runs/docker' } else { 'results/runs/kubernetes' }
            New-Item -ItemType Directory -Force $folder | Out-Null
            if ($Target -eq 'docker') {
                Invoke-Compose @('cp', 'coordinator:/results/.', "$folder/")
            } else {
                $pod = Invoke-Kube @('get', 'pod', '-l', 'app=coordinator', '-o', 'jsonpath={.items[0].metadata.name}')
                if (-not $pod) { throw 'No coordinator pod found. Start services before copying results.' }
                Invoke-Kube @('cp', "${pod}:/results/.", "$folder/")
            }
            Write-Host "Results copied to $folder. Existing copies with matching filenames may be replaced."
            $latest = Get-ChildItem -LiteralPath $folder -Directory | Where-Object { $_.Name -like 'three_bank_federated__*' } | Sort-Object Name -Descending | Select-Object -First 1
            if (-not $latest) { Write-Host 'No saved training runs found yet.'; return }
            Write-Host "Newest saved run: $($latest.Name) (may be an earlier experiment)."
            foreach ($name in @('training_status.json', 'results_summary.txt')) {
                $path = Join-Path $latest.FullName $name
                if (Test-Path $path) { Get-Content -LiteralPath $path }
            }
        }
        'status' {
            if ($Target -eq 'docker') { Invoke-Compose @('ps') }
            else { Invoke-Kube @('get', 'pods') }
        }
        'logs' {
            if ($Target -eq 'docker') { Invoke-Compose @('logs', '--tail', '100', 'coordinator', 'bank-a', 'bank-b', 'bank-c') }
            else {
                foreach ($role in @('coordinator', 'bank-a', 'bank-b', 'bank-c')) {
                    Write-Host "--- $role ---"
                    Invoke-Kube @('logs', "deployment/$role", '--tail=100')
                }
            }
        }
        'stop' {
            Write-Host 'Stopping services. Any active training will be interrupted; stored data and results are kept.'
            if ($Target -eq 'docker') { Invoke-Compose @('down') }
            else { Invoke-Kube @('scale', 'deployment', 'coordinator', 'bank-a', 'bank-b', 'bank-c', '--replicas=0') }
        }
    }
} finally { Pop-Location }
