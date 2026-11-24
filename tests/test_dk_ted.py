#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A notice only TED holds, read into the same target a udbud.dk row becomes.

TED's search is a stand-in for `net.open_url`, its Danish rendering one for `net.get_text`.
Nothing reaches the network.
"""

import copy
import json
import os
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dk_ted
import net

PROCEDURE = "7c03c120-69c0-4112-af76-3d30b1aab18e"
NOTICE = "f104f4f6-8fc3-4624-b286-6968e40f18d1"

RECORD = {
    "publication-number": "811676-2026",
    "publication-date": "2026-11-23+01:00",
    "notice-identifier": NOTICE,
    "notice-version": 1,
    "procedure-identifier": PROCEDURE.upper(),
    "internal-identifier-proc": ["SAG-7"],
    "form-type": "competition",
    "notice-type": "cn-standard",
    "title-proc": {"eng": ["Alfa school"], "dan": ["Alfa skole"]},
    "description-proc": {"dan": ["Renovering af skolen."]},
    "buyer-name": {"dan": ["Eksempel Kommune"]},
    "buyer-identifier": ["12345678"],
    "main-classification-proc": ["45000000"],
    "classification-cpv": ["45000000"],
    "deadline-receipt-tender-date-lot": ["2027-01-22+01:00"],
    "deadline-receipt-tender-time-lot": ["10:00:00+01:00"],
    "estimated-value-proc": "25000000.00",
    "estimated-value-cur-proc": ["DKK"],
    "document-url-lot": ["https://www.ethics.dk/ethics/eo#/x/publicMaterial"],
    "identifier-lot": ["LOT-0001"],
}

KEYS = ("pid procedure_id notice_id notice_version npn ref kind form_code eu title titles "
        "description buyer buyer_id published deadline deadlines deadline_tender "
        "deadline_request value currency cpv_main cpv link link_verified documents_url "
        "documents_urls documents_host source record").split()

HTML = ("<html><head><style>p { color: red }</style><script>var hidden = 1;</script></head>"
        "<body><p>Rådgivning om skolens tag</p></body></html>")


def record(drop=(), **changes):
    """The record with some keys changed (`form_type=` for `form-type`) and some dropped."""
    r = copy.deepcopy(RECORD)
    for key, value in changes.items():
        r[key.replace("_", "-")] = value
    for key in drop:
        del r[key]
    return r


class Answer(object):
    """Stands in for an opener, as in test_net: one body, served once."""

    def __init__(self, body):
        self.body, self.headers = body, {}

    def open(self, request, timeout=None):
        return self

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def no_network(*args, **kwargs):
    raise AssertionError("a test reached the network: %r" % (args[:1],))


class Offline(unittest.TestCase):

    def setUp(self):
        # The shape `net.get_text` answers in is its own, taken before the network is cut.
        rendering = net.get_text("https://example.invalid/", opener=Answer(HTML.encode("utf-8")))
        for name, replacement in (("open_url", mock.Mock(side_effect=no_network)),
                                  ("get_text", mock.Mock(return_value=rendering))):
            patcher = mock.patch.object(net, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def ted(self, *records):
        answer = ({"notices": list(records), "totalNoticeCount": len(records)}, {})
        net.open_url.side_effect = lambda *args, **kwargs: copy.deepcopy(answer)

    def query(self):
        return json.loads(net.open_url.call_args_list[0].args[0].data.decode("utf-8"))["query"]


class Search(Offline):

    def test_the_records_of_the_answer(self):
        self.ted(RECORD)
        self.assertEqual(dk_ted.search("publication-number=811676-2026"), [RECORD])

    def test_the_query_is_posted_as_it_was_given(self):
        self.ted()
        dk_ted.search("publication-number=811676-2026")
        self.assertEqual(self.query(), "publication-number=811676-2026")

    def test_no_notice_is_an_empty_list(self):
        self.ted()
        self.assertEqual(dk_ted.search("publication-number=811676-2026"), [])


class Notice(Offline):

    def test_the_keys_of_a_udbud_row(self):
        target = dk_ted.notice(RECORD)
        self.assertEqual([k for k in KEYS if k not in target], [])

    def test_the_key_is_the_procedure_lower_cased(self):
        self.assertEqual(dk_ted.notice(RECORD)["pid"], PROCEDURE)

    def test_the_number_is_zero_padded_and_is_the_reference(self):
        target = dk_ted.notice(RECORD)
        self.assertEqual(target["npn"], "00811676-2026")
        self.assertEqual(target["ref"], "00811676-2026")
        self.assertTrue(target["eu"])

    def test_a_number_of_eight_digits_is_kept(self):
        target = dk_ted.notice(record(publication_number="12345678-2026"))
        self.assertEqual(target["npn"], "12345678-2026")

    def test_kinds(self):
        self.assertEqual(dk_ted.notice(RECORD)["kind"], "tender")
        self.assertEqual(dk_ted.notice(record(form_type="result"))["kind"], "award")
        changed = record(change_notice_version_identifier="%s-01" % NOTICE)
        self.assertEqual(dk_ted.notice(changed)["kind"], "amendment")

    def test_facts(self):
        target = dk_ted.notice(RECORD)
        self.assertEqual(target["notice_id"], NOTICE)
        self.assertEqual(target["published"], "2026-11-23")
        self.assertEqual(target["buyer"], "Eksempel Kommune")
        self.assertEqual(target["buyer_id"], "12345678")
        self.assertEqual(target["description"], "Renovering af skolen.")
        self.assertEqual(target["cpv_main"], "45000000")
        self.assertEqual(target["cpv"], ["45000000"])

    def test_danish_comes_first(self):
        target = dk_ted.notice(RECORD)
        self.assertEqual(target["title"], "Alfa skole")
        self.assertEqual(target["titles"], "Alfa skole Alfa school")

    def test_the_english_title_stands_in(self):
        target = dk_ted.notice(record(title_proc={"eng": ["Alfa school"]}))
        self.assertEqual(target["title"], "Alfa school")

    def test_source_and_link(self):
        target = dk_ted.notice(RECORD)
        self.assertEqual(target["source"], "ted.europa.eu")
        self.assertIn("ted.europa.eu", target["link"])
        self.assertIn("811676-2026", target["link"])

    def test_value_with_its_currency(self):
        target = dk_ted.notice(RECORD)
        self.assertEqual(target["value"], 25000000.0)
        self.assertEqual(target["currency"], "DKK")

    def test_an_absent_value_is_none_and_so_is_its_currency(self):
        target = dk_ted.notice(record(drop=["estimated-value-proc"]))
        self.assertIsNone(target["value"])
        self.assertIsNone(target["currency"])

    def test_the_documents_link_and_its_host(self):
        target = dk_ted.notice(RECORD)
        self.assertEqual(target["documents_url"], RECORD["document-url-lot"][0])
        self.assertEqual(target["documents_urls"], RECORD["document-url-lot"])
        self.assertEqual(target["documents_host"], "www.ethics.dk")

    def test_no_documents_link(self):
        target = dk_ted.notice(record(drop=["document-url-lot"]))
        self.assertIsNone(target["documents_url"])
        self.assertEqual(target["documents_urls"], [])
        self.assertIsNone(target["documents_host"])

    def test_the_tender_deadline(self):
        target = dk_ted.notice(RECORD)
        self.assertEqual(target["deadline"], "2027-01-22T10:00:00+01:00")
        self.assertEqual(target["deadlines"], ["2027-01-22T10:00:00+01:00"])
        self.assertEqual(target["deadline_tender"], "2027-01-22T10:00:00+01:00")
        self.assertIsNone(target["deadline_request"])

    def test_the_request_deadline(self):
        r = record(drop=["deadline-receipt-tender-date-lot", "deadline-receipt-tender-time-lot"],
                   deadline_receipt_request_date_lot=["2026-12-15+01:00"],
                   deadline_receipt_request_time_lot=["12:00:00+01:00"])
        target = dk_ted.notice(r)
        self.assertEqual(target["deadline_request"], "2026-12-15T12:00:00+01:00")
        self.assertIsNone(target["deadline_tender"])
        self.assertEqual(target["deadline"], "2026-12-15T12:00:00+01:00")

    def test_no_hour_is_made_up(self):
        target = dk_ted.notice(record(drop=["deadline-receipt-tender-time-lot"]))
        self.assertTrue(target["deadline"].startswith("2027-01-22"), target["deadline"])
        self.assertNotIn("T", target["deadline"])

    def test_no_deadline(self):
        target = dk_ted.notice(record(drop=["deadline-receipt-tender-date-lot",
                                            "deadline-receipt-tender-time-lot"]))
        self.assertIsNone(target["deadline"])
        self.assertEqual(target["deadlines"], [])

    def test_a_record_with_only_its_number(self):
        target = dk_ted.notice({"publication-number": "811676-2026"})
        self.assertEqual(target["npn"], "00811676-2026")


class NoProcedure(Offline):

    def without(self, **changes):
        return dk_ted.notice(record(drop=["procedure-identifier"], **changes))

    def test_the_buyer_and_the_internal_id_key_the_home(self):
        self.assertEqual(self.without()["pid"], "int-12345678-SAG-7")

    def test_then_the_notice_keys_it(self):
        target = dk_ted.notice(record(drop=["procedure-identifier", "internal-identifier-proc"]))
        self.assertEqual(target["pid"], "notice-%s" % NOTICE)

    def test_two_internal_ids_do_not_share_a_home(self):
        first = self.without()
        second = self.without(internal_identifier_proc=["SAG-8"], notice_identifier="other")
        self.assertTrue(first["pid"] and second["pid"])
        self.assertNotEqual(first["pid"], second["pid"])

    def test_two_notices_with_neither_do_not_share_a_home(self):
        drop = ["procedure-identifier", "internal-identifier-proc"]
        first = dk_ted.notice(record(drop=drop))
        second = dk_ted.notice(record(drop=drop, notice_identifier="0aaa",
                                      publication_number="811677-2026"))
        self.assertTrue(first["pid"] and second["pid"])
        self.assertNotEqual(first["pid"], second["pid"])


class Deadlines(Offline):

    def test_a_date_and_its_time(self):
        self.assertEqual(dk_ted.deadlines(["2027-01-22+01:00"], ["10:00:00+01:00"]),
                         ["2027-01-22T10:00:00+01:00"])

    def test_sorted(self):
        found = dk_ted.deadlines(["2027-02-05+01:00", "2027-01-22+01:00"],
                                 ["12:00:00+01:00", "10:00:00+01:00"])
        self.assertEqual(found, ["2027-01-22T10:00:00+01:00", "2027-02-05T12:00:00+01:00"])

    def test_a_date_without_a_time_gets_no_hour(self):
        for times in ([], None):
            found = dk_ted.deadlines(["2027-01-22+01:00"], times)
            self.assertEqual(len(found), 1)
            self.assertTrue(found[0].startswith("2027-01-22"), found)
            self.assertNotIn("T", found[0])

    def test_no_dates(self):
        self.assertEqual(dk_ted.deadlines([], []), [])
        self.assertEqual(dk_ted.deadlines(None, None), [])


class Plain(Offline):

    def test_style_and_script_are_dropped_and_text_is_kept(self):
        text = dk_ted.plain(HTML)
        self.assertIn("Rådgivning om skolens tag", text)
        self.assertNotIn("color", text)
        self.assertNotIn("hidden", text)
        self.assertNotIn("<", text)


class Document(Offline):

    def test_the_rendering_as_text(self):
        found = dk_ted.document(dk_ted.notice(RECORD))
        self.assertEqual(found["source"], "ted.europa.eu")
        self.assertIn("record", found)
        self.assertIn("Rådgivning om skolens tag", found["text"])
        self.assertNotIn("color", found["text"])

    def test_the_rendering_failing_is_survived(self):
        for error in (net.Unreachable("gave up"),
                      urllib.error.HTTPError("u", 404, "", {}, None)):
            with self.subTest(error=type(error).__name__):
                net.get_text.side_effect = error
                found = dk_ted.document(dk_ted.notice(RECORD))
                self.assertEqual(found["source"], "ted.europa.eu")
                self.assertIn("record", found)
                self.assertFalse(found["text"])


class One(Offline):

    def test_a_number_is_read(self):
        self.ted(RECORD)
        target, document = dk_ted.one("811676-2026")
        self.assertEqual(target["pid"], PROCEDURE)
        self.assertIn("Rådgivning om skolens tag", document["text"])
        self.assertIn("811676-2026", self.query())

    def test_a_number_ted_does_not_hold(self):
        self.ted()
        self.assertEqual(dk_ted.one("811676-2026"), (None, None))


class Procedure(Offline):

    def test_a_dk_prefix_is_accepted(self):
        self.ted(RECORD)
        target, document = dk_ted.procedure("DK:" + PROCEDURE)
        self.assertEqual(target["pid"], PROCEDURE)
        self.assertIn("Rådgivning om skolens tag", document["text"])
        self.assertIn(PROCEDURE, self.query().lower())
        self.assertNotIn("DK:", self.query())

    def test_the_bare_id(self):
        self.ted(RECORD)
        target, document = dk_ted.procedure(PROCEDURE)
        self.assertEqual(target["pid"], PROCEDURE)

    def test_what_is_not_a_uuid_is_not_asked(self):
        for reference in ("DK:gone", "gone", "811676-2026", "DK:", "", None,
                          "int-12345678-SAG-7"):
            self.assertEqual(dk_ted.procedure(reference), (None, None), reference)
        net.open_url.assert_not_called()

    def test_nothing_held(self):
        self.ted()
        self.assertEqual(dk_ted.procedure(PROCEDURE), (None, None))

    def test_the_newest_notice_is_the_one_read(self):
        newer = record(publication_number="820000-2026", publication_date="2026-12-01+01:00",
                       notice_identifier="0bbb",
                       change_notice_version_identifier="%s-01" % NOTICE)
        for records in ((RECORD, newer), (newer, RECORD)):
            self.ted(*records)
            target, document = dk_ted.procedure(PROCEDURE)
            self.assertEqual(target["npn"], "00820000-2026")
            self.assertEqual(target["kind"], "amendment")

    def test_an_award_as_the_newest_notice_is_nothing_to_read(self):
        award = record(publication_number="830000-2026", publication_date="2026-12-20+01:00",
                       notice_identifier="0ccc", form_type="result")
        for records in ((RECORD, award), (award, RECORD)):
            self.ted(*records)
            self.assertEqual(dk_ted.procedure(PROCEDURE), (None, None))


if __name__ == "__main__":
    unittest.main()
