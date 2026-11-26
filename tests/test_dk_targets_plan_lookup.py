#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A plan's card, `DK:notice-<uuid>`: what the lookup keeps and what it answers.

README, "Three ids": the lookup searches the notice id lower-cased, keeps only the notice that
carries exactly that id in any case of letters, and answers a competition before a plan, also
when it was asked for a plan that prints that procedure. `dk_page.search` and `dk_page.detail`
are stand-ins; nothing reaches the network.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dk_page
import dk_targets

PROCEDURE = "7c03c120-69c0-4112-af76-3d30b1aab18e"
OTHER_PROCEDURE = "0b9e8d7c-6f5a-4b3c-8d2e-1f0a9b8c7d6e"
PLAN = "a183b490-5a69-4788-9a0b-c1d2e3f40001"
UNRELATED = "5e6f7a8b-1c2d-4e3f-9a0b-c1d2e3f40002"


def row(nid, date="02-09-2026", code="competition", version="01", change=False):
    return {"dataDa": {"titel": "Opgave %s" % nid, "publiceringsdato": date,
                       "formulartypeKode": code, "ordregiver": "Kommune",
                       "ordregiverIdDatavasket": "12345678", "erAendring": change},
            "dataEn": {},
            "noticeId": nid, "noticeVersion": version, "noticePublicationNumber": ""}


def _leaf(label, value):
    return ('<section><span class="label">%s</span><span class="text">: </span>'
            '<span class="value">%s</span></section>' % (label, value))


def detail_of(procedure=None, intern=None):
    html = ""
    if procedure is not None:
        html += _leaf("Identifikator for proceduren", procedure)
    if intern is not None:
        html += _leaf("Intern ID", intern)
    return {"htmlDA": html, "opsummeringDA": {}}


class Lookup(unittest.TestCase):
    """A stand-in portal: rows by the free text searched, details by notice id."""

    def setUp(self):
        self.by_text = {}
        self.details = {}
        self.texts = []

    def search(self, date_from=None, date_to=None, page=1, text=None, size=None):
        self.texts.append(text)
        rows = self.by_text.get(text, [])
        return {"resultatElementDtoList": rows, "totaltAntalResultater": len(rows)}

    def detail(self, notice_id, version, npn, timeout=60):
        return self.details.get(notice_id)

    def patched(self):
        return mock.patch.object(dk_page, "search", side_effect=self.search), \
            mock.patch.object(dk_page, "detail", side_effect=self.detail)

    def one(self, reference):
        s, d = self.patched()
        with s, d:
            return dk_targets.one(reference)

    def procedure(self, reference):
        s, d = self.patched()
        with s, d:
            return dk_targets.procedure(reference)


class CompetitionFirst(Lookup):
    """Answer 1: asked for a plan that prints procedure P, the lookup answers P's competition."""

    def setUp(self):
        super().setUp()
        self.by_text[PLAN] = [row(PLAN, date="01-09-2026", code="planning")]
        self.details[PLAN] = detail_of(PROCEDURE)

    def test_a_newer_plan_and_an_older_competition_answer_the_competition(self):
        self.by_text[PROCEDURE] = [row(PLAN, date="01-09-2026", code="planning"),
                                   row("n-comp", date="05-09-2026"),
                                   row("n-plan2", date="10-09-2026", code="planning")]
        self.details["n-comp"] = detail_of(PROCEDURE)
        self.details["n-plan2"] = detail_of(PROCEDURE)
        found = self.one("DK:notice-%s" % PLAN)
        self.assertIsNotNone(found)
        self.assertEqual(found["notice_id"], "n-comp")
        self.assertEqual(found["kind"], "tender")
        self.assertEqual(found["pid"], PROCEDURE)

    def test_the_bare_home_name_too(self):
        self.by_text[PROCEDURE] = [row(PLAN, date="01-09-2026", code="planning"),
                                   row("n-comp", date="05-09-2026"),
                                   row("n-cons", date="10-09-2026", code="consultation")]
        self.details["n-comp"] = detail_of(PROCEDURE)
        self.details["n-cons"] = detail_of(PROCEDURE)
        self.assertEqual(self.one("notice-%s" % PLAN)["notice_id"], "n-comp")

    def test_of_two_bid_notices_the_newer_is_taken_before_a_newest_plan(self):
        self.by_text[PROCEDURE] = [row(PLAN, date="01-09-2026", code="planning"),
                                   row("n-comp", date="03-09-2026"),
                                   row("n-amend", date="06-09-2026", code="change"),
                                   row("n-plan2", date="10-09-2026", code="planning")]
        for nid in ("n-comp", "n-amend", "n-plan2"):
            self.details[nid] = detail_of(PROCEDURE)
        found = self.one("DK:notice-%s" % PLAN)
        self.assertEqual(found["notice_id"], "n-amend")
        self.assertEqual(found["kind"], "amendment")

    def test_with_no_bid_notice_the_newest_plan_of_the_procedure_is_taken(self):
        self.by_text[PROCEDURE] = [row(PLAN, date="01-09-2026", code="planning"),
                                   row("n-plan2", date="05-09-2026", code="preplanning"),
                                   row("n-plan3", date="10-09-2026", code="planning")]
        self.details["n-plan2"] = detail_of(PROCEDURE)
        self.details["n-plan3"] = detail_of(PROCEDURE)
        found = self.one("DK:notice-%s" % PLAN)
        self.assertEqual(found["notice_id"], "n-plan3")
        self.assertEqual(found["kind"], "plan")
        self.assertEqual(found["pid"], PROCEDURE)


class UuidCase(Lookup):
    """Answer 2: the uuid is lower-cased before the search, and compared without regard to case."""

    def test_an_upper_case_uuid_is_searched_lower_cased(self):
        self.procedure("DK:notice-%s" % PLAN.upper())
        self.assertEqual(self.texts, [PLAN])

    def test_a_mixed_case_uuid_without_the_prefix(self):
        mixed = PLAN[:8].upper() + PLAN[8:]
        self.procedure("Notice-%s" % mixed)
        self.assertEqual(self.texts, [PLAN])

    def test_an_upper_case_reference_answers_the_plan(self):
        self.by_text[PLAN] = [row(PLAN, code="planning")]
        self.details[PLAN] = detail_of()
        found = self.one("DK:notice-%s" % PLAN.upper())
        self.assertIsNotNone(found)
        self.assertEqual(found["notice_id"].lower(), PLAN)
        self.assertEqual(found["kind"], "plan")

    def test_a_notice_the_portal_prints_upper_case_is_kept(self):
        self.by_text[PLAN] = [row(PLAN.upper(), code="planning")]
        self.details[PLAN.upper()] = detail_of()
        found = self.procedure("DK:notice-%s" % PLAN)
        self.assertEqual([t["notice_id"] for t in found], [PLAN.upper()])
        answered = self.one("DK:notice-%s" % PLAN)
        self.assertIsNotNone(answered)
        self.assertEqual(answered["notice_id"], PLAN.upper())


class OnlyThatNotice(Lookup):
    """A new rule: for `notice-<uuid>` only the rows whose noticeId is that uuid are kept."""

    def setUp(self):
        super().setUp()
        # Measured on 26 Nov 2026: the plan came back second, under an unrelated competition.
        self.by_text[PLAN] = [row(UNRELATED, date="10-09-2026"),
                              row(PLAN, date="01-09-2026", code="planning")]
        self.details[UNRELATED] = detail_of(OTHER_PROCEDURE)
        self.details[PLAN] = detail_of(intern="KYC#1")

    def test_the_procedure_holds_the_plan_alone(self):
        found = self.procedure("DK:notice-%s" % PLAN)
        self.assertEqual([t["notice_id"] for t in found], [PLAN])

    def test_without_the_prefix_too(self):
        found = self.procedure("notice-%s" % PLAN)
        self.assertEqual([t["notice_id"] for t in found], [PLAN])

    def test_one_answers_the_plan_not_the_unrelated_competition(self):
        found = self.one("DK:notice-%s" % PLAN)
        self.assertIsNotNone(found)
        self.assertEqual(found["notice_id"], PLAN)
        self.assertEqual(found["kind"], "plan")
        self.assertEqual(found["pid"], "notice-%s" % PLAN)

    def test_a_search_that_only_mentions_the_id_holds_nothing(self):
        self.by_text[PLAN] = [row(UNRELATED, date="10-09-2026")]
        self.assertEqual(self.procedure("DK:notice-%s" % PLAN), [])
        self.assertIsNone(self.one("DK:notice-%s" % PLAN))

    def test_a_procedure_id_reference_is_not_filtered(self):
        self.by_text[PROCEDURE] = [row("n-a", date="01-09-2026"),
                                   row("n-b", date="05-09-2026", code="planning")]
        found = self.procedure("DK:" + PROCEDURE)
        self.assertEqual(sorted(t["notice_id"] for t in found), ["n-a", "n-b"])


if __name__ == "__main__":
    unittest.main()
