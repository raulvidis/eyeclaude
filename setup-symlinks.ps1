# Setup cross-agent symlinks for eyeclaude
# Run as Administrator or with Developer Mode enabled
# This creates symlinks so .agents/commands/ works across Claude Code, opencode, and Cursor
#
# Usage: pwsh -ExecutionPolicy Bypass -File setup-symlinks.ps1

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

# Create .agents/commands if it doesn't exist
$commandsDir = "$repoRoot\.agents\commands"
if (Test-Path $commandsDir) {
    Write-Host "  OK  .agents/commands/ exists"
} else {
    Write-Host "  SKIP  .agents/commands/ not found — copy from agent-repo-standards first"
    Write-Host "    cp -r <agent-repo-standards>/commands $commandsDir"
}

# Create .agents/skills symlink if agent-repo-standards exists
$devDir = Split-Path -Parent $repoRoot
$standardsDir = "$devDir\agent-repo-standards"
if (Test-Path "$standardsDir\skills") {
    $skillsDir = "$repoRoot\.agents\skills"
    if (Test-Path $skillsDir) {
        Write-Host "  OK  .agents/skills/ exists"
    } else {
        New-Item -ItemType SymbolicLink -Path $skillsDir -Target "..\agent-repo-standards\skills" -Force | Out-Null
        Write-Host "  LINK  .agents/skills -> ..\agent-repo-standards\skills"
    }
} else {
    Write-Host "  SKIP  agent-repo-standards not found at $standardsDir"
}

# Create cross-agent symlinks (Claude Code, opencode, Cursor)
$symlinks = @(
    @{ Name = ".claude/commands"; Target = ".agents/commands" },
    @{ Name = ".opencode/commands"; Target = ".agents/commands" },
    @{ Name = ".cursor/commands"; Target = ".agents/commands" }
)

foreach ($s in $symlinks) {
    $path = Join-Path $repoRoot $s.Name
    if (Test-Path $path) {
        Write-Host "  OK  $s.Name exists"
    } else {
        try {
            New-Item -ItemType SymbolicLink -Path $path -Target $s.Target -Force | Out-Null
            Write-Host "  LINK  $s.Name -> $s.Target"
        } catch {
            Write-Host "  WARN  $s.Name failed (need admin or Dev Mode): $_"
        }
    }
}

Write-Host "`nDone. Verify with: Get-ChildItem -Force $repoRoot\.agents"
