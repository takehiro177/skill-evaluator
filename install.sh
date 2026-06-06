#!/usr/bin/env bash
# Install the skill-evaluator skill + subagents into a Claude Code project
# (or your user-global config).
#
#   skills/skill-evaluator  ->  <target>/.claude/skills/skill-evaluator
#   agents/*.md             ->  <target>/.claude/agents/
#
# The skill is self-contained: its agent_tools/ scripts and templates/ live
# inside skills/skill-evaluator/, so they are copied along with it and resolve
# relative to the installed skill directory.
#
# Usage:
#   ./install.sh                 # install into the current project
#   ./install.sh /path/to/app    # install into another project
#   ./install.sh --global        # install for all projects (~/.claude)
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

target="."
if [[ "${1:-}" == "--global" ]]; then
  claude_dir="${HOME}/.claude"
else
  target="${1:-.}"
  claude_dir="$(cd "$target" && pwd)/.claude"
fi

skills_dst="${claude_dir}/skills"
agents_dst="${claude_dir}/agents"
mkdir -p "$skills_dst" "$agents_dst"

cp -R "${repo}/skills/skill-evaluator" "$skills_dst/"
# Don't ship local Python bytecode caches that may sit in the bundled tools.
find "${skills_dst}/skill-evaluator" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
cp -f "${repo}/agents/skill-eval-runner.md" "$agents_dst/"
cp -f "${repo}/agents/skill-eval-judge.md" "$agents_dst/"

echo "Installed skill-evaluator into: ${claude_dir}"
echo "  skills/skill-evaluator       (incl. bundled agent_tools/ + templates/)"
echo "  agents/skill-eval-runner.md"
echo "  agents/skill-eval-judge.md"
echo
echo "Open Claude Code in your project and say: 'Evaluate the skill at <path>'"
