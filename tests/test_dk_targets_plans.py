#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A plan's card is held by its home's name; a competition is answered before a plan.

README, "Three ids". `dk_page.search` and `dk_page.detail` are stand-ins; nothing reaches the
network.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dk_page
import dk_targets

PROCEDURE = "7c03c120-69c0-4112-af76-3d30b1aab18e"
PLAN = "3f1d2c4b-5a69-4788-9a0b-c1d2e3f40001"


def row(nid, date="02-09-2026", code="competition", version="01", change=False):
    return {"dataDa": {"titel": "Opgave %s" % nid, "publiceringsdato": date,
                       "formulartypeKode": code, "ordregiver": "Kommune",
                       "ordregiverIdDatavasket": "12345678", "erAendring": change},
            "dataEn": {},
            "noticeId": nid, "noticeVersion": version, "noticePublicationNumber": ""}


def page(rows):
    return {"resultatElementDtoList": rows, "totaltAntalResultater": len(rows)}


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


class Procedure(unittest.TestCase):

    def text(self, reference):
        with mock.patch.object(dk_page, "search", return_value=page([])) as search:
            dk_targets.procedure(reference)
        search.assert_called()
        return search.call_args

    def test_a_plans_home_name_is_searched_as_the_bare_notice_id(self):
        call = self.text("DK:notice-%s" % PLAN)
        self.assertEqual(call.kwargs.get("text"), PLAN)
        self.assertEqual(call.kwargs.get("size"), dk_page.PAGE)

    def test_without_the_prefix_too(self):
        self.assertEqual(self.text("notice-%s" % PLAN).kwargs.get("text"), PLAN)

    def test_the_home_name_in_any_case_of_letters(self):
        self.assertEqual(self.text("dk:NOTICE-%s" % PLAN).kwargs.get("text"), PLAN)
        self.assertEqual(self.text("Notice-%s" % PLAN).kwargs.get("text"), PLAN)

    def test_notice_not_followed_by_a_uuid_is_searched_as_it_stands(self):
        self.assertEqual(self.text("notice-1").kwargs.get("text"), "notice-1")
        self.assertEqual(self.text("DK:notice-1").kwargs.get("text"), "notice-1")

    def test_a_procedure_id_is_searched_as_it_stands(self):
        self.assertEqual(self.text("DK:" + PROCEDURE).kwargs.get("text"), PROCEDURE)


class One(unittest.TestCase):

    def setUp(self):
        self.by_text = {}
        self.details = {}

    def search(self, date_from=None, date_to=None, page=1, text=None, size=None):
        rows = self.by_text.get(text, [])
        return {"resultatElementDtoList": rows, "totaltAntalResultater": len(rows)}

    def detail(self, notice_id, version, npn, timeout=60):
        return self.details.get(notice_id)

    def one(self, reference):
        with mock.patch.object(dk_page, "search", side_effect=self.search), \
                mock.patch.object(dk_page, "detail", side_effect=self.detail):
            return dk_targets.one(reference)

    def test_a_plans_home_name_answers_the_live_plan(self):
        self.by_text[PLAN] = [row(PLAN, code="planning")]
        self.details[PLAN] = detail_of(intern="KYC#1")
        found = self.one("DK:notice-%s" % PLAN)
        self.assertIsNotNone(found)
        self.assertEqual(found["notice_id"], PLAN)
        self.assertEqual(found["kind"], "plan")
        self.assertEqual(found["pid"], "notice-%s" % PLAN)

    def test_a_consultation_by_its_bare_home_name(self):
        self.by_text[PLAN] = [row(PLAN, code="consultation")]
        self.details[PLAN] = detail_of()
        found = self.one("notice-%s" % PLAN)
        self.assertEqual(found["kind"], "consultation")
        self.assertEqual(found["pid"], "notice-%s" % PLAN)

    def test_a_newer_plan_and_an_older_competition_answer_the_competition(self):
        self.by_text[PROCEDURE] = [row("n-comp", date="01-09-2026"),
                                   row("n-plan", date="10-09-2026", code="planning")]
        self.details = {"n-comp": detail_of(PROCEDURE), "n-plan": detail_of(PROCEDURE)}
        found = self.one("DK:" + PROCEDURE)
        self.assertEqual(found["notice_id"], "n-comp")
        self.assertEqual(found["kind"], "tender")
        self.assertEqual(found["pid"], PROCEDURE)

    def test_a_newer_consultation_and_an_older_amendment_answer_the_amendment(self):
        self.by_text[PROCEDURE] = [row("n-amend", date="01-09-2026", code="change"),
                                   row("n-cons", date="10-09-2026", code="consultation")]
        self.details = {"n-amend": detail_of(PROCEDURE), "n-cons": detail_of(PROCEDURE)}
        found = self.one(PROCEDURE)
        self.assertEqual(found["notice_id"], "n-amend")

    def test_with_no_competition_the_newest_live_plan_is_answered(self):
        # An award is not live; the plan before it is.
        self.by_text[PROCEDURE] = [row("n-plan", date="01-09-2026", code="planning"),
                                   row("n-award", date="10-09-2026", code="result")]
        self.details = {"n-plan": detail_of(PROCEDURE), "n-award": detail_of(PROCEDURE)}
        found = self.one(PROCEDURE)
        self.assertEqual(found["notice_id"], "n-plan")
        self.assertEqual(found["kind"], "plan")

    def test_of_two_plans_the_newer_is_answered(self):
        self.by_text[PROCEDURE] = [row("n-old-plan", date="01-09-2026", code="planning"),
                                   row("n-new-plan", date="10-09-2026", code="preplanning")]
        self.details = {"n-old-plan": detail_of(PROCEDURE), "n-new-plan": detail_of(PROCEDURE)}
        self.assertEqual(self.one(PROCEDURE)["notice_id"], "n-new-plan")

    def test_a_plans_home_name_whose_notice_is_unknown_is_none(self):
        self.assertIsNone(self.one("DK:notice-%s" % PLAN))

    def test_a_plan_that_is_no_longer_live_is_none(self):
        # Only closes under the notice id: nothing live to answer.
        self.by_text[PLAN] = [row(PLAN, code="result")]
        self.details[PLAN] = detail_of()
        self.assertIsNone(self.one("DK:notice-%s" % PLAN))


if __name__ == "__main__":
    unittest.main()
