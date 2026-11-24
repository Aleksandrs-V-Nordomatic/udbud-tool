#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Control 2 after the notices only TED holds were read from TED.

TED is replaced by a set of publication numbers per day; nothing reaches the network.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dk_recon
import net


def row(npn, date="02-09-2026"):
    return {"dataDa": {"publiceringsdato": date}, "noticeId": "n-%s" % (npn or "national"),
            "noticeVersion": "01", "noticePublicationNumber": npn}


ROWS = [row("00604959-2026"), row("00603665-2026"), row("")]
BOTH = {"604959-2026", "603665-2026"}


def no_network(*args, **kwargs):
    raise AssertionError("a test reached the network")


class Offline(unittest.TestCase):

    def setUp(self):
        patcher = mock.patch.object(net, "open_url", side_effect=no_network)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_with(self, ted, rows=ROWS, count=None, date_from="2026-09-02", date_to=None):
        count = len(rows) if count is None else count
        answer = ted if callable(ted) else (lambda day: set(ted))
        with mock.patch.object(dk_recon, "ted_numbers", side_effect=answer):
            return dk_recon.run(date_from, date_to, rows=rows, count=count)


class OnlyTed(Offline):

    def test_the_numbers_only_ted_holds(self):
        report = self.run_with(BOTH | {"699998-2026", "699999-2026"})
        self.assertEqual(sorted(dk_recon.only_ted(report)), ["699998-2026", "699999-2026"])

    def test_nothing_missing_is_nothing(self):
        self.assertEqual(list(dk_recon.only_ted(self.run_with(BOTH))), [])

    def test_a_number_only_udbud_holds_is_not_among_them(self):
        self.assertEqual(list(dk_recon.only_ted(self.run_with({"604959-2026"}))), [])

    def test_no_report(self):
        self.assertEqual(list(dk_recon.only_ted(None)), [])

    def test_no_ted_control(self):
        report = dk_recon.run("2026-09-02", rows=ROWS, count=3, ted=False)
        self.assertEqual(list(dk_recon.only_ted(report)), [])

    def test_a_day_ted_did_not_answer(self):
        def broken(day):
            raise net.Unreachable("gave up")
        self.assertEqual(list(dk_recon.only_ted(self.run_with(broken))), [])

    def test_every_day_of_the_window(self):
        rows = [row("00600001-2026", date="01-09-2026"), row("00600002-2026", date="02-09-2026")]
        by_day = {"2026-09-01": {"600001-2026", "699998-2026"},
                  "2026-09-02": {"600002-2026", "699999-2026"}}
        report = self.run_with(lambda day: by_day[day], rows=rows,
                               date_from="2026-09-01", date_to="2026-09-02")
        self.assertEqual(sorted(dk_recon.only_ted(report)), ["699998-2026", "699999-2026"])


class Taken(Offline):

    def test_all_taken_is_ok_and_still_named(self):
        report = self.run_with(BOTH | {"699998-2026", "699999-2026"})
        self.assertFalse(report["ok"])
        report = dk_recon.taken(report, ["699998-2026", "699999-2026"])
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["problems"], [])
        day = report["ted"][0]
        self.assertEqual(sorted(day["only_ted"]), ["699998-2026", "699999-2026"])
        self.assertEqual(sorted(day["read_from_ted"]), ["699998-2026", "699999-2026"])

    def test_the_rows_held_stay_udbuds(self):
        report = dk_recon.taken(self.run_with(BOTH | {"699999-2026"}), ["699999-2026"])
        self.assertEqual(report["rows_held"], 3)
        self.assertEqual(report["index_count"], 3)

    def test_part_taken_is_still_a_problem(self):
        report = self.run_with(BOTH | {"699998-2026", "699999-2026"})
        report = dk_recon.taken(report, ["699999-2026"])
        self.assertFalse(report["ok"])
        self.assertTrue(report["problems"])
        self.assertEqual(sorted(report["ted"][0]["only_ted"]), ["699998-2026", "699999-2026"])
        self.assertEqual(report["ted"][0]["read_from_ted"], ["699999-2026"])

    def test_none_taken_is_still_a_problem(self):
        report = dk_recon.taken(self.run_with(BOTH | {"699999-2026"}), [])
        self.assertFalse(report["ok"])
        self.assertTrue(report["problems"])

    def test_an_only_udbud_left_is_still_a_problem(self):
        report = self.run_with({"604959-2026", "699999-2026"})
        report = dk_recon.taken(report, ["699999-2026"])
        self.assertFalse(report["ok"])
        self.assertTrue(report["problems"])
        self.assertEqual(report["ted"][0]["only_udbud"], ["603665-2026"])

    def test_a_count_mismatch_is_kept(self):
        report = self.run_with(BOTH | {"699999-2026"}, count=4)
        short = [p for p in report["problems"] if "rows held 3" in p]
        self.assertEqual(len(short), 1)
        report = dk_recon.taken(report, ["699999-2026"])
        self.assertFalse(report["ok"])
        self.assertEqual(report["problems"], short)

    def test_a_day_ted_did_not_answer_is_kept(self):
        rows = [row("00600001-2026", date="01-09-2026"), row("00600002-2026", date="02-09-2026")]

        def answer(day):
            if day == "2026-09-01":
                raise net.Unreachable("gave up")
            return {"600002-2026", "699999-2026"}
        report = self.run_with(answer, rows=rows, date_from="2026-09-01", date_to="2026-09-02")
        report = dk_recon.taken(report, ["699999-2026"])
        self.assertFalse(report["ok"])
        self.assertEqual(len(report["problems"]), 1)

    def test_each_day_names_its_own(self):
        rows = [row("00600001-2026", date="01-09-2026"), row("00600002-2026", date="02-09-2026")]
        by_day = {"2026-09-01": {"600001-2026", "699998-2026"},
                  "2026-09-02": {"600002-2026", "699999-2026"}}
        report = self.run_with(lambda day: by_day[day], rows=rows,
                               date_from="2026-09-01", date_to="2026-09-02")
        report = dk_recon.taken(report, ["699998-2026", "699999-2026"])
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual([d["read_from_ted"] for d in report["ted"]],
                         [["699998-2026"], ["699999-2026"]])


if __name__ == "__main__":
    unittest.main()
