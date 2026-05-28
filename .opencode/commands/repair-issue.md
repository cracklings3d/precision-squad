---
description: Dry-run publish a GitHub issue repair
---

Handle GitHub issue repair requests only.

Before continuing, load or use the `precision-squad` skill from `skills/precision-squad/SKILL.md`.

Treat `$1` as `issue_ref`.

- `issue_ref` is required and must be in `owner/repo#number` format.
- If `$1` is missing, ask the user for `issue_ref` before running anything.

Treat `$2` as `repo_path`.

- `repo_path` is required and must be the local checkout path of the target repository.
- If `$2` is missing, ask the user for `repo_path` before running anything.
- If you are already in the target repository root, `repo_path` may be `.` and the command may use `--repo-path .`.

After both values are known, run only:

`python -m precision_squad.cli repair issue <issue_ref> --repo-path <repo_path> --publish --dry-run`
