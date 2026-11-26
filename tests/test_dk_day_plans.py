#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Plans and market consultations in a Danish window: judged, fetched and homed like competitions.

README, "Three ids" and "What a day fetches". `dk_page.search` serves one window,
`dk_page.detail` a detail per notice, `dk_recon.ted_numbers` the EU numbers of the day.
`dk_fetch.fetch` runs for real into a temporary folder; no detail names a documents link.
`net.open_url` fails loudly.
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

DATE = "2026-09-02"
POLICY = json.dumps({"recall_title_terms": ["alfa"]})

P1 = "11111111-1111-4111-8111-111111111111"
P2 = "22222222-2222-4222-8222-222222222222"

PLAN = "a0000000-0000-4000-8000-000000000001"
GATED_PLAN = "a0000000-0000-4000-8000-000000000002"
WATCHED_PLAN = "a0000000-0000-4000-8000-000000000003"

SUMMARY_KEYS = ("pid", "ref", "kind", "title", "buyer", "published", "link", "notice_id", "npn",
                "form_code")


def row(nid, title, code="competition", npn="", version="01", date="02-09-2026", change=False):
    return {"dataDa": {"titel": title, "ordregiver": "Eksempel Kommune",
                       "ordregiverIdDatavasket": "12345678", "publiceringsdato": date,
                       "cpvKode": "45000000", "cpvTitel": "Bygge- og anlægsarbejder",
                       "formulartype": code, "formulartypeKode": code,
                       "tidsfrister": ["2030-01-01T10:00:00Z"],
                       "beskrivelse": "Beskrivelse af %s." % title, "erAendring": change},
            "dataEn": {"titel": title},
            "noticeId": nid, "noticeVersion": version, "noticePublicationNumber": npn}


def _leaf(label, value):
    return ('<section><span class="label">%s</span><span class="text">: </span>'
            '<span class="value">%s</span></section>' % (label, value))


def detail(procedure=None, intern=None):
    """A detail that prints a procedure, an internal id, both or neither."""
    leaves = ""
    if procedure is not None:
        leaves += _leaf("Identifikator for proceduren", procedure)
    if intern is not None:
        leaves += _leaf("Intern ID", intern)
    html = ('<html><body><section>2&nbsp;<span class="label">Procedure</span>'
            '<section>%s</section></section></body></html>' % leaves)
    return {"htmlDA": html, "htmlEN": "", "opsummeringDA": {"udbudsDokumenter": []}}


# The window of Wednesday 2026-09-02: a competition, a plan with no procedure (but a buyer and
# an internal id), a consultation that prints a procedure, and a plan the gate cuts.
ROWS = [
    row("n-comp", "Alfa skole renovering", npn="00600001-2026"),
    row(PLAN, "Alfa varmestyring og ventilation", code="planning"),
    row("n-cons", "Alfa markedsdialog om CTS", code="consultation"),
    row(GATED_PLAN, "Omega kantinedrift", code="preplanning"),
]
TED = {"600001-2026"}


def no_network(*args, **kwargs):
    raise AssertionError("a test reached the network")


class Plans(unittest.TestCase):

    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.out, True)
        self.details = {"n-comp": detail(P1),
                        PLAN: detail(intern="KYC#1"),
                        "n-cons": detail(P2),
                        GATED_PLAN: detail(intern="KYC#1"),
                        WATCHED_PLAN: detail(intern="Holbæk Kommune")}
        for patcher in (mock.patch.object(net, "open_url", side_effect=no_network),
                        mock.patch.object(dk_page, "detail", side_effect=self.detail),
                        mock.patch.object(dk_recon, "ted_numbers", side_effect=self.ted)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def ted(self, day):
        return set(TED) if day == DATE else set()

    def detail(self, notice_id, version, npn, timeout=60):
        return self.details.get(notice_id)

    def run_day(self, rows=ROWS, watch=None, one=None):
        page = {"resultatElementDtoList": list(rows), "totaltAntalResultater": len(rows)}
        with mock.patch.object(dk_page, "search", return_value=page), \
                mock.patch.object(dk_targets, "one", side_effect=one or (lambda ref: None)), \
                mock.patch.object(dk_fetch, "fetch", wraps=dk_fetch.fetch) as fetch:
            day, changes = dk_day.run(DATE, self.out, policy=POLICY, watch=watch, run_id="test")
        self.fetched = [c.args[0]["pid"] for c in fetch.call_args_list]
        return day, changes

    def home(self, pid, *parts):
        return os.path.join(self.out, "tenders", pid, *parts)

    def homes(self):
        return sorted(os.listdir(os.path.join(self.out, "tenders")))

    def entry(self, listing, pid):
        found = [t for t in listing if t["pid"] == pid]
        self.assertEqual(len(found), 1, (pid, listing))
        return found[0]

    def test_a_plan_past_the_gate_gets_a_home_keyed_on_its_notice(self):
        day, changes = self.run_day()
        pid = "notice-%s" % PLAN
        self.assertIn(pid, self.fetched)
        self.assertTrue(os.path.exists(self.home(pid, "index.json")))
        self.assertTrue(os.path.exists(self.home(pid, "doc", "notice.md")))
        self.assertNotIn("int-12345678-KYC#1", self.homes())
        self.assertEqual([h for h in self.homes() if h.startswith("int-")], [])

    def test_a_plan_past_the_gate_is_listed_under_tenders_with_kind_plan(self):
        day, changes = self.run_day()
        pid = "notice-%s" % PLAN
        self.assertEqual(self.entry(changes["tenders"], pid)["kind"], "plan")
        listed = self.entry(day["tenders"], pid)
        self.assertEqual(listed["kind"], "plan")
        self.assertEqual(listed["home"], "tenders/%s" % pid)

    def test_a_consultation_that_prints_a_procedure_is_homed_on_it(self):
        day, changes = self.run_day()
        self.assertIn(P2, self.fetched)
        self.assertTrue(os.path.exists(self.home(P2, "index.json")))
        self.assertEqual(self.entry(changes["tenders"], P2)["kind"], "consultation")
        self.assertEqual(self.entry(day["tenders"], P2)["kind"], "consultation")

    def test_the_competition_is_still_fetched(self):
        day, changes = self.run_day()
        self.assertIn(P1, self.fetched)
        self.assertEqual(self.entry(changes["tenders"], P1)["kind"], "tender")

    def test_a_plan_the_gate_cuts_is_gated_and_not_fetched(self):
        day, changes = self.run_day()
        pid = "notice-%s" % GATED_PLAN
        gated = self.entry(changes["gated"], pid)
        self.assertEqual(gated["notice_id"], GATED_PLAN)
        self.assertEqual(gated["title"], "Omega kantinedrift")
        self.assertNotIn(pid, self.fetched)
        self.assertFalse(os.path.exists(self.home(pid)))
        self.assertEqual([t for t in changes["tenders"] if t["pid"] == pid], [])
        self.assertEqual(day["coverage"]["gated"], 1)

    def test_plans_still_names_every_plan_fetched_or_gated(self):
        day, changes = self.run_day()
        self.assertEqual(sorted(p["pid"] for p in changes["plans"]),
                         sorted(["notice-%s" % PLAN, P2, "notice-%s" % GATED_PLAN]))
        self.assertEqual(changes["counts"]["plans"], 3)
        self.assertEqual(day["coverage"]["plans"], 3)

    def test_the_summary_of_a_plan(self):
        day, changes = self.run_day()
        for summary in changes["plans"]:
            self.assertEqual([k for k in SUMMARY_KEYS if k not in summary], [], summary)
        plan = self.entry(changes["plans"], "notice-%s" % PLAN)
        self.assertEqual(plan["kind"], "plan")
        self.assertEqual(plan["notice_id"], PLAN)
        self.assertEqual(plan["ref"], PLAN)
        self.assertEqual(plan["npn"], "")
        self.assertEqual(plan["form_code"], "planning")
        self.assertEqual(plan["title"], "Alfa varmestyring og ventilation")
        self.assertEqual(plan["buyer"], "Eksempel Kommune")
        self.assertEqual(plan["published"], "2026-09-02")
        self.assertEqual(self.entry(changes["plans"], P2)["kind"], "consultation")
        self.assertEqual(self.entry(changes["plans"], "notice-%s" % GATED_PLAN)["form_code"],
                         "preplanning")

    def test_competitions_are_not_named_as_plans(self):
        day, changes = self.run_day()
        self.assertNotIn(P1, [p["pid"] for p in changes["plans"]])

    def test_the_whole_window_is_complete(self):
        day, changes = self.run_day()
        self.assertTrue(day["complete"], day)
        self.assertEqual(day["lost"], [])

    def test_a_plan_whose_detail_is_gone_is_lost_and_the_day_incomplete(self):
        del self.details[PLAN]
        day, changes = self.run_day()
        self.assertFalse(day["complete"])
        self.assertIn(PLAN, [lost["ref"] for lost in day["lost"]])
        self.assertNotIn("notice-%s" % PLAN, self.fetched)

    def test_two_plans_of_one_buyer_and_one_internal_id_make_two_homes(self):
        other = "a0000000-0000-4000-8000-000000000009"
        self.details[other] = detail(intern="KYC#1")
        rows = [row(PLAN, "Alfa varmestyring", code="planning"),
                row(other, "Alfa ventilation", code="planning")]
        day, changes = self.run_day(rows=rows)
        both = sorted(["notice-%s" % PLAN, "notice-%s" % other])
        self.assertEqual(sorted(self.fetched), both)
        self.assertEqual(self.homes(), both)
        self.assertEqual(changes["superseded"], [])

    def test_a_watched_plan_is_held_by_its_home_name(self):
        # The title would not pass the gate: a watched card bypasses it.
        reference = "DK:notice-%s" % WATCHED_PLAN
        outside = row(WATCHED_PLAN, "Omega markedsdialog", code="planning", date="20-08-2026")
        asked = []

        def one(ref):
            asked.append(ref)
            return dk_page.enrich(dk_page.notice(outside), self.details[WATCHED_PLAN])
        day, changes = self.run_day(watch=[reference], one=one)
        pid = "notice-%s" % WATCHED_PLAN
        self.assertIn(reference, asked)
        self.assertIn(pid, self.fetched)
        self.assertTrue(os.path.exists(self.home(pid, "index.json")))
        watched = self.entry(changes["tenders"], pid)
        self.assertTrue(watched["watched"])
        self.assertEqual(watched["kind"], "plan")
        self.assertTrue(day["complete"], day)


if __name__ == "__main__":
    unittest.main()
