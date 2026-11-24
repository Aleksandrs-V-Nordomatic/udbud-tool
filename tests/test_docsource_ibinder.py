#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iBinder's public view, read as an anonymous visitor.

The host is a stand-in for `docsource.common.fetch` that answers by address. An address the brief
does not list, or a folder that must not be asked for, is noted as a stray call and fails the test
in `tearDown`, because the module under test may swallow what the stand-in raises. `net.open_url`
fails loudly, so nothing reaches the network.
"""

import io
import json
import os
import re
import sys
import unittest
import urllib.error
from unittest import mock
from urllib.parse import parse_qsl

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import docsource
import net
from docsource import common, ibinder


def guid(n):
    return "%08d-0000-4000-8000-%012d" % (n, n)


ORG = guid(900001)
TENDER = guid(900002)
MY = "my.ibinder.com"
BOOKSHELF = "bookshelf.ibinder.com"

LINK = "https://store.blob.core.windows.net/previews/a.pdf?sv=VERSIONPART&sig=SECRET"
PDF = b"%PDF-1.7 preview"

DOCUMENTS = re.compile(r"/version/latest/procurementSections/([^/]+)/documents\?(.+)")
PREVIEW = re.compile(r"/procurementSections/([^/]+)/documents/([^/]+)/versions/([^/]+)/preview")


def link(host=MY):
    return "https://%s/etendering/%s/tenders/%s/public" % (host, ORG, TENDER)


def row(n, name, preview=True, deleted=False, version="AFQ"):
    """A row of a file list; its version guid is `guid(n + 5000)`."""
    url = "/documents/%s/versions/%s/preview" % (guid(n), guid(n + 5000))
    return {"id": guid(n), "name": name, "deleted": deleted,
            "metadata": [{"metadataElementId": "GLOBAL_Other", "valueId": "NOT-THIS"},
                         {"metadataElementId": "GLOBAL_TenderVersionId", "valueId": version}],
            "files": {"preview": {"url": url} if preview else None}}


def refusal(code):
    return urllib.error.HTTPError("https://my.ibinder.com/x", code, "refused", {}, io.BytesIO(b""))


def no_network(*args, **kwargs):
    raise AssertionError("a test reached the network: %r" % (args[:1],))


class Host(unittest.TestCase):

    def setUp(self):
        for patcher in (mock.patch.object(net, "open_url", side_effect=no_network),
                        mock.patch.object(common, "fetch", side_effect=self.fetch)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.host = MY
        self.config = {"publicLinkEnabled": True, "procurementSections": []}
        self.pages = {}         # folder id -> pages of rows; only these folders may be asked for
        self.totals = {}        # folder id -> a totalCount other than the rows held
        self.fail = {}          # kind of call -> what it raises
        self.preview = {"url": LINK}
        self.stored = PDF
        self.calls = []         # (kind, detail, headers) in order
        self.strays = []

    def tearDown(self):
        self.assertEqual(self.strays, [], "calls that must not be made")

    # --- the stand-in

    def fetch(self, url, data=None, headers=None, opener=None, timeout=60, tries=None):
        headers = {k.lower(): v for k, v in (headers or {}).items()}
        kind, detail = self.read(url, data)
        if kind is None:
            self.strays.append((url, data))
            raise AssertionError("a call outside the list: %s" % url)
        self.calls.append((kind, detail, headers))
        if kind in self.fail:
            raise self.fail[kind]
        if kind == "store":
            return self.stored
        if kind == "preview" and isinstance(self.preview, bytes):
            return self.preview
        answer = {"tender": lambda: {"name": "Ny skole"},
                  "configuration": lambda: self.config,
                  "documents": lambda: self.page(*detail),
                  "preview": lambda: self.preview}[kind]()
        return json.dumps(answer).encode("utf-8")

    def read(self, url, data):
        """The call an address is, as (kind, detail), or (None, None)."""
        base = "https://%s/api/etendering/tenders/%s" % (self.host, TENDER)
        if url == LINK and data is None:
            return "store", None
        if not url.startswith(base):
            return None, None
        rest = url[len(base):]
        if rest == "" and data is None:
            return "tender", None
        if rest == "/configuration" and data is None:
            return "configuration", None
        m = DOCUMENTS.fullmatch(rest)
        if m and data is not None:
            json.loads(data.decode("utf-8"))
            query = dict(parse_qsl(m.group(2)))
            number = query.get("pageNumber", "")
            if (m.group(1) in self.pages and set(query) == {"pageSize", "pageNumber"}
                    and query["pageSize"] == "250" and number.isdigit() and 1 <= int(number) < 10):
                return "documents", (m.group(1), int(number))
        m = PREVIEW.fullmatch(rest)
        if m and data is None:
            return "preview", m.groups()
        return None, None

    def page(self, folder, number):
        pages = self.pages[folder]
        total = self.totals.get(folder, sum(len(p) for p in pages))
        return {"data": pages[number - 1] if number <= len(pages) else [], "totalCount": total}

    # --- building a tender

    def folder(self, n, name, rows=(), type="Document", enabled=True, **subtabs):
        """A section; a Document or Drawing folder may be asked for its files."""
        if type in ("Document", "Drawing"):
            rows = list(rows)
            self.pages[guid(n)] = [rows[i:i + 250] for i in range(0, len(rows), 250)]
        return dict({"id": guid(n), "name": name, "type": type, "enabled": enabled}, **subtabs)

    def tender(self, *sections):
        self.config["procurementSections"] = list(sections)

    def one_file(self, name="Plan.pdf", **kwargs):
        self.tender(self.folder(1, "Udbud", [row(101, name, **kwargs)]))
        return self.listing()["files"][0]

    # --- asking

    def listing(self):
        return ibinder.listing([link(self.host)])

    def kinds(self):
        return [kind for kind, _, _ in self.calls]

    def asked(self):
        return [detail for kind, detail, _ in self.calls if kind == "documents"]

    def paths(self, found):
        return sorted(f["folder"] + "/" + f["name"] for f in found["files"])


class Link(Host):

    def test_the_constants(self):
        self.assertEqual(ibinder.NAME, "ibinder")
        self.assertEqual(ibinder.PAGE_SIZE, 250)

    def test_the_host_and_its_subdomains(self):
        for url in (link(MY), link(BOOKSHELF), "https://ibinder.com/x",
                    "https://other.ibinder.com/x", "HTTPS://MY.IBINDER.COM/x"):
            self.assertIs(docsource.module_for(url), ibinder, url)
        for url in ("https://notibinder.com/x", "https://ibinder.com.evil.test/x",
                    link("my.ibinder.com.evil.test")):
            self.assertIsNone(docsource.module_for(url), url)

    def test_both_hosts_are_read_at_the_host_of_the_link(self):
        for host in (MY, BOOKSHELF):
            with self.subTest(host=host):
                self.host = host
                entry = self.one_file()
                self.assertTrue(entry["download"].startswith("https://%s/api/" % host))
                self.assertEqual(ibinder.download(entry), (PDF, None))

    def test_a_link_of_another_shape_is_unknown_and_asks_nothing(self):
        for url in ("https://my.ibinder.com/",
                    "https://my.ibinder.com/%s/tenders/%s/public" % (ORG, TENDER),
                    "https://my.ibinder.com/etendering/%s" % ORG,
                    link("ibinder.com.evil.test"), link("my.ibinder.com.evil.test"),
                    link("evil.test"), link("other.ibinder.com"),
                    link().replace("https://", "http://"),
                    "https://evil.test/?next=" + link()):
            with self.subTest(url=url):
                found = ibinder.listing([url])
                self.assertEqual(found["access"], "unknown")
                self.assertEqual(found["files"], [])
                self.assertEqual(self.calls, [])

    def test_the_organisation_is_on_every_call_to_ibinder_and_none_to_the_store(self):
        self.assertEqual(ibinder.download(self.one_file()), (PDF, None))
        self.assertEqual(set(self.kinds()),
                         {"tender", "configuration", "documents", "preview", "store"})
        for kind, _, headers in self.calls:
            if kind == "store":
                self.assertNotIn("x-ibinder-tenantid", headers)
                self.assertNotIn(ORG, "".join(str(v) for v in headers.values()))
            else:
                self.assertEqual(headers.get("x-ibinder-tenantid"), ORG, kind)


class Refusals(Host):

    def test_401_403_404_410_are_gated_with_the_code(self):
        self.tender(self.folder(1, "Udbud", [row(101, "Plan.pdf")]))
        for kind in ("tender", "configuration"):
            for code in (401, 403, 404, 410):
                with self.subTest(kind=kind, code=code):
                    self.fail = {kind: refusal(code)}
                    found = self.listing()
                    self.assertEqual(found["access"], "gated")
                    self.assertEqual(found["tender_id"], TENDER)
                    self.assertEqual(found["files"], [])
                    self.assertIn(str(code), found["note"])
                    self.assertEqual(self.asked(), [])

    def test_any_other_error_is_raised(self):
        self.tender(self.folder(1, "Udbud", [row(101, "Plan.pdf")]))
        for kind in ("tender", "configuration", "documents"):
            for error in (refusal(500), refusal(429), OSError("connection reset"),
                          RuntimeError("down")):
                with self.subTest(kind=kind, error=error):
                    self.fail = {kind: error}
                    with self.assertRaises(type(error)):
                        self.listing()

    def test_through_the_package_the_host_failed(self):
        self.tender(self.folder(1, "Udbud", [row(101, "Plan.pdf")]))
        for error in (refusal(500), OSError("connection reset")):
            with self.subTest(error=error):
                self.fail = {"tender": error}
                found = docsource.listing([link()])
                self.assertEqual(found["access"], "unknown")
                self.assertIs(found["failed"], True)
                self.assertEqual(found["files"], [])
                self.assertEqual(found["host"], MY)
                self.assertEqual(found["platform"], "ibinder")
                self.assertTrue(found["note"])

    def test_through_the_package_a_refusal_is_not_a_failure(self):
        self.fail = {"tender": refusal(403)}
        found = docsource.listing([link()])
        self.assertEqual(found["access"], "gated")
        self.assertFalse(found.get("failed"))

    def test_a_link_that_is_not_public_is_gated_and_no_folder_is_asked_for(self):
        self.tender(self.folder(1, "Udbud", [row(101, "Plan.pdf")]))
        for change in ({"publicLinkEnabled": False}, {"publicLinkEnabled": None}, {}):
            with self.subTest(change=change):
                del self.calls[:]
                self.config.pop("publicLinkEnabled", None)
                self.config.update(change)
                found = self.listing()
                self.assertEqual(found["access"], "gated")
                self.assertEqual(found["tender_id"], TENDER)
                self.assertEqual(found["files"], [])
                self.assertEqual(self.asked(), [])


class Folders(Host):

    def test_nested_folders_to_any_depth(self):
        deep = self.folder(4, "Snit", [row(104, "d.pdf")], type="Drawing")
        third = self.folder(3, "Plan", [row(103, "c.pdf")], subTabs=[deep])
        second = self.folder(2, "Tegninger", [row(102, "b.pdf")], subTabs=[third])
        self.tender(self.folder(1, "Udbud", [row(101, "a.pdf")], subTabs=[second]))
        self.assertEqual(self.paths(self.listing()), [
            "Udbud/Tegninger/Plan/Snit/d.pdf", "Udbud/Tegninger/Plan/c.pdf",
            "Udbud/Tegninger/b.pdf", "Udbud/a.pdf"])

    def test_navigation_is_not_asked_for_and_its_sub_folders_are(self):
        inner = self.folder(3, "Indre", type="Navigation",
                            subTabs=[self.folder(4, "Bilag", [row(104, "x.pdf")])])
        outer = self.folder(2, "Ydre", type="Navigation",
                            subTabs=[inner, self.folder(5, "Tegn", [row(105, "y.pdf")],
                                                        type="Drawing")])
        self.tender(outer)
        self.assertEqual(self.paths(self.listing()), ["Ydre/Indre/Bilag/x.pdf", "Ydre/Tegn/y.pdf"])
        self.assertEqual({folder for folder, _ in self.asked()}, {guid(4), guid(5)})

    def test_espd_is_not_asked_for(self):
        self.tender(self.folder(1, "ESPD", type="Espd"),
                    self.folder(2, "Udbud", [row(102, "a.pdf")]))
        self.assertEqual(self.paths(self.listing()), ["Udbud/a.pdf"])
        self.assertEqual(self.asked(), [(guid(2), 1)])

    def test_enabled_false_is_asked_for(self):
        self.tender(self.folder(1, "Fra", [row(101, "a.pdf")], enabled=False),
                    self.folder(2, "Nav", type="Navigation", enabled=False,
                                subTabs=[self.folder(3, "Til", [row(103, "b.pdf")])]))
        self.assertEqual(self.paths(self.listing()), ["Fra/a.pdf", "Nav/Til/b.pdf"])

    def test_no_sub_folders_in_each_spelling(self):
        self.tender(self.folder(1, "A", [row(101, "a.pdf")]),
                    self.folder(2, "B", [row(102, "b.pdf")], subTabs=None),
                    self.folder(3, "C", [row(103, "c.pdf")], subTabs=[]),
                    self.folder(4, "D", type="Navigation", subTabs=None))
        self.assertEqual(self.paths(self.listing()), ["A/a.pdf", "B/b.pdf", "C/c.pdf"])


class Pages(Host):

    def test_more_than_one_page_until_the_total_is_reached(self):
        self.tender(self.folder(1, "Udbud", [row(1000 + i, "f%d.pdf" % i) for i in range(251)]))
        found = self.listing()
        self.assertEqual(len(found["files"]), 251)
        self.assertEqual({f["name"] for f in found["files"]}, {"f%d.pdf" % i for i in range(251)})
        self.assertEqual(self.asked(), [(guid(1), 1), (guid(1), 2)])

    def test_a_short_page_before_the_total_is_not_the_end(self):
        self.tender(self.folder(1, "Udbud"))
        self.pages[guid(1)] = [[row(101, "a.pdf"), row(102, "b.pdf")], [row(103, "c.pdf")]]
        self.assertEqual(self.paths(self.listing()), ["Udbud/a.pdf", "Udbud/b.pdf", "Udbud/c.pdf"])
        self.assertEqual(self.asked(), [(guid(1), 1), (guid(1), 2)])

    def test_an_empty_page_ends_it(self):
        self.tender(self.folder(1, "Udbud", [row(101, "a.pdf")]))
        self.totals[guid(1)] = 10
        self.assertEqual(self.paths(self.listing()), ["Udbud/a.pdf"])
        self.assertEqual(self.asked(), [(guid(1), 1), (guid(1), 2)])


class Rows(Host):

    def test_deleted_rows_are_skipped(self):
        self.tender(self.folder(1, "Udbud", [row(101, "a.pdf"), row(102, "b.pdf", deleted=True),
                                             row(103, "c.zip", preview=False, deleted=True)]))
        found = self.listing()
        self.assertEqual(self.paths(found), ["Udbud/a.pdf"])
        self.assertEqual(found["gated"], [])
        self.assertEqual(found["access"], "public")

    def test_no_preview_in_each_spelling_is_gated_by_path_and_counted(self):
        null, absent = row(102, "b.xml"), row(103, "c.xlsm")
        null["files"] = None
        del absent["files"]
        inner = self.folder(2, "Data", [row(101, "a.zip", preview=False), null, absent])
        self.tender(self.folder(1, "Udbud", [row(104, "d.pdf")], subTabs=[inner]))
        found = self.listing()
        self.assertEqual(self.paths(found), ["Udbud/d.pdf"])
        self.assertEqual(sorted(found["gated"]),
                         ["Udbud/Data/a.zip", "Udbud/Data/b.xml", "Udbud/Data/c.xlsm"])
        self.assertRegex(found["note"], r"\b3\b")

    def test_names(self):
        names = ("a.pdf", "b.PDF", "c.xlsx", "d.dwg")
        self.tender(self.folder(1, "Udbud", [row(101 + i, n) for i, n in enumerate(names)]))
        stored = [f["name"] for f in self.listing()["files"]]
        for name in ("a.pdf", "c.xlsx.pdf", "d.dwg.pdf"):
            self.assertIn(name, stored)
        self.assertEqual(len(stored), 4)
        # Whether `.PDF` ends in `.pdf` is left open: see QUESTIONS.md.
        self.assertEqual(len({"b.PDF", "b.PDF.pdf"} & set(stored)), 1, stored)

    def test_the_download_is_the_address_of_the_preview_call(self):
        entry = self.one_file()
        self.assertTrue(entry["id"])
        self.assertEqual(entry["folder"], "Udbud")
        self.assertEqual(entry["download"],
                         "https://my.ibinder.com/api/etendering/tenders/%s/procurementSections/%s"
                         "/documents/%s/versions/%s/preview"
                         % (TENDER, guid(1), guid(101), guid(5101)))


class Access(Host):

    def test_public_partial_gated_and_none(self):
        read, unread = row(101, "a.pdf"), row(102, "b.zip", preview=False)
        gone = row(103, "c.pdf", deleted=True)
        for rows, access, files, gated in (
                ([read], "public", 1, []),
                ([read, unread], "partial", 1, ["Udbud/b.zip"]),
                ([unread], "gated", 0, ["Udbud/b.zip"]),
                ([], "none", 0, []),
                ([gone], "none", 0, [])):
            with self.subTest(access=access, rows=len(rows)):
                self.tender(self.folder(1, "Udbud", rows))
                found = self.listing()
                self.assertEqual(found["access"], access)
                self.assertEqual(len(found["files"]), files)
                self.assertEqual(found["gated"], gated)
                self.assertEqual(found["tender_id"], TENDER)
                if gated:
                    self.assertRegex(found["note"], r"\b1\b")

    def test_no_folders_is_none(self):
        self.assertEqual(self.listing()["access"], "none")


class Download(Host):

    def refused(self, entry):
        data, reason = ibinder.download(entry)
        self.assertIsNone(data)
        self.assertTrue(reason)
        for part in (LINK, "SECRET", "VERSIONPART", "sig=", "sv="):
            self.assertNotIn(part, reason)

    def test_the_bytes_and_the_two_calls(self):
        entry = self.one_file()
        del self.calls[:]
        self.assertEqual(ibinder.download(entry), (PDF, None))
        self.assertEqual([(kind, detail) for kind, detail, _ in self.calls],
                         [("preview", (guid(1), guid(101), guid(5101))), ("store", None)])

    def test_the_preview_call_carries_the_context(self):
        self.tender(self.folder(1, "Udbud", [row(101, "a.pdf", version="AFQ"),
                                             row(102, "b.pdf", version="BID2")]))
        for entry in self.listing()["files"]:
            del self.calls[:]
            ibinder.download(entry)
            context = json.loads(self.calls[0][2]["x-ibinder-context"])
            self.assertEqual(context["domain"], "etendering")
            self.assertEqual(context["resourceid"], TENDER)
            self.assertEqual(context["subresource"], "tenderversions")
            self.assertEqual(context["subresourceid"], "AFQ" if entry["name"] == "a.pdf" else "BID2")

    def test_a_link_to_another_host_or_over_http_is_not_followed(self):
        entry = self.one_file()
        query = "?sv=VERSIONPART&sig=SECRET"
        for where in ("https://evil.test/a.pdf", "http://store.blob.core.windows.net/a.pdf",
                      "https://store.blob.core.windows.net.evil.test/a.pdf",
                      "https://storeblob.core.windows.net/a.pdf",
                      "https://blob.core.windows.net/a.pdf",
                      "https://store.blob.core.windows.net@evil.test/a.pdf",
                      "https://evil.test/store.blob.core.windows.net/a.pdf"):
            with self.subTest(where=where):
                del self.calls[:]
                self.preview = {"url": where + query}
                self.refused(entry)
                self.assertEqual(self.kinds(), ["preview"])

    def test_an_answer_that_is_not_a_pdf(self):
        entry = self.one_file()
        for body in (b"<html>sign in</html>", b"PK\x03\x04zip", b""):
            with self.subTest(body=body):
                self.stored = body
                self.refused(entry)

    def test_an_answer_with_no_url(self):
        entry = self.one_file()
        for answer in ({}, {"url": None}, {"url": ""}, None, [], b"<html>not json</html>"):
            with self.subTest(answer=answer):
                del self.calls[:]
                self.preview = answer
                self.refused(entry)
                self.assertEqual(self.kinds(), ["preview"])

    def test_an_exception_on_either_step_is_a_reason_without_the_link(self):
        entry = self.one_file()
        for kind in ("preview", "store"):
            for error in (refusal(403), refusal(500), OSError("cannot open " + LINK),
                          RuntimeError("at " + LINK.partition("?")[2]),
                          urllib.error.HTTPError(LINK, 403, "refused " + LINK, {}, io.BytesIO(b"")),
                          urllib.error.URLError("no route to " + LINK)):
                with self.subTest(kind=kind, error=error):
                    self.fail = {kind: error}
                    self.refused(entry)


class ThroughThePackage(Host):

    def test_listing_and_download_together_and_only_the_calls_of_the_list(self):
        self.tender(self.folder(1, "ESPD", type="Espd"),
                    self.folder(2, "Udbud", type="Navigation", subTabs=[
                        self.folder(3, "Bilag", [row(103, "a.pdf"), row(104, "b.xlsx"),
                                                 row(105, "c.zip", preview=False)])]))
        found = docsource.listing([link()])
        self.assertEqual(found["platform"], "ibinder")
        self.assertEqual(found["host"], MY)
        self.assertEqual(found["access"], "partial")
        self.assertEqual(self.paths(found), ["Udbud/Bilag/a.pdf", "Udbud/Bilag/b.xlsx.pdf"])
        self.assertEqual(found["gated"], ["Udbud/Bilag/c.zip"])
        self.assertNotIn("SECRET", found["note"])
        self.assertEqual(sorted(self.kinds()), ["configuration", "documents", "tender"])
        del self.calls[:]
        for entry in found["files"]:
            self.assertEqual(docsource.download(found["platform"], entry), (PDF, None))
        self.assertEqual(self.kinds(), ["preview", "store"] * 2)


if __name__ == "__main__":
    unittest.main()
