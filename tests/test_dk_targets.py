#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The window, proved against the portal's own count, and a procedure held by its id.

`dk_page.search` is replaced by a stand-in that serves pages shaped like the portal's answer
(`resultatElementDtoList`, `totaltAntalResultater`); nothing reaches the network.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dk_page
import dk_targets


def row(n, date="02-09-2026", code="competition", version="01", npn=""):
    return {"dataDa": {"titel": "Opgave %d" % n, "publiceringsdato": date,
                       "formulartypeKode": code, "ordregiver": "Kommune"},
            "dataEn": {},
            "noticeId": "notice-%d" % n, "noticeVersion": version,
            "noticePublicationNumber": npn}


def page(rows, total):
    return {"resultatElementDtoList": rows, "totaltAntalResultater": total}


class Rows(unittest.TestCase):

    def test_one_page_that_holds_the_count(self):
        with mock.patch.object(dk_page, "search", return_value=page([row(1), row(2)], 2)) as search:
            count, held = dk_targets.rows("2026-09-02")
        self.assertEqual(count, 2)
        self.assertEqual([r["noticeId"] for r in held], ["notice-1", "notice-2"])
        search.assert_called_once()
        args, kwargs = search.call_args
        self.assertEqual(args[:2], ("2026-09-02", "2026-09-02"))
        self.assertEqual(kwargs.get("page"), 1)

    def test_pages_until_the_count_is_held(self):
        pages = [page([row(1), row(2)], 5), page([row(3), row(4)], 5), page([row(5)], 5)]
        with mock.patch.object(dk_page, "search", side_effect=pages) as search:
            count, held = dk_targets.rows("2026-09-02")
        self.assertEqual((count, len(held)), (5, 5))
        self.assertEqual([c.kwargs.get("page") for c in search.call_args_list], [1, 2, 3])

    def test_fewer_rows_than_the_count_is_truncated(self):
        pages = [page([row(1), row(2)], 3), page([], 3)]
        with mock.patch.object(dk_page, "search", side_effect=pages):
            with self.assertRaises(dk_targets.Truncated):
                dk_targets.rows("2026-09-02")

    def test_no_count_is_truncated(self):
        with mock.patch.object(dk_page, "search", return_value={"resultatElementDtoList": [row(1)]}):
            with self.assertRaises(dk_targets.Truncated):
                dk_targets.rows("2026-09-02")

    def test_a_row_outside_the_window_means_the_filter_was_dropped(self):
        rows = [row(1), row(2, date="01-09-2026")]
        with mock.patch.object(dk_page, "search", return_value=page(rows, 2)):
            with self.assertRaises(dk_targets.OutsideWindow):
                dk_targets.rows("2026-09-02")

    def test_a_row_with_no_readable_date_is_outside(self):
        with mock.patch.object(dk_page, "search", return_value=page([row(1, date="2026-09-02")], 1)):
            with self.assertRaises(dk_targets.OutsideWindow):
                dk_targets.rows("2026-09-02")

    def test_a_wider_window_holds_every_day_in_it(self):
        rows = [row(1, date="31-08-2026"), row(2, date="01-09-2026"), row(3, date="02-09-2026")]
        with mock.patch.object(dk_page, "search", return_value=page(rows, 3)) as search:
            count, held = dk_targets.rows("2026-08-31", "2026-09-02")
        self.assertEqual(count, 3)
        self.assertEqual(search.call_args.args[:2], ("2026-08-31", "2026-09-02"))

    def test_an_empty_window_with_count_zero_is_whole(self):
        with mock.patch.object(dk_page, "search", return_value=page([], 0)):
            self.assertEqual(dk_targets.rows("2026-08-30"), (0, []))

    def test_window_returns_notices(self):
        with mock.patch.object(dk_page, "search", return_value=page([row(1)], 1)):
            found = dk_targets.window("2026-09-02")
        self.assertEqual(found[0]["notice_id"], "notice-1")
        self.assertEqual(found[0]["kind"], "tender")


class Days(unittest.TestCase):

    def test_days_are_inclusive(self):
        self.assertEqual(dk_targets.days("2026-08-31", "2026-09-02"),
                         ["2026-08-31", "2026-09-01", "2026-09-02"])
        self.assertEqual(dk_targets.days("2026-09-02", None), ["2026-09-02"])

    def test_a_window_that_ends_before_it_starts_is_refused(self):
        with self.assertRaises(ValueError):
            dk_targets.days("2026-09-02", "2026-09-01")

    def test_publishing_days_exclude_the_weekend(self):
        # 2026-11-13 is a Friday, 14 and 15 the weekend, 16 a Monday.
        self.assertEqual(dk_targets.publishing_days("2026-11-13", "2026-11-16"),
                         ["2026-11-13", "2026-11-16"])

    def test_a_weekend_has_no_publishing_days(self):
        self.assertEqual(dk_targets.publishing_days("2026-08-29", "2026-08-30"), [])


class Procedure(unittest.TestCase):

    def test_a_dk_prefix_is_stripped_before_the_search(self):
        with mock.patch.object(dk_page, "search", return_value=page([], 0)) as search:
            dk_targets.procedure("DK:7c03c120-69c0-4112-af76-3d30b1aab18e")
        self.assertEqual(search.call_args.kwargs.get("text"), "7c03c120-69c0-4112-af76-3d30b1aab18e")

    def test_a_lower_case_prefix_is_stripped_too(self):
        with mock.patch.object(dk_page, "search", return_value=page([], 0)) as search:
            dk_targets.procedure("  dk:abc  ")
        self.assertEqual(search.call_args.kwargs.get("text"), "abc")

    def test_nothing_to_look_for_asks_nothing(self):
        with mock.patch.object(dk_page, "search") as search:
            self.assertEqual(dk_targets.procedure("DK:"), [])
            self.assertEqual(dk_targets.procedure(None), [])
        search.assert_not_called()

    def test_newest_first(self):
        rows = [row(1, date="01-09-2026"), row(2, date="03-09-2026"),
                row(3, date="03-09-2026", version="02"), row(4, date="02-09-2026")]
        with mock.patch.object(dk_page, "search", return_value=page(rows, 4)):
            found = dk_targets.procedure("abc")
        self.assertEqual([t["notice_id"] for t in found],
                         ["notice-3", "notice-2", "notice-4", "notice-1"])


def detail_of(procedure):
    html = ('<section><span class="label">Identifikator for proceduren</span>'
            '<span class="text">: </span><span class="value">%s</span></section>' % procedure)
    return {"htmlDA": html, "opsummeringDA": {}}


class One(unittest.TestCase):
    """A notice id is followed to its procedure's newest live notice."""

    PROCEDURE = "7c03c120-69c0-4112-af76-3d30b1aab18e"

    def setUp(self):
        old = row(1, date="01-09-2026")
        new = row(2, date="10-09-2026", code="change")
        self.by_text = {"notice-1": [old], self.PROCEDURE: [old, new]}
        self.details = {"notice-1": detail_of(self.PROCEDURE), "notice-2": detail_of(self.PROCEDURE)}

    def search(self, date_from=None, date_to=None, page=1, text=None, size=None):
        rows = self.by_text.get(text, [])
        return {"resultatElementDtoList": rows, "totaltAntalResultater": len(rows)}

    def detail(self, notice_id, version, npn, timeout=60):
        return self.details.get(notice_id)

    def one(self, reference):
        with mock.patch.object(dk_page, "search", side_effect=self.search), \
                mock.patch.object(dk_page, "detail", side_effect=self.detail):
            return dk_targets.one(reference)

    def test_a_notice_id_is_followed_to_the_newest_live_notice(self):
        found = self.one("notice-1")
        self.assertEqual(found["notice_id"], "notice-2")
        self.assertEqual(found["kind"], "amendment")
        self.assertEqual(found["pid"], self.PROCEDURE)

    def test_a_procedure_id_with_a_prefix(self):
        found = self.one("DK:" + self.PROCEDURE)
        self.assertEqual(found["notice_id"], "notice-2")

    def test_nothing_found_is_none(self):
        self.assertIsNone(self.one("DK:unknown"))

    def test_only_closes_is_none(self):
        self.by_text["notice-9"] = [row(9, code="result")]
        self.details["notice-9"] = detail_of("notice-9")
        self.assertIsNone(self.one("notice-9"))


if __name__ == "__main__":
    unittest.main()
