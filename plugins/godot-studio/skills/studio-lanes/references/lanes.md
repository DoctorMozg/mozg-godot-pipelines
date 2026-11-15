# Lanes in practice

## The subagent prompt

The brief is the whole hand-off; the prompt around it stays short. For a coder:

```text
You are the coder of lane <id>. Work only as this brief says:

<the brief from studiokit lane brief, verbatim>

Write the change, run the checks the brief names, and commit on the lane's branch.
Reply with the branch, the commit and each check's JSON line. If you need a file you
do not own, or a frozen test looks wrong, stop and say so instead of working around it.
```

A test writer gets the same brief with "write and commit only tests for the task that fail now; do not touch production code" in place of the second paragraph. Use `mz-dev-pipe:pipeline-coder` and `pipeline-test-writer` when they are installed, `general-purpose` otherwise, always in the background.

## A worked example

A plan has two tasks: a health bar for the HUD (P3) and a dash for the player (P4).

```bash
studiokit lane new hud --task docs/plan.md#P3 --own 'scenes/hud/*' --own 'scripts/hud/*' \
  --own 'tests/hud/*' --risk normal
studiokit lane new dash --task docs/plan.md#P4 --own 'scripts/player/dash.gd' \
  --own 'tests/player/test_dash.gd' --check 'godotkit test --changed' --risk normal
```

Both open: no tracked file matches both. The dash needs a new input action in `project.godot`, so its coder writes `.mozg/requests/dash-input.md` ("add action `dash`, key Shift") rather than editing the file. After the test writers commit, `studiokit lane freeze hud 'tests/hud/*'` and `studiokit lane freeze dash tests/player/test_dash.gd` lock the suites, and the coders start.

The dash lane returns first. `studiokit lane check dash` is clean; `studiokit merge dash` lands "Merge verified dash" and lists `.mozg/requests/dash-input.md`. The orchestrator adds the action in the main checkout, runs `godotkit gate`, commits "Add dash input action" and deletes the request file in the same commit. The HUD lane merges after it.

## Risk and review depth

| Risk     | When                                                       | Before the merge                          |
| -------- | ---------------------------------------------------------- | ----------------------------------------- |
| `low`    | renames, caller migrations, moves with no new behaviour    | `lane check` (gate receipt, ownership)    |
| `normal` | new behaviour inside existing systems                      | tests first, frozen, then `lane check`    |
| `high`   | a new system, autoload or layer edge; a save format change | as `normal`, plus `architecture-reviewer` |

A `high` lane whose design has no accepted record goes to `studio-decide` before it opens.

## Rebasing a conflicting lane

`studiokit merge` refuses a lane that conflicts with main and names main's commit. The lane's coder, in the lane's worktree:

```bash
git rebase <named commit>
godotkit gate --project <lane project>
```

Then `studiokit lane check <id>` and `studiokit merge <id>` again. The check diffs from where the lane left main (the merge-base with main's HEAD), so after a rebase main's own changes never count against the lane. A rebase that would touch a frozen test is a stop: the frozen hash was made for the old base.

## Applying requests

A request is a short markdown file a lane commits under `.mozg/requests/`: what to change in which single-writer file, and why. `studiokit merge` lists the ones the lane added. For each, in the main checkout:

1. Make the change it asks for, or decide not to and say why in the report.
1. Delete the request file.
1. `godotkit gate`, then commit both together.

## The task state after each merge

The orchestrator's task state (`.mz/task/<task>/state.md` or the plan's status table) records, per merge: the lane id, the merge commit, the requests applied, and the next ready task. `studiokit lane list --all` is the lane-side record; the task state does not copy it, it points at the merge commits.

## When lanes are the wrong tool

- One file, one small change: the main checkout and a gate.
- Work whose files cannot be known before starting (an exploratory spike): a scratch worktree from `godotkit worktree new`, thrown away after; its findings become tasks.
- Tasks that all edit the same scene: split the scene first, or run them serially.
