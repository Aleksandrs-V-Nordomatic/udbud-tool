#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A Danish window with a notice only TED holds, and a document host that fails.

`dk_page.search` serves the window and the procedure lookups, `dk_page.detail` a detail per
notice, `dk_recon.ted_numbers` the EU numbers of the day, `net.open_url` TED's search and
`net.get_text` TED's Danish rendering. `dk_fetch.fetch` runs for real into a temporary folder.
"""

import contextlib
import copy
import io
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
import net
from docsource import dalux
from tools import day_verdict

DATE = "2026-09-02"
POLICY = json.dumps({"recall_title_terms": ["alfa"]})

P1 = "11111111-1111-1111-1111-111111111111"
P3 = "33333333-3333-3333-3333-333333333333"
P8 = "88888888-8888-4888-8888-888888888888"
P9 = "aaaaaaaa-9999-4999-8999-999999999999"

DALUX = "https://node1.build.dalux.com/da-dk/public/tender/TID-4711"

HTML = ("<html><head><style>p { color: red }</style></head>"
        "<body><p>Rådgivning om svømmehallens tag</p></body></html>")


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


def record(number, procedure, title, published="2026-09-02+02:00"):
    return {"publication-number": number, "publication-date": published,
            "notice-identifier": "notice-of-%s" % number, "notice-version": 1,
            "procedure-identifier": procedure.upper(), "form-type": "competition",
            "notice-type": "cn-standard", "title-proc": {"dan": [title]},
            "description-proc": {"dan": ["Beskrivelse af %s." % title]},
            "buyer-name": {"dan": ["Eksempel Kommune"]}, "buyer-identifier": ["12345678"],
            "main-classification-proc": ["45000000"], "classification-cpv": ["45000000"],
            "deadline-receipt-tender-date-lot": ["2030-01-01+01:00"],
            "deadline-receipt-tender-time-lot": ["10:00:00+01:00"],
            "identifier-lot": ["LOT-0001"]}


# The window of Wednesday 2026-09-02, as udbud.dk holds it.
ROWS = [row("n-a", "Alfa skole renovering", npn="00600001-2026"),
        row("n-d", "Omega kantinedrift")]
UDBUD = {"600001-2026"}
ONLY_TED = "699999-2026"


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


class Window(unittest.TestCase):

    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.out, True)
        self.details = {"n-a": detail(P1), "n-d": detail(P3)}
        self.ted_day = set(UDBUD)
        self.ted_records = []
        self.by_text = {}
        self.queries = []
        # The shape `net.get_text` answers in is its own, taken before the network is cut.
        rendering = net.get_text("https://example.invalid/", opener=Answer(HTML.encode("utf-8")))
        for patcher in (mock.patch.object(net, "open_url", side_effect=self.ted_search),
                        mock.patch.object(net, "get_text", return_value=rendering),
                        mock.patch.object(dk_page, "search", side_effect=self.search),
                        mock.patch.object(dk_page, "detail", side_effect=self.detail),
                        mock.patch.object(dk_recon, "ted_numbers", side_effect=self.numbers)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def numbers(self, day):
        return set(self.ted_day) if day == DATE else set()

    def detail(self, notice_id, version, npn, timeout=60):
        return self.details.get(notice_id)

    def search(self, date_from=None, date_to=None, page=1, text=None, size=None, **kwargs):
        rows = ROWS if text is None else self.by_text.get(text.lower(), [])
        return {"resultatElementDtoList": rows if page == 1 else [],
                "totaltAntalResultater": len(rows)}

    def ted_search(self, request, *args, **kwargs):
        query = json.loads(request.data.decode("utf-8"))["query"].lower()
        self.queries.append(query)
        held = [r for r in self.ted_records
                if r["publication-number"] in query or r["procedure-identifier"].lower() in query]
        return {"notices": copy.deepcopy(held), "totalNoticeCount": len(held)}, {}

    def only_on_ted(self, title="Alfa svømmehal", held=True):
        self.ted_day.add(ONLY_TED)
        if held:
            self.ted_records.append(record(ONLY_TED, P9, title))

    def run_day(self, watch=None):
        with mock.patch.object(dk_fetch, "fetch", wraps=dk_fetch.fetch) as fetch:
            day, changes = dk_day.run(DATE, self.out, policy=POLICY, watch=watch, run_id="test")
        self.fetched = [c.args[0]["pid"] for c in fetch.call_args_list]
        return day, changes

    def read(self, *parts):
        with open(os.path.join(self.out, *parts), encoding="utf-8") as fh:
            return fh.read()

    def main(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return day_verdict.main([os.path.join(self.out, DATE, "day.json")])


class OnlyTed(Window):

    def test_it_joins_the_targets_and_the_day_is_complete(self):
        self.only_on_ted()
        day, changes = self.run_day()
        self.assertEqual(sorted(self.fetched), [P1, P9])
        self.assertIn(P9, [t["pid"] for t in day["tenders"]])
        self.assertTrue(day["complete"], day)
        self.assertTrue(day["reconciliation"]["ok"], day["reconciliation"])

    def test_it_is_counted_apart_from_udbuds_rows(self):
        self.only_on_ted()
        day, changes = self.run_day()
        self.assertEqual(day["coverage"]["from_ted"], 1)
        self.assertEqual(day["coverage"]["rows_held"], 2)

    def test_the_report_names_it(self):
        self.only_on_ted()
        day, changes = self.run_day()
        ted = day["reconciliation"]["ted"][0]
        self.assertEqual(ted["only_ted"], [ONLY_TED])
        self.assertEqual(ted["read_from_ted"], [ONLY_TED])

    def test_its_home_says_where_it_came_from_and_holds_the_rendering(self):
        self.only_on_ted()
        self.run_day()
        index = json.loads(self.read("tenders", P9, "index.json"))
        self.assertEqual(index["source"], "ted.europa.eu")
        self.assertEqual(index["pid"], P9)
        notice = self.read("tenders", P9, "doc", "notice.md")
        self.assertIn("Rådgivning om svømmehallens tag", notice)
        self.assertIn("Beskrivelse af Alfa svømmehal.", notice)
        self.assertNotIn("color: red", notice)

    def test_the_gate_holds_it_like_any_other(self):
        self.only_on_ted(title="Omega svømmehal")
        day, changes = self.run_day()
        self.assertNotIn(P9, self.fetched)
        gated = [g for g in changes["gated"] if g["pid"] == P9]
        self.assertEqual(len(gated), 1)
        self.assertEqual(gated[0]["title"], "Omega svømmehal")
        self.assertNotIn("record", gated[0])
        self.assertFalse(os.path.exists(os.path.join(self.out, "tenders", P9)))
        self.assertEqual(day["coverage"]["from_ted"], 1)
        self.assertTrue(day["complete"], day)

    def test_a_day_ted_agrees_on_counts_none(self):
        day, changes = self.run_day()
        self.assertEqual(day["coverage"]["from_ted"], 0)
        self.assertTrue(day["complete"], day)

    def test_ted_failing_to_hand_it_over_is_incomplete(self):
        self.only_on_ted()
        with mock.patch.object(net, "open_url", side_effect=net.Unreachable("gave up")):
            day, changes = self.run_day()
        self.assertFalse(day["complete"])
        self.assertFalse(day["reconciliation"]["ok"])
        self.assertEqual(day["coverage"]["from_ted"], 0)
        self.assertEqual(self.fetched, [P1], "what udbud.dk holds is still read")

    def test_ted_answering_nothing_is_incomplete(self):
        self.only_on_ted(held=False)
        day, changes = self.run_day()
        self.assertFalse(day["complete"])
        self.assertFalse(day["reconciliation"]["ok"])
        self.assertEqual(day["coverage"]["from_ted"], 0)
        self.assertEqual(self.fetched, [P1])

    def test_one_of_two_handed_over_is_incomplete(self):
        self.only_on_ted()
        self.ted_day.add("699998-2026")
        day, changes = self.run_day()
        self.assertFalse(day["complete"])
        self.assertIn(P9, self.fetched)
        self.assertEqual(day["coverage"]["from_ted"], 1)


class Watched(Window):

    def test_a_tender_udbud_holds_no_notice_of_is_read_from_ted(self):
        self.ted_records.append(record("588888-2026", P8, "Omega bro", "2026-08-20+02:00"))
        day, changes = self.run_day(watch=["DK:%s" % P8])
        self.assertIn(P8, self.fetched)
        self.assertEqual(day["coverage"]["watch_holes"], 0)
        self.assertEqual(json.loads(self.read("tenders", P8, "index.json"))["source"],
                         "ted.europa.eu")

    def test_one_neither_holds_is_a_watch_hole(self):
        day, changes = self.run_day(watch=["DK:%s" % P8])
        self.assertNotIn(P8, self.fetched)
        self.assertEqual(day["coverage"]["watch_holes"], 1)

    def test_one_udbud_knows_but_no_longer_live_is_not_resurrected(self):
        self.ted_records.append(record("588888-2026", P8, "Omega bro", "2026-08-20+02:00"))
        self.by_text[P8] = [row("n-r", "Omega bro", code="result", npn="00590000-2026",
                                date="28-08-2026")]
        self.details["n-r"] = detail(P8)
        day, changes = self.run_day(watch=["DK:%s" % P8])
        self.assertNotIn(P8, self.fetched)
        self.assertEqual(day["coverage"]["watch_holes"], 1)
        self.assertEqual([q for q in self.queries if P8 in q], [], "TED is not asked about it")

    def test_one_udbud_holds_live_is_not_asked_of_ted(self):
        self.by_text[P3] = [ROWS[1]]
        self.run_day(watch=["DK:%s" % P3])
        self.assertIn(P3, self.fetched)
        self.assertEqual(self.queries, [])


class HostFailures(Window):

    def documents(self, url):
        self.details["n-a"] = detail(P1, [url])

    def tender(self, day):
        return [t for t in day["tenders"] if t["pid"] == P1][0]

    def test_a_host_that_fails_is_named_and_the_tender_is_unknown(self):
        self.documents(DALUX)
        with mock.patch.object(dalux, "listing", side_effect=dalux.Refused("no such version")):
            day, changes = self.run_day()
        self.assertEqual(len(day["host_failures"]), 1)
        failure = day["host_failures"][0]
        self.assertEqual(failure["pid"], P1)
        self.assertEqual(failure["ref"], "00600001-2026")
        self.assertEqual(failure["host"], "node1.build.dalux.com")
        self.assertIn("no such version", failure["note"])
        self.assertEqual(self.tender(day)["documents_available"], "unknown")
        index = json.loads(self.read("tenders", P1, "index.json"))
        self.assertEqual(index["documents_available"], "unknown")

    def test_the_verdict_is_not_ok_and_main_exits_1(self):
        self.documents(DALUX)
        with mock.patch.object(dalux, "listing", side_effect=dalux.Refused("no such version")):
            day, changes = self.run_day()
        ok, lines = day_verdict.verdict(day)
        self.assertFalse(ok)
        self.assertTrue(lines)
        self.assertEqual(self.main(), 1)

    def test_they_are_written_to_day_json(self):
        self.documents(DALUX)
        with mock.patch.object(dalux, "listing", side_effect=dalux.Refused("no such version")):
            day, changes = self.run_day()
        self.assertEqual(json.loads(self.read(DATE, "day.json"))["host_failures"],
                         day["host_failures"])

    def test_a_ted_only_notice_whose_host_fails(self):
        self.only_on_ted()
        self.ted_records[0]["document-url-lot"] = [DALUX]
        with mock.patch.object(dalux, "listing", side_effect=dalux.Refused("no such version")):
            day, changes = self.run_day()
        self.assertEqual([f["pid"] for f in day["host_failures"]], [P9])

    def test_fetch_says_the_host_failed(self):
        self.documents(DALUX)
        target = dk_page.enrich(dk_page.notice(ROWS[0]), self.details["n-a"])
        with mock.patch.object(dalux, "listing", side_effect=dalux.Refused("no such version")):
            done = dk_fetch.fetch(target, self.out, self.details["n-a"], with_text=False)
        self.assertTrue(done["host_failed"])
        self.assertEqual(done["documents_available"], "unknown")

    def test_a_gated_host_has_not_failed(self):
        self.documents(DALUX)
        found = {"access": "gated", "files": [], "gated": [], "note": "not public"}
        with mock.patch.object(dalux, "listing", return_value=found):
            day, changes = self.run_day()
        self.assertEqual(self.tender(day)["documents_available"], "gated")
        self.assertFalse(day.get("host_failures"))
        self.assertTrue(day_verdict.verdict(day)[0])
        self.assertEqual(self.main(), 0)

    def test_a_host_with_no_reader_has_not_failed(self):
        self.documents("https://www.amgros.dk/udbud/123")
        day, changes = self.run_day()
        self.assertEqual(self.tender(day)["documents_available"], "unknown")
        self.assertFalse(day.get("host_failures"))
        self.assertTrue(day_verdict.verdict(day)[0])

    def test_a_day_with_no_documents_link_has_none(self):
        day, changes = self.run_day()
        self.assertFalse(day.get("host_failures"))
        self.assertTrue(day_verdict.verdict(day)[0])


if __name__ == "__main__":
    unittest.main()
