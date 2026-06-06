# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Use GitHub's private vulnerability reporting instead:

➡️ **[Report a vulnerability](https://github.com/takehiro177/skill-evaluator/security/advisories/new)**

(Repository → **Security** tab → **Report a vulnerability**.)

This lets us discuss and fix the issue privately before any public disclosure.
We aim to acknowledge reports within a few days.

## Scope

This is a Claude Code-native evaluation tool. The most likely "security" issues
here are:

- **Secret leakage** — e.g. an `ANTHROPIC_API_KEY` written into a report,
  transcript, or committed file. `.env` is gitignored and a `detect-private-key`
  pre-commit hook guards commits, but please report any path that can leak a key.
- **Untrusted input handling** — `transcript_tokens.py` / `deepeval_runner.py`
  parsing transcripts or skill files in an unsafe way.

If you've **accidentally committed a secret**, rotate the key immediately
(it must be considered compromised once pushed) and then report it so we can
help scrub history if needed.
