#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One notice into a home: `documents_available`, the files that are always written, and
the notice history carried from the procurement already on the drive.

`docsource.listing` and `docsource.download` are replaced; `net.open_url` fails loudly.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dk_fetch
import dk_page
import docsource
import net

PROCEDURE = "7c03c120-69c0-4112-af76-3d30b1aab18e"
DESCRIPTION = "Rådgivning om ventilation på skolen.\nAnden linje: »citat«."

ROW = {
    "dataDa": {"titel": "Ventilation, Bøgeskolen", "ordregiver": "Eksempel Kommune",
               "ordregiverIdDatavasket": "12345678", "publiceringsdato": "02-09-2026",
               "cpvKode": "45331210", "cpvTitel": "Installation af ventilationsanlæg",
               "formulartype": "Konkurrencevilkår", "formulartypeKode": "competition",
               "tidsfrister": ["2026-10-02T10:00:00Z"], "beskrivelse": DESCRIPTION,
               "erAendring": False},
    "dataEn": {"titel": "Ventilation, Bogeskolen"},
    "noticeId": "f104f4f6-8fc3-4624-b286-6968e40f18d1",
    "noticeVersion": "01",
    "noticePublicationNumber": "00603665-2026",
}


def document(urls=()):
    html = ('<html><body><section>2&nbsp;<span class="label">Procedure</span>'
            '<section><span class="label">Identifikator for proceduren</span>'
            '<span class="text">: </span><span class="value">%s</span></section>'
            '</section></body></html>' % PROCEDURE)
    return {"htmlDA": html, "htmlEN": "<html>en</html>",
            "opsummeringDA": {"udbudsDokumenter": list(urls), "antalLots": 1}}


def target(urls=()):
    doc = document(urls)
    return dk_page.enrich(dk_page.notice(ROW), doc), doc


def no_network(*args, **kwargs):
    raise AssertionError("a test reached the network")


class Available(unittest.TestCase):

    def test_the_mapping(self):
        record, withheld = [{"id": "1"}], [{"id": "2"}]
        self.assertEqual(dk_fetch._available({"access": "none"}, [], []), "none")
        self.assertEqual(dk_fetch._available({"access": "unknown"}, [], []), "unknown")
        self.assertEqual(dk_fetch._available({"access": "public"}, record, []), "public")
        self.assertEqual(dk_fetch._available({"access": "partial", "gated": ["x.pdf"]}, record, []),
                         "partial")
        self.assertEqual(dk_fetch._available({"access": "public"}, record, withheld), "partial")
        self.assertEqual(dk_fetch._available({"access": "gated", "gated": ["x.pdf"]}, [], []), "gated")
        self.assertEqual(dk_fetch._available({"access": "gated"}, [], []), "gated")

    def test_nothing_read_from_a_public_listing_is_not_public(self):
        self.assertNotEqual(dk_fetch._available({"access": "public"}, [], [{"id": "1"}]), "public")


class Fetch(unittest.TestCase):

    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.out, True)
        patcher = mock.patch.object(net, "open_url", side_effect=no_network)
        patcher.start()
        self.addCleanup(patcher.stop)

    def read(self, *parts):
        with open(os.path.join(self.out, "tenders", PROCEDURE, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_no_documents_still_writes_index_and_notice(self):
        t, doc = target()
        done = dk_fetch.fetch(t, self.out, doc, with_text=False)
        self.assertEqual(done["pid"], PROCEDURE)
        self.assertEqual(done["documents_available"], "none")
        index = json.loads(self.read("index.json"))
        self.assertEqual(index["pid"], PROCEDURE)
        self.assertEqual(index["country"], "DK")
        self.assertEqual(index["documents_available"], "none")
        self.assertEqual(index["notice_document"], "doc/notice.md")
        self.assertEqual(index["description"], DESCRIPTION)
        self.assertEqual(index["ref"], "00603665-2026")
        notice = self.read("doc", "notice.md")
        self.assertIn(DESCRIPTION, notice)
        procurement = json.loads(self.read("procurement.json"))
        self.assertEqual(procurement["documents_available"], "none")
        self.assertFalse(procurement["documents_gated"])
        stored = json.loads(self.read("notice.json"))
        self.assertNotIn("htmlEN", stored)
        self.assertIn("htmlDA", stored)
        json.loads(self.read("manifest.json"))

    def test_no_detail_still_writes_the_notice_document(self):
        t = dk_page.enrich(dk_page.notice(ROW), None)
        done = dk_fetch.fetch(t, self.out, None, with_text=False)
        home = done["home"]
        self.assertTrue(os.path.exists(os.path.join(home, "doc", "notice.md")))
        self.assertTrue(os.path.exists(os.path.join(home, "index.json")))
        self.assertFalse(os.path.exists(os.path.join(home, "notice.json")))
        with open(os.path.join(home, "doc", "notice.md"), encoding="utf-8") as fh:
            self.assertIn(DESCRIPTION, fh.read())

    def test_a_gated_platform_names_its_files_as_withheld(self):
        t, doc = target(["https://eu.eu-supply.com/app/rfq/rwlentrance_s.asp?PID=1"])
        found = {"host": "eu.eu-supply.com", "platform": "eu-supply", "access": "gated",
                 "files": [], "gated": ["Udbudsbetingelser.pdf", "Bilag 1.docx"], "note": "names only"}
        with mock.patch.object(docsource, "listing", return_value=found), \
                mock.patch.object(docsource, "download", side_effect=AssertionError("no download")):
            done = dk_fetch.fetch(t, self.out, doc, with_text=False)
        self.assertEqual(done["documents_available"], "gated")
        index = json.loads(self.read("index.json"))
        self.assertEqual(index["gated_documents"], ["Udbudsbetingelser.pdf", "Bilag 1.docx"])
        self.assertTrue(index["documents_gated"])
        self.assertEqual(index["withheld_documents"], 2)
        self.assertEqual(index["documents"], [])
        manifest = json.loads(self.read("manifest.json"))
        self.assertEqual([w["title"] for w in manifest["withheld_records"]],
                         ["Udbudsbetingelser.pdf", "Bilag 1.docx"])
        self.assertIn("doc", os.listdir(os.path.join(self.out, "tenders", PROCEDURE)))
        self.assertIn(DESCRIPTION, self.read("doc", "notice.md"))

    def test_public_files_are_stored_and_listed(self):
        t, doc = target(["https://www.ethics.dk/ethics/eo#/x/publicMaterial"])
        found = {"host": "www.ethics.dk", "platform": "ethics", "access": "partial",
                 "files": [{"id": "a1", "name": "Udbudsbetingelser.pdf", "download": "https://e/a1"},
                           {"id": "a2", "name": "Udbudsbetingelser.pdf", "download": "https://e/a2"},
                           {"id": "a3", "name": "Login.pdf", "download": "https://e/a3"}],
                 "gated": ["Tilbudsliste.xlsx"]}
        answers = {"a1": (b"%PDF-1", None), "a2": (b"%PDF-2", None),
                   "a3": (None, "the host served an HTML page")}
        with mock.patch.object(docsource, "listing", return_value=found), \
                mock.patch.object(docsource, "download", side_effect=lambda p, e: answers[e["id"]]):
            done = dk_fetch.fetch(t, self.out, doc, with_text=False)
        self.assertEqual(done["documents_available"], "partial")
        self.assertEqual(done["documents"], 2)
        index = json.loads(self.read("index.json"))
        names = sorted(os.listdir(os.path.join(self.out, "tenders", PROCEDURE, "originals")))
        self.assertEqual(len(names), 2, names)
        self.assertEqual(len({d["original"] for d in index["documents"]}), 2)
        self.assertEqual(index["withheld_documents"], 2)
        self.assertEqual(index["catalogued_documents"], 4)

    def test_every_public_file_read_is_public(self):
        t, doc = target(["https://api.udbud.dk/udbud/vedhaeftning/a/01/fil/b/x.pdf"])
        found = {"host": "api.udbud.dk", "platform": "api.udbud.dk", "access": "public",
                 "files": [{"id": "0", "name": "x.pdf", "download": "https://api.udbud.dk/x.pdf"}]}
        with mock.patch.object(docsource, "listing", return_value=found), \
                mock.patch.object(docsource, "download", return_value=(b"%PDF", None)):
            done = dk_fetch.fetch(t, self.out, doc, with_text=False)
        self.assertEqual(done["documents_available"], "public")

    def test_notice_history_is_carried_from_previous(self):
        t, doc = target()
        older = {"notice_id": "0aaa", "version": "01", "npn": "00600001-2026", "kind": "tender",
                 "published": "2026-08-20"}
        dk_fetch.fetch(t, self.out, doc, with_text=False, previous={"notices": [older]})
        procurement = json.loads(self.read("procurement.json"))
        self.assertEqual(procurement["notices"][0], older)
        self.assertEqual(procurement["notices"][1]["notice_id"], ROW["noticeId"])
        self.assertEqual(len(procurement["notices"]), 2)

    def test_the_same_notice_twice_is_not_duplicated(self):
        t, doc = target()
        dk_fetch.fetch(t, self.out, doc, with_text=False)
        previous = json.loads(self.read("procurement.json"))
        dk_fetch.fetch(t, self.out, doc, with_text=False, previous=previous)
        self.assertEqual(len(json.loads(self.read("procurement.json"))["notices"]), 1)

    def test_safe_names_stay_inside_the_home(self):
        self.assertEqual(dk_fetch._safe("../../etc/passwd"), "passwd")
        self.assertEqual(dk_fetch._safe("a\\b\\..\\c.pdf"), "c.pdf")
        self.assertEqual(dk_fetch._safe('..x:"y".pdf'), "xy.pdf")
        self.assertEqual(dk_fetch._safe(""), "unnamed")


if __name__ == "__main__":
    unittest.main()
