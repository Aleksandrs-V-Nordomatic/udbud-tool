#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A plan only TED holds is keyed as udbud.dk keys it (README, "Three ids").

The record is the one of test_dk_ted, made a plan. Nothing reaches the network.
"""

import copy
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dk_ted
import net

PROCEDURE = "7c03c120-69c0-4112-af76-3d30b1aab18e"
NOTICE = "f104f4f6-8fc3-4624-b286-6968e40f18d1"
OTHER_NOTICE = "f104f4f6-8fc3-4624-b286-6968e40f18d2"

RECORD = {
    "publication-number": "811676-2026",
    "publication-date": "2026-11-23+01:00",
    "notice-identifier": NOTICE,
    "notice-version": 1,
    "procedure-identifier": PROCEDURE.upper(),
    "internal-identifier-proc": ["SAG-7"],
    "form-type": "planning",
    "notice-type": "pin-only",
    "title-proc": {"eng": ["Building automation"], "dan": ["Bygningsautomation"]},
    "description-proc": {"dan": ["Markedsdialog om CTS."]},
    "buyer-name": {"dan": ["Eksempel Kommune"]},
    "buyer-identifier": ["12345678"],
    "main-classification-proc": ["45000000"],
    "classification-cpv": ["45000000"],
}


def record(drop=(), **changes):
    """The record with some keys changed (`form_type=` for `form-type`) and some dropped."""
    r = copy.deepcopy(RECORD)
    for key, value in changes.items():
        r[key.replace("_", "-")] = value
    for key in drop:
        del r[key]
    return r


def no_network(*args, **kwargs):
    raise AssertionError("a test reached the network: %r" % (args[:1],))


class PlanKey(unittest.TestCase):

    def setUp(self):
        for name in ("open_url", "get_text"):
            patcher = mock.patch.object(net, name, mock.Mock(side_effect=no_network))
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_planning_is_a_plan(self):
        self.assertEqual(dk_ted.notice(RECORD)["kind"], "plan")

    def test_a_plan_with_no_procedure_is_keyed_on_its_notice(self):
        # The buyer and the internal id are there; a plan is still keyed on its notice.
        target = dk_ted.notice(record(drop=["procedure-identifier"]))
        self.assertEqual(target["kind"], "plan")
        self.assertEqual(target["pid"], "notice-%s" % NOTICE)

    def test_two_plans_of_one_buyer_and_one_internal_id_get_two_keys(self):
        first = dk_ted.notice(record(drop=["procedure-identifier"]))
        second = dk_ted.notice(record(drop=["procedure-identifier"], notice_identifier=OTHER_NOTICE,
                                      publication_number="811677-2026"))
        self.assertEqual(first["pid"], "notice-%s" % NOTICE)
        self.assertEqual(second["pid"], "notice-%s" % OTHER_NOTICE)

    def test_a_plan_that_prints_a_procedure_is_keyed_on_it(self):
        self.assertEqual(dk_ted.notice(RECORD)["pid"], PROCEDURE)

    def test_a_competition_with_no_procedure_still_gets_int(self):
        target = dk_ted.notice(record(drop=["procedure-identifier"], form_type="competition"))
        self.assertEqual(target["kind"], "tender")
        self.assertEqual(target["pid"], "int-12345678-SAG-7")

    def test_a_plan_with_neither_is_keyed_on_its_notice(self):
        target = dk_ted.notice(record(drop=["procedure-identifier", "internal-identifier-proc"]))
        self.assertEqual(target["pid"], "notice-%s" % NOTICE)


if __name__ == "__main__":
    unittest.main()
