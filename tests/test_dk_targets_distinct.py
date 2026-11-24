#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The window proved on distinct notices: a repeat never stands in for a row left out.

`dk_page.search` is replaced by a stand-in that answers from a table keyed by the window, the pass
and the page. A pass starts at page 1. A pass beyond the scripted ones is answered with the last
one, and a page beyond a pass's pages is empty. Nothing reaches the network.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dk_page
import dk_targets


def row(n, date="02-09-2026", version="01", npn=""):
    return {"dataDa": {"titel": "Opgave %d" % n, "publiceringsdato": date,
                       "formulartypeKode": "competition", "ordregiver": "Kommune"},
            "dataEn": {},
            "noticeId": "notice-%d" % n, "noticeVersion": version,
            "noticePublicationNumber": npn}


def keys(rows):
    return sorted((r["noticeId"], r["noticeVersion"]) for r in rows)


def first(*numbers):
    """The keys of the first versions of these notices."""
    return [("notice-%d" % n, "01") for n in numbers]


class Portal(object):
    """`windows` maps (from, to) to (total, passes); a pass is a list of pages, a page its rows."""

    def __init__(self, windows):
        self.windows = windows
        self.calls = []

    def search(self, date_from, date_to, page=1, **kwargs):
        window = (date_from, date_to)
        self.calls.append((window, page))
        if window not in self.windows:
            raise AssertionError("a window nobody scripted was asked for: %r" % (window,))
        total, passes = self.windows[window]
        number = max(self.asked(*window).count(1), 1)
        pages = passes[min(number, len(passes)) - 1]
        rows = pages[page - 1] if page <= len(pages) else []
        return {"resultatElementDtoList": list(rows), "totaltAntalResultater": total}

    def asked(self, date_from, date_to):
        """The pages asked for of one window, in the order they were asked."""
        return [p for window, p in self.calls if window == (date_from, date_to)]


class Case(unittest.TestCase):

    def rows(self, windows, *dates):
        self.portal = Portal(windows)
        with mock.patch.object(dk_page, "search", side_effect=self.portal.search):
            return dk_targets.rows(*dates)


class SingleDay(Case):

    DAY = ("2026-09-02", "2026-09-02")

    def day(self, total, *passes):
        return self.rows({self.DAY: (total, list(passes))}, "2026-09-02")

    def test_a_clean_page_is_asked_once(self):
        count, held = self.day(2, [[row(1), row(2)]])
        self.assertEqual(count, 2)
        self.assertEqual(keys(held), first(1, 2))
        self.assertEqual(self.portal.asked(*self.DAY), [1])

    def test_two_versions_of_one_notice_are_two_rows(self):
        count, held = self.day(2, [[row(1, version="01"), row(1, version="02")]])
        self.assertEqual(count, 2)
        self.assertEqual(keys(held), [("notice-1", "01"), ("notice-1", "02")])
        self.assertEqual(self.portal.asked(*self.DAY), [1])

    def test_a_repeat_is_asked_again_and_what_each_pass_brings_is_added(self):
        # Neither pass is whole on its own: the first lacks notice-4, the second notice-3.
        count, held = self.day(4,
                               [[row(1), row(2)], [row(2), row(3)]],
                               [[row(1), row(2)], [row(2), row(4)]])
        self.assertEqual(count, 4)
        self.assertEqual(keys(held), first(1, 2, 3, 4))
        self.assertEqual(self.portal.asked(*self.DAY), [1, 2, 1, 2])

    def test_the_fourth_pass_still_counts(self):
        short = [[row(1), row(2)], [row(2), row(3)]]
        count, held = self.day(4, short, short, short, [[row(1), row(2)], [row(3), row(4)]])
        self.assertEqual(count, 4)
        self.assertEqual(keys(held), first(1, 2, 3, 4))
        self.assertEqual(self.portal.asked(*self.DAY), [1, 2] * 4)

    def test_a_row_that_never_comes_is_truncated_after_four_passes(self):
        with self.assertRaises(dk_targets.Truncated):
            self.day(4, [[row(1), row(2)], [row(2), row(3)]])
        self.assertEqual(self.portal.asked(*self.DAY), [1, 2] * 4)

    def test_fewer_rows_than_the_total_is_truncated(self):
        with self.assertRaises(dk_targets.Truncated):
            self.day(3, [[row(1), row(2)], []])


class SeveralDays(Case):

    WINDOW = ("2026-09-01", "2026-09-02")
    FIRST = ("2026-09-01", "2026-09-01")
    SECOND = ("2026-09-02", "2026-09-02")

    def setUp(self):
        self.one = row(1, date="01-09-2026")
        # Four rows handed out for a total of four; notice-3 comes twice and notice-4 not at all.
        self.windows = {
            self.WINDOW: (4, [[[self.one, row(2)], [row(3), row(3)]]]),
            self.FIRST: (1, [[[self.one]]]),
            self.SECOND: (3, [[[row(2), row(3), row(4)]]]),
        }

    def test_a_clean_window_of_two_pages_is_asked_once_per_page(self):
        self.windows[self.WINDOW] = (4, [[[self.one, row(2)], [row(3), row(4)]]])
        count, held = self.rows(self.windows, *self.WINDOW)
        self.assertEqual(count, 4)
        self.assertEqual(keys(held), first(1, 2, 3, 4))
        self.assertEqual(self.portal.calls, [(self.WINDOW, 1), (self.WINDOW, 2)])

    def test_a_repeat_falls_back_to_single_days(self):
        count, held = self.rows(self.windows, *self.WINDOW)
        # The total of the window, not of the last day read.
        self.assertEqual(count, 4)
        self.assertEqual(keys(held), first(1, 2, 3, 4))
        self.assertEqual(self.portal.asked(*self.WINDOW), [1, 2])
        self.assertEqual(self.portal.asked(*self.FIRST), [1])
        self.assertEqual(self.portal.asked(*self.SECOND), [1])

    def test_a_day_short_in_the_fallback_is_asked_again(self):
        self.windows[self.SECOND] = (3, [[[row(2), row(3)], [row(3)]],
                                         [[row(2), row(3)], [row(4)]]])
        count, held = self.rows(self.windows, *self.WINDOW)
        self.assertEqual(count, 4)
        self.assertEqual(keys(held), first(1, 2, 3, 4))
        self.assertEqual(self.portal.asked(*self.SECOND), [1, 2, 1, 2])

    def test_one_day_that_stays_short_is_truncated(self):
        self.windows[self.SECOND] = (3, [[[row(2), row(3)], [row(3)]]])
        with self.assertRaises(dk_targets.Truncated):
            self.rows(self.windows, *self.WINDOW)

    def test_a_row_outside_the_window_on_the_first_read(self):
        outside = row(4, date="05-09-2026")
        self.windows[self.WINDOW] = (4, [[[self.one, row(2)], [row(3), outside]]])
        with self.assertRaises(dk_targets.OutsideWindow):
            self.rows(self.windows, *self.WINDOW)

    def test_a_row_outside_the_window_in_the_fallback(self):
        outside = row(4, date="05-09-2026")
        self.windows[self.SECOND] = (3, [[[row(2), row(3), outside]]])
        with self.assertRaises(dk_targets.OutsideWindow):
            self.rows(self.windows, *self.WINDOW)


if __name__ == "__main__":
    unittest.main()
