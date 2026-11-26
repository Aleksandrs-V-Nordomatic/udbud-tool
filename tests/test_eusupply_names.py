#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EU-Supply names: every public and gated name goes through `eusupply.clean_name`.

The documents page is single-byte, but every file name on it is led by a UTF-8 non-breaking space
(the bytes C2 A0), which read as latin-1 is A-circumflex and a non-breaking space. The two pages of
a listing are answered by a stand-in for `docsource.common.fetch`; `net.open_url` fails loudly.
Every character outside ASCII is built with `chr`, so the source shows what it holds.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import net
from docsource import common, eusupply

NBSP_UTF8 = bytes([0xC2, 0xA0])
NBSP = chr(0xA0)
A_CIRC = chr(0xC2)
PAIR = A_CIRC + NBSP              # the UTF-8 non-breaking space read as latin-1
AE, OE, AA = chr(0xE6), chr(0xF8), chr(0xE5)

PURCHASE_URL = "https://eu.eu-supply.com/app/rfq/rwlentrance_s.asp?PID=123456&B=EXAMPLE"
DOCS_PATH = "/app/rfq/publicpurchase_docs.asp?PID=123456&LID=654321"

# Where the stand-in for `common.fetch` expects the two pages to be asked:
# the purchase page is `eusupply.PURCHASE % pid`, the documents page is the host + the href.
PURCHASE_PAGE_URL = "https://eu.eu-supply.com/ctm/Supplier/PublicPurchase/123456/0/0?returnUrl=&b="
DOCS_URL = "https://eu.eu-supply.com" + DOCS_PATH

PURCHASE_PAGE = (b'<html><body><h1>Udbud</h1>'
                 b'<a href="' + DOCS_PATH.encode("ascii") + b'">Udbudsdokumenter</a>'
                 b'</body></html>')


def latin1(text):
    return text.encode("latin-1")


def public_file(dvid, name):
    """A public file as the documents page prints it; `name` is the bytes on the page."""
    return (b"<script>var sDoc_" + dvid + b" = '" + name + b"';</script>"
            b"<a href=\"javascript:DownloadPublicDocument('" + dvid + b"','sDoc_" + dvid +
            b"','654321')\">Hent</a>")


def gated_file(name):
    return b'<tr><td valign="top" class="tblcell" colspan="2">' + name + b'</td></tr>'


def documents_page(public=(), gated=()):
    body = b"<html><body><h2>Dokumenter</h2>"
    body += b"".join(public_file(d, n) for d, n in public)
    if gated:
        body += b"<p>Available after expression of interest</p><table>"
        body += b"".join(gated_file(n) for n in gated)
        body += b"</table>"
    return body + b"</body></html>"


def no_network(*args, **kwargs):
    raise AssertionError("a test reached the network: %r" % (args[:1],))


def names(items):
    return [i["name"] if isinstance(i, dict) else i for i in items or []]


# ---------------------------------------------------------------- clean_name

class CleanName(unittest.TestCase):

    def test_the_constants_are_what_they_say(self):
        self.assertEqual(len(NBSP), 1)
        self.assertEqual(len(PAIR), 2)
        self.assertEqual(PAIR, NBSP_UTF8.decode("latin-1"))
        self.assertEqual(NBSP_UTF8.decode("utf-8"), NBSP)

    def test_the_pair_that_leads_a_name_is_gone(self):
        self.assertEqual(eusupply.clean_name(PAIR + "Tilbudsliste.xlsx"), "Tilbudsliste.xlsx")

    def test_the_pair_inside_a_name_is_a_space(self):
        self.assertEqual(eusupply.clean_name("Bilag" + PAIR + "1.pdf"), "Bilag 1.pdf")

    def test_any_other_non_breaking_space_is_a_space(self):
        self.assertEqual(eusupply.clean_name("Bilag" + NBSP + "1.pdf"), "Bilag 1.pdf")
        self.assertEqual(eusupply.clean_name(NBSP + "Bilag 1.pdf" + NBSP), "Bilag 1.pdf")

    def test_html_entities_are_unescaped(self):
        self.assertEqual(eusupply.clean_name("Bilag &amp; tegninger.pdf"), "Bilag & tegninger.pdf")
        self.assertEqual(eusupply.clean_name("&quot;K&#248;bstad&quot;.pdf"),
                         '"K' + OE + 'bstad".pdf')

    def test_an_escaped_non_breaking_space_is_a_space(self):
        self.assertEqual(eusupply.clean_name("&nbsp;Bilag&nbsp;2.pdf"), "Bilag 2.pdf")

    def test_an_escaped_pair_is_gone(self):
        self.assertEqual(eusupply.clean_name("&Acirc;&nbsp;Bilag 3.pdf"), "Bilag 3.pdf")

    def test_runs_of_spaces_collapse(self):
        self.assertEqual(eusupply.clean_name("Bilag   1 " + NBSP + " " + PAIR + " .pdf"),
                         "Bilag 1 .pdf")

    def test_the_ends_are_trimmed(self):
        self.assertEqual(eusupply.clean_name("   Bilag 1.pdf   "), "Bilag 1.pdf")
        self.assertEqual(eusupply.clean_name(PAIR + PAIR + "Bilag 1.pdf " + PAIR), "Bilag 1.pdf")

    def test_danish_letters_are_kept(self):
        name = "Tegning %s%s%s %s.pdf" % (AE, OE, AA, (AE + OE + AA).upper())
        self.assertEqual(eusupply.clean_name(name), name)

    def test_a_capital_a_circumflex_alone_is_kept(self):
        self.assertEqual(eusupply.clean_name(A_CIRC + "ge.pdf"), A_CIRC + "ge.pdf")

    def test_a_clean_name_is_unchanged(self):
        self.assertEqual(eusupply.clean_name("Udbudsbetingelser.pdf"), "Udbudsbetingelser.pdf")
        cleaned = eusupply.clean_name(PAIR + "Udbud &amp;  bilag.pdf")
        self.assertEqual(eusupply.clean_name(cleaned), cleaned)

    def test_nothing_is_nothing(self):
        self.assertEqual(eusupply.clean_name(""), "")
        self.assertEqual(eusupply.clean_name(PAIR), "")


# ---------------------------------------------------------------- listing

class Listing(unittest.TestCase):

    def setUp(self):
        patcher = mock.patch.object(net, "open_url", side_effect=no_network)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.asked = []

    def listing(self, docs):
        def fetch(url, *args, **kwargs):
            self.asked.append(url)
            if url == DOCS_URL:
                return docs
            if url == PURCHASE_PAGE_URL:
                return PURCHASE_PAGE
            raise AssertionError("an unexpected address: %s" % url)

        with mock.patch.object(common, "fetch", side_effect=fetch):
            return eusupply.listing([PURCHASE_URL])

    def test_the_result_has_its_fields(self):
        found = self.listing(documents_page(public=[(b"111", b"Udbudsbetingelser.pdf")]))
        for key in ("access", "files", "gated", "public_names", "tender_id", "note"):
            self.assertIn(key, found)

    def test_the_two_pages_are_asked_and_no_document(self):
        self.listing(documents_page(public=[(b"111", b"Udbudsbetingelser.pdf")],
                                    gated=[NBSP_UTF8 + b"Bilag 1.pdf"]))
        self.assertEqual(len(self.asked), 2, self.asked)
        # The first address asked is the purchase page, `eusupply.PURCHASE % pid`.
        self.assertEqual(self.asked[0], PURCHASE_PAGE_URL)
        self.assertIn("publicpurchase_docs.asp", self.asked[1])
        self.assertIn("PID=123456", self.asked[1])
        self.assertIn("LID=654321", self.asked[1])
        for url in self.asked:
            self.assertNotIn("/app/docmgmt", url)

    def test_a_gated_name_led_by_a_utf8_space_is_clean(self):
        page = documents_page(gated=[NBSP_UTF8 + latin1("Bilag " + AE + "ndring.pdf"),
                                     NBSP_UTF8 + latin1("Tilbudsliste " + OE + "konomi.xlsx")])
        found = self.listing(page)
        self.assertEqual(names(found["gated"]),
                         ["Bilag " + AE + "ndring.pdf", "Tilbudsliste " + OE + "konomi.xlsx"])

    def test_no_gated_name_carries_the_pair(self):
        page = documents_page(gated=[NBSP_UTF8 + b"Bilag 1.pdf", NBSP_UTF8 + b"Bilag 2.pdf"])
        found = names(self.listing(page)["gated"])
        self.assertEqual(found, ["Bilag 1.pdf", "Bilag 2.pdf"])
        for name in found:
            self.assertNotIn(A_CIRC, name)
            self.assertNotIn(NBSP, name)

    def test_a_gated_name_with_an_entity(self):
        page = documents_page(gated=[NBSP_UTF8 + b"Bilag &amp; tegninger.pdf"])
        self.assertEqual(names(self.listing(page)["gated"]), ["Bilag & tegninger.pdf"])

    def test_public_names_are_clean_too(self):
        page = documents_page(public=[(b"111", NBSP_UTF8 + latin1("Udbudsbetingelser " + AE + ".pdf")),
                                      (b"222", b"Kontrakt &amp; bilag.pdf")])
        self.assertEqual(sorted(names(self.listing(page)["public_names"])),
                         ["Kontrakt & bilag.pdf", "Udbudsbetingelser " + AE + ".pdf"])

    def test_public_and_gated_names_on_one_page(self):
        # EU-Supply is read for "names only - public ones too" and nothing is downloaded there,
        # so a public file is not read either: `gated` names it beside the names after
        # "Available after expression of interest"; `public_names` holds the public ones alone.
        page = documents_page(public=[(b"111", b"Udbudsbetingelser.pdf")],
                              gated=[NBSP_UTF8 + b"Tilbudsliste.xlsx"])
        found = self.listing(page)
        self.assertEqual(names(found["public_names"]), ["Udbudsbetingelser.pdf"])
        self.assertEqual(sorted(names(found["gated"])),
                         ["Tilbudsliste.xlsx", "Udbudsbetingelser.pdf"])


if __name__ == "__main__":
    unittest.main()
