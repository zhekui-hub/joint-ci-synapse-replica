import importlib.util
from pathlib import Path
import unittest


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
