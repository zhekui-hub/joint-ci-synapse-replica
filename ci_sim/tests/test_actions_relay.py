"""Author: zhekui. Regression coverage for Actions-only source binding and checks.

Uses isolated API responses to protect SHA/attempt guards and local-token writes.
"""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("actions_relay", Path(__file__).parents[1] / "actions_relay.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
REPO = MODULE.PARTICIPANTS["driver"]


def fixture(attempt=1):
    run = {"id": 700, "run_attempt": attempt, "path": MODULE.SOURCE_PATH,
           "name": MODULE.SOURCE_NAME, "event": "workflow_dispatch",
           "head_branch": MODULE.SOURCE_REF, "head_sha": "c" * 40,
           "repository": {"full_name": MODULE.SOURCE}, "status": "completed"}
    state = {"schema": 1, "source_repo": MODULE.SOURCE, "source_sha": "c" * 40,
             "source_ref": MODULE.SOURCE_REF, "run_id": "700", "tests": MODULE.TESTS,
             "fail_once": "unit", "ready": True, "waiting": [],
             "participants": {name: {"repo": repo, "ref": "trial", "sha": letter * 40, "pr": 0}
                              for (name, repo), letter in zip(MODULE.PARTICIPANTS.items(), "ab")}}
    state["key"] = MODULE.state_key(state)
    return run, state, state["participants"]["driver"]


def jobs():
    source = f"https://github.com/{MODULE.SOURCE}/actions/runs/700"
    return {f"joint/{name}": {"id": index, "name": f"joint/{name}", "status": "completed",
                             "conclusion": "success", "_attempt": 1,
                             "html_url": f"{source}/job/{index}",
                             "steps": [{"name": "actual step", "status": "completed", "conclusion": "success"}]}
            for index, name in enumerate(MODULE.TESTS, 100)}


class ActionsRelayTests(unittest.TestCase):
    def test_valid_manifest_binds_local_sha(self):
        run, state, member = fixture()
        self.assertEqual(MODULE.validate_state(state, run, REPO, 700, 1), member)

    def test_wrong_source_identity_or_attempt_rejected(self):
        for field, value in [("path", ".github/workflows/other.yml"), ("name", "other"),
                             ("head_branch", "main"), ("head_sha", "d" * 40), ("run_attempt", 2)]:
            run, state, _ = fixture()
            run[field] = value
            with self.subTest(field=field), self.assertRaises(MODULE.RelayError):
                MODULE.validate_state(state, run, REPO, 700, 1)

    def test_manifest_change_without_hash_update_rejected(self):
        run, state, _ = fixture()
        state["participants"]["synapse"]["sha"] = "d" * 40
        with self.assertRaisesRegex(MODULE.RelayError, "snapshot key"):
            MODULE.validate_state(state, run, REPO, 700, 1)

    def test_pr_number_does_not_change_execution_key(self):
        _, state, _ = fixture()
        original = MODULE.state_key(state)
        state["participants"]["synapse"]["pr"] = 32
        self.assertEqual(MODULE.state_key(state), original)

    def test_waiting_accepts_only_missing_dependency_sha(self):
        run, state, _ = fixture()
        state.update(waiting=["synapse"], ready=False)
        state["participants"]["synapse"]["sha"] = None
        MODULE.validate_state(state, run, REPO, 700, 1)
        with self.assertRaisesRegex(MODULE.RelayError, "missing participant"):
            MODULE.validate_state(state, run, MODULE.PARTICIPANTS["synapse"], 700, 1)

    def publish(self, run=None, state=None, source_jobs=None, checks=None, pending=False):
        default_run, default_state, _ = fixture()
        run = run or default_run
        state = state or default_state
        writes = []
        def api(method, path, body=None, **kwargs):
            if method == "GET":
                return copy.deepcopy(run)
            self.assertTrue(kwargs.get("local"))
            self.assertIn(f"repos/{REPO}/check-runs", path)
            writes.append(copy.deepcopy(body))
            return {"id": len(writes), "app": {"slug": "github-actions", "id": 15368}}
        with patch.object(MODULE, "api", side_effect=api), patch.object(MODULE, "paged", return_value=checks or []), patch.object(MODULE, "source_jobs", return_value=jobs() if source_jobs is None else source_jobs), patch.object(MODULE, "validate_refs"), patch.object(MODULE.time, "sleep"), patch("builtins.print"):
            MODULE.publish(REPO, run, state, state["participants"]["driver"], run["run_attempt"], pending=pending)
        return writes

    def test_summary_written_first_and_all_writes_use_local_token(self):
        writes = self.publish()
        self.assertEqual([item["name"] for item in writes], ["joint/actions-summary", "joint/build", "joint/unit", "joint/integration"])
        self.assertTrue(all(item["conclusion"] == "success" for item in writes))
        self.assertTrue(all(item["head_sha"] == "a" * 40 for item in writes))
        self.assertIn("actual step", writes[1]["output"]["text"])
        self.assertTrue(writes[1]["details_url"].endswith("/job/100"))

    def test_missing_or_skipped_jobs_do_not_pass_summary(self):
        for mutated in ({}, dict(jobs(), **{"joint/unit": dict(jobs()["joint/unit"], conclusion="skipped")})):
            with self.subTest(jobs=mutated):
                self.assertEqual(self.publish(source_jobs=mutated)[0]["conclusion"], "failure")

    def test_new_attempt_metadata_cannot_reuse_old_success_as_pass(self):
        run, state, _ = fixture(attempt=2)
        run["status"] = "in_progress"
        writes = self.publish(run, state)
        self.assertEqual(writes[0]["status"], "in_progress")
        self.assertNotIn("conclusion", writes[0])

    def test_pending_only_queues_next_summary(self):
        writes = self.publish(pending=True)
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["status"], "queued")
        self.assertEqual(writes[0]["external_id"], "actions-only:700:2:actions-summary")

    def test_waiting_only_queues_summary(self):
        run, state, _ = fixture()
        state.update(waiting=["synapse"], ready=False)
        state["participants"]["synapse"]["sha"] = None
        writes = self.publish(run, state)
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["status"], "queued")
        self.assertIn("No shared tests started", writes[0]["output"]["summary"])

    def test_late_source_is_rejected_after_newer_summary(self):
        checks = [{"app": {"slug": "github-actions", "id": 15368},
                   "external_id": "actions-only:701:1:actions-summary"}]
        with self.assertRaisesRegex(MODULE.RelayError, "newer source"):
            self.publish(checks=checks)

    def test_self_hosted_app_checks_not_modified(self):
        checks = [{"id": 2, "app": {"slug": "joint-ci", "id": 5130657},
                   "external_id": "actions-only:700:1:actions-summary"}]
        self.assertEqual(len(self.publish(checks=checks)), 4)

    def test_duplicate_sync_skips_identical_check_payloads(self):
        first = self.publish()
        checks = [dict(item, id=index, app={"slug": "github-actions", "id": 15368})
                  for index, item in enumerate(first, 1)]
        self.assertEqual(self.publish(checks=checks), [])

    def test_partial_rerun_preserves_earlier_successful_job(self):
        first = list(jobs().values())
        second = [dict(first[1], id=200, run_attempt=2), dict(first[2], id=201, run_attempt=2)]
        with patch.object(MODULE, "paged", side_effect=[first, second]):
            latest = MODULE.source_jobs(700, 2)
        self.assertEqual(latest["joint/build"]["id"], 100)
        self.assertEqual(latest["joint/build"]["_attempt"], 1)
        self.assertEqual(latest["joint/unit"]["id"], 200)

    def test_rerun_scope_and_actor_go_to_source_dispatch(self):
        run, _, _ = fixture()
        with patch.object(MODULE, "api") as api, patch.dict(MODULE.os.environ, {"GITHUB_ACTOR": "tester"}), patch("builtins.print"):
            MODULE.request_rerun(REPO, run, "failed", 1)
        inputs = api.call_args.args[2]["inputs"]
        self.assertEqual(inputs["caller_actor"], "tester")
        self.assertEqual(inputs["caller_repo"], REPO)
        self.assertEqual(inputs["operation"], "rerun")
        self.assertEqual(inputs["rerun_scope"], "failed")
        self.assertNotIn("local", api.call_args.kwargs)

    def test_push_only_dispatches_for_explicit_demo_branch(self):
        env = {"GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/" + MODULE.DEMO_REF,
               "GITHUB_SHA": "a" * 40, "GITHUB_ACTOR": "tester"}
        with patch.dict(MODULE.os.environ, env), patch.object(MODULE, "api") as api, patch("builtins.print"):
            MODULE.request_start(REPO)
        self.assertEqual(api.call_args.args[2]["inputs"]["driver_ref"], MODULE.DEMO_REF)
        with patch.dict(MODULE.os.environ, dict(env, GITHUB_REF="refs/heads/main")):
            with self.assertRaises(MODULE.RelayError):
                MODULE.request_start(REPO)


if __name__ == "__main__":
    unittest.main()
