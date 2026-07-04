Run `git diff` (staged and unstaged) and `git status` to understand what has changed, then compose a commit message following the format below. Show me the staged files and the commit message for review before committing or pushing.

## Commit message format

```
<type>: <short description>
- <optional additional line>
- <optional additional line>
```

### Types

| Type | When to use |
|------|-------------|
| `feat` | New feature or functionality |
| `fix` | Bug, error, or crash fix |
| `chore` | Maintenance with no source/test changes (e.g. `.gitignore`, package bumps) |
| `docs` | Documentation-only changes (README, wikis, inline comments) |
| `refactor` | Restructuring production code without behavior change |
| `style` | Formatting only — indentation, semicolons, whitespace |
| `test` | Adding or updating automated tests without touching production code |
| `perf` | Runtime speed or resource usage improvements |
| `ci` | CI/CD config changes (GitHub Actions, GitLab pipelines, etc.) |
| `build` | Build pipeline, dependencies, or packaging changes |
| `revert` | Reverting a prior commit |

## Steps

1. Run `git diff HEAD` and `git status` to see all changes.
2. Choose the appropriate `<type>` from the table above.
3. Write a concise `<description>` (imperative mood, ≤72 chars total for the first line).
4. Add bullet lines only when the single-line description is insufficient to capture important details.
5. **Show the user the proposed commit message and the list of files that will be staged, and wait for approval before proceeding.**
6. Once approved, stage the relevant files, create the commit, and push to the current remote branch.

## Commit command template

```bash
git commit -m "$(cat <<'EOF'
<type>: <description>
- <optional line>
EOF
)"
```
