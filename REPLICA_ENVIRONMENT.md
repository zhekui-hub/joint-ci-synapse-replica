# Production CI replica environment

- Source repository: `ChipLTech/DLCSynapse`
- Source main SHA: `be4dd338979bbab8c628ec1ee58aadc47d7d2567`
- Replica mode: `dry-run`
- Runner label: `grok-box`
- Heavy production commands are replaced by `python3 ci_sim/runner.py`.
- Required checks are documented in `replica-gate-policy.json`; GitHub branch protection is intentionally not changed.
- The Grok Bot cloud runner must be registered for this repository with labels `self-hosted` and `grok-box` before dispatch.
- Suggested dispatch: `gh workflow run <workflow.yml> --repo zhekui-hub/joint-ci-synapse-replica --ref zhekui/chore-production-ci-replica-20260928`
- Production gate check names are retained where the source ruleset requires them; only the implementation behind the check is simulated.
- Participant reports fail closed when `JOINT_DISPATCH_TOKEN` is absent or dispatch returns a non-204 response; the report is retained as an artifact.
- Arsenal replica stores cross-run participant state in private issue #1; the checkout directory is only a cache.
