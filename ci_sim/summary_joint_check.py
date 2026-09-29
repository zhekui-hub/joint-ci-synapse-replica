"""Publish one participant-facing Check Run for the Arsenal shared matrix.

The individual test rows remain commit statuses owned by Arsenal.  This file
only creates/updates one aggregate Check Run so the PR Checks page has a
clickable, readable matrix without duplicating every test as a Check Run.
"""
import json
import os
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API = "https://api.github.com"
API_VERSION = "2022-11-28"
CHECK_NAME = "Joint CI public"
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
        f"{API}/{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "Content-Type": "application/json",
            "User-Agent": "joint-ci-public-summary",
        },
    )
    try:
        with urlopen(req, timeout=30) as response:
            body = response.read().decode()
            return json.loads(body) if body else {}
    except HTTPError as exc:
        print(f"SUMMARY_CHECK_HTTP={exc.code} path={path}")
        return None
    except URLError as exc:
        print(f"SUMMARY_CHECK_NETWORK={exc.reason} path={path}")
        return None


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def cell(value):
    """Keep payload values safe and compact inside a Markdown table cell."""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    value = str(value if value is not None else "-")
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def check_runs(repo, sha):
    found = []
    for page in range(1, 21):
        response = request("GET", f"repos/{repo}/commits/{sha}/check-runs?per_page=100&page={page}")
        if response is None:
            raise SystemExit("cannot list participant check runs")
        batch = response.get("check_runs", [])
        found.extend(batch)
        if len(batch) < 100:
            break
    return found


def _is_sha(value):
    return isinstance(value, str) and len(value) == 40 and all(
        char in "0123456789abcdefABCDEF" for char in value
    )


def validate_payload(payload, repository):
    """Reject a summary that could write to a different PR or repository."""
    phase = payload.get("phase")
    repo = payload.get("participant_repository")
    sha = payload.get("head_sha")
    snapshot = payload.get("participant_snapshot")
    required = payload.get("required_participants")
    if phase not in {"running", "completed"} or repo != repository:
        raise ValueError("participant repository does not match the workflow repository")
    if repo not in ALLOWED_PARTICIPANTS or not _is_sha(sha):
        raise ValueError("participant repository or head SHA is not valid")
    if not isinstance(snapshot, dict) or not snapshot:
        raise ValueError("participant snapshot is required")
    if any(not isinstance(key, str) or key not in ALLOWED_PARTICIPANTS for key in snapshot):
        raise ValueError("participant snapshot contains an unknown repository")
    if any(not _is_sha(value) for value in snapshot.values()):
        raise ValueError("participant snapshot contains an invalid SHA")
    if snapshot.get(repo) != sha:
        raise ValueError("head SHA does not match this repository snapshot")
    if required is not None:
        if not isinstance(required, list) or not required:
            raise ValueError("required participants must be a non-empty list")
        required_set = set(required)
        if required_set != set(snapshot) or repo not in required_set:
            raise ValueError("participant snapshot is incomplete for required participants")
    return phase, repo, sha, snapshot


def select_existing(checks, external_id):
    """Reuse this generation, or repair a legacy same-name check on this SHA."""
    exact = [item for item in checks if item.get("external_id") == external_id]
    if exact:
        return exact[0]
    same_name = [
        item
        for item in checks
        if item.get("name") == CHECK_NAME
        and not item.get("external_id")
        and (item.get("app") or {}).get("slug") == "github-actions"
    ]
    same_name.sort(
        key=lambda item: item.get("completed_at") or item.get("started_at") or "",
        reverse=True,
    )
    return same_name[0] if same_name else None


def is_explicit_rerun(payload):
    value = payload.get("rerun", False)
    return value is True or str(value).lower() == "true"


def is_stale_running(existing, phase, payload):
    return bool(
        existing
        and existing.get("status") == "completed"
        and phase == "running"
        and not is_explicit_rerun(payload)
    )


def rerun_url(repository):
    return f"https://github.com/{repository}/actions/workflows/joint_ci_rerun.yml"


def render(payload, tests, phase):
    results = [test.get("result", "pending") for test in tests]
    passed = sum(result == "success" for result in results)
    failed = sum(result == "failure" for result in results)
    running = len(results) - passed - failed
    total = len(results)
    if phase == "running":
        title = f"Arsenal shared matrix running ({passed}/{total} passed)"
        summary = "Arsenal is executing this shared matrix once; this check is a participant view."
    else:
        if failed:
            outcome = "failed"
        elif running:
            outcome = "incomplete"
        else:
            outcome = "passed"
        title = f"Arsenal shared matrix {outcome} ({passed}/{total})"
        summary = f"Arsenal executed the shared matrix once: {passed}/{total} passed"
        if failed:
            summary += f", {failed} failed"
        if running:
            summary += f", {running} pending"
        summary += "."
    lines = [
        "Arsenal owns execution; this participant check is a single aggregate view.",
        "",
        f"**Joint:** `{cell(payload.get('joint_id', 'unknown'))}`  ",
        f"**Joint key:** `{cell(payload.get('joint_key', 'unknown'))}`  ",
        f"**Participant:** `{cell(payload.get('participant_repository', 'unknown'))}`  ",
        f"**Head SHA:** `{cell(payload.get('head_sha', 'unknown'))}`  ",
        f"**Matrix:** `{passed}/{total} passed`  ",
        f"**Arsenal run:** {payload.get('public_run_url') or '-'}",
        "",
        "| Test | Workflow | Job | Matrix | Needs | Runner | Result | Arsenal job | Rerun |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    rerun = rerun_url(payload.get("participant_repository", ""))
    for test in tests:
        result = test.get("result", "pending")
        target = test.get("target_url") or payload.get("public_run_url") or "#"
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{cell(test.get('display_name') or test.get('id', 'unknown'))}`",
                    f"`{cell(test.get('workflow', 'unknown'))}`",
                    f"`{cell(test.get('job', 'unknown'))}`",
                    f"`{cell(test.get('matrix', {}))}`",
                    f"`{cell(test.get('needs', []))}`",
                    f"`{cell(test.get('runner', 'grok-box-arsenal'))}`",
                    f"**{cell(result)}**",
                    f"[job]({target})",
                    f"[workflow]({rerun})",
                ]
            )
            + " |"
        )
    text = "\n".join(lines)
    # Check Run output is bounded.  Preserve the table header and a link to the
    # complete Arsenal run if an unusually large catalog exceeds the API limit.
    if len(text) > 60000:
        text = text[:59000] + "\n\n[Full matrix in Arsenal]({})\n".format(
            payload.get("public_run_url") or "#"
        )
    return title, summary, text


def main():
    payload = json.loads(os.environ.get("JOINT_CHECK_PAYLOAD", "{}"))
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    try:
        phase, repo, sha, _snapshot = validate_payload(payload, repository)
    except ValueError as exc:
        raise SystemExit(f"SUMMARY_CHECK_BLOCKED: {exc}")
    joint_key = payload.get("joint_key", "")
    tests = payload.get("tests", [])
    if not joint_key:
        raise SystemExit("invalid joint summary payload: joint_key is required")
    if not isinstance(tests, list) or not tests:
        raise SystemExit("joint summary payload has no tests")

    external_id = f"{joint_key}:summary"
    checks = check_runs(repo, sha)
    existing = select_existing(checks, external_id)
    if is_stale_running(existing, phase, payload):
        raise SystemExit("SUMMARY_CHECK_BLOCKED: stale running update after completed summary")
    title, summary, text = render(payload, tests, phase)
    completed = phase == "completed"
    results = [test.get("result", "pending") for test in tests]
    body = {
        "name": CHECK_NAME,
        "head_sha": sha,
        "external_id": external_id,
        "status": "completed" if completed else "in_progress",
        "details_url": payload.get("public_run_url") or f"https://github.com/{repo}/actions",
        "output": {"title": title[:255], "summary": summary[:65535], "text": text},
    }
    if completed:
        if any(result == "failure" for result in results):
            body["conclusion"] = "failure"
        elif any(result not in {"success"} for result in results):
            body["conclusion"] = "neutral"
        else:
            body["conclusion"] = "success"
        body["completed_at"] = now_iso()
    else:
        body["started_at"] = now_iso()

    path = f"repos/{repo}/check-runs"
    if existing:
        path += f"/{existing['id']}"
    response = request("PATCH" if existing else "POST", path, body)
    if not response or not response.get("id"):
        raise SystemExit("could not publish aggregate Joint CI public check")
    print(json.dumps({"repo": repo, "sha": sha, "phase": phase, "check_id": response["id"]}))


if __name__ == "__main__":
    main()
