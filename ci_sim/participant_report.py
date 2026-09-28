"""Build a participant report, publish a pending readiness status, and dispatch it to Arsenal."""
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

TARGET = "zhekui-hub/joint-ci-arsenal-replica"
STATUS_CONTEXT = os.environ.get("JOINT_STATUS_CONTEXT", "Joint CI readiness")


def set_local_status(token, repository, sha, state, description):
    if not token or not repository or len(sha) != 40:
        return False
    endpoint = f"https://api.github.com/repos/{repository}/statuses/{sha}"
    payload = {
        "state": state,
        "context": STATUS_CONTEXT,
        "description": description[:140],
        "target_url": (
            f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
            f"{repository}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"
        ),
    }
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
            "User-Agent": "joint-ci-participant-replica",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            print(f"JOINT_STATUS_HTTP_STATUS={response.status}", flush=True)
            return response.status == 201
    except HTTPError as exc:
        print(f"JOINT_STATUS_HTTP_STATUS={exc.code}", file=sys.stderr, flush=True)
        return False


def resolve_joint_id(pr, branch):
    body = pr.get("body", "") or ""
    for line in body.splitlines():
        if line.startswith("DLC_KERNEL_DRIVER_BRANCH="):
            value = line.split("=", 1)[1].strip()
            if value and value != "DEFAULT_BRANCH":
                return value
    return os.environ.get("JOINT_CI_ID") or branch


def main():
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    event = json.loads(Path(event_path).read_text()) if event_path else {}
    pr = event.get("pull_request", {})
    head = pr.get("head", {})
    branch = head.get("ref") or os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME", "")
    sha = head.get("sha") or os.environ.get("GITHUB_SHA", "")
    report = {
        "schema_version": 1,
        "joint_id": resolve_joint_id(pr, branch),
        "repo": os.environ.get("REPLICA_REPOSITORY", "unknown"),
        "branch": branch,
        "head_sha": sha,
        "pr_number": str(event.get("number", 0)),
        "ci_mode": "joint",
        "is_draft": bool(pr.get("draft", False)),
        "deps": json.loads(os.environ.get("JOINT_DEPS_JSON", "{}")),
        "required_members": json.loads(os.environ.get("JOINT_MEMBERS_JSON", '["driver", "synapse"]')),
        "source_run_id": int(os.environ.get("GITHUB_RUN_ID", "0")),
        "source_run_attempt": int(os.environ.get("GITHUB_RUN_ATTEMPT", "1")),
        "private_result": "unknown",
        "remote_tests": [{"id": "public.smoke", "params": {"profile": "default"}}],
    }
    if not branch or len(sha) != 40:
        raise ValueError("report requires a branch and a full commit SHA")
    Path("joint-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, sort_keys=True), flush=True)
    if os.environ.get("JOINT_REPORT_ONLY", "false").lower() == "true":
        print("REPORT_ONLY: no cross-repository dispatch attempted")
        return 0

    local_token = os.environ.get("GITHUB_TOKEN", "").strip()
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not set_local_status(local_token, repository, sha, "pending", "Waiting for all joint CI participants"):
        print("JOINT_STATUS_BLOCKED: cannot create pending readiness status", file=sys.stderr)
        return 1

    token = os.environ.get("JOINT_DISPATCH_TOKEN", "").strip()
    if not token:
        set_local_status(local_token, repository, sha, "failure", "Joint CI dispatch token is missing")
        print("DISPATCH_BLOCKED: JOINT_DISPATCH_TOKEN missing", file=sys.stderr)
        return 1
    if os.environ.get("JOINT_TARGET_REPO", TARGET) != TARGET:
        raise ValueError("dispatch target must be the private Arsenal replica")
    payload = {"event_type": "joint_ci_report", "client_payload": {"report": report}}
    request = Request(
        f"https://api.github.com/repos/{TARGET}/dispatches",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            print(f"DISPATCH_HTTP_STATUS={response.status}")
            if response.status != 204:
                set_local_status(local_token, repository, sha, "failure", "Joint CI report dispatch failed")
                return 1
            return 0
    except HTTPError as exc:
        set_local_status(local_token, repository, sha, "failure", "Joint CI report dispatch failed")
        print(f"DISPATCH_HTTP_STATUS={exc.code}; report retained as artifact", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
