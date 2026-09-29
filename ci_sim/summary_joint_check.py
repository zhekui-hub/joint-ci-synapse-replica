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
        title = f"Arsenal shared matrix {'passed' if failed == 0 else 'failed'} ({passed}/{total})"
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


payload = json.loads(os.environ.get("JOINT_CHECK_PAYLOAD", "{}"))
phase = payload.get("phase")
repo = payload.get("participant_repository") or os.environ.get("GITHUB_REPOSITORY", "")
sha = payload.get("head_sha", "")
joint_key = payload.get("joint_key", "")
tests = payload.get("tests", [])
if phase not in {"running", "completed"} or "/" not in repo or len(sha) != 40 or not joint_key:
    raise SystemExit("invalid joint summary payload")
if not isinstance(tests, list) or not tests:
    raise SystemExit("joint summary payload has no tests")

external_id = f"{joint_key}:summary"
existing = next(
    (
        check
        for check in check_runs(repo, sha)
        if check.get("external_id") == external_id and check.get("name") == CHECK_NAME
    ),
    None,
)
title, summary, text = render(payload, tests, phase)
completed = phase == "completed"
body = {
    "name": CHECK_NAME,
    "head_sha": sha,
    "external_id": external_id,
    "status": "completed" if completed else "in_progress",
    "details_url": payload.get("public_run_url") or f"https://github.com/{repo}/actions",
    "output": {"title": title[:255], "summary": summary[:65535], "text": text},
}
if completed:
    body["conclusion"] = "success" if not any(t.get("result") != "success" for t in tests) else "failure"
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
