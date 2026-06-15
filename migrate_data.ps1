<#
.SYNOPSIS
    MeteorAI machine-to-machine migration helper.

    Wraps export_backup.py / import_backup.py (which handle the PostgreSQL DB,
    meteorite_scraper/images, and Label Studio annotations) and adds the parts
    those scripts do NOT cover: the large media directories, the per-image
    metadata, the ML model weights, and the machine-local secrets. On import it
    also rewrites the hardcoded absolute project path baked into the launch
    scripts.

.DESCRIPTION
    Run in two phases.

    OLD MACHINE:
        .\migrate_data.ps1 -Mode Export -Dest E:\meteorai_migration

    NEW MACHINE (after: git clone, install Python + PostgreSQL 18, pip install):
        .\migrate_data.ps1 -Mode Import -Source E:\meteorai_migration

    Add -DryRun to either to preview what would be copied (and the total size)
    without touching anything.

    -Dest / -Source is a transfer folder (external drive, network share, etc.).
    It does NOT need to be inside the repo.

.PARAMETER Mode
    Export or Import.

.PARAMETER Dest
    (Export) Folder to write the migration bundle into. Created if missing.

.PARAMETER Source
    (Import) The migration bundle folder produced by an earlier Export.

.PARAMETER ProjectDir
    Project root. Defaults to the folder this script lives in.

.PARAMETER SkipRegenerable
    Omit large directories that can be rebuilt/redownloaded on the new machine
    (classifier_training_data, training, label_studio/sam_weights,
    label_studio/model_dir, root *.pt weights). Use this for a lean transfer.

.PARAMETER DryRun
    Preview only. Lists every item that would be copied with its size and a
    grand total, and prints the backup commands that would run, without copying,
    rewriting, or invoking Python.

.PARAMETER DbPassword
    (Import) PostgreSQL password to pass through to import_backup.py.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Export', 'Import')]
    [string]$Mode,

    [string]$Dest,
    [string]$Source,
    [string]$ProjectDir = $PSScriptRoot,
    [switch]$SkipRegenerable,
    [switch]$DryRun,
    [string]$DbPassword,
    [string]$Python,
    [switch]$SkipBackup
)

$ErrorActionPreference = 'Stop'
$ProjectDir = (Resolve-Path $ProjectDir).Path

# Resolve the FULL path to a Python interpreter that actually has the project
# deps. On this project the deps live in the Windows Store Python 3.12, while
# bare `python` may resolve elsewhere without them. We return sys.executable
# (not just "py") so the backup scripts' "#!/usr/bin/env python3" shebang can't
# reroute `py script.py` to a different, dep-less interpreter.
function Resolve-Python {
    if ($Python) { return $Python }
    $probe = 'import requests, psycopg2, sys; print(sys.executable)'
    $cands = @(@('py', '-3.12'), @('py'), @('python'))
    foreach ($c in $cands) {
        $exe = $c[0]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $pre = if ($c.Count -gt 1) { $c[1..($c.Count - 1)] } else { @() }
        $out = & $exe @pre -c $probe 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) { return ($out | Select-Object -Last 1).ToString().Trim() }
    }
    throw "No Python with project deps (requests, psycopg2) found on PATH. Pass -Python <path-to-python.exe>, or pip install -r meteorite_scraper\requirements.txt into the interpreter you want to use."
}
$Py = if ($DryRun) { try { Resolve-Python } catch { 'python' } } else { Resolve-Python }
Write-Host "Using Python: $Py" -ForegroundColor DarkGray

# ---------------------------------------------------------------------------
# Directories NOT covered by export_backup.py - copied verbatim.
# Paths are relative to the project root.
# ---------------------------------------------------------------------------
$EssentialDirs = @(
    'unsorted_media',
    'sorted_in_situ',
    'sorted_in_situ_undersized',
    'sorted_not_in_situ',
    'sorted_cut',
    'import',
    'meteorite_scraper/videos',
    'meteorite_scraper/metadata'
)

# Large but rebuildable on the new machine. Omitted when -SkipRegenerable.
$RegenerableDirs = @(
    'classifier_training_data',
    'training',
    'label_studio/exports',
    'label_studio/sam_weights',
    'label_studio/model_dir'
)

# Machine-local secrets (gitignored - never committed, must be carried by hand).
$SecretFiles = @(
    'meteorite_scraper/.env',
    'meteorite_scraper/db_config.py'
)

# Root-level model weights (regenerable via re-download).
$WeightGlob = 'yolo*.pt'

$script:PlannedBytes = 0

function Get-DirList {
    $dirs = $EssentialDirs
    if (-not $SkipRegenerable) { $dirs += $RegenerableDirs }
    return $dirs
}

function Format-Size([long]$bytes) {
    if ($bytes -ge 1GB) { return ('{0:N2} GB' -f ($bytes / 1GB)) }
    if ($bytes -ge 1MB) { return ('{0:N1} MB' -f ($bytes / 1MB)) }
    if ($bytes -ge 1KB) { return ('{0:N1} KB' -f ($bytes / 1KB)) }
    return "$bytes B"
}

function Get-PathSize($path) {
    $item = Get-Item -LiteralPath $path
    if ($item.PSIsContainer) {
        $sum = (Get-ChildItem -LiteralPath $path -Recurse -File -ErrorAction SilentlyContinue |
                Measure-Object -Property Length -Sum).Sum
        if ($null -eq $sum) { return [long]0 }
        return [long]$sum
    }
    return [long]$item.Length
}

function Copy-Tree($src, $dst) {
    # robocopy: /E recurse incl. empty, /Z resumable, /R:2 /W:2 light retry,
    # quiet listing. Exit codes 0-7 are success for robocopy.
    robocopy $src $dst /E /Z /R:2 /W:2 /NFL /NDL /NJH /NP | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy failed copying '$src' -> '$dst' (exit $LASTEXITCODE)"
    }
}

# Unified copy: handles files and directories, dry-run accounting, and
# absent-source reporting. $dst is the full destination path.
function Transfer($label, $src, $dst) {
    if (-not (Test-Path -LiteralPath $src)) {
        Write-Host "  - $label (absent, skipped)" -ForegroundColor DarkGray
        return
    }
    if ($DryRun) {
        $sz = Get-PathSize $src
        $script:PlannedBytes += $sz
        Write-Host ("  + {0}  [{1}]" -f $label, (Format-Size $sz))
        return
    }
    Write-Host "  + $label"
    if ((Get-Item -LiteralPath $src).PSIsContainer) {
        Copy-Tree $src $dst
    } else {
        New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
        Copy-Item -LiteralPath $src -Destination $dst -Force
    }
}

function Show-Total {
    if ($DryRun) {
        Write-Host ("`n[dry-run] Total to copy (excludes the backup zip): {0}" -f (Format-Size $script:PlannedBytes)) -ForegroundColor Cyan
        Write-Host "[dry-run] No files were copied, no paths rewritten, no Python invoked." -ForegroundColor Cyan
    }
}

# ===========================================================================
# EXPORT
# ===========================================================================
if ($Mode -eq 'Export') {
    if (-not $Dest) { throw "Export requires -Dest <folder>." }
    if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $Dest | Out-Null }
    if (Test-Path $Dest) { $Dest = (Resolve-Path $Dest).Path }
    Write-Host "=== MeteorAI Export$(if ($DryRun) {' (DRY RUN)'}) ===" -ForegroundColor Cyan
    Write-Host "  Project: $ProjectDir"
    Write-Host "  Bundle : $Dest`n"

    $dataRoot = Join-Path $Dest 'data'

    # 1. DB + images + Label Studio annotations via the existing backup script.
    Write-Host "[1/4] export_backup.py (DB + images + annotations)..." -ForegroundColor Yellow
    $zipPath = Join-Path $Dest 'meteorai_backup.zip'
    if ($SkipBackup) {
        if (Test-Path $zipPath) {
            Write-Host "  -SkipBackup: reusing existing $zipPath" -ForegroundColor Green
        } else {
            Write-Host "  -SkipBackup set but no zip at $zipPath (continuing without it)." -ForegroundColor Yellow
        }
    } elseif ($DryRun) {
        Write-Host "  [dry-run] would run: $Py export_backup.py --output `"$zipPath`""
    } else {
        Push-Location $ProjectDir
        try {
            & $Py export_backup.py --output $zipPath
            if ($LASTEXITCODE -ne 0) { throw "export_backup.py failed (exit $LASTEXITCODE)." }
        } finally { Pop-Location }
    }

    # 2. Large media / data directories.
    Write-Host "`n[2/4] Media & data directories..." -ForegroundColor Yellow
    foreach ($rel in Get-DirList) {
        Transfer $rel (Join-Path $ProjectDir $rel) (Join-Path $dataRoot $rel)
    }

    # 3. Root model weights.
    if (-not $SkipRegenerable) {
        Write-Host "`n[3/4] Root model weights ($WeightGlob)..." -ForegroundColor Yellow
        $weights = Get-ChildItem -Path $ProjectDir -Filter $WeightGlob -File -ErrorAction SilentlyContinue
        foreach ($w in $weights) {
            Transfer $w.Name $w.FullName (Join-Path (Join-Path $dataRoot '_root_weights') $w.Name)
        }
    } else {
        Write-Host "`n[3/4] Skipping model weights (-SkipRegenerable)." -ForegroundColor DarkGray
    }

    # 4. Secrets.
    Write-Host "`n[4/4] Secrets (.env, db_config.py)..." -ForegroundColor Yellow
    foreach ($rel in $SecretFiles) {
        Transfer $rel (Join-Path $ProjectDir $rel) (Join-Path (Join-Path $Dest 'secrets') $rel)
    }

    Show-Total
    if (-not $DryRun) {
        Write-Host "`n=== Export complete ===" -ForegroundColor Green
        Write-Host "Bundle ready at: $Dest"
        Write-Host "Transfer the whole folder to the new machine, then run:"
        Write-Host "  .\migrate_data.ps1 -Mode Import -Source <bundle-folder>" -ForegroundColor Cyan
        Write-Host "`nNOTE: the secrets\ folder contains your DB password and LS API key." -ForegroundColor Yellow
        Write-Host "      Transfer it securely and consider rotating both after the move." -ForegroundColor Yellow
    }
    exit 0
}

# ===========================================================================
# IMPORT
# ===========================================================================
if ($Mode -eq 'Import') {
    if (-not $Source) { throw "Import requires -Source <folder>." }
    $Source = (Resolve-Path $Source).Path
    Write-Host "=== MeteorAI Import$(if ($DryRun) {' (DRY RUN)'}) ===" -ForegroundColor Cyan
    Write-Host "  Bundle : $Source"
    Write-Host "  Project: $ProjectDir`n"

    $dataRoot = Join-Path $Source 'data'

    # 1. Restore secrets first - import_backup.py needs db_config.py / .env.
    Write-Host "[1/4] Secrets..." -ForegroundColor Yellow
    foreach ($rel in $SecretFiles) {
        Transfer $rel (Join-Path (Join-Path $Source 'secrets') $rel) (Join-Path $ProjectDir $rel)
    }

    # 2. Restore media / data directories.
    Write-Host "`n[2/4] Media & data directories..." -ForegroundColor Yellow
    foreach ($rel in Get-DirList) {
        Transfer $rel (Join-Path $dataRoot $rel) (Join-Path $ProjectDir $rel)
    }
    $wSrc = Join-Path $dataRoot '_root_weights'
    if (Test-Path $wSrc) {
        foreach ($w in (Get-ChildItem $wSrc -File)) {
            Transfer "weights\$($w.Name)" $w.FullName (Join-Path $ProjectDir $w.Name)
        }
    }

    # 3. Rewrite the hardcoded absolute project path in launch scripts.
    Write-Host "`n[3/4] Rewriting hardcoded project paths to '$ProjectDir'..." -ForegroundColor Yellow
    $oldPath = 'C:\cygwin64\home\charl\meteorai'
    if ($ProjectDir -ieq $oldPath) {
        Write-Host "  Project path unchanged - nothing to rewrite." -ForegroundColor Green
    } else {
        $targets = @('start_services.ps1', 'start_label_studio.bat', 'stop_services.ps1')
        foreach ($t in $targets) {
            $f = Join-Path $ProjectDir $t
            if (Test-Path $f) {
                $content = Get-Content $f -Raw
                if ($content -match [regex]::Escape($oldPath)) {
                    if ($DryRun) {
                        Write-Host "  [dry-run] would rewrite path in $t"
                    } else {
                        $content.Replace($oldPath, $ProjectDir) | Set-Content $f -Encoding UTF8 -NoNewline
                        Write-Host "  ~ $t"
                    }
                }
            }
        }
    }

    # 4. Restore DB + images + annotations via the existing import script.
    Write-Host "`n[4/4] import_backup.py (DB + images + annotations)..." -ForegroundColor Yellow
    $zipPath = Join-Path $Source 'meteorai_backup.zip'
    if (-not (Test-Path $zipPath)) { throw "Backup zip not found at $zipPath" }
    if ($DryRun) {
        $cmd = "$Py import_backup.py `"$zipPath`""
        if ($DbPassword) { $cmd += " --db-password ***" }
        Write-Host "  [dry-run] would run: $cmd"
    } else {
        Push-Location $ProjectDir
        try {
            $argv = @($zipPath)
            if ($DbPassword) { $argv += @('--db-password', $DbPassword) }
            & $Py import_backup.py @argv
            if ($LASTEXITCODE -ne 0) { throw "import_backup.py failed (exit $LASTEXITCODE)." }
        } finally { Pop-Location }
    }

    Show-Total
    if (-not $DryRun) {
        Write-Host "`n=== Import complete ===" -ForegroundColor Green
        Write-Host "Next: verify with  .\start_services.ps1" -ForegroundColor Cyan
    }
    exit 0
}
