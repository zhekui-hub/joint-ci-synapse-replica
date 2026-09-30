# Shared checks without a custom GitHub App

Push the matching Driver and Synapse branches to request the shared lightweight
build, unit, and integration jobs in Arsenal. A missing branch leaves only the
joint summary queued. Creating a PR is not a prerequisite for running tests.

Each participant repository publishes its own per-test Checks using its workflow
GITHUB_TOKEN. The check contains the original steps and links to the exact Arsenal
job log. Use the participant relay workflow to request failed, all, or single-job
reruns; a mirrored Check is not a native Actions job with a native rerun button.

This isolated demonstration targets the implementation branch. Production branch
protection and normal CI are not replaced by this demonstration.
