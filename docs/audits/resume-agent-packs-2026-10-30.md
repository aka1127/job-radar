# Audit: resume agent packs (2026-10-30)

Audited with the skill-auditor procedure: shallow clones into `%TEMP%\sk-audit\`, files read only, nothing installed or run.

## Audit: ats-resume-skill (https://github.com/msdanyg/ats-resume-skill)
Verdict: INSTALL
Tier: GitHub (MIT, Daniel Glickman, last commit 2026-07-08, 5 stars)
Why: pure knowledge (SKILL.md + references/failure-patterns.md), no scripts, no tools, no network. Precise, testable
rules for how Workday/Greenhouse/Lever/iCIMS parsers fail (year-only dates, fused title/company lines, parentheticals on
title lines, DOCX vs PDF).

| Risk | Severity | Evidence |
|---|---|---|
| Suggests a placeholder month (July) when the real month is unknown, which would put an unverified date on a CV | low | SKILL.md Rule Set A, item 6 |
| Long always-loaded description (one skill) | low | SKILL.md frontmatter |

Windows: OK. Context cost: 1 skill, hooks: none.
Install: copy `SKILL.md` and `references/` to `.claude/skills/ats-resume-formatting/` in Job Radar.
Use: ats-auditor and the strict-portal CV variant. Ignore the placeholder-month advice (truth rules).

## Audit: resume-helper (https://github.com/MadeByTokens/resume-helper)
Verdict: INSTALL SUBSET
Tier: GitHub (MIT, MadeByTokens, last commit 2026-01-12, 7 stars, v0.7.3)
Why: clean adversarial agents (writer, fact-checker, skeptical interviewer, coach, quantification). Tools limited to
Read/Write/Edit, no network, no hooks. They expect their own `working/` file layout, so they need a small I/O edit.

| Risk | Severity | Evidence |
|---|---|---|
| Bash script with sed (only regenerates coach-premium.md from coach.md) | low | scripts/generate-premium-agents.sh |
| Agents read and write a fixed `working/` folder; out of the box they will not find our files | low | agents/fact-checker.md:14-30 |
| Overlap with our truth check and AI-screener step | low | agents/fact-checker.md, agents/interviewer.md |

Windows: OK for the agents; the script needs Git Bash (not needed). Context cost: subset of 2 agents, hooks: none.
Install: `agents/interviewer.md` (as `skeptical-interviewer`) and `agents/suggest-quantification.md` (as
`quantify-coach`), with their file-I/O section pointed at `candidates/<name>/profile.yaml` and `output/<name>/...`.
Skip the loop commands, writer and coach (our pipeline already writes the packs).

## Audit: ats-resume-agent (https://github.com/NullSpace-BitCradle/ats-resume-agent)
Verdict: REJECT
Tier: GitHub (MIT, last commit 2026-10-20, 13 stars, v1.2.0)
Why: LaTeX + bun stack that does not fit our Python/Chromium engine; the writer agent inherits every tool (Bash
included) and runs pdflatex/bun; setup.sh offers `curl ... | bash` installs and Homebrew/MacTeX (macOS-centric).

| Risk | Severity | Evidence |
|---|---|---|
| setup.sh pipes a remote script to bash on request | med | setup.sh (Install Claude Code branch) |
| Agent has no tool restriction (Bash) | med | agents/ats-resume-writer.md frontmatter |
| Stack mismatch (pdflatex, CormorantGaramond, bun) | med | package.json, setup.sh |

Windows: needs Git Bash + MiKTeX + bun. Context cost: 2 agents, hooks: none.
Idea worth borrowing: career-doc-builder.md, a guided interview that builds a master career document (for a candidate's metrics).

## Audit: career-ops (https://github.com/santifer/career-ops)
Verdict: REJECT
Tier: GitHub (MIT, Santiago Fernández de Valderrama, last commit 2026-10-30, v1.38.0)
Why: a full competing application (about 2,900 files, many Node scripts) rather than an agent pack. Its plugin runs a
SessionStart hook on every session and a postinstall that downloads Chromium.

| Risk | Severity | Evidence |
|---|---|---|
| SessionStart hook runs a Node script (installs packages, creates folders) every session, 300 s timeout | high | hooks/hooks.json |
| package.json postinstall runs `npx playwright install chromium` | med | package.json:82 |
| Massive overlap with our engine (scanning, scoring, tailoring, tracking) | med | repository root |

Windows: unknown without running. Context cost: 1 large skill + hook.
Ideas worth borrowing (read, not installed): its CV templates warn that variable web fonts can make PDF extractors split
words, and that ligatures must be disabled (we already disable them); template set (modern, executive, compact).

## Installed (2026-10-30, on request, to add resume agents)
- ats-resume-skill -> `.claude/skills/ats-resume-formatting/` (SKILL.md, references/, LICENSE). Rule Set A item 6
  (placeholder month) replaced: ask the candidate instead.
- resume-helper subset -> `.claude/agents/skeptical-interviewer.md` (from interviewer.md) and
  `.claude/agents/quantify-coach.md` (from suggest-quantification.md, patterns rewritten for marketing). Both
  read-only (Read, Glob, Grep), reply in chat instead of writing `working/` files. License:
  `docs/licenses/resume-helper-LICENSE.txt`.
- Not installed: writer, coach, fact-checker, loop commands, scripts; ats-resume-agent; career-ops.
