#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A home never goes back to an older notice, across runs either.

The window and the portal are those of `test_dk_day_newest`: `dk_page.search` serves the window,
`dk_targets.procedure` every notice of a procedure and `dk_page.detail` a detail per notice.
`dk_fetch.fetch` runs for real into a temporary folder. The home a run finds is either answered by
a stand-in for `homes.held`, or built on disk under `<out>/tenders/<pid>/` and read by the real
one. `net.open_url` fails loudly and the five GRAPH_* variables are cleared, so no drive is read.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
if HERE not in sys.path:
    sys.path.insert(1, HERE)

import dk_day
import dk_fetch
import dk_page
import dk_recon
import dk_targets
import homes
import net
from test_dk_day_newest import DATE, NEW, OLD, P1, P2, POLICY, detail, no_network, row

GRAPH = ("GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET", "GRAPH_DRIVE_ID",
         "GRAPH_DEST_ROOT")


def a_home(pid, published, notices=None):
    """What `homes.held` answers for a home whose newest notice was published on `published`."""
    notices = [published] if notices is None else notices
    return {"index": {"pid": pid, "documents": []},
            "manifest": {"documents": [], "withheld_records": []},
            "normalized": {"documents": [], "unreadable_files": []},
            "procurement": {"pid": pid, "published": published,
                            "notices": [{"published": p} for p in notices]},
            "state": {"pid": pid, "tool": "an older run"},
            "where": "disk"}


class DayCase(unittest.TestCase):

    def setUp(self):
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for name in GRAPH:
            os.environ.pop(name, None)
        self.out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.out, True)
        self.details = {"n-old": detail(P1), "n-new": detail(P1)}
        self.portal = {P1: [OLD]}
        self.unreachable = set()
        self.homes = {}
        for patcher in (mock.patch.object(net, "open_url", side_effect=no_network),
                        mock.patch.object(dk_page, "detail", side_effect=self.detail),
                        mock.patch.object(dk_targets, "procedure", side_effect=self.procedure),
                        mock.patch.object(dk_recon, "ted_numbers", side_effect=self.ted)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def ted(self, day):
        return {"600001-2026"} if day == DATE else set()

    def detail(self, notice_id, version, npn, timeout=60):
        return self.details.get(notice_id)

    def procedure(self, reference):
        key = reference.strip().lower()
        key = key[3:] if key.startswith("dk:") else key
        if key in self.unreachable:
            raise net.Unreachable("gave up")
        found = [dk_page.notice(r) for r in self.portal.get(key, [])]
        return sorted(found, key=lambda t: (t["published"], t["notice_version"]), reverse=True)

    def held(self, out_root, pid):
        return self.homes.get(pid)

    def run_day(self, watch=None, one=None, patch_held=True):
        page = {"resultatElementDtoList": [OLD], "totaltAntalResultater": 1}
        patches = [mock.patch.object(dk_page, "search", return_value=page),
                   mock.patch.object(dk_targets, "one", side_effect=one or (lambda ref: None))]
        if patch_held:
            patches.append(mock.patch.object(homes, "held", side_effect=self.held))
        started = [p.start() for p in patches]
        try:
            with mock.patch.object(dk_fetch, "fetch", wraps=dk_fetch.fetch) as fetch:
                day, changes = dk_day.run(DATE, self.out, policy=POLICY, watch=watch,
                                          run_id="test")
        finally:
            for p in reversed(patches):
                p.stop()
        self.held_calls = started[2].call_args_list if patch_held else []
        self.fetch_calls = fetch.call_args_list
        self.fetched = [(c.args[0]["pid"], c.args[0]["notice_id"]) for c in fetch.call_args_list]
        return day, changes

    def kept(self, changes, pid=P1):
        return [s for s in changes["superseded"] if s.get("pid") == pid and "kept_home" in s]

    def written(self, name):
        with open(os.path.join(self.out, DATE, name), encoding="utf-8") as fh:
            return json.load(fh)


class KeptHome(DayCase):

    # ------------------------------------------------------------ a later home keeps the tender

    def test_a_home_with_a_later_notice_is_not_fetched(self):
        self.homes[P1] = a_home(P1, "2026-09-09")
        day, changes = self.run_day()
        self.assertEqual(self.fetched, [])
        self.assertNotIn(P1, [t["pid"] for t in day["tenders"]])

    def test_the_notice_is_named_under_superseded_with_the_homes_date(self):
        self.homes[P1] = a_home(P1, "2026-09-09")
        day, changes = self.run_day()
        kept, = self.kept(changes)
        self.assertEqual((kept["pid"], kept["notice_id"], kept["kept_home"]),
                         (P1, "n-old", "2026-09-09"))

    def test_the_changes_file_written_says_the_same(self):
        self.homes[P1] = a_home(P1, "2026-09-09")
        self.run_day()
        kept, = self.kept(self.written("changes.json"))
        self.assertEqual((kept["notice_id"], kept["kept_home"]), ("n-old", "2026-09-09"))
        self.assertNotIn(P1, [t["pid"] for t in self.written("day.json")["tenders"]])

    def test_a_tender_of_the_window_kept_is_not_lost(self):
        self.homes[P1] = a_home(P1, "2026-09-09")
        day, changes = self.run_day()
        self.assertEqual(day["lost"], [])
        self.assertTrue(day["complete"], day)

    def test_the_newest_of_the_homes_notices_counts(self):
        self.homes[P1] = a_home(P1, "2026-08-20", notices=["2026-08-20", "2026-09-16"])
        day, changes = self.run_day()
        self.assertEqual(self.fetched, [])
        kept, = self.kept(changes)
        self.assertEqual(kept["kept_home"], "2026-09-16")

    def test_held_is_asked_for_the_tender(self):
        self.homes[P1] = a_home(P1, "2026-09-09")
        self.run_day()
        asked = [tuple((c.args + tuple(c.kwargs.values()))[:2]) for c in self.held_calls]
        self.assertIn((self.out, P1), asked)

    # ------------------------------------------------------------ otherwise it is fetched

    def test_a_home_of_the_same_day_is_fetched(self):
        self.homes[P1] = a_home(P1, DATE)
        day, changes = self.run_day()
        self.assertEqual(self.fetched, [(P1, "n-old")])
        self.assertEqual(self.kept(changes), [])
        self.assertEqual([t["pid"] for t in day["tenders"]], [P1])

    def test_a_home_of_an_earlier_day_is_fetched(self):
        self.homes[P1] = a_home(P1, "2026-08-20")
        day, changes = self.run_day()
        self.assertEqual(self.fetched, [(P1, "n-old")])
        self.assertEqual(self.kept(changes), [])

    def test_no_home_is_fetched(self):
        day, changes = self.run_day()
        self.assertEqual(self.fetched, [(P1, "n-old")])
        self.assertEqual(self.kept(changes), [])

    def test_the_fetch_is_given_the_home(self):
        self.homes[P1] = a_home(P1, "2026-08-20")
        self.run_day()
        call, = self.fetch_calls
        self.assertIs(call.kwargs.get("held"), self.homes[P1])

    # ------------------------------------------------------------ the notice about to be read

    def test_compared_with_the_newer_notice_the_portal_answers(self):
        self.portal[P1] = [NEW, OLD]
        self.homes[P1] = a_home(P1, "2026-09-05")
        day, changes = self.run_day()
        self.assertEqual(self.fetched, [(P1, "n-new")])
        self.assertEqual(self.kept(changes), [])

    def test_a_home_later_than_the_portals_newer_notice_keeps_it(self):
        self.portal[P1] = [NEW, OLD]
        self.homes[P1] = a_home(P1, "2026-09-16")
        day, changes = self.run_day()
        self.assertEqual(self.fetched, [])
        self.assertNotIn(P1, [t["pid"] for t in day["tenders"]])
        kept = self.kept(changes)
        self.assertIn("n-new", [k["notice_id"] for k in kept])
        for k in kept:
            self.assertEqual(k["kept_home"], "2026-09-16")

    def test_a_portal_that_does_not_answer_is_closed_by_the_homes_history(self):
        self.portal[P1] = [NEW, OLD]
        self.unreachable.add(P1)
        self.homes[P1] = a_home(P1, "2026-09-09")
        day, changes = self.run_day()
        self.assertEqual(self.fetched, [])
        kept, = self.kept(changes)
        self.assertEqual((kept["notice_id"], kept["kept_home"]), ("n-old", "2026-09-09"))

    # ------------------------------------------------------------ a watched tender

    def watched_outside(self):
        outside = row("n-watch", "Omega bro", date="20-08-2026")
        self.details["n-watch"] = detail(P2)
        self.portal[P2] = [outside]
        return outside

    def watch_lookup(self, outside):
        return lambda ref: dk_page.enrich(dk_page.notice(outside), self.details["n-watch"])

    def test_a_watched_tender_kept_is_lost_and_watched(self):
        outside = self.watched_outside()
        self.homes[P2] = a_home(P2, "2026-09-09")
        day, changes = self.run_day(watch=["DK:" + P2], one=self.watch_lookup(outside))
        self.assertNotIn(P2, [pid for pid, _ in self.fetched])
        self.assertNotIn(P2, [t["pid"] for t in day["tenders"]])
        kept, = self.kept(changes, P2)
        self.assertEqual((kept["notice_id"], kept["kept_home"]), ("n-watch", "2026-09-09"))
        lost = [entry for entry in day["lost"] if P2 in json.dumps(entry)]
        self.assertEqual(len(lost), 1, day["lost"])
        self.assertIs(lost[0]["watched"], True)

    def test_a_watched_tender_with_an_older_home_is_fetched(self):
        outside = self.watched_outside()
        self.homes[P2] = a_home(P2, "2026-08-01")
        day, changes = self.run_day(watch=["DK:" + P2], one=self.watch_lookup(outside))
        self.assertIn((P2, "n-watch"), self.fetched)
        self.assertEqual(self.kept(changes, P2), [])
        self.assertFalse([entry for entry in day["lost"] if P2 in json.dumps(entry)])


class KeptHomeOnDisk(DayCase):
    """The same rule with a home on disk, read by the real `homes.held`."""

    def build(self, published):
        home = os.path.join(self.out, "tenders", P1)
        os.makedirs(home)
        files = {"index.json": {"pid": P1, "documents": []},
                 "state.json": {"pid": P1, "tool": "an older run"},
                 "procurement.json": {"pid": P1, "published": published,
                                      "notices": [{"published": published}]}}
        for name, body in files.items():
            with open(os.path.join(home, name), "w", encoding="utf-8") as fh:
                json.dump(body, fh)
        return home

    def snapshot(self, home):
        found = {}
        for where, _, names in os.walk(home):
            for name in names:
                path = os.path.join(where, name)
                with open(path, "rb") as fh:
                    found[os.path.relpath(path, home)] = fh.read()
        return found

    def test_a_later_home_on_disk_is_left_as_it_is(self):
        home = self.build("2026-09-09")
        before = self.snapshot(home)
        day, changes = self.run_day(patch_held=False)
        self.assertEqual(self.fetched, [])
        self.assertEqual(self.snapshot(home), before)
        kept, = self.kept(changes)
        self.assertEqual(kept["kept_home"], "2026-09-09")

    def test_an_earlier_home_on_disk_is_fetched(self):
        self.build("2026-08-20")
        day, changes = self.run_day(patch_held=False)
        self.assertEqual(self.fetched, [(P1, "n-old")])
        self.assertEqual(self.kept(changes), [])


class NewestPublished(unittest.TestCase):

    def test_the_notices_alone(self):
        held = {"procurement": {"notices": [{"published": "2026-09-02"},
                                            {"published": "2026-11-23"}]}}
        self.assertEqual(homes.newest_published(held), "2026-11-23")

    def test_the_procurement_alone(self):
        self.assertEqual(homes.newest_published({"procurement": {"published": "2026-11-17",
                                                                 "notices": []}}),
                         "2026-11-17")


if __name__ == "__main__":
    unittest.main()
