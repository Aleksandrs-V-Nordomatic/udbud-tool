#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where a Danish tender's documents live, and what of them is read without an account.

Every host is answered by a stand-in for `docsource.common.fetch` (or by the module's lister
itself), so nothing reaches the network. `net.open_url` is made to fail loudly in every test,
so a request that slipped past the stand-in would show up as an error rather than a call.
Comdia is answered by a stand-in for its one network seam, `comdia._send`.
"""

import contextlib
import io
import json
import os
import struct
import sys
import unittest
import zipfile
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


# --- Comdia, under an account -------------------------------------------------------------

USER = "tenders@nordomatic.example"
PASSWORD = "S3cret-Pa55word"

P = "ctl00$ctl00$cphMain$cphMain$"
ACCESS_NAME = P + "lbRegisterTender"
GO_NAME = P + "lbGoToTender"
SHOW_INTEREST = P + "lbShowInterest"
SUBSCRIBE = P + "lbSubscribe"
REFRESH = P + "lbRefresh"
DOWNLOAD_ALL2 = P + "lbDownloadAll2"
SIGN_IN_NAME = "ctl00$cphInnerContent$lbLogin"

TENDER_URL = "https://www.comdia.com/Site/public/tenderinformationshow.aspx?Id=144703"
VENDOR_URL = "https://www.comdia.com/Site/vendor/user/tenderentity/show.aspx?Id=144703"
HOME_URL = "https://www.comdia.com/Site/default.aspx"
LOGIN_URL = "https://www.comdia.com/login.aspx"


def per_file(n):
    return P + "rpStepsTabContent$ctl00$rpTenderList$ctl00$gvDocument$ctl%02d$lbDownload" % n


def link(name, quote="&#39;"):
    return '<a href="javascript:__doPostBack(%s%s%s,%s%s)">x</a>' % (quote, name, quote, quote, quote)


def hidden(name, value):
    return '<input type="hidden" name="%s" id="%s" value="%s" />' % (name, name, value)


def page(controls=(), signed=True, viewstate="vs", extra=""):
    parts = ["<html><body><form method=\"post\">",
             hidden("__VIEWSTATE", viewstate), hidden("__EVENTVALIDATION", "ev-" + viewstate)]
    if signed:
        parts.append('<a href="/logout.ashx">Log ud</a>')
    else:
        parts.append('<input name="ctl00$cphInnerContent$txtEmail" type="text" />'
                     '<input name="ctl00$cphInnerContent$txtPassword" type="password" />')
    parts.extend(link(c) for c in controls)
    parts.append(extra)
    parts.append("</form></body></html>")
    return "".join(parts)


LOGIN_PAGE = page([SIGN_IN_NAME], signed=False, viewstate="login")
HOME_PAGE = page(viewstate="home")
TENDER_NO_ACCESS = page([ACCESS_NAME, SHOW_INTEREST, SUBSCRIBE], viewstate="tender")
TENDER_WITH_ACCESS = page([GO_NAME, SHOW_INTEREST, SUBSCRIBE, REFRESH], viewstate="tender2")
TENDER_NOTHING = page([SHOW_INTEREST, SUBSCRIBE], viewstate="tender3")
ENDED_PAGE = page(signed=False, viewstate="ended")
VENDOR_PAGE_HTML = page([DOWNLOAD_ALL2, per_file(2), per_file(3)], viewstate="vendor")


def zip_bytes(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for name, data in members:
            z.writestr(name, data)
    return buf.getvalue()


def renamed(raw, placeholder, real):
    """The raw zip with a member's name bytes swapped (same length), no UTF-8 flag added."""
    assert len(placeholder) == len(real)
    return raw.replace(placeholder, real)


def claiming(raw, size):
    """The raw zip with every member claiming `size` bytes uncompressed."""
    b = bytearray(raw)
    for signature, offset in ((b"PK\x03\x04", 22), (b"PK\x01\x02", 24)):
        at = b.find(signature)
        while at != -1:
            struct.pack_into("<I", b, at + offset, size)
            at = b.find(signature, at + 4)
    return bytes(b)


PDF = b"%PDF-1.7 Udbudsbetingelser"
DWG = b"AC1032 plan"
SAMPLE_ZIP = zip_bytes([
    ("144703/Udbudsmateriale/", b""),
    ("144703/Udbudsmateriale/Udbudsbetingelser.pdf", PDF),
    ("144703/Tegninger/Plan.dwg", DWG),
])


def html(body, url):
    return (body.encode("utf-8"), url, "text/html; charset=utf-8")


class FakeComdia:
    """Comdia as `_send` sees it: a login page, a tender page, Access, Go to tender, Download all."""

    def __init__(self, tender_pages=(TENDER_NO_ACCESS,), access=None, go=None,
                 archive=SAMPLE_ZIP, login_page=LOGIN_PAGE, login_answer=HOME_PAGE,
                 vendor_page=VENDOR_PAGE_HTML, fail=None):
        self.tender_pages = list(tender_pages)
        self.vendor = html(vendor_page, VENDOR_URL)
        self.access = access if access is not None else html(TENDER_WITH_ACCESS, TENDER_URL)
        self.go = go if go is not None else self.vendor
        self.archive = archive
        self.login_page = login_page
        self.login_answer = login_answer
        self.fail = fail or {}
        self.calls = []

    @property
    def targets(self):
        return [d.get("__EVENTTARGET") for u, d in self.calls
                if d is not None and not u.lower().startswith(LOGIN_URL)]

    @property
    def login_posts(self):
        return [d for u, d in self.calls if d is not None and u.lower().startswith(LOGIN_URL)]

    @property
    def gets(self):
        return [u for u, d in self.calls if d is None and not u.lower().startswith(LOGIN_URL)]

    def __call__(self, opener, url, data=None, *rest, **kwargs):
        data = dict(data) if data is not None else None
        self.calls.append((url, data))
        login = url.lower().startswith(LOGIN_URL)
        step = ("login-get" if login and data is None else "login-post" if login
                else "get" if data is None else data.get("__EVENTTARGET"))
        if step in self.fail:
            raise self.fail[step]
        if step == "login-get":
            return html(self.login_page, LOGIN_URL)
        if step == "login-post":
            return html(self.login_answer, HOME_URL)
        if step == "get":
            body = self.tender_pages.pop(0) if len(self.tender_pages) > 1 else self.tender_pages[0]
            return html(body, url)
        if step == ACCESS_NAME:
            return self.access
        if step == GO_NAME:
            return self.go
        if step and comdia.DOWNLOAD_ALL.fullmatch(step):
            return (self.archive, VENDOR_URL, "application/octet-stream")
        raise AssertionError("pressed a control the module must not press: %r" % step)


def sent_data(call):
    return call.args[2] if len(call.args) > 2 else call.kwargs.get("data")


class ComdiaCase(Offline):

    def setUp(self):
        super().setUp()
        self.reset_state()
        self.addCleanup(self.reset_state)
        env = mock.patch.dict(os.environ, {"COMDIA_USER": USER, "COMDIA_PASSWORD": PASSWORD})
        env.start()
        self.addCleanup(env.stop)
        sleeper = mock.patch("time.sleep")
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)
        sender = mock.patch.object(comdia, "_send", side_effect=no_network)
        self.send = sender.start()
        self.addCleanup(sender.stop)

    @staticmethod
    def reset_state():
        comdia._SESSION.clear()
        comdia._SESSION.update({"opener": None, "failed": None})
        comdia._ARCHIVE.clear()
        comdia._ARCHIVE.update({"key": None, "zip": None})

    def serve(self, fake):
        self.send.side_effect = fake
        return fake

    def no_account(self):
        os.environ.pop("COMDIA_USER", None)
        os.environ.pop("COMDIA_PASSWORD", None)


class Comdia(ComdiaCase):
    """The module's constants and its page readers."""

    def test_the_constants(self):
        self.assertEqual(comdia.NAME, "comdia")
        self.assertEqual(comdia.BASE, "https://www.comdia.com")
        self.assertEqual(comdia.LOGIN, "https://www.comdia.com/login.aspx")
        self.assertEqual(comdia.VENDOR_PAGE, "/site/vendor/user/tenderentity/show.aspx")
        self.assertEqual(comdia.SIGN_IN, SIGN_IN_NAME)
        self.assertEqual(comdia.ACCESS, ACCESS_NAME)
        self.assertEqual(comdia.GO_TO_TENDER, GO_NAME)
        self.assertEqual(comdia.PRESSED, frozenset({SIGN_IN_NAME, ACCESS_NAME, GO_NAME}))
        self.assertEqual(comdia.PAUSE, 2.0)
        self.assertEqual(comdia.ARCHIVE_TIMEOUT, 600)
        self.assertEqual(comdia.MAX_UNPACKED, 1024 ** 3)
        self.assertTrue(issubclass(comdia.SignInFailed, Exception))

    def test_download_all_and_per_file_patterns(self):
        for name in (P + "lbDownloadAll", DOWNLOAD_ALL2, P + "lbDownloadAll17"):
            self.assertTrue(comdia.DOWNLOAD_ALL.fullmatch(name), name)
        for name in (P + "lbDownloadAllx", "x" + P + "lbDownloadAll", P + "lbDownload",
                     per_file(2), SHOW_INTEREST):
            self.assertFalse(comdia.DOWNLOAD_ALL.fullmatch(name), name)
        self.assertTrue(comdia.PER_FILE.search(per_file(2)))
        self.assertTrue(comdia.PER_FILE.search(per_file(14)))
        self.assertFalse(comdia.PER_FILE.search(DOWNLOAD_ALL2))
        self.assertFalse(comdia.PER_FILE.search(SHOW_INTEREST))

    def test_hidden_fields(self):
        text = (hidden("__VIEWSTATE", "dDwtMTA4=") + hidden("__EVENTVALIDATION", "abc")
                + '<input type="hidden" name="a&amp;b" id="x" value="1" />'
                + '<input type="hidden" name="__LASTFOCUS" id="__LASTFOCUS" />'
                + '<input type="text" name="ctl00$cphInnerContent$txtEmail" value="typed" />')
        fields = comdia.hidden_fields(text)
        self.assertEqual(fields, {"__VIEWSTATE": "dDwtMTA4=", "__EVENTVALIDATION": "abc",
                                  "a&b": "1", "__LASTFOCUS": ""})

    def test_controls_in_either_quoting(self):
        text = (link(ACCESS_NAME) + link(SHOW_INTEREST, quote="'")
                + link("ctl00&#36;ctl00&#36;cphMain&#36;cphMain&#36;lbRefresh"))
        found = comdia.controls(text)
        self.assertIn(ACCESS_NAME, found)
        self.assertIn(SHOW_INTEREST, found)
        self.assertIn(REFRESH, found)
        self.assertEqual(comdia.controls("<html>no postbacks</html>"), [])

    def test_signed_in(self):
        self.assertTrue(comdia.signed_in(HOME_PAGE))
        self.assertTrue(comdia.signed_in(TENDER_NO_ACCESS))
        self.assertFalse(comdia.signed_in(LOGIN_PAGE))
        self.assertFalse(comdia.signed_in("<html>nothing</html>"))
        self.assertFalse(comdia.signed_in('<a href="/logout.ashx">x</a><input name="txtPassword">'))

    def test_tender_id(self):
        self.assertEqual(comdia.tender_id(TENDER_URL), "144703")
        self.assertEqual(comdia.tender_id("https://www.comdia.com/x.aspx?foo=1&id=42"), "42")
        self.assertEqual(comdia.tender_id("https://www.comdia.com/x.aspx?ID=7&b=2"), "7")
        self.assertIsNone(comdia.tender_id("https://www.comdia.com/tender/1"))
        self.assertIsNone(comdia.tender_id("https://www.comdia.com/x.aspx?foo=1"))


class ComdiaPostback(ComdiaCase):

    def test_controls_outside_the_four_are_refused_before_any_request(self):
        self.send.side_effect = None
        self.send.return_value = html(HOME_PAGE, TENDER_URL)
        for target in (SHOW_INTEREST, SUBSCRIBE, REFRESH, per_file(2), P + "lbDownloadAllx", ""):
            with self.assertRaises(PermissionError, msg=target):
                comdia._postback(object(), TENDER_URL, TENDER_NO_ACCESS, target)
        self.send.assert_not_called()

    def test_a_pressed_control_sleeps_then_posts_the_hidden_fields(self):
        order = []
        self.sleep.side_effect = lambda seconds: order.append(("sleep", seconds))

        def send(*args, **kwargs):
            order.append(("send",))
            return html(TENDER_WITH_ACCESS, TENDER_URL)
        self.send.side_effect = send
        opener = object()
        for target in (ACCESS_NAME, GO_NAME, SIGN_IN_NAME, DOWNLOAD_ALL2, P + "lbDownloadAll"):
            order.clear()
            self.send.reset_mock()
            comdia._postback(opener, TENDER_URL, TENDER_NO_ACCESS, target)
            self.assertEqual(order, [("sleep", 2.0), ("send",)], target)
            call = self.send.call_args
            self.assertIs(call.args[0], opener)
            self.assertEqual(call.args[1], TENDER_URL)
            self.assertEqual(sent_data(call), {
                "__VIEWSTATE": "tender", "__EVENTVALIDATION": "ev-tender",
                "__EVENTTARGET": target, "__EVENTARGUMENT": ""})


class ComdiaSignIn(ComdiaCase):

    def test_get_then_post_the_account_with_the_hidden_fields(self):
        fake = self.serve(FakeComdia())
        opener = comdia.sign_in(USER, PASSWORD)
        self.assertIsNotNone(opener)
        self.assertEqual(fake.calls[0], (LOGIN_URL, None))
        self.assertEqual(len(fake.calls), 2)
        url, data = fake.calls[1]
        self.assertEqual(url, LOGIN_URL)
        self.assertEqual(data["__EVENTTARGET"], SIGN_IN_NAME)
        self.assertEqual(data["ctl00$cphInnerContent$txtEmail"], USER)
        self.assertEqual(data["ctl00$cphInnerContent$txtPassword"], PASSWORD)
        self.assertEqual(data["__VIEWSTATE"], "login")
        self.assertEqual(data["__EVENTVALIDATION"], "ev-login")

    def test_a_refused_account(self):
        self.serve(FakeComdia(login_answer=LOGIN_PAGE))
        with self.assertRaises(comdia.SignInFailed):
            comdia.sign_in(USER, PASSWORD)

    def test_a_captcha_or_challenge(self):
        for marks in ('<div class="cf-turnstile" data-sitekey="k"></div>',
                      '<script src="/cdn-cgi/challenge-platform/h/b/orchestrate"></script>',
                      '<div class="g-recaptcha">captcha</div>',
                      '<form id="cf-chl-form"></form>'):
            self.serve(FakeComdia(login_page=page([SIGN_IN_NAME], signed=False, extra=marks)))
            with self.assertRaises(comdia.SignInFailed, msg=marks):
                comdia.sign_in(USER, PASSWORD)
            self.serve(FakeComdia(login_answer=page(extra=marks)))
            with self.assertRaises(comdia.SignInFailed, msg=marks):
                comdia.sign_in(USER, PASSWORD)

    def test_a_request_that_raises(self):
        for step in ("login-get", "login-post"):
            self.serve(FakeComdia(fail={step: OSError("connection reset")}))
            with self.assertRaises(comdia.SignInFailed, msg=step):
                comdia.sign_in(USER, PASSWORD)


class ComdiaSession(ComdiaCase):

    def test_no_account_raises_and_asks_nothing(self):
        for user, password in ((None, None), (USER, None), (None, PASSWORD),
                               ("   ", PASSWORD), (USER, "")):
            self.reset_state()
            self.no_account()
            if user is not None:
                os.environ["COMDIA_USER"] = user
            if password is not None:
                os.environ["COMDIA_PASSWORD"] = password
            with mock.patch.object(comdia, "sign_in") as sign_in:
                with self.assertRaises(comdia.SignInFailed, msg=(user, password)):
                    comdia.session()
            sign_in.assert_not_called()
        self.send.assert_not_called()

    def test_signs_in_once_and_reuses_the_opener(self):
        opener = object()
        with mock.patch.object(comdia, "sign_in", autospec=True, return_value=opener) as sign_in:
            self.assertIs(comdia.session(), opener)
            self.assertIs(comdia.session(), opener)
        sign_in.assert_called_once_with(USER, PASSWORD)

    def test_fresh_signs_in_again(self):
        first, second = object(), object()
        with mock.patch.object(comdia, "sign_in", side_effect=[first, second]) as sign_in:
            self.assertIs(comdia.session(), first)
            self.assertIs(comdia.session(fresh=True), second)
        self.assertEqual(sign_in.call_count, 2)

    def test_a_refused_account_is_not_asked_again(self):
        with mock.patch.object(comdia, "sign_in",
                               side_effect=comdia.SignInFailed("refused")) as sign_in:
            for _ in range(3):
                with self.assertRaises(comdia.SignInFailed):
                    comdia.session()
        sign_in.assert_called_once()
        self.assertTrue(comdia._SESSION["failed"])


class ComdiaOpenTender(ComdiaCase):

    def test_access_then_go_to_tender(self):
        fake = self.serve(FakeComdia())
        text, vendor_url, reason = comdia.open_tender(object(), TENDER_URL)
        self.assertIsNone(reason)
        self.assertEqual(vendor_url, VENDOR_URL)
        self.assertIn(DOWNLOAD_ALL2, text)
        self.assertEqual(fake.gets, [TENDER_URL])
        self.assertEqual(fake.targets, [ACCESS_NAME, GO_NAME])

    def test_access_that_lands_on_the_vendor_page(self):
        fake = FakeComdia()
        fake.access = fake.vendor
        self.serve(fake)
        text, vendor_url, reason = comdia.open_tender(object(), TENDER_URL)
        self.assertIsNone(reason)
        self.assertEqual(vendor_url, VENDOR_URL)
        self.assertEqual(fake.targets, [ACCESS_NAME])

    def test_a_tender_already_accessed_is_not_accessed_again(self):
        fake = self.serve(FakeComdia(tender_pages=[TENDER_WITH_ACCESS]))
        text, vendor_url, reason = comdia.open_tender(object(), TENDER_URL)
        self.assertIsNone(reason)
        self.assertEqual(vendor_url, VENDOR_URL)
        self.assertEqual(fake.targets, [GO_NAME])

    def test_go_to_tender_that_leads_elsewhere(self):
        fake = self.serve(FakeComdia(tender_pages=[TENDER_WITH_ACCESS],
                                     go=html(HOME_PAGE, HOME_URL)))
        text, vendor_url, reason = comdia.open_tender(object(), TENDER_URL)
        self.assertIsNone(text)
        self.assertIsNone(vendor_url)
        self.assertTrue(reason)
        self.assertEqual(fake.targets, [GO_NAME])

    def test_access_pressed_and_the_tender_did_not_open(self):
        fake = self.serve(FakeComdia(access=html(TENDER_NOTHING, TENDER_URL)))
        text, vendor_url, reason = comdia.open_tender(object(), TENDER_URL)
        self.assertIsNone(text)
        self.assertIsNone(vendor_url)
        self.assertTrue(reason)
        self.assertEqual(fake.targets, [ACCESS_NAME])

    def test_no_access_offered_names_what_is_offered_and_presses_nothing(self):
        fake = self.serve(FakeComdia(tender_pages=[TENDER_NOTHING]))
        text, vendor_url, reason = comdia.open_tender(object(), TENDER_URL)
        self.assertIsNone(text)
        self.assertIsNone(vendor_url)
        self.assertIn("lbShowInterest", reason)
        self.assertIn("lbSubscribe", reason)
        self.assertEqual(fake.targets, [])

    def test_a_session_that_ended(self):
        fake = self.serve(FakeComdia(tender_pages=[ENDED_PAGE]))
        with self.assertRaises(comdia.SignInFailed):
            comdia.open_tender(object(), TENDER_URL)
        self.assertEqual(fake.targets, [])


class ComdiaArchiveFiles(ComdiaCase):

    SOURCE = VENDOR_URL

    def files(self, raw):
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            return comdia.archive_files(z, self.SOURCE), z.namelist()

    def test_one_file_per_member_under_its_group(self):
        raw = zip_bytes([
            ("144703/Udbudsmateriale/", b""),
            ("144703/Udbudsmateriale/Udbudsbetingelser.pdf", PDF),
            ("144703/Tegninger/Plan.dwg", DWG),
            ("144703/Tegninger/Snit/S1.pdf", b"%PDF s1"),
            ("144703/readme.txt", b"hello"),
        ])
        files, _ = self.files(raw)
        self.assertEqual([f["member"] for f in files], [
            "144703/Tegninger/Plan.dwg", "144703/Tegninger/Snit/S1.pdf",
            "144703/Udbudsmateriale/Udbudsbetingelser.pdf", "144703/readme.txt"])
        self.assertEqual([f["name"] for f in files],
                         ["Plan.dwg", "S1.pdf", "Udbudsbetingelser.pdf", "readme.txt"])
        self.assertEqual([f["folder"] for f in files],
                         ["Tegninger", "Tegninger/Snit", "Udbudsmateriale", ""])
        self.assertEqual([f["bytes"] for f in files], [len(DWG), 7, len(PDF), 5])
        for f in files:
            self.assertEqual(f["download"], self.SOURCE)
            self.assertTrue(f["id"].startswith("zip:"), f["id"])
        self.assertEqual(len({f["id"] for f in files}), len(files))

    def test_no_common_top_folder_keeps_the_whole_path(self):
        files, _ = self.files(zip_bytes([("a/x.pdf", b"1"), ("b/c/y.pdf", b"2"), ("z.pdf", b"3")]))
        self.assertEqual([f["name"] for f in files], ["x.pdf", "y.pdf", "z.pdf"])
        self.assertEqual([f["folder"] for f in files], ["a", "b/c", ""])

    def test_backslashes_are_folders(self):
        raw = renamed(zip_bytes([("144703|Udbud|a.pdf", b"1")]),
                      b"144703|Udbud|a.pdf", b"144703\\Udbud\\a.pdf")
        files, names = self.files(raw)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["name"], "a.pdf")
        self.assertEqual(files[0]["folder"], "Udbud")
        self.assertEqual(files[0]["member"], names[0])

    def test_names_without_the_utf8_flag(self):
        cases = (
            (b"144703/BXXgevej.pdf", "144703/Bøgevej.pdf".encode("utf-8")),   # utf-8 bytes
            (b"144703/BXgevej.pdf", "144703/Bøgevej.pdf".encode("cp1252")),   # cp1252 bytes
        )
        for placeholder, real in cases:
            raw = renamed(zip_bytes([(placeholder.decode("ascii"), b"1")]), placeholder, real)
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                self.assertFalse(z.infolist()[0].flag_bits & 0x800)
                files = comdia.archive_files(z, self.SOURCE)
                self.assertEqual(files[0]["name"], "Bøgevej.pdf", real)
                self.assertEqual(files[0]["folder"], "")
                self.assertEqual(z.read(files[0]["member"]), b"1")

    def test_names_with_the_utf8_flag_are_kept(self):
        files, _ = self.files(zip_bytes([("144703/Tilbud/Bøgevej ø.pdf", b"1")]))
        self.assertEqual(files[0]["name"], "Bøgevej ø.pdf")
        self.assertEqual(files[0]["folder"], "Tilbud")


class ComdiaListing(ComdiaCase):

    def listing(self, fake=None, url=TENDER_URL):
        if fake is not None:
            self.serve(fake)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            found = comdia.listing([url])
        self.assertEqual(out.getvalue() + err.getvalue(), "", "the module prints nothing")
        return found

    def test_no_id_is_unknown_and_asks_nothing(self):
        comdia._ARCHIVE.update({"key": "old", "zip": object()})
        found = self.listing(url="https://www.comdia.com/tender/123")
        self.assertEqual(found["access"], "unknown")
        self.send.assert_not_called()
        self.assertIsNone(comdia._ARCHIVE["key"])

    def test_no_account_is_gated_with_a_note_and_asks_nothing(self):
        self.no_account()
        found = self.listing()
        self.assertEqual(found["access"], "gated")
        self.assertTrue(found["note"])
        self.send.assert_not_called()

    def test_every_member_is_a_file(self):
        fake = FakeComdia()
        found = self.listing(fake)
        self.assertEqual(found["access"], "public")
        self.assertEqual(found["tender_id"], "144703")
        self.assertEqual(found["note"], "")
        self.assertEqual([f["name"] for f in found["files"]], ["Plan.dwg", "Udbudsbetingelser.pdf"])
        self.assertEqual([f["folder"] for f in found["files"]], ["Tegninger", "Udbudsmateriale"])
        for f in found["files"]:
            self.assertEqual(f["download"], VENDOR_URL)
        self.assertEqual(comdia._ARCHIVE["key"], VENDOR_URL)
        self.assertEqual(fake.gets, [TENDER_URL])
        self.assertEqual(fake.targets, [ACCESS_NAME, GO_NAME, DOWNLOAD_ALL2])
        self.assertEqual(len(fake.login_posts), 1)

    def test_show_interest_and_subscribe_are_never_pressed(self):
        fake = FakeComdia(tender_pages=[TENDER_WITH_ACCESS])
        self.listing(fake)
        for target in fake.targets:
            self.assertTrue(target in comdia.PRESSED or comdia.DOWNLOAD_ALL.fullmatch(target), target)
        self.assertNotIn(SHOW_INTEREST, fake.targets)
        self.assertNotIn(SUBSCRIBE, fake.targets)

    def test_the_first_download_all_is_pressed(self):
        vendor = page([per_file(2), DOWNLOAD_ALL2, P + "lbDownloadAll", P + "lbDownloadAll3"])
        fake = FakeComdia(vendor_page=vendor)
        self.assertEqual(self.listing(fake)["access"], "public")
        self.assertEqual(fake.targets[-1], DOWNLOAD_ALL2)
        self.assertEqual(len([t for t in fake.targets if comdia.DOWNLOAD_ALL.fullmatch(t)]), 1)

    def test_more_files_on_the_page_than_in_the_archive_names_both_counts(self):
        vendor = page([DOWNLOAD_ALL2, per_file(2), per_file(3), per_file(4), per_file(2)])
        found = self.listing(FakeComdia(vendor_page=vendor))
        self.assertEqual(found["access"], "public")
        self.assertEqual(len(found["files"]), 2)
        self.assertIn("3", found["note"])
        self.assertIn("2", found["note"])

    def test_a_repeated_per_file_link_counts_once(self):
        vendor = page([DOWNLOAD_ALL2, per_file(2), per_file(3), per_file(2)])
        found = self.listing(FakeComdia(vendor_page=vendor))
        self.assertEqual(found["access"], "public")
        self.assertEqual(found["note"], "")

    def test_a_reason_from_the_tender_page_is_the_note(self):
        fake = FakeComdia(tender_pages=[TENDER_NOTHING])
        found = self.listing(fake)
        self.assertEqual(found["access"], "gated")
        self.assertIn("lbShowInterest", found["note"])
        self.assertEqual(fake.targets, [])

    def test_no_download_all_with_per_file_links_is_gated(self):
        found = self.listing(FakeComdia(vendor_page=page([per_file(2), per_file(3)])))
        self.assertEqual(found["access"], "gated")
        self.assertTrue(found["note"])

    def test_no_download_all_and_no_files_is_none(self):
        fake = FakeComdia(vendor_page=page([REFRESH]))
        self.assertEqual(self.listing(fake)["access"], "none")
        self.assertEqual(fake.targets, [ACCESS_NAME, GO_NAME])

    def test_an_empty_archive_is_none(self):
        empty = zip_bytes([])
        self.assertTrue(empty.startswith(b"PK\x05\x06"))
        self.assertEqual(self.listing(FakeComdia(archive=empty))["access"], "none")

    def test_an_archive_of_folders_only_is_none(self):
        found = self.listing(FakeComdia(archive=zip_bytes([("144703/", b""), ("144703/A/", b"")])))
        self.assertEqual(found["access"], "none")
        self.assertEqual(found["files"], [])

    def test_an_answer_that_is_not_an_archive_is_gated(self):
        found = self.listing(FakeComdia(archive=b"<!DOCTYPE html><html>error</html>"))
        self.assertEqual(found["access"], "gated")
        self.assertTrue(found["note"])

    def test_an_archive_over_a_gigabyte_unpacked_is_gated(self):
        one = claiming(zip_bytes([("144703/A/big.bin", b"x")]), 1024 ** 3 + 1)
        two = claiming(zip_bytes([("144703/A/a.bin", b"x"), ("144703/A/b.bin", b"y")]),
                       600 * 1024 ** 2)
        for raw in (one, two):
            self.reset_state()
            found = self.listing(FakeComdia(archive=raw))
            self.assertEqual(found["access"], "gated")
            self.assertTrue(found["note"])

    def test_a_refused_sign_in(self):
        fake = FakeComdia(login_answer=LOGIN_PAGE)
        found = self.listing(fake)
        self.assertEqual(found["access"], "gated")
        self.assertTrue(found["note"].startswith("Comdia sign-in failed:"), found["note"])
        self.assertEqual(fake.gets, [])

    def test_a_refused_account_is_asked_once_per_run(self):
        fake = FakeComdia(login_answer=LOGIN_PAGE)
        for _ in range(3):
            found = self.listing(fake)
            self.assertTrue(found["note"].startswith("Comdia sign-in failed:"))
        self.assertEqual(len(fake.login_posts), 1)

    def test_one_sign_in_serves_every_tender(self):
        fake = FakeComdia()
        self.listing(fake)
        self.listing(fake)
        self.assertEqual(len(fake.login_posts), 1)

    def test_a_session_that_ends_gets_one_fresh_sign_in(self):
        fake = FakeComdia(tender_pages=[ENDED_PAGE, TENDER_NO_ACCESS])
        found = self.listing(fake)
        self.assertEqual(found["access"], "public")
        self.assertEqual(len(fake.login_posts), 2)
        self.assertEqual(fake.gets, [TENDER_URL, TENDER_URL])

    def test_a_session_that_stays_ended_is_retried_once(self):
        fake = FakeComdia(tender_pages=[ENDED_PAGE])
        found = self.listing(fake)
        self.assertEqual(found["access"], "gated")
        self.assertTrue(found["note"].startswith("Comdia sign-in failed:"), found["note"])
        self.assertEqual(len(fake.login_posts), 2)
        self.assertEqual(len(fake.gets), 2)

    def test_any_other_failure_is_gated_never_raised(self):
        found = self.listing(FakeComdia(fail={"get": RuntimeError("comdia is down")}))
        self.assertEqual(found["access"], "gated")
        self.assertTrue(found["note"].startswith("the Comdia step failed:"), found["note"])

    def test_notes_never_carry_the_account(self):
        leak = RuntimeError("refused %s with %s" % (USER, PASSWORD))
        found = self.listing(FakeComdia(fail={"get": leak}))
        self.assertTrue(found["note"].startswith("the Comdia step failed:"), found["note"])
        self.assertNotIn(USER, found["note"])
        self.assertNotIn(PASSWORD, found["note"])
        self.assertIn("<account>", found["note"])
        self.reset_state()
        found = self.listing(FakeComdia(fail={"login-post": OSError("no %s / %s" % (USER, PASSWORD))}))
        self.assertTrue(found["note"].startswith("Comdia sign-in failed:"), found["note"])
        self.assertNotIn(USER, found["note"])
        self.assertNotIn(PASSWORD, found["note"])

    def test_through_the_package(self):
        self.serve(FakeComdia())
        found = docsource.listing([TENDER_URL])
        self.assertEqual(found["platform"], "comdia")
        self.assertEqual(found["access"], "public")
        self.assertEqual(len(found["files"]), 2)
        entry = [f for f in found["files"] if f["name"] == "Udbudsbetingelser.pdf"][0]
        data, reason = docsource.download("comdia", entry)
        self.assertEqual(data, PDF)
        self.assertIsNone(reason)

    def test_no_account_through_the_package(self):
        self.no_account()
        found = docsource.listing([TENDER_URL])
        self.assertEqual(found["platform"], "comdia")
        self.assertEqual(found["access"], "gated")
        self.assertEqual(found["files"], [])
        self.assertTrue(found["note"])
        self.send.assert_not_called()


class ComdiaDownload(ComdiaCase):

    def listed(self, archive=SAMPLE_ZIP):
        self.serve(FakeComdia(archive=archive))
        found = comdia.listing([TENDER_URL])
        self.assertEqual(found["access"], "public")
        self.send.reset_mock()
        return {f["name"]: f for f in found["files"]}

    def test_a_member_from_the_archive_held(self):
        files = self.listed()
        self.assertEqual(comdia.download(files["Udbudsbetingelser.pdf"]), (PDF, None))
        self.assertEqual(comdia.download(files["Plan.dwg"]), (DWG, None))
        self.send.assert_not_called()

    def test_an_entry_of_another_archive(self):
        files = self.listed()
        entry = dict(files["Plan.dwg"], download="https://www.comdia.com/Site/vendor/user/"
                                                 "tenderentity/show.aspx?Id=1")
        data, reason = comdia.download(entry)
        self.assertIsNone(data)
        self.assertTrue(reason)

    def test_nothing_held(self):
        data, reason = comdia.download({"download": VENDOR_URL, "member": "144703/x.pdf",
                                        "name": "x.pdf"})
        self.assertIsNone(data)
        self.assertTrue(reason)

    def test_a_member_that_is_not_there(self):
        files = self.listed()
        data, reason = comdia.download(dict(files["Plan.dwg"], member="144703/Tegninger/Nope.dwg"))
        self.assertIsNone(data)
        self.assertTrue(reason)

    def test_an_empty_member(self):
        files = self.listed(zip_bytes([("144703/A/tom.txt", b""), ("144703/A/b.pdf", PDF)]))
        data, reason = comdia.download(files["tom.txt"])
        self.assertIsNone(data)
        self.assertTrue(reason)

    def test_a_new_listing_lets_go_of_the_old_archive(self):
        files = self.listed()
        comdia.listing(["https://www.comdia.com/tender/123"])
        data, reason = comdia.download(files["Plan.dwg"])
        self.assertIsNone(data)
        self.assertTrue(reason)


class ComdiaCheck(ComdiaCase):

    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = comdia.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_signed_in(self):
        fake = self.serve(FakeComdia())
        code, out, err = self.run_main(["--check"])
        self.assertEqual(code, 0)
        self.assertIn("comdia: signed in", out)
        self.assertEqual(fake.targets, [])
        self.assertEqual(fake.gets, [])
        self.assertNotIn(USER, out + err)
        self.assertNotIn(PASSWORD, out + err)

    def test_refused(self):
        self.serve(FakeComdia(login_answer=LOGIN_PAGE))
        code, out, err = self.run_main(["--check"])
        self.assertEqual(code, 1)
        self.assertIn("comdia: sign-in failed: ", out)
        self.assertNotIn(USER, out + err)
        self.assertNotIn(PASSWORD, out + err)

    def test_a_failure_that_names_the_account_is_printed_without_it(self):
        self.serve(FakeComdia(fail={"login-post": OSError("no %s / %s" % (USER, PASSWORD))}))
        code, out, err = self.run_main(["--check"])
        self.assertEqual(code, 1)
        self.assertIn("comdia: sign-in failed: ", out)
        self.assertNotIn(USER, out + err)
        self.assertNotIn(PASSWORD, out + err)

    def test_no_account(self):
        self.no_account()
        code, out, err = self.run_main(["--check"])
        self.assertEqual(code, 1)
        self.assertIn("comdia: sign-in failed: ", out)
        self.send.assert_not_called()

    def test_only_check_is_accepted(self):
        for argv in ([], ["--sign-in"], ["--check", "extra"], ["check"]):
            code, out, err = self.run_main(argv)
            self.assertEqual(code, 2, argv)
            self.assertTrue(out + err, argv)
        self.send.assert_not_called()


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
