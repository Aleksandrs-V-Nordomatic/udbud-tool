#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One Danish window, end to end, with the portal, TED and the watch list replaced.

`dk_page.search` serves one window, `dk_page.detail` a detail per notice, and
`dk_recon.ted_numbers` the EU numbers of the day. `dk_fetch.fetch` runs for real into a
temporary folder; none of the details names a documents link, so no document host is asked.
`net.open_url` fails loudly, so anything that slipped through would be an error.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dk_day
import dk_fetch
import dk_page
import dk_recon
import dk_targets
import net

POLICY = json.dumps({"recall_title_terms": ["alfa"]})

P1 = "11111111-1111-1111-1111-111111111111"
P2 = "22222222-2222-2222-2222-222222222222"
P3 = "33333333-3333-3333-3333-333333333333"
P4 = "44444444-4444-4444-4444-444444444444"
P5 = "55555555-5555-5555-5555-555555555555"


def row(nid, title, code="competition", npn="", version="01", date="02-09-2026", change=False):
    return {"dataDa": {"titel": title, "ordregiver": "Eksempel Kommune",
                       "ordregiverIdDatavasket": "12345678", "publiceringsdato": date,
                       "cpvKode": "45000000", "cpvTitel": "Bygge- og anlægsarbejder",
                       "formulartype": code, "formulartypeKode": code,
                       "tidsfrister": ["2030-01-01T10:00:00Z"],
                       "beskrivelse": "Beskrivelse af %s." % title, "erAendring": change},
            "dataEn": {"titel": title},
            "noticeId": nid, "noticeVersion": version, "noticePublicationNumber": npn}


def detail(procedure):
    html = ('<html><body><section>2&nbsp;<span class="label">Procedure</span>'
            '<section><span class="label">Identifikator for proceduren</span>'
            '<span class="text">: </span><span class="value">%s</span></section>'
            '</section></body></html>' % procedure)
    return {"htmlDA": html, "htmlEN": "", "opsummeringDA": {"udbudsDokumenter": []}}


# The window of Wednesday 2026-09-02.
ROWS = [
    row("n-a1", "Alfa skole renovering", npn="00600001-2026", version="01"),
    row("n-a2", "Alfa skole renovering", npn="00600002-2026", version="02", change=True),
    row("n-b", "Alfa hal", code="result", npn="00600003-2026"),
    row("n-c", "Alfa plan", code="planning"),
    row("n-d", "Omega kantinedrift", npn=""),
    row("n-e", "Alfa direkte tildeling", code="dir-awa-pre", npn="00600004-2026"),
]
PROCEDURES = {"n-a1": P1, "n-a2": P1, "n-b": P2, "n-c": P4, "n-d": P3, "n-e": P5}
TED = {"600001-2026", "600002-2026", "600003-2026", "600004-2026"}


def no_network(*args, **kwargs):
    raise AssertionError("a test reached the network")


class Day(unittest.TestCase):

    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.out, True)
        self.details = dict((nid, detail(p)) for nid, p in PROCEDURES.items())
        for patcher in (mock.patch.object(net, "open_url", side_effect=no_network),
                        mock.patch.object(dk_page, "detail", side_effect=self.detail),
                        mock.patch.object(dk_recon, "ted_numbers", side_effect=self.ted)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def ted(self, day):
        return set(TED) if day == "2026-09-02" else set()

    def detail(self, notice_id, version, npn, timeout=60):
        return self.details.get(notice_id)

    def run_day(self, rows=ROWS, date="2026-09-02", date_to=None, watch=None, one=None):
        page = {"resultatElementDtoList": rows, "totaltAntalResultater": len(rows)}
        written = []
        real_write = dk_day._write

        def write(path, payload):
            written.append(os.path.basename(path))
            real_write(path, payload)
        with mock.patch.object(dk_page, "search", return_value=page), \
                mock.patch.object(dk_day, "_write", side_effect=write), \
                mock.patch.object(dk_targets, "one", side_effect=one or (lambda ref: None)), \
                mock.patch.object(dk_fetch, "fetch", wraps=dk_fetch.fetch) as fetch:
            day, changes = dk_day.run(date, self.out, policy=POLICY, watch=watch, date_to=date_to,
                                      run_id="test")
        self.written, self.fetch = written, fetch
        return day, changes

    def fetched(self):
        return [c.args[0]["pid"] for c in self.fetch.call_args_list]

    def test_a_whole_window(self):
        day, changes = self.run_day()
        self.assertTrue(day["complete"], day)
        self.assertFalse(day["discovery_failed"])
        self.assertTrue(day["reconciliation"]["ok"], day["reconciliation"])
        self.assertEqual(day["coverage"]["index_count"], 6)
        self.assertEqual(day["coverage"]["rows_held"], 6)

    def test_competition_rows_are_fetched_into_their_procedure_home(self):
        day, changes = self.run_day()
        self.assertEqual(self.fetched(), [P1])
        self.assertTrue(os.path.exists(os.path.join(self.out, "tenders", P1, "index.json")))
        self.assertTrue(os.path.exists(os.path.join(self.out, "tenders", P1, "doc", "notice.md")))
        self.assertEqual([t["pid"] for t in day["tenders"]], [P1])
        self.assertEqual(day["tenders"][0]["home"], "tenders/%s" % P1)

    def test_awards_go_to_closed_and_are_not_fetched(self):
        day, changes = self.run_day()
        self.assertEqual(sorted(c["pid"] for c in changes["closed"]), [P2, P5])
        self.assertEqual(changes["counts"]["closed"], 2)
        self.assertNotIn(P2, self.fetched())
        self.assertFalse(os.path.exists(os.path.join(self.out, "tenders", P2)))

    def test_plans_are_recorded_and_counted(self):
        day, changes = self.run_day()
        self.assertEqual([p["pid"] for p in changes["plans"]], [P4])
        self.assertEqual(changes["counts"]["plans"], 1)
        self.assertEqual(day["coverage"]["plans"], 1)
        self.assertNotIn(P4, self.fetched())

    def test_a_gated_row_is_recorded_whole_and_not_fetched(self):
        day, changes = self.run_day()
        self.assertEqual(len(changes["gated"]), 1)
        gated = changes["gated"][0]
        self.assertEqual(gated["pid"], P3)
        self.assertEqual(gated["title"], "Omega kantinedrift")
        self.assertEqual(gated["description"], "Beskrivelse af Omega kantinedrift.")
        self.assertEqual(gated["notice_id"], "n-d")
        self.assertIn("link", gated)
        self.assertNotIn("record", gated)
        self.assertNotIn(P3, self.fetched())
        self.assertFalse(os.path.exists(os.path.join(self.out, "tenders", P3)))
        self.assertEqual(day["coverage"]["gated"], 1)

    def test_a_watched_reference_bypasses_the_gate(self):
        def one(reference):
            self.assertEqual(reference, "DK:%s" % P3)
            return dk_page.enrich(dk_page.notice(ROWS[4]), self.details["n-d"])
        day, changes = self.run_day(watch=["DK:%s" % P3], one=one)
        self.assertIn(P3, self.fetched())
        self.assertEqual(changes["gated"], [])
        watched = [t for t in changes["tenders"] if t["pid"] == P3][0]
        self.assertTrue(watched["watched"])
        self.assertEqual(changes["counts"]["watched"], 1)

    def test_a_watched_procedure_outside_the_window_is_fetched(self):
        outside = row("n-w", "Omega uden for vinduet", date="20-08-2026")
        self.details["n-w"] = detail("99999999-9999-9999-9999-999999999999")

        def one(reference):
            return dk_page.enrich(dk_page.notice(outside), self.details["n-w"])
        day, changes = self.run_day(watch=["99999999-9999-9999-9999-999999999999"], one=one)
        self.assertIn("99999999-9999-9999-9999-999999999999", self.fetched())
        self.assertTrue(day["complete"])

    def test_a_watched_procedure_with_no_live_notice_is_a_watch_hole(self):
        day, changes = self.run_day(watch=["DK:gone"], one=lambda ref: None)
        self.assertEqual(day["coverage"]["watch_holes"], 1)
        self.assertTrue(day["lost"][0]["watched"])
        self.assertTrue(day["complete"], "a watch hole does not make the window incomplete")

    def test_two_notices_of_one_procedure_make_one_home(self):
        day, changes = self.run_day()
        self.assertEqual(self.fetch.call_count, 1)
        self.assertEqual(self.fetch.call_args.args[0]["notice_id"], "n-a2")
        self.assertEqual([s["notice_id"] for s in changes["superseded"]], ["n-a1"])
        homes = os.listdir(os.path.join(self.out, "tenders"))
        self.assertEqual(homes, [P1])

    def test_day_json_is_written_after_changes_json(self):
        self.run_day()
        self.assertEqual(self.written[-2:], ["changes.json", "day.json"])
        folder = os.path.join(self.out, "2026-09-02")
        self.assertTrue(os.path.exists(os.path.join(folder, "changes.json")))
        with open(os.path.join(folder, "day.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["schema"], "day/1")

    def test_a_live_row_whose_detail_is_gone_is_lost_and_the_day_incomplete(self):
        del self.details["n-a2"]
        day, changes = self.run_day()
        self.assertFalse(day["complete"])
        self.assertEqual(day["coverage"]["failed"], 1)
        self.assertEqual(day["lost"][0]["ref"], "00600002-2026")

    def test_an_empty_weekday_is_a_failed_discovery(self):
        day, changes = self.run_day(rows=[], date="2026-09-02")
        self.assertTrue(day["discovery_failed"])
        self.assertFalse(day["complete"])
        self.assertTrue(changes["discovery_failed"])
        self.assertFalse(changes["complete"])

    def test_an_empty_weekend_is_a_normal_empty_day(self):
        day, changes = self.run_day(rows=[], date="2026-08-29", date_to="2026-08-30")
        self.assertFalse(day["discovery_failed"])
        self.assertTrue(day["complete"], day)
        self.assertEqual(day["date"], "2026-08-30")
        self.assertTrue(os.path.exists(os.path.join(self.out, "2026-08-30", "day.json")))

    def test_a_truncated_window_is_a_failed_discovery_with_its_reason(self):
        page = {"resultatElementDtoList": ROWS[:2], "totaltAntalResultater": 40}
        with mock.patch.object(dk_page, "search", side_effect=[page, {"resultatElementDtoList": [], "totaltAntalResultater": 40}]):
            day, changes = dk_day.run("2026-09-02", self.out, policy=POLICY, run_id="test")
        self.assertTrue(day["discovery_failed"])
        self.assertFalse(day["complete"])
        self.assertIn("40", day["discovery_error"])
        self.assertIsNone(day["reconciliation"])

    def test_a_ted_difference_makes_the_day_incomplete(self):
        with mock.patch.object(dk_recon, "ted_numbers", side_effect=lambda day: TED | {"699999-2026"}):
            day, changes = self.run_day()
        self.assertFalse(day["complete"])
        self.assertFalse(day["reconciliation"]["ok"])


if __name__ == "__main__":
    unittest.main()
