"""Window matching for partner reports. Run: python -m unittest discover tests"""
import importlib.util, os, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("report", os.path.join(HERE, "..", "report.py"))
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def inc(host, created, resolved=None, started=None, name="Confluence degraded"):
    return {"host": f"{host}.status.atlassian.com", "name": name, "created_at": created,
            "started_at": started or created, "resolved_at": resolved}


REPORT = {"product": "confluence", "start": "2026-09-01T18:55:00Z", "end": "2026-09-02T06:32:00Z"}


class Matches(unittest.TestCase):
    def test_opened_inside_window(self):
        i = inc("confluence", "2026-09-01T20:00:00.000Z", "2026-09-01T21:00:00.000Z")
        self.assertEqual(report.matches(REPORT, [i]), [i])

    def test_opened_before_and_still_open_counts(self):
        # opened 10h before the window, resolved during it: the old check missed this
        i = inc("confluence", "2026-09-01T09:00:00.000Z", "2026-09-01T23:00:00.000Z")
        self.assertEqual(report.matches(REPORT, [i]), [i])

    def test_resolved_before_window_does_not_count(self):
        i = inc("confluence", "2026-09-01T09:00:00.000Z", "2026-09-01T12:00:00.000Z")
        self.assertEqual(report.matches(REPORT, [i]), [])

    def test_backdated_started_at_is_used(self):
        # created after the window, but Atlassian says it started inside it
        i = inc("confluence", "2026-09-02T12:00:00.000Z", "2026-09-02T13:00:00.000Z",
                started="2026-09-02T05:00:00.000Z")
        self.assertEqual(report.matches(REPORT, [i]), [i])

    def test_history_row_without_end_uses_opening_only(self):
        early = inc("confluence", "2026-09-01T09:00:00Z")
        inside = inc("confluence", "2026-09-01T19:00:00Z")
        self.assertEqual(report.matches(REPORT, [early, inside]), [inside])

    def test_lag_allows_late_declaration(self):
        i = inc("confluence", "2026-09-02T08:00:00.000Z", "2026-09-02T09:00:00.000Z")
        self.assertEqual(report.matches(REPORT, [i]), [i])

    def test_other_pages_ignored(self):
        i = inc("trello", "2026-09-01T20:00:00.000Z", "2026-09-01T21:00:00.000Z")
        self.assertEqual(report.matches(REPORT, [i]), [])

    def test_jira_includes_work_management(self):
        r = dict(REPORT, product="jira")
        i = inc("jira-work-management", "2026-09-01T20:00:00.000Z", "2026-09-01T21:00:00.000Z")
        self.assertEqual(report.matches(r, [i]), [i])


if __name__ == "__main__":
    unittest.main()
