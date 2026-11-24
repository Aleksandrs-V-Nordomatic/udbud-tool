#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Comdia: prequalification tenders opened for building work and watched cards, and media left
in the archive.

Comdia is answered by the stand-in of `test_docsource.py`, taught one more control; the one
network seam is `comdia._send`. Nothing reaches the network.
"""

import contextlib
import io
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
if HERE not in sys.path:
    sys.path.insert(1, HERE)

import dk_fetch
import docsource
from docsource import byggeweb, comdia, dalux, ethics, eusupply, mercell, udbuddk
from test_dk_fetch import target as fetch_target
from test_docsource import (ACCESS_NAME, DOWNLOAD_ALL2, ENDED_PAGE, GO_NAME, HOME_PAGE, HOME_URL,
                            P, PDF, REFRESH, SHOW_INTEREST, SUBSCRIBE, TENDER_URL, VENDOR_URL,
                            ComdiaCase, FakeComdia, html, page, per_file, zip_bytes)

PREQUAL = P + "lbRegisterPreQual"

TENDER_PREQUAL = page([PREQUAL, SHOW_INTEREST, SUBSCRIBE], viewstate="prequal")
PREQUAL_AND_GO = page([PREQUAL, GO_NAME, SHOW_INTEREST, SUBSCRIBE], viewstate="prequal-go")
PREQUAL_AND_ACCESS = page([PREQUAL, ACCESS_NAME, SHOW_INTEREST, SUBSCRIBE],
                          viewstate="prequal-access")

BUILDING = ("45000000", "45210000", "45300000", "45400000", "50700000", "71000000", "71200000",
            "71315000", "71320000")
NOT_BUILDING = ("45233140", "45231300", "45240000", "71351914", "71313000", "71311000",
                "50111100", "35521000", "38550000")

WORK = {"cpv_main": "45210000", "cpv": ["45210000"], "watched": False}
ROADS = {"cpv_main": "45233140", "cpv": ["45233140"], "watched": False}
WATCHED = {"cpv_main": "45233140", "cpv": ["45233140"], "watched": True}

OVER = 1024 ** 3 + 1


class FakePrequal(FakeComdia):
    """Comdia with a tender page that offers Access to prequalification, and an answer to it."""

    def __init__(self, tender_pages=(TENDER_PREQUAL,), prequal=None, **kwargs):
        super().__init__(tender_pages=tender_pages, **kwargs)
        self.prequal = prequal if prequal is not None else self.vendor

    def __call__(self, opener, url, data=None, *rest, **kwargs):
        if data is not None and dict(data).get("__EVENTTARGET") == PREQUAL:
            self.calls.append((url, dict(data)))
            return self.prequal
        return super().__call__(opener, url, data, *rest, **kwargs)


def claiming_for(raw, name, size):
    """The raw zip with the one member `name` claiming `size` bytes uncompressed."""
    b, name = bytearray(raw), name.encode("ascii")
    for signature, size_at, length_at, name_at in ((b"PK\x03\x04", 22, 26, 30),
                                                   (b"PK\x01\x02", 24, 28, 46)):
        at = b.find(signature)
        while at != -1:
            length = struct.unpack_from("<H", b, at + length_at)[0]
            if bytes(b[at + name_at:at + name_at + length]) == name:
                struct.pack_into("<I", b, at + size_at, size)
            at = b.find(signature, at + 4)
    return bytes(b)


def opened(raw):
    return zipfile.ZipFile(io.BytesIO(raw))


class PrequalCase(ComdiaCase):

    def listing(self, fake, *facts):
        self.serve(fake)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            found = comdia.listing([TENDER_URL], *facts)
        self.assertEqual(out.getvalue() + err.getvalue(), "", "the module prints nothing")
        return found

    def assert_opened(self, found, fake):
        self.assertEqual(found["access"], "public", found.get("note"))
        self.assertEqual([f["name"] for f in found["files"]], ["Plan.dwg", "Udbudsbetingelser.pdf"])
        self.assertEqual(fake.targets, [PREQUAL, DOWNLOAD_ALL2])

    def assert_not_pressed(self, found, fake):
        self.assertEqual(found["access"], "gated")
        self.assertEqual(found["files"], [])
        self.assertEqual(fake.targets, [])
        self.assertIn("prequalification", found["note"].lower())
        self.assertIn("not building work", found["note"].lower())


class BuildingWork(PrequalCase):

    def test_the_constants(self):
        self.assertEqual(comdia.PREQUALIFICATION, PREQUAL)
        self.assertNotIn(PREQUAL, comdia.PRESSED)
        self.assertIsInstance(comdia.BUILDING_CPV, tuple)
        self.assertEqual(comdia.MEDIA, frozenset({
            "mp4", "avi", "mov", "wmv", "mkv", "mpg", "mpeg", "m4v", "bmp", "dat", "evtdat"}))

    def test_each_code(self):
        for code in BUILDING:
            self.assertIs(comdia.building_work([code]), True, code)
        for code in NOT_BUILDING:
            self.assertIs(comdia.building_work([code]), False, code)
        self.assertIs(comdia.building_work(NOT_BUILDING), False)

    def test_one_building_code_among_others_is_enough(self):
        self.assertIs(comdia.building_work(["45233140", "45300000"]), True)
        self.assertIs(comdia.building_work([None, "71320000"]), True)

    def test_no_codes(self):
        for codes in (None, [], (), [None], [None, None]):
            self.assertIs(comdia.building_work(codes), False, codes)


class Opened(PrequalCase):

    def test_building_work_by_the_main_code_alone(self):
        for code in BUILDING:
            for facts in ({"cpv_main": code}, {"cpv_main": code, "cpv": None},
                          {"cpv_main": code, "cpv": [], "watched": False}):
                self.reset_state()
                fake = FakePrequal()
                with self.subTest(facts=facts):
                    self.assert_opened(self.listing(fake, facts), fake)

    def test_building_work_by_a_code_in_the_list_alone(self):
        for code in BUILDING[1:]:
            for facts in ({"cpv": [code]}, {"cpv_main": None, "cpv": [code]},
                          {"cpv_main": "45233140", "cpv": ["45233140", code], "watched": False}):
                self.reset_state()
                fake = FakePrequal()
                with self.subTest(facts=facts):
                    self.assert_opened(self.listing(fake, facts), fake)

    def test_a_watched_card_that_is_not_building_work(self):
        for facts in (WATCHED, {"watched": True}, {"cpv_main": None, "cpv": None, "watched": True}):
            self.reset_state()
            fake = FakePrequal()
            with self.subTest(facts=facts):
                self.assert_opened(self.listing(fake, facts), fake)

    def test_neither_building_work_nor_watched_is_gated_and_nothing_is_pressed(self):
        cases = [{"cpv_main": code, "cpv": [code], "watched": False} for code in NOT_BUILDING]
        cases += [{"cpv_main": "45233140"}, {"cpv": []}, {"cpv_main": None, "cpv": None}]
        for facts in cases:
            self.reset_state()
            fake = FakePrequal()
            with self.subTest(facts=facts):
                self.assert_not_pressed(self.listing(fake, facts), fake)

    def test_without_facts_it_is_gated_and_nothing_is_pressed(self):
        for facts in ((), (None,), ({},)):
            self.reset_state()
            fake = FakePrequal()
            with self.subTest(facts=facts):
                self.assert_not_pressed(self.listing(fake, *facts), fake)

    def test_open_tender_presses_only_when_told(self):
        fake = self.serve(FakePrequal())
        text, vendor_url, reason = comdia.open_tender(object(), TENDER_URL)
        self.assertIsNone(text)
        self.assertIsNone(vendor_url)
        self.assertIn("prequalification", reason.lower())
        self.assertEqual(fake.targets, [])
        text, vendor_url, reason = comdia.open_tender(object(), TENDER_URL, prequalify=True)
        self.assertIsNone(reason)
        self.assertEqual(vendor_url, VENDOR_URL)
        self.assertIn(DOWNLOAD_ALL2, text)
        self.assertEqual(fake.targets, [PREQUAL])

    def test_go_to_tender_and_access_to_tender_win(self):
        cases = ((PREQUAL_AND_GO, [GO_NAME, DOWNLOAD_ALL2]),
                 (PREQUAL_AND_ACCESS, [ACCESS_NAME, GO_NAME, DOWNLOAD_ALL2]))
        for offered, pressed in cases:
            for facts in (WORK, WATCHED, ROADS, None):
                self.reset_state()
                fake = FakePrequal(tender_pages=[offered])
                with self.subTest(pressed=pressed, facts=facts):
                    self.assertEqual(self.listing(fake, facts)["access"], "public")
                    self.assertEqual(fake.targets, pressed)

    def test_a_press_that_leads_elsewhere_is_gated_with_a_note(self):
        for answer in (html(HOME_PAGE, HOME_URL), html(TENDER_PREQUAL, TENDER_URL)):
            self.reset_state()
            fake = FakePrequal(prequal=answer)
            found = self.listing(fake, WORK)
            self.assertEqual(found["access"], "gated")
            self.assertEqual(found["files"], [])
            self.assertTrue(found["note"])
            self.assertEqual(fake.targets, [PREQUAL])

    def test_the_press_is_made_again_on_a_later_run(self):
        for _ in range(2):
            self.reset_state()
            fake = FakePrequal()
            self.assert_opened(self.listing(fake, WORK), fake)

    def test_a_session_that_ends_keeps_prequalify_on_the_fresh_sign_in(self):
        for facts in (WORK, WATCHED):
            self.reset_state()
            fake = FakePrequal(tender_pages=[ENDED_PAGE, TENDER_PREQUAL])
            self.assert_opened(self.listing(fake, facts), fake)
            self.assertEqual(len(fake.login_posts), 2)
            self.assertEqual(fake.gets, [TENDER_URL, TENDER_URL])


class Refused(PrequalCase):

    def test_prequalification_is_refused_without_prequalify(self):
        for kwargs in ({}, {"prequalify": False}):
            with self.assertRaises(PermissionError):
                comdia._postback(object(), TENDER_URL, TENDER_PREQUAL, PREQUAL, **kwargs)
        self.send.assert_not_called()

    def test_prequalify_opens_that_control_and_no_other(self):
        fake = self.serve(FakePrequal())
        for control in (SHOW_INTEREST, SUBSCRIBE, REFRESH, per_file(2), ""):
            with self.assertRaises(PermissionError, msg=control):
                comdia._postback(object(), TENDER_URL, TENDER_PREQUAL, control, prequalify=True)
        self.assertEqual(fake.calls, [])
        comdia._postback(object(), TENDER_URL, TENDER_PREQUAL, PREQUAL, prequalify=True)
        self.assertEqual(fake.targets, [PREQUAL])

    def test_show_interest_and_subscribe_are_never_pressed(self):
        allowed = {PREQUAL, ACCESS_NAME, GO_NAME, DOWNLOAD_ALL2}
        for offered in (TENDER_PREQUAL, PREQUAL_AND_GO, PREQUAL_AND_ACCESS):
            for answer in (None, html(HOME_PAGE, HOME_URL), html(TENDER_PREQUAL, TENDER_URL)):
                for facts in (WORK, WATCHED, ROADS, None):
                    self.reset_state()
                    fake = FakePrequal(tender_pages=[offered], prequal=answer)
                    self.listing(fake, facts)
                    self.assertLessEqual(set(fake.targets), allowed)


class Media(PrequalCase):

    MIXED = zip_bytes([
        ("144703/Udbud/Udbudsbetingelser.pdf", PDF),
        ("144703/Udbud/LAESMIG", b"no extension"),
        ("144703/Bilag.mp4/Notat", b"a dot in the folder, no extension"),
        ("144703/Foto.v1.bmp/Plan.pdf", b"a dot in the folder"),
        ("144703/Film/a.mp4", b"1"),
        ("144703/Film/b.MP4", b"2"),
        ("144703/Foto/c.Bmp", b"3"),
        ("144703/TV/d.EvtDat", b"4"),
    ])
    KEPT = ["LAESMIG", "Notat", "Plan.pdf", "Udbudsbetingelser.pdf"]

    def test_left_out_counts_each_extension(self):
        with opened(self.MIXED) as z:
            self.assertEqual(comdia.left_out(z), {"mp4": 2, "bmp": 1, "evtdat": 1})
        with opened(zip_bytes([("144703/A/a.pdf", PDF)])) as z:
            self.assertEqual(comdia.left_out(z), {})

    def test_every_media_extension_in_any_case_is_left_out(self):
        for ext in sorted(comdia.MEDIA):
            for spelled in (ext, ext.upper(), ext.capitalize()):
                raw = zip_bytes([("144703/A/x." + spelled, b"1"), ("144703/B/y.pdf", PDF)])
                with opened(raw) as z:
                    self.assertEqual([f["name"] for f in comdia.archive_files(z, VENDOR_URL)],
                                     ["y.pdf"], spelled)
                    self.assertEqual(comdia.left_out(z), {ext: 1}, spelled)

    def test_a_listing_leaves_media_out_and_the_note_counts_them(self):
        found = self.listing(FakeComdia(archive=self.MIXED))
        self.assertEqual(found["access"], "public")
        self.assertEqual(sorted(f["name"] for f in found["files"]), self.KEPT)
        self.assertIn("left out, nothing reads them:", found["note"])
        for counted in (r"\b2 \.mp4\b", r"\b1 \.bmp\b", r"\b1 \.evtdat\b"):
            self.assertRegex(found["note"], counted)

    def test_media_do_not_count_against_the_gigabyte_and_other_members_do(self):
        raw = zip_bytes([("144703/A/a.pdf", PDF), ("144703/B/b.mp4", b"1"),
                         ("144703/B/c.BMP", b"2")])
        big_media = claiming_for(claiming_for(raw, "144703/B/b.mp4", OVER), "144703/B/c.BMP", OVER)
        found = self.listing(FakeComdia(archive=big_media))
        self.assertEqual(found["access"], "public", found.get("note"))
        self.assertEqual([f["name"] for f in found["files"]], ["a.pdf"])
        self.reset_state()
        found = self.listing(FakeComdia(archive=claiming_for(big_media, "144703/A/a.pdf", OVER)))
        self.assertEqual(found["access"], "gated")
        self.assertTrue(found["note"])

    def test_the_count_of_the_archive_holds_media(self):
        raw = zip_bytes([("144703/A/a.pdf", PDF), ("144703/B/b.mp4", b"1"),
                         ("144703/B/c.mp4", b"2")])
        vendor = [DOWNLOAD_ALL2, per_file(2), per_file(3), per_file(4)]
        found = self.listing(FakeComdia(archive=raw, vendor_page=page(vendor)))
        self.assertEqual(found["access"], "public")
        self.assertNotIn("vendor page lists", found["note"])
        self.reset_state()
        found = self.listing(FakeComdia(archive=raw, vendor_page=page(vendor + [per_file(5)])))
        self.assertIn("the vendor page lists 4; the archive holds 3", found["note"])

    def test_an_archive_of_media_only_is_none(self):
        raw = zip_bytes([("144703/", b""), ("144703/B/b.mp4", b"1"), ("144703/B/c.avi", b"2")])
        found = self.listing(FakeComdia(archive=raw))
        self.assertEqual(found["access"], "none")
        self.assertEqual(found["files"], [])


class Handed(PrequalCase):

    def test_facts_reach_comdia_through_the_package(self):
        for facts in (WORK, WATCHED):
            self.reset_state()
            fake = self.serve(FakePrequal())
            found = docsource.listing([TENDER_URL], facts)
            self.assertEqual(found["platform"], "comdia")
            self.assert_opened(found, fake)
        for facts in ((ROADS,), ()):
            self.reset_state()
            fake = self.serve(FakePrequal())
            self.assert_not_pressed(docsource.listing([TENDER_URL], *facts), fake)

    def test_another_module_is_called_with_the_urls_alone(self):
        urls = {
            "https://www.ethics.dk/ethics/eo#/x/publicMaterial": ethics,
            "https://node1.build.dalux.com/da-dk/public/tender/TID-1": dalux,
            "https://api.udbud.dk/udbud/vedhaeftning/1/01/fil/1/a.pdf": udbuddk,
            "https://www.byggeweb.dk/controller?tn=TN1": byggeweb,
            "https://eu.eu-supply.com/app/rfq/rwlentrance_s.asp?PID=1": eusupply,
            "https://permalink.mercell.com/12345.aspx": mercell,
        }
        for url, module in urls.items():
            with mock.patch.object(module, "listing", autospec=True,
                                   return_value={"access": "none"}) as lister:
                docsource.listing([url], WATCHED)
            lister.assert_called_once_with([url])

    def test_fetch_hands_its_target_to_the_listing(self):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        t, doc = fetch_target([TENDER_URL])
        found = {"host": "www.comdia.com", "platform": "comdia", "access": "gated",
                 "files": [], "gated": [], "note": "prequalification"}
        with mock.patch.object(docsource, "listing", return_value=found) as lister:
            dk_fetch.fetch(t, out, doc, with_text=False)
        lister.assert_called_once()
        self.assertEqual(len(lister.call_args.args), 2)
        self.assertIs(lister.call_args.args[1], t)


if __name__ == "__main__":
    unittest.main()
