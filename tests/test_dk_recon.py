#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The coverage controls: rows held against the portal's count, EU numbers against TED.

TED is replaced by a set of publication numbers per day; `net.open_url` is replaced where the
TED client itself is under test. Nothing reaches the network.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dk_recon
import dk_targets
import net


def row(npn, date="02-09-2026"):
    return {"dataDa": {"publiceringsdato": date}, "noticeId": "n-%s" % (npn or "national"),
            "noticeVersion": "01", "noticePublicationNumber": npn}


ROWS = [row("00604959-2026"), row("00603665-2026"), row("")]


class Run(unittest.TestCase):

    def run_with(self, ted, rows=ROWS, count=None, date_from="2026-09-02", date_to=None):
        count = len(rows) if count is None else count
        answer = ted if callable(ted) else (lambda day: set(ted))
        with mock.patch.object(dk_recon, "ted_numbers", side_effect=answer):
            return dk_recon.run(date_from, date_to, rows=rows, count=count)

    def test_equal_sets_are_ok_and_leading_zeros_do_not_count(self):
        report = self.run_with({"604959-2026", "603665-2026"})
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["ted"][0]["udbud"], 2)
        self.assertEqual(report["ted"][0]["ted"], 2)

    def test_leading_zeros_on_both_sides(self):
        report = self.run_with({dk_recon._norm("00604959-2026"), dk_recon._norm("0603665-2026")})
        self.assertTrue(report["ok"], report["problems"])

    def test_a_national_notice_is_outside_the_ted_control(self):
        report = self.run_with({"604959-2026", "603665-2026"})
        self.assertEqual(report["national"], 1)
        self.assertEqual(report["rows_held"], 3)
        self.assertEqual(report["index_count"], 3)

    def test_a_number_only_on_udbud_is_a_problem(self):
        report = self.run_with({"604959-2026"})
        self.assertFalse(report["ok"])
        self.assertEqual(report["ted"][0]["only_udbud"], ["603665-2026"])
        self.assertEqual(report["ted"][0]["only_ted"], [])
        self.assertEqual(len(report["problems"]), 1)

    def test_a_number_only_on_ted_is_a_problem(self):
        report = self.run_with({"604959-2026", "603665-2026", "699999-2026"})
        self.assertFalse(report["ok"])
        self.assertEqual(report["ted"][0]["only_ted"], ["699999-2026"])
        self.assertEqual(report["ted"][0]["only_udbud"], [])

    def test_both_ways_at_once(self):
        report = self.run_with({"604959-2026", "699999-2026"})
        self.assertFalse(report["ok"])
        self.assertEqual(report["ted"][0]["only_udbud"], ["603665-2026"])
        self.assertEqual(report["ted"][0]["only_ted"], ["699999-2026"])

    def test_a_count_mismatch_is_a_problem(self):
        report = self.run_with({"604959-2026", "603665-2026"}, count=4)
        self.assertFalse(report["ok"])
        self.assertTrue(any("rows held 3" in p for p in report["problems"]), report["problems"])

    def test_no_count_is_a_problem(self):
        with mock.patch.object(dk_recon, "ted_numbers", return_value={"604959-2026", "603665-2026"}):
            report = dk_recon.run("2026-09-02", rows=ROWS, count=None)
        self.assertFalse(report["ok"])

    def test_each_day_is_compared_with_its_own_ted_day(self):
        rows = [row("00600001-2026", date="01-09-2026"), row("00600002-2026", date="02-09-2026")]
        by_day = {"2026-09-01": {"600001-2026"}, "2026-09-02": {"600002-2026"}}
        report = self.run_with(lambda day: by_day[day], rows=rows,
                               date_from="2026-09-01", date_to="2026-09-02")
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual([d["day"] for d in report["ted"]], ["2026-09-01", "2026-09-02"])

    def test_a_number_on_the_wrong_day_is_a_problem(self):
        rows = [row("00600001-2026", date="01-09-2026")]
        by_day = {"2026-09-01": set(), "2026-09-02": {"600001-2026"}}
        report = self.run_with(lambda day: by_day[day], rows=rows,
                               date_from="2026-09-01", date_to="2026-09-02")
        self.assertFalse(report["ok"])

    def test_ted_not_answering_is_a_problem_not_a_crash(self):
        def broken(day):
            raise net.Unreachable("gave up")
        report = self.run_with(broken)
        self.assertFalse(report["ok"])
        self.assertIn("error", report["ted"][0])

    def test_an_empty_weekend_is_ok(self):
        report = self.run_with(set(), rows=[], count=0, date_from="2026-08-29", date_to="2026-08-30")
        self.assertTrue(report["ok"], report["problems"])

    def test_ted_false_skips_the_ted_control(self):
        with mock.patch.object(dk_recon, "ted_numbers") as ted:
            report = dk_recon.run("2026-09-02", rows=ROWS, count=3, ted=False)
        ted.assert_not_called()
        self.assertTrue(report["ok"])
        self.assertIsNone(report["ted"])

    def test_a_truncated_window_is_reported_not_raised(self):
        with mock.patch.object(dk_targets, "rows", side_effect=dk_targets.Truncated("short")), \
                mock.patch.object(dk_recon, "ted_numbers") as ted:
            report = dk_recon.run("2026-09-02")
        self.assertFalse(report["ok"])
        self.assertEqual(report["problems"], ["short"])
        ted.assert_not_called()
        self.assertTrue(dk_recon.line(report).startswith("coverage: "))

    def test_line_says_ok_or_short(self):
        good = self.run_with({"604959-2026", "603665-2026"})
        self.assertIn("coverage OK", dk_recon.line(good))
        bad = self.run_with({"604959-2026"})
        self.assertIn("coverage SHORT", dk_recon.line(bad))


class TedNumbers(unittest.TestCase):

    def test_pages_until_the_total_and_strips_leading_zeros(self):
        answers = [({"notices": [{"publication-number": "00600001-2026"},
                                 {"publication-number": "00600002-2026"}],
                     "totalNoticeCount": 3}, {}),
                   ({"notices": [{"publication-number": "00600003-2026"}],
                     "totalNoticeCount": 3}, {})]
        with mock.patch.object(net, "open_url", side_effect=answers) as opened:
            numbers = dk_recon.ted_numbers("2026-09-02")
        self.assertEqual(numbers, {"600001-2026", "600002-2026", "600003-2026"})
        self.assertEqual(opened.call_count, 2)
        import json
        body = json.loads(opened.call_args_list[0].args[0].data.decode("utf-8"))
        self.assertIn("buyer-country=DNK", body["query"])
        self.assertIn("publication-date=20260902", body["query"])

    def test_an_empty_day(self):
        with mock.patch.object(net, "open_url", return_value=({"notices": [], "totalNoticeCount": 0}, {})):
            self.assertEqual(dk_recon.ted_numbers("2026-08-30"), set())


if __name__ == "__main__":
    unittest.main()
