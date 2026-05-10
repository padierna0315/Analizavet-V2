# Skill Registry

**Delegator use only.** Any agent that launches sub-agents reads this registry to resolve compact rules, then injects them directly into sub-agent prompts. Sub-agents do NOT read this registry or individual SKILL.md files.

See `_shared/skill-resolver.md` for the full resolution protocol.

## User Skills

| Trigger | Skill | Path |
|---------|-------|------|
| creating, opening, or preparing PRs for review | branch-pr | /home/laboratorio/.config/opencode/skills/branch-pr/SKILL.md |
| PRs over 400 lines, stacked PRs, review slices | gentle-ai-chained-pr | /home/laboratorio/.config/opencode/skills/chained-pr/SKILL.md |
| writing guides, READMEs, RFCs, onboarding, architecture, or review-facing docs | cognitive-doc-design | /home/laboratorio/.config/opencode/skills/cognitive-doc-design/SKILL.md |
| PR feedback, issue replies, reviews, Slack messages, or GitHub comments | comment-writer | /home/laboratorio/.config/opencode/skills/comment-writer/SKILL.md |
| Go tests, go test coverage, Bubbletea teatest, golden files | go-testing | /home/laboratorio/.config/opencode/skills/go-testing/SKILL.md |
| creating GitHub issues, bug reports, or feature requests | issue-creation | /home/laboratorio/.config/opencode/skills/issue-creation/SKILL.md |
| judgment day, dual review, adversarial review, juzgar | judgment-day | /home/laboratorio/.config/opencode/skills/judgment-day/SKILL.md |
| new skills, agent instructions, documenting AI usage patterns | skill-creator | /home/laboratorio/.config/opencode/skills/skill-creator/SKILL.md |
| update skills, skill registry, actualizar skills, or after skill changes | skill-registry | /home/laboratorio/.config/opencode/skills/skill-registry/SKILL.md |
| implementation, commit splitting, chained PRs, or keeping tests and docs with code | work-unit-commits | /home/laboratorio/.config/opencode/skills/work-unit-commits/SKILL.md |

## Compact Rules

Pre-digested rules per skill. Delegators copy matching blocks into sub-agent prompts as `## Project Standards (auto-resolved)`.

### branch-pr
- Create pull requests with issue-first checks
- Always link PR to an existing issue
- Keep PR descriptions concise

### gentle-ai-chained-pr
- Split oversized changes (>400 lines) into chained PRs
- Protect review focus by keeping PRs atomic
- Ensure tests run per chained step

### cognitive-doc-design
- Design docs that reduce cognitive load
- Focus on clarity and ease of reading
- Use clear headings and structured formatting

### comment-writer
- Write warm, direct collaboration comments
- Provide actionable feedback
- Respect the other developer's perspective

### go-testing
- Apply focused Go testing patterns
- Use golden files where appropriate
- Maintain high test coverage for Go components

### issue-creation
- Create issues with issue-first checks
- Verify bug reports before creating issues
- Provide reproduction steps for bugs

### judgment-day
- Run blind dual review
- Fix confirmed issues, then re-judge
- Document all review findings

### skill-creator
- Create LLM-first skills with valid frontmatter
- Document triggers and patterns clearly
- Keep skills modular and focused

### skill-registry
- Update the project skill registry after skill changes
- Write `.atl/skill-registry.md` and save to Engram

### work-unit-commits
- Plan commits as reviewable work units
- Keep tests and docs alongside the code changes
- Use conventional commits

## Project Conventions

| File | Path | Notes |
|------|------|-------|
| None | None | |
