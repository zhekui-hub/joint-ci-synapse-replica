"""Lightweight replica job; propagate dependency failures before simulating work."""
import hashlib
import json
import os
import sys


def main():
    repo = os.environ.get("REPLICA_REPOSITORY", "unknown")
    workflow = os.environ.get("REPLICA_SOURCE_WORKFLOW", "unknown")
    job = os.environ.get("REPLICA_SOURCE_JOB", "unknown")
    matrix = os.environ.get("MATRIX_JSON", "{}")
    failure = os.environ.get("SIMULATE_FAILURE", "")
    needs = json.loads(os.environ.get("NEEDS_JSON", "{}"))
    failed_needs = {key: value.get("result") for key, value in needs.items()
                    if value.get("result") != "success"}
    result = "failure" if failed_needs or failure in (repo, workflow, job, "all") else "success"
    identity = f"{repo}:{workflow}:{job}:{matrix}"
    print(json.dumps({"repo": repo, "workflow": workflow, "job": job,
                      "scope": os.environ.get("REPLICA_SCOPE", "private"),
                      "matrix": matrix, "result": result, "failed_needs": failed_needs,
                      "test_key": "replica-" + hashlib.sha256(identity.encode()).hexdigest()[:16]},
                     sort_keys=True))
    return 0 if result == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
