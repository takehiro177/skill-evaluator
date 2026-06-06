<#
.SYNOPSIS
  Install the skill-evaluator skill + subagents into a Claude Code project
  (or your user-global config).

.DESCRIPTION
  Copies:
    skills/skill-evaluator  ->  <target>/.claude/skills/skill-evaluator
    agents/*.md             ->  <target>/.claude/agents/

  The skill is self-contained: its agent_tools/ scripts and templates/ live
  inside skills/skill-evaluator/, so they are copied along with it and resolve
  relative to the installed skill directory.

.PARAMETER Target
  Project directory to install into. Default: current directory.

.PARAMETER Global
  Install into the user-global config (~/.claude) instead of a project.

.EXAMPLE
  ./install.ps1                      # install into the current project
  ./install.ps1 -Target C:\src\app  # install into another project
  ./install.ps1 -Global             # install for all projects
#>
[CmdletBinding()]
param(
    [string]$Target = ".",
    [switch]$Global
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($Global) {
    $claudeDir = Join-Path $HOME ".claude"
} else {
    $claudeDir = Join-Path (Resolve-Path $Target) ".claude"
}

$skillsDst = Join-Path $claudeDir "skills"
$agentsDst = Join-Path $claudeDir "agents"
New-Item -ItemType Directory -Force -Path $skillsDst | Out-Null
New-Item -ItemType Directory -Force -Path $agentsDst | Out-Null

Copy-Item -Recurse -Force (Join-Path $repo "skills\skill-evaluator") $skillsDst
# Don't ship local Python bytecode caches that may sit in the bundled tools.
Get-ChildItem -Path (Join-Path $skillsDst "skill-evaluator") -Recurse -Directory -Filter __pycache__ -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force
Copy-Item -Force (Join-Path $repo "agents\skill-eval-runner.md") $agentsDst
Copy-Item -Force (Join-Path $repo "agents\skill-eval-judge.md") $agentsDst

Write-Host "Installed skill-evaluator into: $claudeDir" -ForegroundColor Green
Write-Host "  skills/skill-evaluator       (incl. bundled agent_tools/ + templates/)"
Write-Host "  agents/skill-eval-runner.md"
Write-Host "  agents/skill-eval-judge.md"
Write-Host ""
Write-Host "Open Claude Code in your project and say: 'Evaluate the skill at <path>'"
