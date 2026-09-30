"""Mirror Arsenal's shared matrix as native checks in this participant repository."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API = "https://api.github.com"
VERSION = "2022-11-28"
ALLOWED_PARTICIPANTS = {
    "zhekui-hub/joint-ci-driver-replica",
    "zhekui-hub/joint-ci-synapse-replica",
    "zhekui-hub/joint-ci-sim-replica",
}


def token():
    value = os.environ.get("GITHUB_TOKEN", "").strip()
    if not value:
        raise SystemExit("GITHUB_TOKEN missing")
    return value


def request(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(
        API + "/" + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": VERSION,
            "Content-Type": "application/json",
            "User-Agent": "joint-ci-participant-check-mirror",
        },
    )
    try:
        with urlopen(req, timeout=30) as response:
            body = response.read().decode()
            return json.loads(body) if body else {}
    except HTTPError as exc:
        print(f"MIRROR_CHECK_HTTP={exc.code} path={path}")
        return None
    except URLError as exc:
        print(f"MIRROR_CHECK_NETWORK={exc.reason} path={path}")
        return None


def iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_sha(value):
    return isinstance(value, str) and len(value) == 40 and all(
        char in "0123456789abcdefABCDEF" for char in value
    )


def validate_payload(payload, repository):
    """Ensure a relay can only publish checks for this exact participant SHA."""
    phase = payload.get("phase")
    repo = payload.get("participant_repository") or repository
    sha = payload.get("head_sha")
    snapshot = payload.get("participant_snapshot")
    required = payload.get("required_participants")
    if phase not in {"running", "completed"} or repo != repository:
        raise SystemExit("invalid participant repository or phase")
    if repo not in ALLOWED_PARTICIPANTS or not is_sha(sha):
        raise SystemExit("invalid participant repository or head SHA")
    if not isinstance(snapshot, dict) or not snapshot:
        raise SystemExit("participant snapshot is required")
    if any(key not in ALLOWED_PARTICIPANTS or not is_sha(value) for key, value in snapshot.items()):
        raise SystemExit("participant snapshot contains an invalid repository or SHA")
    if snapshot.get(repo) != sha:
        raise SystemExit("head SHA does not match participant snapshot")
    if required is not None:
        if not isinstance(required, list) or set(required) != set(snapshot) or repo not in required:
            raise SystemExit("participant snapshot is incomplete")
    return phase, repo, sha


def check_name(test):
    """Use the short native-check name requested by the participant repos."""
    job = test.get("job") or test.get("id") or "shared-test"
    return f"joint/{job}"


def existing_checks(repo, sha):
    checks = []
    for page in range(1, 21):
        response = request(
            "GET", f"repos/{repo}/commits/{sha}/check-runs?per_page=100&page={page}"
        )
        if response is None:
            raise SystemExit("cannot list participant check runs")
        batch = response.get("check_runs", [])
        checks.extend(batch)
        if len(batch) < 100:
            break
    return {
        (item.get("external_id"), item.get("name")): item.get("id")
        for item in checks
    }


def output(test, phase, target):
    result = test.get("result", "pending")
    summary = (
        "Arsenal is running this shared test once; this participant check is a mirror."
        if phase == "running"
        else f"Arsenal ran this shared test once; result: **{result}**."
    )
    matrix = json.dumps(test.get("matrix", {}), ensure_ascii=False, sort_keys=True)
    needs = json.dumps(test.get("needs", []), ensure_ascii=False)
    text = "\n".join(
        [
            f"### {check_name(test)}",
            f"- Test ID: `{test.get('id', 'unknown')}`",
            f"- Workflow: `{test.get('workflow', 'unknown')}`",
            f"- Job: `{test.get('job', 'unknown')}`",
            f"- Matrix: `{matrix}`",
            f"- Needs: `{needs}`",
            f"- Runner: `{test.get('runner', 'grok-box-arsenal')}`",
            "- Execution owner: `arsenal`",
            f"- Arsenal job: [Open job]({target})",
            f"- Manual rerun: https://github.com/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/workflows/joint_ci_rerun.yml",
        ]
    )
    return {
        "title": "Arsenal shared test running" if phase == "running" else f"Arsenal shared test {result}",
        "summary": summary,
        "text": text,
    }


def upsert(repo, sha, joint_key, test, phase, check_id=None, target=None):
    external_id = f"{joint_key}:{test['id']}"
    target = target or os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    payload = {
        "name": check_name(test),
        "head_sha": sha,
        "external_id": external_id,
        "status": "in_progress" if phase == "running" else "completed",
        "details_url": target,
        "output": output(test, phase, target),
    }
    if phase == "running":
        payload["started_at"] = iso_now()
    else:
        payload["conclusion"] = {
            "success": "success",
            "failure": "failure",
            "cancelled": "cancelled",
            "skipped": "neutral",
        }.get(test.get("result"), "neutral")
        payload["completed_at"] = iso_now()
    path = f"repos/{repo}/check-runs"
    if check_id:
        path += f"/{check_id}"
        response = request("PATCH", path, payload)
    else:
        response = request("POST", path, payload)
    return bool(response and response.get("id"))


def main():
    payload = json.loads(os.environ.get("JOINT_CHECK_PAYLOAD", "{}"))
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    phase, repo, sha = validate_payload(payload, repository)
    joint_key = payload.get("joint_key", "")
    tests = payload.get("tests", [])
    if not joint_key:
        raise SystemExit("invalid joint check mirror payload")
    if not tests:
        raise SystemExit("joint check mirror payload has no tests")

    existing = existing_checks(repo, sha)
    target_default = payload.get("public_run_url", "")
    work = []
    for test in tests:
        key = (f"{joint_key}:{test['id']}", check_name(test))
        work.append((test, existing.get(key), test.get("target_url") or target_default))
    with ThreadPoolExecutor(max_workers=12) as pool:
        ok = all(
            pool.map(
                lambda item: upsert(repo, sha, joint_key, item[0], phase, item[1], item[2]),
                work,
            )
        )
    if not ok:
        raise SystemExit("one or more participant Check Runs could not be updated")
    print(json.dumps({"repo": repo, "sha": sha, "phase": phase, "tests": len(tests)}))


if __name__ == "__main__":
    main()
