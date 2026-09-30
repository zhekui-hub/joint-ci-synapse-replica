import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "mirror_joint_checks.py"
SPEC = importlib.util.spec_from_file_location("mirror_joint_checks", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


DRIVER_REPO = "zhekui-hub/joint-ci-driver-replica"
DRIVER_SHA = "a" * 40
SYNAPSE_SHA = "b" * 40


def payload(**overrides):
    value = {
        "phase": "completed",
        "participant_repository": DRIVER_REPO,
        "head_sha": DRIVER_SHA,
        "participant_snapshot": {
            DRIVER_REPO: DRIVER_SHA,
            "zhekui-hub/joint-ci-synapse-replica": SYNAPSE_SHA,
        },
        "required_participants": [DRIVER_REPO, "zhekui-hub/joint-ci-synapse-replica"],
    }
    value.update(overrides)
    return value


class MirrorCheckTests(unittest.TestCase):
    def test_app_publisher_returns_before_payload_token_or_api(self):
        with (
            patch.dict(MODULE.os.environ, {
                "JOINT_CI_CHECK_PUBLISHER": "app",
                "JOINT_CHECK_PAYLOAD": "not valid JSON",
            }, clear=True),
            patch.object(MODULE, "token") as token,
            patch.object(MODULE, "request") as request,
            patch("builtins.print"),
        ):
            MODULE.main()
        token.assert_not_called()
        request.assert_not_called()

    def test_default_publisher_keeps_legacy_api_path(self):
        report = payload(
            joint_key="generation",
            tests=[{"id": "test.compile", "job": "compile", "result": "success"}],
        )
        with (
            patch.dict(MODULE.os.environ, {
                "GITHUB_REPOSITORY": DRIVER_REPO,
                "JOINT_CHECK_PAYLOAD": json.dumps(report),
            }, clear=True),
            patch.object(MODULE, "request", side_effect=[
                {"check_runs": []}, {"id": 123}
            ]) as request,
            patch("builtins.print"),
        ):
            MODULE.main()
        self.assertEqual([call.args[0] for call in request.call_args_list], ["GET", "POST"])
        self.assertEqual(request.call_args_list[1].args[2]["head_sha"], DRIVER_SHA)

    def test_unknown_publisher_fails_before_api(self):
        with (
            patch.dict(MODULE.os.environ, {"JOINT_CI_CHECK_PUBLISHER": "other"}, clear=True),
            patch.object(MODULE, "token") as token,
            patch.object(MODULE, "request") as request,
        ):
            with self.assertRaisesRegex(SystemExit, "must be legacy or app"):
                MODULE.main()
        token.assert_not_called()
        request.assert_not_called()

    def test_check_name_is_short_and_stable(self):
        self.assertEqual(MODULE.check_name({"job": "compile"}), "joint/compile")

    def test_snapshot_must_match_local_participant(self):
        phase, repo, sha = MODULE.validate_payload(payload(), DRIVER_REPO)
        self.assertEqual((phase, repo, sha), ("completed", DRIVER_REPO, DRIVER_SHA))
        with self.assertRaises(SystemExit):
            MODULE.validate_payload(payload(head_sha=SYNAPSE_SHA), DRIVER_REPO)

    def test_output_keeps_matrix_and_arsenal_job_link(self):
        rendered = MODULE.output(
            {
                "id": "compile.0",
                "job": "compile",
                "workflow": "build.yml",
                "matrix": {"profile": ["default"]},
                "needs": ["precheck"],
                "result": "success",
            },
            "completed",
            "https://github.com/example/arsenal/actions/runs/1/job/2",
        )
        self.assertIn('"profile": ["default"]', rendered["text"])
        self.assertIn("precheck", rendered["text"])
        self.assertIn("/job/2", rendered["text"])


if __name__ == "__main__":
    unittest.main()
