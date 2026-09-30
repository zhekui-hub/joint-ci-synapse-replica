"""Author: zhekui.

Publish source-verified shared checks with this workflow's GITHUB_TOKEN.
load_source binds an immutable artifact to live refs and the source attempt;
publish updates local checks; request_rerun delegates execution to Arsenal.
"""
import hashlib
import io
import json
import os
import re
import time
import zipfile
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

SOURCE = "zhekui-hub/joint-ci-arsenal-replica"
SOURCE_PATH = ".github/workflows/joint_ci_app_smoke.yml"
SOURCE_REF = "zhekui/feat-joint-ci-actions-20260930"
SOURCE_NAME = "Joint CI Actions smoke"
DEMO_REF = "zhekui/feat-no-app-demo-20260930"
PARTICIPANTS = {
    "driver": "zhekui-hub/joint-ci-driver-replica",
    "synapse": "zhekui-hub/joint-ci-synapse-replica",
}
TESTS = ["build", "unit", "integration"]
OPERATIONS = {"sync", "pending", "failed", "all", *TESTS}


class RelayError(ValueError):
    pass


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected.remove_header("Authorization")
        return redirected


def api(method, path, payload=None, local=False, binary=False):
    env_key = "GITHUB_TOKEN" if local else "JOINT_DISPATCH_TOKEN"
    credential = os.environ.get(env_key, "").strip()
    if not credential:
        raise RelayError(f"{env_key} missing")
    request = Request(
        "https://api.github.com/" + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {credential}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "joint-ci-actions-relay",
        },
    )
    try:
        with build_opener(SafeRedirect()).open(request, timeout=30) as response:
            content = response.read()
    except HTTPError as exc:
        raise RelayError(f"GitHub HTTP {exc.code}: {method} {path}") from None
    return content if binary else json.loads(content) if content else {}


def paged(path, key, local=False):
    items = []
    for page in range(1, 21):
        separator = "&" if "?" in path else "?"
        response = api("GET", f"{path}{separator}per_page=100&page={page}", local=local)
        batch = response[key]
        items.extend(batch)
        if len(batch) < 100:
            return items
    raise RelayError("pagination limit reached; refusing incomplete source data")


def full_sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def state_key(state):
    identity = {
        "participants": {role: {key: member[key] for key in ("repo", "ref", "sha")}
                         for role, member in state["participants"].items()},
        "source_sha": state["source_sha"], "tests": state["tests"],
        "fail_once": state["fail_once"],
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_state(state, run, repository, run_id, expected_attempt):
    if repository not in PARTICIPANTS.values():
        raise RelayError("unexpected participant repository")
    if (run.get("id") != run_id or run.get("run_attempt") != expected_attempt
            or run.get("path", "").split("@")[0] != SOURCE_PATH
            or run.get("name") != SOURCE_NAME or run.get("event") != "workflow_dispatch"
            or run.get("head_branch") != SOURCE_REF
            or (run.get("repository") or {}).get("full_name") != SOURCE):
        raise RelayError("source run identity or attempt does not match")
    if (state.get("schema") != 1 or state.get("source_repo") != SOURCE
            or str(state.get("run_id")) != str(run_id)
            or state.get("source_ref") != SOURCE_REF
            or not full_sha(state.get("source_sha"))
            or state["source_sha"] != run.get("head_sha")
            or state.get("tests") != TESTS
            or state.get("fail_once") not in {"none", *TESTS}
            or not re.fullmatch(r"[0-9a-f]{64}", str(state.get("key", "")))):
        raise RelayError("source manifest does not match the source execution")
    members = state.get("participants")
    if not isinstance(members, dict) or set(members) != set(PARTICIPANTS):
        raise RelayError("manifest must contain exactly driver and synapse")
    waiting = state.get("waiting", [])
    if (not isinstance(waiting, list) or len(waiting) != len(set(waiting))
            or any(role not in PARTICIPANTS for role in waiting)
            or state.get("ready", not waiting) is not (not waiting)):
        raise RelayError("invalid waiting state")
    for name, repo in PARTICIPANTS.items():
        member = members[name]
        if (not isinstance(member, dict) or member.get("repo") != repo
                or (member.get("sha") is not None if name in waiting else not full_sha(member.get("sha")))
                or not isinstance(member.get("ref"), str) or not member["ref"].strip()
                or type(member.get("pr")) is not int or member["pr"] < 0):
            raise RelayError("invalid participant identity in source manifest")
    if not waiting and state["key"] != state_key(state):
        raise RelayError("frozen snapshot key does not match source inputs")
    local = next(member for member in members.values() if member["repo"] == repository)
    if not full_sha(local["sha"]):
        raise RelayError("cannot publish checks to the missing participant")
    return local


def load_source(repository, run_id, expected_attempt):
    run = api("GET", f"repos/{SOURCE}/actions/runs/{run_id}")
    artifacts = paged(f"repos/{SOURCE}/actions/runs/{run_id}/artifacts", "artifacts")
    selected = [item for item in artifacts if item.get("name") == f"actions-state-{run_id}"]
    if len(selected) != 1 or selected[0].get("expired"):
        raise RelayError("source manifest artifact missing, duplicate, or expired")
    artifact = selected[0]
    if (artifact.get("workflow_run") or {}).get("id", run_id) != run_id:
        raise RelayError("manifest artifact belongs to another source run")
    zipped = api("GET", f"repos/{SOURCE}/actions/artifacts/{artifact['id']}/zip", binary=True)
    with zipfile.ZipFile(io.BytesIO(zipped)) as archive:
        if archive.namelist() != ["state.json"] or archive.getinfo("state.json").file_size > 1048576:
            raise RelayError("invalid source manifest archive")
        state = json.loads(archive.read("state.json"))
    member = validate_state(state, run, repository, run_id, expected_attempt)
    validate_refs(state)
    return run, state, member


def validate_refs(state):
    for participant in state["participants"].values():
        if participant["sha"] is None:
            continue
        repo = participant["repo"]
        ref = quote(participant["ref"], safe="")
        live = api("GET", f"repos/{repo}/git/ref/heads/{ref}")
        if live.get("object", {}).get("sha") != participant["sha"]:
            raise RelayError("participant branch changed or disappeared")
        if participant["pr"]:
            pr = api("GET", f"repos/{repo}/pulls/{participant['pr']}")
            head = pr.get("head") or {}
            if (pr.get("state") != "open" or head.get("sha") != participant["sha"]
                    or head.get("ref") != participant["ref"]
                    or (head.get("repo") or {}).get("full_name") != repo):
                raise RelayError("participant PR no longer matches the frozen source")


def source_jobs(run_id, expected_attempt):
    latest = {}
    for attempt in range(1, expected_attempt + 1):
        jobs = paged(f"repos/{SOURCE}/actions/runs/{run_id}/attempts/{attempt}/jobs", "jobs")
        for job in jobs:
            if job.get("name") not in {f"joint/{name}" for name in TESTS}:
                continue
            item = dict(job, _attempt=int(job.get("run_attempt") or attempt))
            previous = latest.get(item["name"])
            if previous is None or (item["_attempt"], item["id"]) > (previous["_attempt"], previous["id"]):
                latest[item["name"]] = item
    return latest


def render_job(name, job, source, source_complete):
    if not job:
        status = "completed" if source_complete else "queued"
        conclusion = "failure" if source_complete else None
    else:
        status = job.get("status", "queued")
        conclusion = job.get("conclusion") if status == "completed" else None
        if status == "completed" and conclusion not in {"success", "failure", "cancelled", "timed_out", "skipped", "neutral", "action_required", "stale"}:
            conclusion = "failure"
    target = (job or {}).get("html_url") or source
    if job and target != f"{source}/job/{job['id']}":
        raise RelayError("source job URL does not belong to the validated source run")
    text = "| Step | Status | Result |\n| --- | --- | --- |\n"
    for step in (job or {}).get("steps") or []:
        label = str(step.get("name", "")).replace("|", "\\|").replace("\n", " ")
        text += f"| {label} | {step.get('status', '')} | {step.get('conclusion') or '-'} |\n"
    text += f"\n[Full Arsenal job log]({target})\n\nSource job attempt: `{(job or {}).get('_attempt', '-')}`."
    return {
        "name": f"joint/{name}", "status": status, "conclusion": conclusion,
        "details_url": target,
        "output": {"title": f"{name}: {conclusion or status}",
                   "summary": "Shared test executes once in Arsenal. This check mirrors its actual job and steps.",
                   "text": text},
    }


def is_owned(item):
    app = item.get("app") or {}
    return app.get("slug") == "github-actions" and app.get("id") == 15368


def publish(repository, run, state, member, expected_attempt, pending=False):
    if pending and run.get("status") != "completed":
        raise RelayError("cannot queue a rerun while the source is active")
    run_id = run["id"]
    attempt = expected_attempt + 1 if pending else expected_attempt
    source = f"https://github.com/{SOURCE}/actions/runs/{run_id}"
    waiting = state.get("waiting", [])
    jobs = {} if pending or waiting else source_jobs(run_id, expected_attempt)
    existing = paged(f"repos/{repository}/commits/{member['sha']}/check-runs?filter=all", "check_runs", local=True)
    owned = [item for item in existing if is_owned(item)]
    for item in owned:
        match = re.fullmatch(r"actions-only:(\d+):(\d+):actions-summary", item.get("external_id") or "")
        if match and int(match[1]) > run_id:
            raise RelayError("newer source run already owns the participant summary")
    prefix = f"actions-only:{run_id}:{attempt}:"
    if pending and any(item.get("external_id", "").startswith(prefix) and item.get("status") == "completed" for item in owned):
        raise RelayError("late pending request cannot overwrite completed next-attempt checks")
    rows = [] if pending or waiting else [render_job(name, jobs.get(f"joint/{name}"), source, run.get("status") == "completed") for name in TESTS]
    # Final notification can arrive just before GitHub marks the source complete.
    # This bounded grace period never waits for actual tests or missing branches.
    if rows and all(row["status"] == "completed" for row in rows) and run.get("status") != "completed":
        for _ in range(10):
            time.sleep(3)
            run = api("GET", f"repos/{SOURCE}/actions/runs/{run_id}")
            validate_state(state, run, repository, run_id, expected_attempt)
            if run.get("status") == "completed":
                break
    terminal = run.get("status") == "completed" and bool(rows) and all(row["status"] == "completed" for row in rows)
    summary = {
        "name": "joint/actions-summary", "status": "completed" if terminal else "queued" if pending or waiting else "in_progress",
        "conclusion": ("success" if all(row["conclusion"] == "success" for row in rows) else "failure") if terminal else None,
        "details_url": source,
        "output": {"title": "Shared test rerun queued" if pending else "Shared test result",
                   "summary": "Waiting for Arsenal rerun dispatch." if pending else "\n".join(f"- {row['name']}: {row['conclusion'] or row['status']}" for row in rows),
                   "text": f"Source run `{run_id}`, attempt `{attempt}`.\n\n[Request failed/all/single rerun in this repository](https://github.com/{repository}/actions/workflows/joint_ci_rerun.yml)."},
    }
    if waiting:
        missing = [f"{state['participants'][role]['repo']} @ {state['participants'][role]['ref']}" for role in waiting]
        summary["output"]["title"] = "Waiting for dependency branches"
        summary["output"]["summary"] = "No shared tests started. Missing: " + ", ".join(missing)
    current = api("GET", f"repos/{SOURCE}/actions/runs/{run_id}")
    validate_state(state, current, repository, run_id, expected_attempt)
    validate_refs(state)
    by_external = {}
    for item in owned:
        identity = item.get("external_id")
        if identity and identity.startswith("actions-only:"):
            if identity in by_external:
                raise RelayError("duplicate owned Check Run identity")
            by_external[identity] = item
    for row in [summary] + rows:
        identity = prefix + row["name"].removeprefix("joint/")
        previous = by_external.get(identity)
        if previous and previous.get("status") == "completed" and row["status"] != "completed":
            raise RelayError("late source progress cannot overwrite a completed check")
        body = dict(row, head_sha=member["sha"], external_id=identity)
        if body["status"] == "completed":
            body["completed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        else:
            body.pop("conclusion")
        if previous and all(previous.get(key) == body[key] for key in ("status", "conclusion", "details_url", "output") if key in body):
            continue
        path = f"repos/{repository}/check-runs" + (f"/{previous['id']}" if previous else "")
        response = api("PATCH" if previous else "POST", path, body, local=True)
        if not response.get("id") or not is_owned(response):
            raise RelayError("check publication did not return a GitHub Actions-owned check")
    print(json.dumps({"repository": repository, "head_sha": member["sha"], "source_run": run_id, "attempt": attempt, "checks": len(rows) + 1, "pending": pending}))


def request_rerun(repository, run, operation, expected_attempt):
    if run.get("status") != "completed":
        raise RelayError("source is still active; no second execution requested")
    api("POST", f"repos/{SOURCE}/actions/workflows/{SOURCE_PATH.rsplit('/', 1)[-1]}/dispatches", {
        "ref": SOURCE_REF,
        "inputs": {"operation": "rerun", "source_run_id": str(run["id"]),
                   "expected_attempt": str(expected_attempt), "rerun_scope": operation,
                   "caller_repo": repository, "caller_actor": os.environ.get("GITHUB_ACTOR", "")},
    })
    print(json.dumps({"requested": operation, "source_run": run["id"], "expected_attempt": expected_attempt}))


def request_start(repository):
    if (repository not in PARTICIPANTS.values()
            or os.environ.get("GITHUB_EVENT_NAME") != "push"
            or os.environ.get("GITHUB_REF") != "refs/heads/" + DEMO_REF
            or not full_sha(os.environ.get("GITHUB_SHA"))):
        raise RelayError("push start is limited to the explicit replica demonstration branch")
    api("POST", f"repos/{SOURCE}/actions/workflows/{SOURCE_PATH.rsplit('/', 1)[-1]}/dispatches", {
        "ref": SOURCE_REF,
        "inputs": {"operation": "start", "driver_ref": DEMO_REF, "synapse_ref": DEMO_REF,
                   "driver_pr": "0", "synapse_pr": "0", "fail_once": "unit",
                   "caller_repo": repository, "caller_actor": os.environ.get("GITHUB_ACTOR", "")},
    })
    print(json.dumps({"requested": "start", "repository": repository, "ref": DEMO_REF}))


def main():
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if os.environ.get("GITHUB_EVENT_NAME") == "push":
        request_start(repository)
        return
    payload = json.loads(os.environ.get("JOINT_RELAY_INPUTS", "{}"))
    operation = payload.get("operation")
    if operation not in OPERATIONS:
        raise RelayError("unsupported relay operation")
    run_id, expected_attempt = int(payload.get("source_run_id", "0")), int(payload.get("expected_attempt", "0"))
    if run_id <= 0 or expected_attempt <= 0:
        raise RelayError("positive source run and attempt are required")
    run, state, member = load_source(repository, run_id, expected_attempt)
    if state.get("waiting") and operation != "sync":
        raise RelayError("dependency branches must exist before rerunning tests")
    if operation in {"sync", "pending"}:
        publish(repository, run, state, member, expected_attempt, pending=operation == "pending")
    else:
        request_rerun(repository, run, operation, expected_attempt)


if __name__ == "__main__":
    try:
        main()
    except (RelayError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise SystemExit(f"ACTIONS_RELAY_BLOCKED: {exc}")
