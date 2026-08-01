# Working with the Agent During Each Phase

## First message

Use the phase prompt as written. Do not add instructions such as "build everything" or "continue
through the rest of the project."

## During implementation

Allow the agent to:

- Read the project.
- Modify files inside the repository.
- Run uv, pytest, Ruff, Mypy, and safe Docker validation.
- Search documentation when necessary and when web access is enabled.

Require direct human approval before:

- Terraform apply or destroy.
- AWS resource changes.
- GitHub push.
- Deleting large files or rewriting history.

## If the agent stops after producing only a plan

Send:

```text
Proceed with the implementation for the current phase. Keep the phase boundary, run the required tests, and finish with evidence. Do not only describe the plan.
```

## If the agent claims completion without tests

Send:

```text
The phase is not complete. Run every required validation command from the phase prompt, fix failures, and report the exact command results. Do not weaken tests or configuration.
```

## If the same failure occurs more than twice

Increase the reasoning level from XHigh to Max and provide the exact failure output rather than a
general description. For example:

```text
Diagnose the failures below before editing. Identify the root cause, propose the smallest correct fix, implement it, and rerun the failing test followed by the full phase gate.

<PASTE OUTPUT>
```

## After each phase

Review:

```bash
git diff --check
git diff --stat
make verify
```

Then create the commit manually.
