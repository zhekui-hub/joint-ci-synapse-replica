"""Dispatch a targeted shared-test rerun to Arsenal."""
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

payload = json.loads(os.environ.get("JOINT_RERUN_INPUTS", "{}"))
required = ["joint_key", "head_sha", "test_name"]
if any(not payload.get(key) for key in required):
    raise SystemExit("joint_key, head_sha, and test_name are required")
if len(payload["head_sha"]) != 40:
    raise SystemExit("head_sha must be a full commit SHA")
repository = os.environ.get("GITHUB_REPOSITORY", "")
token = os.environ.get("JOINT_DISPATCH_TOKEN", "").strip()
if not token or "/" not in repository:
    raise SystemExit("dispatch configuration is incomplete")
body = {
    "event_type": "joint_ci_rerun",
    "client_payload": {
        "participant_repository": repository,
        "head_sha": payload["head_sha"],
        "joint_key": payload["joint_key"],
        "test_name": payload["test_name"],
    },
}
request = Request(
    "https://api.github.com/repos/zhekui-hub/joint-ci-arsenal-replica/dispatches",
    data=json.dumps(body).encode(),
    method="POST",
    headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    },
)
try:
    with urlopen(request, timeout=30) as response:
        print(f"JOINT_RERUN_DISPATCH={response.status}")
        if response.status != 204:
            raise SystemExit(1)
except HTTPError as exc:
    print(f"JOINT_RERUN_DISPATCH={exc.code}")
    raise SystemExit(1)

