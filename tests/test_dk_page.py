#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What one udbud.dk notice becomes: the row's facts, the detail's key, and doc/notice.md.

The fixtures are trimmed from a real search answer and a real detail of the public portal:
a search row keeps the fields `notice()` reads, and `htmlDA` keeps the few sections the
procedure, the internal id and the Markdown rendering need.
"""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dk_page


ROW = {
    "dataDa": {
        "titel": "Handel med CO2-Kvoter",
        "ordregiver": "I/S Amager Ressourcecenter",
        "ordregiverId": "ORG-34 20 81 15",
        "ordregiverIdDatavasket": "34208115",
        "publiceringsdato": "02-09-2026",
        "cpvKode": "90000000",
        "cpvTitel": "Tjenesteydelser i forbindelse med spildevand, affald, rengøring og miljøbeskyttelse",
        "formulartype": "Konkurrencevilkår",
        "formulartypeKode": "competition",
        "tidsfrister": ["2026-09-30T08:00:00Z", "2026-09-23T08:00:00Z"],
        "alleOrdregivere": ["I/S Amager Ressourcecenter", "ARC Affaldsenergi / Waste to Energy A/S"],
        "anslaaetVaerdi": "1000000",
        "anslaaetVaerdiValuta": "DKK",
        "beskrivelse": "Indkøbet omfatter handel med CO2-kvoter på vegne af ARC Affaldsenergi.",
        "bkSubTypeKode": "DKE3",
        "bkSubType": "Annoncering under tærskelværdien",
        "erAendring": False,
    },
    "dataEn": {
        "titel": "Trading of CO2 allowances",
        "beskrivelse": "The purchase covers trading of CO2 allowances.",
    },
    "noticeId": "ed2a934c-c8eb-4539-8e74-501f4f70aaa0",
    "noticeVersion": "01",
    "noticePublicationNumber": "",
}

PROCEDURE = "7c03c120-69c0-4112-af76-3d30b1aab18e"


def _leaf(label, value):
    return ('<section><span class="label">%s</span><span class="text">: </span>'
            '<span class="value">%s</span></section>\n' % (label, value))


def detail(procedure=PROCEDURE.upper(), intern="TS238559", documents=None):
    """A detail as the portal serves it, with `htmlDA` trimmed to two numbered sections."""
    procedure_leaves = _leaf("Beskrivelse", "Første linje.<br/>Anden linje.")
    if procedure is not None:
        procedure_leaves += _leaf("Identifikator for proceduren", procedure)
    if intern is not None:
        procedure_leaves += _leaf("Intern ID", intern)
    html = ('<!DOCTYPE HTML>\n<html><body>\n'
            '<section>1&nbsp;<span class="label">Køber</span>'
            '<section>1.1&nbsp;<span class="label">Køber</span>'
            + _leaf("Officielt navn", "Danmarks Nationalbank")
            + '</section>\n</section>\n'
            '<section>2&nbsp;<span class="label">Procedure</span>'
            '<section>2.1&nbsp;<span class="label">Procedure</span>'
            + procedure_leaves
            + '</section>\n</section>\n</body></html>')
    return {
        "htmlDA": html,
        "htmlEN": "<html>english</html>",
        "opsummeringDA": {
            "indholdsType": "HENTET_FRA_TED",
            "udforelsesstedNutsCode": ["DK011"],
            "udforelsesstedBy": ["Copenhagen Ø"],
            "tilbudsfrister": [],
            "deltagelsefrister": ["2026-10-02T10:00:00Z"],
            "antalLots": 1,
            "udbudsDokumenter": documents if documents is not None else [
                "https://eu.eu-supply.com/app/rfq/rwlentrance_s.asp?PID=460124&TID=200420571&B="],
        },
    }


def row(**changes):
    r = copy.deepcopy(ROW)
    for key, value in changes.items():
        if key in ("noticeId", "noticeVersion", "noticePublicationNumber"):
            r[key] = value
        else:
            r["dataDa"][key] = value
    return r


class DanishDate(unittest.TestCase):

    def test_day_month_year_becomes_iso(self):
        self.assertEqual(dk_page.danish_date("02-09-2026"), "2026-09-02")

    def test_surrounding_whitespace_is_tolerated(self):
        self.assertEqual(dk_page.danish_date(" 13-11-2026 "), "2026-11-13")

    def test_other_shapes_are_none(self):
        for text in (None, "", "2026-09-02", "2-9-2026", "02/09/2026", "2026-09-02+02:00"):
            self.assertIsNone(dk_page.danish_date(text), text)


class KindOf(unittest.TestCase):

    def kind(self, code, change=False):
        return dk_page.kind_of({"dataDa": {"formulartypeKode": code, "erAendring": change}})

    def test_the_readme_table(self):
        self.assertEqual(self.kind("competition"), "tender")
        self.assertEqual(self.kind("change"), "amendment")
        self.assertEqual(self.kind("result"), "award")
        self.assertEqual(self.kind("dir-awa-pre"), "award")
        self.assertEqual(self.kind("cont-modif"), "modification")
        self.assertEqual(self.kind("planning"), "plan")
        self.assertEqual(self.kind("preplanning"), "plan")
        self.assertEqual(self.kind("consultation"), "consultation")

    def test_a_competition_marked_as_a_change_is_an_amendment(self):
        self.assertEqual(self.kind("competition", change=True), "amendment")

    def test_er_aendring_does_not_turn_an_award_into_an_amendment(self):
        self.assertEqual(self.kind("result", change=True), "award")

    def test_an_unknown_code_is_other(self):
        self.assertEqual(self.kind("something-new"), "other")
        self.assertEqual(dk_page.kind_of({}), "other")

    def test_live_and_close_kinds(self):
        self.assertTrue(dk_page.is_live({"kind": "tender"}))
        self.assertTrue(dk_page.is_live({"kind": "amendment"}))
        for kind in ("award", "modification", "plan", "consultation", "other"):
            self.assertFalse(dk_page.is_live({"kind": kind}), kind)


class Notice(unittest.TestCase):

    def test_a_national_notice_is_referred_to_by_its_notice_id(self):
        t = dk_page.notice(row())
        self.assertEqual(t["ref"], ROW["noticeId"])
        self.assertEqual(t["npn"], "")
        self.assertFalse(t["eu"])
        self.assertIsNone(t["pid"])

    def test_an_eu_notice_is_referred_to_by_its_ted_number(self):
        t = dk_page.notice(row(noticePublicationNumber="00603665-2026"))
        self.assertEqual(t["ref"], "00603665-2026")
        self.assertTrue(t["eu"])
        self.assertIn("noticePublicationNumber=00603665-2026", t["link"])

    def test_facts_off_the_row(self):
        t = dk_page.notice(row())
        self.assertEqual(t["kind"], "tender")
        self.assertEqual(t["published"], "2026-09-02")
        self.assertEqual(t["buyer"], "I/S Amager Ressourcecenter")
        self.assertEqual(t["buyer_id"], "34208115")
        self.assertEqual(t["cpv_main"], "90000000")
        self.assertEqual(t["cpv"], ["90000000"])
        self.assertEqual(t["value"], 1000000.0)
        self.assertEqual(t["currency"], "DKK")
        self.assertEqual(t["description"], ROW["dataDa"]["beskrivelse"])

    def test_the_earliest_deadline_is_the_deadline(self):
        t = dk_page.notice(row())
        self.assertEqual(t["deadline"], "2026-09-23T08:00:00Z")
        self.assertEqual(t["deadlines"], ["2026-09-23T08:00:00Z", "2026-09-30T08:00:00Z"])

    def test_titles_join_danish_and_english(self):
        t = dk_page.notice(row())
        self.assertEqual(t["title"], "Handel med CO2-Kvoter")
        self.assertEqual(t["titles"], "Handel med CO2-Kvoter Trading of CO2 allowances")

    def test_titles_do_not_repeat_an_identical_english_title(self):
        r = row()
        r["dataEn"]["titel"] = r["dataDa"]["titel"]
        self.assertEqual(dk_page.notice(r)["titles"], "Handel med CO2-Kvoter")

    def test_the_english_title_stands_in_when_danish_is_missing(self):
        t = dk_page.notice(row(titel=None))
        self.assertEqual(t["title"], "Trading of CO2 allowances")
        self.assertEqual(t["titles"], "Trading of CO2 allowances")

    def test_an_absent_value_is_none_and_so_is_its_currency(self):
        r = row()
        del r["dataDa"]["anslaaetVaerdi"]
        t = dk_page.notice(r)
        self.assertIsNone(t["value"])
        self.assertIsNone(t["currency"])

    def test_an_empty_or_unreadable_value_is_none(self):
        for text in ("", "ikke oplyst"):
            t = dk_page.notice(row(anslaaetVaerdi=text))
            self.assertIsNone(t["value"], text)
            self.assertIsNone(t["currency"], text)

    def test_no_cpv_is_an_empty_list(self):
        t = dk_page.notice(row(cpvKode=None))
        self.assertEqual(t["cpv"], [])

    def test_no_deadlines(self):
        t = dk_page.notice(row(tidsfrister=None))
        self.assertIsNone(t["deadline"])
        self.assertEqual(t["deadlines"], [])


class Enrich(unittest.TestCase):

    def test_the_procedure_is_the_key_lower_cased(self):
        t = dk_page.enrich(dk_page.notice(row()), detail())
        self.assertEqual(t["pid"], PROCEDURE)
        self.assertEqual(t["procedure_id"], PROCEDURE.upper())
        self.assertEqual(t["intern_id"], "TS238559")
        self.assertTrue(t["link_verified"])

    def test_without_a_procedure_the_buyer_and_internal_id_key_the_home(self):
        t = dk_page.enrich(dk_page.notice(row()), detail(procedure=None, intern="TS 2385/59"))
        self.assertIsNone(t["procedure_id"])
        self.assertEqual(t["pid"], "int-34208115-TS_2385_59")

    def test_without_procedure_or_internal_id_the_notice_keys_the_home(self):
        t = dk_page.enrich(dk_page.notice(row()), detail(procedure=None, intern=None))
        self.assertEqual(t["pid"], "notice-%s" % ROW["noticeId"])

    def test_without_a_buyer_id_the_internal_id_is_not_enough(self):
        r = row(ordregiverIdDatavasket="", ordregiverId="")
        t = dk_page.enrich(dk_page.notice(r), detail(procedure=None, intern="TS238559"))
        self.assertEqual(t["pid"], "notice-%s" % ROW["noticeId"])

    def test_no_detail_is_an_unverified_link_with_a_notice_key(self):
        t = dk_page.enrich(dk_page.notice(row()), None)
        self.assertFalse(t["link_verified"])
        self.assertEqual(t["pid"], "notice-%s" % ROW["noticeId"])
        self.assertEqual(t["documents_urls"], [])
        self.assertIsNone(t["documents_url"])
        self.assertIsNone(t["documents_host"])

    def test_the_documents_link_and_its_host(self):
        t = dk_page.enrich(dk_page.notice(row()), detail())
        self.assertEqual(t["documents_url"],
                         "https://eu.eu-supply.com/app/rfq/rwlentrance_s.asp?PID=460124&TID=200420571&B=")
        self.assertEqual(t["documents_host"], "eu.eu-supply.com")
        self.assertEqual(t["lots"], 1)
        self.assertEqual(t["nuts"], ["DK011"])
        self.assertEqual(t["deadline_request"], "2026-10-02T10:00:00Z")
        self.assertIsNone(t["deadline_tender"])

    def test_the_host_is_lower_cased_and_empty_links_skipped(self):
        t = dk_page.enrich(dk_page.notice(row()),
                           detail(documents=["", "https://WWW.Ethics.DK/ethics/eo#/x/publicMaterial"]))
        self.assertEqual(t["documents_urls"], ["https://WWW.Ethics.DK/ethics/eo#/x/publicMaterial"])
        self.assertEqual(t["documents_host"], "www.ethics.dk")

    def test_labelled_unescapes_the_value(self):
        html = ('<section><span class="label">Officielt navn</span><span class="text">: </span>'
                '<span class="value">Bygge &amp; Anlæg</span></section>')
        self.assertEqual(dk_page.labelled(html, "Officielt navn"), "Bygge & Anlæg")
        self.assertIsNone(dk_page.labelled(html, "Intern ID"))
        self.assertIsNone(dk_page.labelled(None, "Intern ID"))


class HtmlMarkdown(unittest.TestCase):

    def setUp(self):
        self.md = dk_page.html_markdown(detail()["htmlDA"])
        self.lines = self.md.splitlines()

    def heading(self, text):
        for line in self.lines:
            if line.lstrip("#").strip() == text and line.startswith("#"):
                return line
        self.fail("no heading %r in:\n%s" % (text, self.md))

    def test_numbered_sections_become_headings(self):
        top = self.heading("1 Køber")
        sub = self.heading("1.1 Køber")
        self.heading("2 Procedure")
        self.heading("2.1 Procedure")
        self.assertGreater(len(sub) - len(sub.lstrip("#")), len(top) - len(top.lstrip("#")))

    def test_leaves_become_label_colon_value(self):
        self.assertIn("Officielt navn: Danmarks Nationalbank", self.lines)
        self.assertIn("Identifikator for proceduren: %s" % PROCEDURE.upper(), self.lines)
        self.assertIn("Intern ID: TS238559", self.lines)

    def test_a_line_break_in_a_value_is_kept(self):
        self.assertIn("Beskrivelse: Første linje.", self.lines)
        self.assertIn("Anden linje.", self.lines)

    def test_no_tags_and_no_runs_of_blank_lines(self):
        self.assertNotIn("<", self.md)
        self.assertNotIn("\n\n\n", self.md)
        self.assertTrue(self.md.endswith("\n"))

    def test_empty_html(self):
        self.assertEqual(dk_page.html_markdown(""), "\n")
        self.assertEqual(dk_page.html_markdown(None), "\n")


class NoticeMarkdown(unittest.TestCase):

    def target(self, description, document):
        r = row(beskrivelse=description)
        return dk_page.enrich(dk_page.notice(r), document)

    def test_the_description_is_held_byte_for_byte(self):
        description = "Første afsnit: rådgivning om ventilation.\n\n  Andet afsnit; »citat« & 50 %.\r\nSlut."
        document = detail()
        t = self.target(description, document)
        text = dk_page.notice_markdown(t, document)
        self.assertIn(description, text)

    def test_the_description_is_held_byte_for_byte_without_a_detail(self):
        description = "Rådgivning om ventilation.\nAnden linje med æøå."
        t = self.target(description, None)
        self.assertIn(description, dk_page.notice_markdown(t, None))

    def test_a_trailing_newline_of_the_description_survives_without_a_detail(self):
        # With no rendered notice after it, the description is the last thing in the file.
        description = "Rådgivning om ventilation.\n"
        t = self.target(description, None)
        self.assertIn(description, dk_page.notice_markdown(t, None))

    def test_facts_description_then_the_whole_notice(self):
        document = detail()
        t = self.target("Beskrivelsen.", document)
        text = dk_page.notice_markdown(t, document)
        self.assertTrue(text.startswith("# Handel med CO2-Kvoter\n"))
        self.assertIn("- Ordregiver: I/S Amager Ressourcecenter", text)
        self.assertIn("- Offentliggjort: 2026-09-02", text)
        self.assertIn("- Procedure: %s" % PROCEDURE.upper(), text)
        self.assertIn("- Anslået værdi: 1000000.0 DKK", text)
        self.assertLess(text.index("## Beskrivelse"), text.index("## Bekendtgørelsen"))
        self.assertIn("Officielt navn: Danmarks Nationalbank", text)

    def test_no_rendered_notice_without_a_detail(self):
        t = self.target("Beskrivelsen.", None)
        text = dk_page.notice_markdown(t, None)
        self.assertIn("## Beskrivelse", text)
        self.assertNotIn("## Bekendtgørelsen", text)
        self.assertNotIn("- Anslået værdi: None", text)

    def test_an_absent_value_is_not_printed(self):
        r = row()
        del r["dataDa"]["anslaaetVaerdi"]
        t = dk_page.enrich(dk_page.notice(r), None)
        self.assertNotIn("Anslået værdi", dk_page.notice_markdown(t, None))


if __name__ == "__main__":
    unittest.main()
