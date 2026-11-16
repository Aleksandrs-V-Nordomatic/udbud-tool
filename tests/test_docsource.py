#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where a Danish tender's documents live, and what of them is read without an account.

Every host is answered by a stand-in for `docsource.common.fetch` (or by the module's lister
itself), so nothing reaches the network. `net.open_url` is made to fail loudly in every test,
so a request that slipped past the stand-in would show up as an error rather than a call.
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import docsource
import net
from docsource import byggeweb, comdia, common, dalux, ethics, eusupply, mercell, udbuddk


def no_network(*args, **kwargs):
    raise AssertionError("a test reached the network: %r" % (args[:1],))


class Offline(unittest.TestCase):

    def setUp(self):
        patcher = mock.patch.object(net, "open_url", side_effect=no_network)
        patcher.start()
        self.addCleanup(patcher.stop)


class ModuleFor(Offline):

    def test_hosts_and_their_subdomains(self):
        cases = {
            "https://www.ethics.dk/ethics/eo#/a/publicMaterial": ethics,
            "https://ethics.dk/x": ethics,
            "https://node1.build.dalux.com/da-dk/public/tender/TID-1": dalux,
            "https://api.udbud.dk/udbud/vedhaeftning/1/01/fil/1/a.pdf": udbuddk,
            "https://www.byggeweb.dk/controller?tn=TN1": byggeweb,
            "https://eu.eu-supply.com/app/rfq/rwlentrance_s.asp?PID=1": eusupply,
            "https://permalink.mercell.com/12345.aspx": mercell,
            "https://www.comdia.com/tender/1": comdia,
            "HTTPS://WWW.ETHICS.DK/x": ethics,
        }
        for url, module in cases.items():
            self.assertIs(docsource.module_for(url), module, url)

    def test_a_lookalike_host_is_not_the_host(self):
        for url in ("https://notethics.dk/x", "https://ethics.dk.example.com/x",
                    "https://udbud.dk/x", "https://www.amgros.dk/x", "", None):
            self.assertIsNone(docsource.module_for(url), url)


class Listing(Offline):

    def test_no_urls_is_none(self):
        for urls in (None, [], ["", None]):
            found = docsource.listing(urls)
            self.assertEqual(found["access"], "none", urls)
            self.assertEqual(found["files"], [])
            self.assertIsNone(found["host"])

    def test_an_unknown_host_is_unknown_and_named(self):
        found = docsource.listing(["https://www.amgros.dk/udbud/123"])
        self.assertEqual(found["access"], "unknown")
        self.assertEqual(found["host"], "www.amgros.dk")
        self.assertIsNone(found["platform"])
        self.assertTrue(found["note"])

    def test_a_lister_that_raises_does_not_lose_the_tender(self):
        with mock.patch.object(ethics, "listing", side_effect=RuntimeError("ethics is down")):
            found = docsource.listing(["https://www.ethics.dk/ethics/eo#/x/publicMaterial"])
        self.assertEqual(found["access"], "unknown")
        self.assertIn("ethics is down", found["note"])
        self.assertIn("RuntimeError", found["note"])
        self.assertEqual(found["files"], [])
        self.assertEqual(found["gated"], [])
        self.assertEqual(found["host"], "www.ethics.dk")
        self.assertEqual(found["platform"], "ethics")

    def test_only_the_first_url_chooses_the_module(self):
        with mock.patch.object(udbuddk, "listing", return_value={"access": "none"}) as lister:
            found = docsource.listing(["", "https://api.udbud.dk/udbud/vedhaeftning/1/01/fil/1/a.pdf",
                                       "https://www.ethics.dk/x"])
        lister.assert_called_once()
        self.assertEqual(found["platform"], "api.udbud.dk")

    def test_download_to_an_unknown_platform(self):
        data, reason = docsource.download("nowhere", {"download": "https://x"})
        self.assertIsNone(data)
        self.assertIn("nowhere", reason)


class Dalux(Offline):

    URL = "https://node1.build.dalux.com/da-dk/public/tender/TID-4711"

    def test_a_command_outside_the_four_is_refused_before_any_request(self):
        with mock.patch.object(common, "fetch") as fetch:
            for command in ("AddFilesToTender", "RemoveFilesFromTender", "getfilelist", ""):
                with self.assertRaises(PermissionError):
                    dalux._call(command, {}, "TID-1")
        fetch.assert_not_called()

    def test_the_four_read_only_commands(self):
        self.assertEqual(dalux.READ_ONLY, frozenset(
            {"IsTenderPublic", "GetTenderInformation", "GetTenderShardUrl", "GetFileList"}))

    def answer(self, folder, public=True):
        sent = []

        def fetch(url, data=None, headers=None, **kwargs):
            body = json.loads(data.decode("utf-8"))
            sent.append(body["command"])
            if body["command"] == "IsTenderPublic":
                return json.dumps({"value": public}).encode()
            if body["command"] == "GetFileList":
                return json.dumps({"value": {"folder": folder}}).encode()
            raise AssertionError("unexpected command %s" % body["command"])
        return fetch, sent

    def test_files_download_from_node1_field(self):
        folder = {
            "files": [{"areaFileRevisionID": 11,
                       "properties": [{"matchName": "FileName", "value": "Udbudsbrev.pdf"}]}],
            "childrenVector": [{
                "properties": [{"matchName": "FolderName", "value": "Tegninger"}],
                "files": [{"areaFileRevisionID": 12,
                           "properties": [{"matchName": "FileName", "value": "Plan.dwg"},
                                          {"matchName": "FileSize", "value": "2 MB"}]}],
            }],
        }
        fetch, sent = self.answer(folder)
        with mock.patch.object(common, "fetch", side_effect=fetch):
            found = dalux.listing([self.URL])
        self.assertEqual(found["access"], "public")
        self.assertEqual(found["tender_id"], "TID-4711")
        self.assertEqual([f["name"] for f in found["files"]], ["Udbudsbrev.pdf", "Plan.dwg"])
        self.assertEqual(found["files"][1]["folder"], "Tegninger")
        for f in found["files"]:
            self.assertTrue(f["download"].startswith("https://node1.field.dalux.com/"), f["download"])
            self.assertNotIn("node1.build", f["download"])
        self.assertIn("/TID-4711/areafilerevision-12/", found["files"][1]["download"])
        self.assertTrue(set(sent) <= dalux.READ_ONLY, sent)

    def test_a_tender_that_is_not_public_is_gated(self):
        fetch, sent = self.answer({}, public=False)
        with mock.patch.object(common, "fetch", side_effect=fetch):
            found = dalux.listing([self.URL])
        self.assertEqual(found["access"], "gated")
        self.assertEqual(sent, ["IsTenderPublic"])

    def test_no_tid_in_the_link_asks_nothing(self):
        with mock.patch.object(common, "fetch") as fetch:
            found = dalux.listing(["https://node1.build.dalux.com/da-dk/public/"])
        self.assertEqual(found["access"], "unknown")
        fetch.assert_not_called()

    def test_the_envelope_is_json_with_a_checksummed_time(self):
        raw = dalux._envelope("GetFileList", {"tenderLinkIdentifier": "TID-1"}, "TID-1")
        body = json.loads(raw.decode("utf-8"))
        self.assertEqual(body["command"], "GetFileList")
        self.assertTrue(body["time"].endswith("Z"))


class EuSupply(Offline):

    TENDER_PAGE = (b'<html><a href="/app/rfq/publicpurchase_docs.asp?PID=460124&amp;LID=99">'
                   b'Documents</a></html>')
    DOCS_PAGE = (b"<html><script>var sDoc_111 = 'Udbudsbetingelser.pdf';</script>"
                 b"<a href=\"javascript:DownloadPublicDocument('111','sDoc_1','99')\">x</a>"
                 b"<b>Available after expression of interest</b><table>"
                 b'<tr><td valign="top" class="tblcell" colspan="2">Kravspecifikation.docx</td></tr>'
                 b'<tr><td valign="top" class="tblcell" colspan="2">Close window</td></tr>'
                 b"</table></html>")

    def test_names_only_and_never_the_docmgmt_path(self):
        pages = [self.TENDER_PAGE, self.DOCS_PAGE]
        with mock.patch.object(common, "fetch", side_effect=pages) as fetch:
            found = eusupply.listing(["https://eu.eu-supply.com/app/rfq/rwlentrance_s.asp?PID=460124&TID=1&B="])
        self.assertEqual(found["access"], "gated")
        self.assertEqual(found["files"], [])
        self.assertEqual(found["gated"], ["Udbudsbetingelser.pdf", "Kravspecifikation.docx"])
        self.assertEqual(found["public_names"], ["Udbudsbetingelser.pdf"])
        self.assertEqual(fetch.call_count, 2)
        for c in fetch.call_args_list:
            self.assertNotIn("/app/docmgmt", c.args[0])

    def test_download_never_requests(self):
        with mock.patch.object(common, "fetch") as fetch:
            data, reason = eusupply.download({"id": "1", "name": "a.pdf",
                                              "download": "https://eu.eu-supply.com/app/docmgmt/x"})
        self.assertIsNone(data)
        self.assertIn("robots", reason)
        fetch.assert_not_called()

    def test_a_listing_through_the_package_downloads_nothing(self):
        pages = [self.TENDER_PAGE, self.DOCS_PAGE]
        with mock.patch.object(common, "fetch", side_effect=pages):
            found = docsource.listing(["https://eu.eu-supply.com/app/rfq/rwlentrance_s.asp?PID=460124"])
        self.assertEqual(found["platform"], "eu-supply")
        self.assertEqual(found["files"], [])


class Comdia(Offline):

    def test_no_request_and_gated(self):
        with mock.patch.object(common, "fetch", side_effect=no_network) as fetch:
            found = docsource.listing(["https://www.comdia.com/tender/123"])
            data, reason = comdia.download({"download": "https://www.comdia.com/x"})
        fetch.assert_not_called()
        self.assertEqual(found["access"], "gated")
        self.assertEqual(found["files"], [])
        self.assertEqual(found["gated"], [])
        self.assertIsNone(data)
        self.assertTrue(reason)


class Mercell(Offline):

    def test_names_only(self):
        page = (b'<td id="rpFiles_ctl00_tdDownload">  Udbudsbetingelser.pdf </td>'
                b'<td id="rpFiles_ctl01_tdDownload"><a>Bilag&nbsp;1 &amp; 2.xlsx</a></td>')
        with mock.patch.object(common, "fetch", return_value=page):
            found = mercell.listing(["https://permalink.mercell.com/1.aspx"])
        self.assertEqual(found["access"], "gated")
        self.assertEqual(found["files"], [])
        self.assertEqual(found["gated"], ["Udbudsbetingelser.pdf", "Bilag 1 & 2.xlsx"])
        self.assertEqual(mercell.download({})[0], None)


class UdbudDk(Offline):

    URL = "https://api.udbud.dk/udbud/vedhaeftning/abc/01/fil/def/Tilbudsliste Bøgevej.pdf"

    def test_the_path_is_quoted_and_the_name_kept(self):
        found = udbuddk.listing([self.URL])
        self.assertEqual(found["access"], "public")
        entry = found["files"][0]
        self.assertEqual(entry["name"], "Tilbudsliste Bøgevej.pdf")
        self.assertEqual(entry["download"],
                         "https://api.udbud.dk/udbud/vedhaeftning/abc/01/fil/def/Tilbudsliste%20B%C3%B8gevej.pdf")

    def test_an_already_quoted_path_is_not_quoted_twice(self):
        quoted = "https://api.udbud.dk/udbud/vedhaeftning/abc/01/fil/def/B%C3%B8gevej.pdf"
        entry = udbuddk.listing([quoted])["files"][0]
        self.assertEqual(entry["download"], quoted)
        self.assertEqual(entry["name"], "Bøgevej.pdf")

    def test_links_that_are_not_attachments_are_skipped(self):
        found = udbuddk.listing(["https://api.udbud.dk/udbud/other/1"])
        self.assertEqual(found["access"], "none")
        self.assertEqual(found["files"], [])

    def test_the_download_asks_for_the_quoted_url(self):
        entry = udbuddk.listing([self.URL])["files"][0]
        with mock.patch.object(common, "fetch", return_value=b"%PDF-1.7 ...") as fetch:
            data, reason = udbuddk.download(entry)
        self.assertEqual(data, b"%PDF-1.7 ...")
        self.assertIsNone(reason)
        self.assertEqual(fetch.call_args.args[0], entry["download"])


class Ethics(Offline):

    URL = "https://www.ethics.dk/ethics/eo#/2F1E0B9C-1111-2222-3333-444455556666/publicMaterial"

    def listing(self, docs):
        body = json.dumps({"tenderDocs": docs}).encode()
        with mock.patch.object(common, "fetch", return_value=body) as fetch:
            found = ethics.listing([self.URL])
        return found, fetch

    def test_records_without_a_file_are_skipped_and_access_required_named(self):
        found, fetch = self.listing([
            {"_id": "a1", "filename": "Udbudsbetingelser.pdf", "length": 1200, "type": "pdf"},
            {"_id": "a2", "filename": None, "type": "espd"},
            {"_id": "a3"},
            {"_id": "a4", "filename": "Tilbudsliste.xlsx", "accessRequired": True},
        ])
        self.assertEqual(found["access"], "partial")
        self.assertEqual([f["name"] for f in found["files"]], ["Udbudsbetingelser.pdf"])
        self.assertEqual(found["gated"], ["Tilbudsliste.xlsx"])
        self.assertEqual(found["tender_id"], "2f1e0b9c-1111-2222-3333-444455556666")
        self.assertIn("/publicTenderDocs/2f1e0b9c-1111-2222-3333-444455556666", fetch.call_args.args[0])
        self.assertTrue(found["files"][0]["download"].endswith(
            "/2f1e0b9c-1111-2222-3333-444455556666/a1/download"))

    def test_access_from_what_is_listed(self):
        self.assertEqual(self.listing([{"_id": "a", "filename": "x.pdf"}])[0]["access"], "public")
        self.assertEqual(self.listing([{"_id": "a", "filename": "x.pdf", "accessRequired": True}])[0]["access"],
                         "gated")
        self.assertEqual(self.listing([{"_id": "a"}])[0]["access"], "none")
        self.assertEqual(self.listing([])[0]["access"], "none")

    def test_no_tender_id_in_the_link_asks_nothing(self):
        with mock.patch.object(common, "fetch") as fetch:
            found = ethics.listing(["https://www.ethics.dk/ethics/eo"])
        self.assertEqual(found["access"], "unknown")
        fetch.assert_not_called()


class Byggeweb(Offline):

    def test_two_steps(self):
        listing_page = (b'<table class="filename" id="901"><tr><td><a href="?fileid=ab12">x</a></td>'
                        b'<td class="fname"> Tegning &amp; plan.pdf </td></tr></table>')
        shim = b"<html><a href='/download-forced/xyz/Tegning.pdf'>here</a></html>"
        with mock.patch.object(common, "fetch", return_value=listing_page):
            found = byggeweb.listing(["https://www.byggeweb.dk/controller?cmd=x&tn=TN123"])
        self.assertEqual(found["access"], "public")
        entry = found["files"][0]
        self.assertEqual(entry["name"], "Tegning & plan.pdf")
        self.assertIn("fileid=ab12", entry["download"])
        with mock.patch.object(common, "fetch", side_effect=[shim, b"%PDF-1.4"]) as fetch:
            data, reason = byggeweb.download(dict(entry, name="Tegning.pdf"))
        self.assertEqual(data, b"%PDF-1.4")
        self.assertEqual(fetch.call_args_list[1].args[0], "https://www.byggeweb.dk/download-forced/xyz/Tegning.pdf")


class LooksLikeHtml(unittest.TestCase):

    def test_an_html_body_is_not_the_file(self):
        for body in (b"<!DOCTYPE html><html>", b"  \r\n<html lang='da'>", b"<!doctype HTML>"):
            self.assertTrue(common.looks_like_html(body, "Udbudsbetingelser.pdf"), body)

    def test_a_file_named_html_may_be_html(self):
        for name in ("bilag.html", "BILAG.HTM", "x.xhtml"):
            self.assertFalse(common.looks_like_html(b"<!DOCTYPE html><html>", name), name)

    def test_a_real_file_is_a_file(self):
        self.assertFalse(common.looks_like_html(b"%PDF-1.7\n...", "a.pdf"))
        self.assertFalse(common.looks_like_html(b"PK\x03\x04", "a.zip"))

    def test_plain_download_refuses_html_under_a_200(self):
        with mock.patch.object(common, "fetch", return_value=b"<!DOCTYPE html><html>login</html>"):
            data, reason = common.plain_download({"download": "https://x", "name": "a.pdf"})
        self.assertIsNone(data)
        self.assertIn("HTML", reason)

    def test_plain_download_refuses_an_empty_body(self):
        with mock.patch.object(common, "fetch", return_value=b""):
            data, reason = common.plain_download({"download": "https://x", "name": "a.pdf"})
        self.assertIsNone(data)
        self.assertTrue(reason)

    def test_plain_download_turns_a_failure_into_a_reason(self):
        with mock.patch.object(common, "fetch", side_effect=net.Unreachable("gave up")):
            data, reason = common.plain_download({"download": "https://x", "name": "a.pdf"})
        self.assertIsNone(data)
        self.assertIn("gave up", reason)


if __name__ == "__main__":
    unittest.main()
