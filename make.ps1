<#
.SYNOPSIS
    Runs the SARANA Makefile targets on Windows without GNU make.

.DESCRIPTION
    The Makefile is the single documented entry point for the project, and the team
    develops on macOS and Linux where `make` is present. Windows has no `make` by
    default, so this shim implements the same target names against the same commands.

    It is a convenience, not a second source of truth: when a target changes in the
    Makefile it changes here too, and CI runs the Makefile.

.EXAMPLE
    .\make.ps1 up
    .\make.ps1 test
    .\make.ps1 logs -Service core-api
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('help', 'bootstrap', 'keys', 'up', 'down', 'reset', 'migrate', 'seed',
        'dev', 'test', 'lint', 'fmt', 'openapi', 'verify-i18n', 'verify-events',
        'downgrade', 'logs', 'ports', 'health')]
    [string]$Target = 'help',

    [string]$Service
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$Compose = @('compose', '-f', 'infra/docker/compose.yml', '--env-file', '.env')
$DataServices = @('core-api', 'incident-svc', 'alerting-svc', 'ledger-svc', 'agent-svc')
$DevKeys = 'infra/docker/dev-keys'

function Invoke-Checked {
    param([string]$Command, [string[]]$CommandArgs)
    & $Command @CommandArgs
    if ($LASTEXITCODE -ne 0) { throw "$Command $($CommandArgs -join ' ') failed ($LASTEXITCODE)" }
}

function New-EnvFile {
    if (-not (Test-Path '.env')) {
        Copy-Item '.env.example' '.env'
        Write-Output 'Created .env from .env.example - review it before running up.'
    }
}

function New-DevKeys {
    if (Test-Path "$DevKeys/jwt-private.pem") { return }
    New-Item -ItemType Directory -Force $DevKeys | Out-Null
    Invoke-Checked 'openssl' @('genpkey', '-algorithm', 'RSA', '-pkeyopt',
        'rsa_keygen_bits:2048', '-out', "$DevKeys/jwt-private.pem")
    Invoke-Checked 'openssl' @('rsa', '-in', "$DevKeys/jwt-private.pem", '-pubout',
        '-out', "$DevKeys/jwt-public.pem")
    Write-Output "Generated a development RS256 keypair in $DevKeys. Local use only."
}

function Show-Ports {
    Write-Output '  core-api      http://localhost:8001   incident-svc  http://localhost:8002'
    Write-Output '  alerting-svc  http://localhost:8003   ledger-svc    http://localhost:8004'
    Write-Output '  agent-svc     http://localhost:8005   gov-mock      http://localhost:8006'
    Write-Output '  web-ops       http://localhost:3000   web-public    http://localhost:3001'
    Write-Output '  minio api     http://localhost:9000   minio console http://localhost:9001'
    Write-Output '  jaeger        http://localhost:16686  mailpit       http://localhost:8025'
    Write-Output '  postgres and redis use SARANA_HOST_PORT_* from .env (defaults 5432, 6379)'
}

switch ($Target) {
    'help' {
        Write-Output 'SARANA targets (mirrors the Makefile):'
        Write-Output '  bootstrap    install uv + pnpm deps, install pre-commit hooks'
        Write-Output '  keys         generate the local RS256 JWT keypair'
        Write-Output '  up           start the stack, wait for health, migrate and seed'
        Write-Output '  down         stop and remove containers, keep volumes'
        Write-Output '  reset        DESTRUCTIVE - delete volumes and rebuild from empty'
        Write-Output '  migrate      alembic upgrade head across data-owning services'
        Write-Output '  seed         load data/seed into the database'
        Write-Output '  dev          turbo dev across web and mobile'
        Write-Output '  test         pytest across services + vitest across packages'
        Write-Output '  lint         ruff + mypy + eslint + tsc --noEmit'
        Write-Output '  fmt          auto-fix formatting and import order'
        Write-Output '  openapi      regenerate the merged spec and the TS client'
        Write-Output '  verify-i18n  fail if any locale key is missing in si, ta or en'
        Write-Output '  verify-events fail if an event contract change breaks a consumer'
        Write-Output '  downgrade    DESTRUCTIVE - roll every service back to empty'
        Write-Output '  logs         tail logs; add -Service <name> for one service'
        Write-Output '  ports        print the local port map'
        Write-Output '  health       curl /healthz on all six services'
    }

    'keys' { New-DevKeys }

    'bootstrap' {
        New-EnvFile
        New-DevKeys
        Invoke-Checked 'uv' @('sync', '--all-packages', '--all-extras', '--all-groups')
        & pnpm install
        Invoke-Checked 'uv' @('run', 'pre-commit', 'install', '--install-hooks')
        Write-Output ''
        Write-Output 'Bootstrap complete. Next: .\make.ps1 up'
    }

    'up' {
        New-EnvFile
        New-DevKeys
        Invoke-Checked 'docker' ($Compose + @('up', '-d', '--build', '--wait'))
        Write-Output 'All containers healthy. Creating object storage buckets...'
        Invoke-Checked 'docker' ($Compose + @('run', '--rm', 'minio-init'))
        Write-Output 'Applying migrations...'
        & $PSCommandPath 'migrate'
        & $PSCommandPath 'seed'
        Write-Output ''
        Show-Ports
    }

    'down' { Invoke-Checked 'docker' ($Compose + @('down', '--remove-orphans')) }

    'reset' {
        $reply = Read-Host 'This deletes the local database, MinIO objects and Redis streams. Type reset to confirm'
        if ($reply -ne 'reset') { Write-Output 'Aborted.'; exit 1 }
        Invoke-Checked 'docker' ($Compose + @('down', '--volumes', '--remove-orphans'))
        & $PSCommandPath 'up'
    }

    'downgrade' {
        $reply = Read-Host "This drops every SARANA table. Type downgrade to confirm"
        if ($reply -ne 'downgrade') { Write-Output 'Aborted.'; exit 1 }
        foreach ($svc in @('agent-svc', 'alerting-svc', 'ledger-svc', 'incident-svc', 'core-api')) {
            Write-Output "--> rolling back $svc"
            Push-Location "services/$svc"
            try { Invoke-Checked 'uv' @('run', 'alembic', 'downgrade', 'base') }
            finally { Pop-Location }
        }
    }

    'migrate' {
        foreach ($svc in $DataServices) {
            Write-Output "--> migrating $svc"
            Push-Location "services/$svc"
            try { Invoke-Checked 'uv' @('run', 'alembic', 'upgrade', 'head') }
            finally { Pop-Location }
        }
    }

    'seed' {
        Invoke-Checked 'uv' @('run', 'python', '-m', 'sarana_shared.seed.load', '--path', 'data/seed')
    }

    'dev' { & pnpm turbo run dev }

    'test' {
        Invoke-Checked 'uv' @('run', 'pytest')
        & pnpm turbo run test
    }

    'lint' {
        Invoke-Checked 'uv' @('run', 'ruff', 'check', '.')
        Invoke-Checked 'uv' @('run', 'ruff', 'format', '--check', '.')
        $srcDirs = @('packages/py-shared/src') + (Get-ChildItem 'services' -Directory |
            ForEach-Object { "services/$($_.Name)/src" })
        Invoke-Checked 'uv' (@('run', 'mypy') + $srcDirs)
        Invoke-Checked 'uv' @('run', 'python', 'tools/hooks/check_event_schemas.py')
        & pnpm run lint
        & pnpm turbo run typecheck
    }

    'fmt' {
        Invoke-Checked 'uv' @('run', 'ruff', 'check', '--fix', '.')
        Invoke-Checked 'uv' @('run', 'ruff', 'format', '.')
        & pnpm run format
    }

    'openapi' {
        Invoke-Checked 'uv' @('run', 'python', '-m', 'sarana_shared.openapi.merge',
            '--out', 'packages/ts-shared/openapi.json')
        & pnpm --filter '@sarana/ts-shared' run 'generate:api'
    }

    'verify-events' {
        Invoke-Checked 'uv' @('run', 'python', 'tools/hooks/check_event_schemas.py')
    }

    'verify-i18n' {
        & pnpm --filter '@sarana/ts-shared' run 'verify-i18n'
        Invoke-Checked 'uv' @('run', 'python', '-m', 'sarana_shared.domain.i18n_check')
    }

    'logs' {
        $logArgs = $Compose + @('logs', '-f', '--tail=100')
        if ($Service) { $logArgs += $Service }
        & docker @logArgs
    }

    'ports' { Show-Ports }

    'health' {
        foreach ($port in 8001, 8002, 8003, 8004, 8005, 8006) {
            Write-Host "  :$port " -NoNewline
            try {
                $response = Invoke-RestMethod "http://localhost:$port/healthz" -TimeoutSec 5
                Write-Output ($response | ConvertTo-Json -Compress)
            }
            catch { Write-Output 'unreachable' }
        }
    }
}
