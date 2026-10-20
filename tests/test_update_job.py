from __future__ import annotations

import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from literature_tracker.tasks.update_job import UpdateJob


class UpdateJobTests(unittest.TestCase):
    def test_start_is_nonblocking_and_does_not_duplicate_a_running_job(self) -> None:
        entered, release = Event(), Event()
        def update(**kwargs):
            entered.set()
            release.wait(3)
            return {"status": "success"}
        job = UpdateJob(Path("test.db"))
        with patch("literature_tracker.tasks.update_job.run_full_pipeline", side_effect=update) as run:
            try:
                future = job.start()
                self.assertTrue(entered.wait(2))
                self.assertFalse(future.done())
                self.assertIs(job.start(), future)
                release.set()
                self.assertEqual(future.result(timeout=2)["status"], "success")
                run.assert_called_once()
            finally:
                release.set()
                job.executor.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
