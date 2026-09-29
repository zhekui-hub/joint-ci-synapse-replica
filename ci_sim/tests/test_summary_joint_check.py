import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "summary_joint_check.py"
SPEC = importlib.util.spec_from_file_location("summary_joint_check", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


DRIVER = "zhekui-hub/joint-ci-driver-replica"
SYNAPSE = "zhekui-hub/joint-ci-synapse-replica"
DRIVER_SHA = "a" * 40
SYNAPSE_SHA = "b" * 40


def payload(**changes):
    value = {
        "phase": "running",
        "participant_repository": DRIVER,
        "head_sha": DRIVER_SHA,
        "participant_snapshot": {DRIVER: DRIVER_SHA, SYNAPSE: SYNAPSE_SHA},
        "required_participants": [DRIVER, SYNAPSE],
        "joint_key": "joint-key",
        "tests": [{"id": "public.one", "result": "pending"}],
    }
    value.update(changes)
    return value


class SummaryCheckTests(unittest.TestCase):
  def test_validate_requires_local_repository_snapshot_identity(self):
    synapse_payload = payload(participant_repository=SYNAPSE, head_sha=SYNAPSE_SHA)
    MODULE.validate_payload(synapse_payload, SYNAPSE)
    with self.assertRaisesRegex(ValueError, "does not match"):
        MODULE.validate_payload(payload(participant_repository=DRIVER), SYNAPSE)
    with self.assertRaisesRegex(ValueError, "does not match"):
        MODULE.validate_payload(payload(head_sha=DRIVER_SHA), SYNAPSE)
    with self.assertRaisesRegex(ValueError, "snapshot"):
        MODULE.validate_payload(
            synapse_payload | {"participant_snapshot": None}, SYNAPSE
        )

  def test_completed_unknown_is_not_reported_as_passed(self):
    title, summary, _ = MODULE.render(
        payload(), [{"id": "public.one", "result": "unknown"}], "completed"
    )
    self.assertIn("incomplete", title)
    self.assertIn("passed", summary)

  def test_legacy_same_name_github_actions_check_is_reused(self):
    legacy = {"id": 7, "name": MODULE.CHECK_NAME, "app": {"slug": "github-actions"}}
    self.assertEqual(MODULE.select_existing([legacy], "new"), legacy)

  def test_late_running_update_does_not_reopen_completed_check(self):
    existing = {"status": "completed"}
    self.assertTrue(MODULE.is_stale_running(existing, "running", payload()))
    self.assertFalse(MODULE.is_stale_running(existing, "running", payload(rerun=True)))


if __name__ == "__main__":
    unittest.main()
