#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A window read late: the newest live notice of a procedure is the one its home is made of.

`dk_page.search` serves the window, `dk_targets.procedure` every notice of a procedure and
`dk_page.detail` a detail per notice. `dk_fetch.fetch` runs for real into a temporary folder;
the only documents links are on a host no reader knows. `net.open_url` fails loudly.
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

P1 = "aaaaaaaa-1111-4111-8111-111111111111"
P2 = "bbbbbbbb-2222-4222-8222-222222222222"
P3 = "cccccccc-3333-4333-8333-333333333333"

OLD_URL = "https://documents.example.invalid/old"
NEW_URL = "https://documents.example.invalid/new"


def row(nid, title, code="competition", npn="", version="01", date="02-09-2026", change=False):
    return {"dataDa": {"titel": title, "ordregiver": "Eksempel Kommune",
                       "ordregiverIdDatavasket": "12345678", "publiceringsdato": date,
                       "cpvKode": "45000000", "cpvTitel": "Bygge- og anlægsarbejder",
                       "formulartype": code, "formulartypeKode": code,
                       "tidsfrister": ["2030-01-01T10:00:00Z"],
                       "beskrivelse": "Beskrivelse af %s." % title, "erAendring": change},
            "dataEn": {"titel": title},
            "noticeId": nid, "noticeVersion": version, "noticePublicationNumber": npn}


def detail(procedure, documents=()):
    html = ('<html><body><section>2&nbsp;<span class="label">Procedure</span>'
            '<section><span class="label">Identifikator for proceduren</span>'
            '<span class="text">: </span><span class="value">%s</span></section>'
            '</section></body></html>' % procedure)
    return {"htmlDA": html, "htmlEN": "", "opsummeringDA": {"udbudsDokumenter": list(documents)}}


def detail_without_procedure():
    """A plan's detail as udbud.dk serves most of them: an internal id, no procedure."""
    html = ('<html><body><section>2&nbsp;<span class="label">Procedure</span>'
            '<section><span class="label">Intern ID</span>'
            '<span class="text">: </span><span class="value">KYC#1</span></section>'
            '</section></body></html>')
    return {"htmlDA": html, "htmlEN": "", "opsummeringDA": {"udbudsDokumenter": []}}


# The window of Wednesday 2026-09-02, read after the notices below it were published.
OLD = row("n-old", "Alfa skole renovering", npn="00600001-2026")
GATED = row("n-gated", "Omega kantinedrift")
NEW = row("n-new", "Alfa skole renovering", npn="00610001-2026", version="02",
          date="09-09-2026", change=True)
AWARD = row("n-award", "Alfa skole renovering", code="result", npn="00620001-2026",
            date="20-10-2026")
# Plans of the same procedure: two published after the window, one inside it (national).
LATER_PLAN = row("n-later-plan", "Alfa skole renovering", code="planning", date="09-09-2026")
LATER_CONSULTATION = row("n-later-cons", "Alfa skole renovering", code="consultation",
                         date="16-09-2026")
WINDOW_PLAN = row("n-window-plan", "Alfa skole renovering", code="planning")


def no_network(*args, **kwargs):
    raise AssertionError("a test reached the network")


class Newest(unittest.TestCase):

    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.out, True)
        self.details = {"n-old": detail(P1), "n-new": detail(P1), "n-award": detail(P1),
                        "n-gated": detail(P3), "n-later-plan": detail(P1),
                        "n-later-cons": detail(P1), "n-window-plan": detail(P1)}
        self.held = {}
        self.asked = []
        self.unreachable = set()
        self.eu = {"600001-2026"}
        for patcher in (mock.patch.object(net, "open_url", side_effect=no_network),
                        mock.patch.object(dk_page, "detail", side_effect=self.detail),
                        mock.patch.object(dk_targets, "procedure", side_effect=self.procedure),
                        mock.patch.object(dk_recon, "ted_numbers", side_effect=self.ted)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def ted(self, day):
        return set(self.eu) if day == DATE else set()

    def detail(self, notice_id, version, npn, timeout=60):
        if notice_id in self.unreachable:
            raise net.Unreachable("gave up")
        return self.details.get(notice_id)

    def procedure(self, reference):
        key = reference.strip().lower()
        key = key[3:] if key.startswith("dk:") else key
        self.asked.append(key)
        if key in self.unreachable:
            raise net.Unreachable("gave up")
        found = [dk_page.notice(r) for r in self.held.get(key, [])]
        return sorted(found, key=lambda t: (t["published"], t["notice_version"]), reverse=True)

    def run_day(self, rows=(OLD,), watch=None, one=None):
        page = {"resultatElementDtoList": list(rows), "totaltAntalResultater": len(rows)}
        with mock.patch.object(dk_page, "search", return_value=page), \
                mock.patch.object(dk_targets, "one", side_effect=one or (lambda ref: None)), \
                mock.patch.object(dk_fetch, "fetch", wraps=dk_fetch.fetch) as fetch:
            day, changes = dk_day.run(DATE, self.out, policy=POLICY, watch=watch, run_id="test")
        self.fetched = [(c.args[0]["pid"], c.args[0]["notice_id"]) for c in fetch.call_args_list]
        return day, changes

    def superseded(self, changes):
        return [s["notice_id"] for s in changes["superseded"]]

    def read(self, name):
        with open(os.path.join(self.out, "tenders", P1, name), encoding="utf-8") as fh:
            return json.load(fh)

    def homes(self):
        return sorted(os.listdir(os.path.join(self.out, "tenders")))

    def assert_window_notice_kept(self, day, changes):
        self.assertEqual(self.fetched, [(P1, "n-old")])
        self.assertEqual(changes["superseded"], [])
        self.assertEqual(self.homes(), [P1])
        self.assertEqual(day["lost"], [])
        self.assertTrue(day["complete"], day)

    def test_a_later_amendment_is_the_one_fetched(self):
        self.held[P1] = [NEW, OLD]
        day, changes = self.run_day()
        self.assertEqual(self.fetched, [(P1, "n-new")])
        self.assertEqual(self.homes(), [P1])
        self.assertEqual([t["pid"] for t in day["tenders"]], [P1])
        tender, = changes["tenders"]
        self.assertEqual((tender["pid"], tender["ref"], tender["kind"], tender["published"]),
                         (P1, "00610001-2026", "amendment", "2026-09-09"))
        self.assertEqual((day["coverage"]["delivered"], day["coverage"]["failed"]), (1, 0))
        self.assertTrue(day["complete"], day)

    def test_the_windows_own_notice_is_named_as_superseded(self):
        self.held[P1] = [NEW, OLD]
        day, changes = self.run_day()
        older, = changes["superseded"]
        self.assertEqual((older["pid"], older["notice_id"], older["ref"], older["kind"]),
                         (P1, "n-old", "00600001-2026", "tender"))

    def test_with_no_later_notice_the_windows_own_is_fetched(self):
        self.held[P1] = [OLD]
        self.assert_window_notice_kept(*self.run_day())
        self.assertEqual(set(self.asked), {P1})

    def test_a_notice_of_the_same_day_never_wins(self):
        self.held[P1] = [dict(NEW, dataDa=dict(NEW["dataDa"], publiceringsdato="02-09-2026")), OLD]
        self.assert_window_notice_kept(*self.run_day())

    def test_a_notice_of_an_earlier_day_never_wins(self):
        self.held[P1] = [OLD, dict(NEW, dataDa=dict(NEW["dataDa"], publiceringsdato="28-08-2026"))]
        self.assert_window_notice_kept(*self.run_day())

    def test_a_later_award_neither_removes_nor_closes_the_competition(self):
        self.held[P1] = [AWARD, OLD]
        day, changes = self.run_day()
        self.assert_window_notice_kept(day, changes)
        self.assertEqual(changes["closed"], [])

    def test_with_a_later_award_and_amendment_the_amendment_is_fetched(self):
        self.held[P1] = [AWARD, NEW, OLD]
        day, changes = self.run_day()
        self.assertEqual(self.fetched, [(P1, "n-new")])
        self.assertEqual(self.superseded(changes), ["n-old"])
        self.assertEqual(changes["closed"], [])

    def test_a_later_notice_with_no_detail_is_ignored(self):
        self.held[P1] = [NEW, OLD]
        del self.details["n-new"]
        self.assert_window_notice_kept(*self.run_day())

    def test_a_later_notice_of_another_procedure_is_ignored(self):
        self.held[P1] = [NEW, OLD]
        self.details["n-new"] = detail(P2)
        self.assert_window_notice_kept(*self.run_day())

    def test_the_lookup_raising_keeps_the_windows_notice(self):
        self.held[P1] = [NEW, OLD]
        self.unreachable.add(P1)
        self.assert_window_notice_kept(*self.run_day())

    def test_the_newer_detail_raising_keeps_the_windows_notice(self):
        self.held[P1] = [NEW, OLD]
        self.unreachable.add("n-new")
        self.assert_window_notice_kept(*self.run_day())

    def test_a_gated_row_asks_for_no_lookup(self):
        self.held[P1] = [OLD]
        day, changes = self.run_day(rows=(OLD, GATED))
        self.assertIn(P1, self.asked)
        self.assertNotIn(P3, self.asked)
        self.assertEqual([g["pid"] for g in changes["gated"]], [P3])
        self.assertEqual(day["coverage"]["gated"], 1)
        self.assertEqual(self.fetched, [(P1, "n-old")])

    def test_a_watched_tender_outside_the_window_is_what_the_watch_lookup_answers(self):
        outside = row("n-watch", "Omega bro", date="20-08-2026")
        later = row("n-later", "Omega bro", version="02", date="09-09-2026", change=True)
        self.details.update({"n-watch": detail(P2), "n-later": detail(P2)})
        self.held = {P1: [OLD], P2: [later, outside]}
        day, changes = self.run_day(watch=["DK:" + P2], one=lambda ref: dk_page.enrich(
            dk_page.notice(outside), self.details["n-watch"]))
        self.assertEqual(sorted(self.fetched), [(P1, "n-old"), (P2, "n-watch")])
        self.assertEqual(changes["superseded"], [])

    def test_a_watched_tender_in_the_window_is_not_changed(self):
        self.held[P1] = [NEW, OLD]
        day, changes = self.run_day(watch=["DK:" + P1], one=lambda ref: dk_page.enrich(
            dk_page.notice(OLD), self.details["n-old"]))
        self.assert_window_notice_kept(day, changes)
        self.assertTrue(changes["tenders"][0]["watched"])

    def test_the_documents_and_the_link_come_from_the_newer_notice(self):
        self.held[P1] = [NEW, OLD]
        self.details.update({"n-old": detail(P1, [OLD_URL]), "n-new": detail(P1, [NEW_URL])})
        day, changes = self.run_day()
        index, procurement = self.read("index.json"), self.read("procurement.json")
        self.assertEqual(index["documents_link"], NEW_URL)
        self.assertEqual(procurement["documents_urls"], [NEW_URL])
        self.assertEqual(procurement["notice_id"], "n-new")
        for link in (index["link"], procurement["link"]):
            self.assertIn("n-new", link)
            self.assertNotIn("n-old", link)
        self.assertEqual(self.read("notice.json")["opsummeringDA"]["udbudsDokumenter"], [NEW_URL])
        self.assertEqual(changes["tenders"][0]["documents_available"], "unknown")

    def test_of_several_later_notices_the_newest_is_fetched(self):
        newest = row("n-newest", "Alfa skole renovering", npn="00615001-2026", version="03",
                     date="16-09-2026", change=True)
        self.details["n-newest"] = detail(P1)
        self.held[P1] = [NEW, newest, OLD]
        day, changes = self.run_day()
        self.assertEqual(self.fetched, [(P1, "n-newest")])
        self.assertIn("n-old", self.superseded(changes))
        self.assertEqual(changes["tenders"][0]["published"], "2026-09-16")

    # Plans and consultations (README, "Three ids" and "Coverage proof"): a plan never takes
    # a competition's place; a newer competition takes a plan's.

    def test_a_later_plan_never_takes_the_place_of_the_competition(self):
        self.held[P1] = [LATER_PLAN, OLD]
        day, changes = self.run_day()
        self.assert_window_notice_kept(day, changes)
        self.assertEqual(changes["tenders"][0]["kind"], "tender")

    def test_a_later_consultation_never_takes_the_place_of_the_competition(self):
        self.held[P1] = [LATER_CONSULTATION, LATER_PLAN, OLD]
        self.assert_window_notice_kept(*self.run_day())

    def test_a_later_plan_does_not_hide_a_later_amendment(self):
        # The consultation is the newest notice of the procedure; the newest one that may take
        # the competition's place is the amendment before it.
        self.held[P1] = [LATER_CONSULTATION, NEW, OLD]
        day, changes = self.run_day()
        self.assertEqual(self.fetched, [(P1, "n-new")])
        self.assertEqual(self.superseded(changes), ["n-old"])

    def test_a_plan_that_prints_a_procedure_is_replaced_by_a_later_competition(self):
        self.eu = set()
        self.held[P1] = [NEW, WINDOW_PLAN]
        day, changes = self.run_day(rows=(WINDOW_PLAN,))
        self.assertEqual(self.fetched, [(P1, "n-new")])
        self.assertEqual(self.homes(), [P1])
        self.assertEqual(self.superseded(changes), ["n-window-plan"])
        tender, = changes["tenders"]
        self.assertEqual((tender["pid"], tender["kind"]), (P1, "amendment"))

    def test_a_plan_keyed_on_its_notice_asks_for_no_lookup(self):
        self.eu = set()
        self.details["n-window-plan"] = detail_without_procedure()
        day, changes = self.run_day(rows=(WINDOW_PLAN,))
        self.assertEqual(self.asked, [])
        self.assertEqual(self.fetched, [("notice-n-window-plan", "n-window-plan")])
        self.assertEqual(self.homes(), ["notice-n-window-plan"])
        self.assertEqual(changes["superseded"], [])
        self.assertTrue(day["complete"], day)


if __name__ == "__main__":
    unittest.main()
