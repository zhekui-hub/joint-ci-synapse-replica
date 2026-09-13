# synapse joint CI replica

This private repository is a dry-run replica of the real ChipLTech `synapse` repository.

- source `main` SHA: `acfe7ff8b51d2fe6391301af0eb5b159720f3a21`
- source workflows/jobs: `10` / `20`
- active runner label: `replica-synapse`
- matrix catalog: `test-catalog.json`

The original workflow YAML is retained under `.ci-source/workflows`. The active `.github/workflows` files preserve names, job IDs, needs edges, triggers, and matrix dimensions, but replace test bodies with `ci_sim/runner.py`. Push, release, and schedule side effects are disabled.

Dispatch `joint_ci_hook.yml` for the participant gate. Arsenal also exposes `joint_ci_replica.yml`, which consumes driver/synapse/sim reports and records a joint state artifact.
