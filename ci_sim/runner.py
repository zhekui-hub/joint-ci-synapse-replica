"""Run a lightweight Synapse replica job while preserving dependencies."""
import hashlib
import json
import os
import sys


def main():
    repo = os.environ.get("REPLICA_REPOSITORY", "unknown")
    workflow = os.environ.get("REPLICA_SOURCE_WORKFLOW", "unknown")
    job = os.environ.get("REPLICA_SOURCE_JOB", "unknown")
    scope = os.environ.get("REPLICA_SCOPE", "private")
    matrix = os.environ.get("MATRIX_JSON", "{}")
    failure = os.environ.get("SIMULATE_FAILURE", "")
    needs = json.loads(os.environ.get("NEEDS_JSON", "{}"))
    allow_skipped = os.environ.get("REPLICA_ALLOW_SKIPPED_NEEDS", "").lower() == "true"
    failed_needs = {
        key: value.get("result")
        for key, value in needs.items()
        if value.get("result") != "success"
        and not (allow_skipped and value.get("result") == "skipped")
    }
    identity = f"{repo}:{workflow}:{job}:{matrix}"
    result = "failure" if failed_needs or failure in (repo, workflow, job, "all") else "success"
    event = {
        "repo": repo,
        "workflow": workflow,
        "job": job,
        "scope": scope,
        "execution_owner": os.environ.get("REPLICA_EXECUTION_OWNER", "participant"),
        "matrix": matrix,
        "result": result,
        "failed_needs": failed_needs,
        "test_key": "replica-" + hashlib.sha256(identity.encode()).hexdigest()[:16],
    }
    print(json.dumps(event, sort_keys=True))
    if result != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()
