<!-- Thanks for contributing! Keep prompt edits minimal — wording is load-bearing here. -->

## What & why

<!-- What does this change, and why? Link any related issue: "Closes #123". -->

## Type of change

- [ ] Bug fix
- [ ] New feature / enhancement
- [ ] Prompt wording (skill / subagent)
- [ ] Docs only
- [ ] Tooling / CI

## Trust invariants

This tool exists to produce *trustworthy* evaluations. Confirm your change preserves the invariants from [CONTRIBUTING.md](https://github.com/takehiro177/skill-evaluator/blob/main/CONTRIBUTING.md), or explain the trade-off:

- [ ] The judge stays **blind** — no arm identity, run markers, token numbers, or the word "skill" reaches it.
- [ ] Tokens come from the **transcript** — never estimated or model-invented.
- [ ] The **skill is the only manipulated variable** between WITH and WITHOUT arms.
- [ ] `transcript_tokens.py` remains **stdlib-only**; deepeval degrades gracefully when deps/key are missing.
- [ ] Negatives are reported **honestly** (prompts not biased toward "the skill helped").

## Checklist

- [ ] `pre-commit run --all-files` passes locally.
- [ ] If I changed the transcript parser, I noted the Claude Code version I tested against.
- [ ] I agree my contribution is licensed under the repo's MIT license.
