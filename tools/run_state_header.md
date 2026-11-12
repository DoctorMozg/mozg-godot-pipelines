The first line is `schema_version: 2`. `Status` is `running`, `blocked` (an answer is awaited and has not come) or `complete`.

```text
schema_version: 2
Status: running
Phase: 1
Started: <ISO timestamp>
phase_complete: false
what_remains: [step names, in order]
Project: <slug>
```

Refresh `what_remains` after each step. At the hand-over set `Status: complete`, `phase_complete: true` and `what_remains: []`. A state that exists when the run opens is read and resumed from its next incomplete step, never started over.
