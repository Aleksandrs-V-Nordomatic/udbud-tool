#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A home read again: a file the home already holds, unchanged, is carried over — not
downloaded, not stored, not read again.

Every home a carry is tested against is made by a first `dk_fetch.fetch` with plain .txt files,
so the index, the manifest and the text manifest are the tool's own. `docsource.listing` and
`docsource.download` are replaced; `net.open_url` fails loudly; the five GRAPH_* variables are
cleared so `homes.held` never reaches for the drive. Comdia is answered by the stand-in of
`test_docsource.py`.
"""

import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
if HERE not in sys.path:
    sys.path.insert(1, HERE)

import changes
import deliver_dk
import deliver_graph
import dk_fetch
import docsource
import homes
import net
from docsource import comdia, dalux, ethics, ibinder
from test_dk_fetch import PROCEDURE, target
from test_docsource import (DOWNLOAD_ALL2, TENDER_URL, VENDOR_URL, ComdiaCase, FakeComdia, page,
                            per_file)

GRAPH = ("GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET", "GRAPH_DRIVE_ID",
         "GRAPH_DEST_ROOT")

URLS = {
    "dalux": "https://node1.build.dalux.com/da-dk/public/tender/TID-1",
    "ethics": "https://www.ethics.dk/ethics/eo#/x/publicMaterial",
    "ibinder": "https://my.ibinder.com/etendering/org/tenders/t1/public",
    "api.udbud.dk": "https://api.udbud.dk/udbud/vedhaeftning/a/01/fil/b/x.pdf",
    "comdia": TENDER_URL,
}

ALPHA = b"Alpha: the conditions of the tender.\n"
BETA = b"Beta: the bill of quantities, read as text.\n"


def no_network(*args, **kwargs):
    raise AssertionError("a test reached the network")


def offline(case):
    """No drive, no network, for the life of one test."""
    env = mock.patch.dict(os.environ)
    env.start()
    case.addCleanup(env.stop)
    for name in GRAPH:
        os.environ.pop(name, None)
    opener = mock.patch.object(net, "open_url", side_effect=no_network)
    case.open_url = opener.start()
    case.addCleanup(opener.stop)


def entry(fid, name, folder="Udbud", download=None, **kw):
    body = {"id": fid, "name": name, "folder": folder,
            "download": download or "https://files.example/%s" % fid}
    body.update(kw)
    return body


def dalux_files():
    return [entry("rev-a", "a.txt", download="https://node1.field.dalux.com/f/rev-a"),
            entry("rev-b", "b.txt", download="https://node1.field.dalux.com/f/rev-b")]


def sha(data):
    return hashlib.sha256(data).hexdigest()


class HomeCase(unittest.TestCase):

    def setUp(self):
        offline(self)
        self.out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.out, True)
        self.home = os.path.join(self.out, "tenders", PROCEDURE)

    def fetch(self, platform, files, contents, held=None, with_text=True):
        """One fetch; answers (result, ids downloaded)."""
        t, doc = target([URLS[platform]])
        found = {"host": "host.example", "platform": platform, "access": "public",
                 "files": [dict(f) for f in files], "gated": []}
        asked = []

        def download(p, e):
            asked.append(e["id"])
            return contents[e["id"]], None

        with mock.patch.object(docsource, "listing", return_value=found), \
                mock.patch.object(docsource, "download", side_effect=download):
            done = dk_fetch.fetch(t, self.out, doc, with_text=with_text, held=held)
        return done, asked

    def first(self, platform="dalux", files=None, contents=None):
        """A home made by a first fetch, read back with `homes.held`; its originals are removed,
        as on a home read from the drive, so anything written later is visible."""
        files = files if files is not None else dalux_files()
        contents = contents or {"rev-a": ALPHA, "rev-b": BETA}
        self.fetch(platform, files, contents)
        held = homes.held(self.out, PROCEDURE)
        self.assertIsNotNone(held)
        shutil.rmtree(os.path.join(self.home, "originals"), True)
        return held

    def originals(self):
        where = os.path.join(self.home, "originals")
        return sorted(os.listdir(where)) if os.path.isdir(where) else []

    def held_filename(self, held, rid):
        for record in held["manifest"]["documents"]:
            if record["id"] == rid:
                return record["files"][0]["filename"]
        self.fail("no record %s in the home" % rid)

    def read_json(self, *parts):
        with open(os.path.join(self.home, *parts), encoding="utf-8") as fh:
            return json.load(fh)


# ---------------------------------------------------------------- what the home holds

class Held(HomeCase):

    def write(self, name, body):
        path = os.path.join(self.home, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(body, fh)

    def test_no_home_is_none(self):
        self.assertIsNone(homes.held(self.out, PROCEDURE))

    def test_a_home_needs_both_its_index_and_its_state(self):
        self.write("index.json", {"pid": PROCEDURE})
        self.assertIsNone(homes.held(self.out, PROCEDURE))
        os.remove(os.path.join(self.home, "index.json"))
        self.write("state.json", {"tool": "v1"})
        self.assertIsNone(homes.held(self.out, PROCEDURE))

    def test_the_five_files_of_a_home_on_disk(self):
        files = {"index.json": {"pid": PROCEDURE, "documents": []},
                 "manifest.json": {"documents": [], "withheld_records": []},
                 os.path.join("normalized", "manifest_normalized.json"):
                     {"documents": [], "unreadable_files": []},
                 "procurement.json": {"notices": [], "published": "2026-09-02"},
                 "state.json": {"tool": "v1"}}
        for name, body in files.items():
            self.write(name, body)
        held = homes.held(self.out, PROCEDURE)
        self.assertEqual(held["where"], "disk")
        self.assertEqual(held["index"], files["index.json"])
        self.assertEqual(held["manifest"], files["manifest.json"])
        self.assertEqual(held["normalized"],
                         files[os.path.join("normalized", "manifest_normalized.json")])
        self.assertEqual(held["procurement"], files["procurement.json"])
        self.assertEqual(held["state"], files["state.json"])

    def test_a_fetched_home_is_held_on_disk(self):
        held = self.first()
        self.assertEqual(held["where"], "disk")
        self.assertEqual(held["index"]["pid"], PROCEDURE)

    def test_without_all_five_graph_variables_the_drive_is_not_asked(self):
        for name in GRAPH[:4]:
            os.environ[name] = "x"
        self.assertIsNone(homes.held(self.out, PROCEDURE))
        self.open_url.assert_not_called()


class NewestPublished(unittest.TestCase):

    def test_the_latest_of_the_notices_and_the_procurement(self):
        held = {"procurement": {"published": "2026-08-01",
                                "notices": [{"published": "2026-09-02"},
                                            {"published": "2026-08-20"}]}}
        self.assertEqual(homes.newest_published(held), "2026-09-02")
        held["procurement"]["published"] = "2026-10-01"
        self.assertEqual(homes.newest_published(held), "2026-10-01")

    def test_nothing_published_is_none(self):
        self.assertIsNone(homes.newest_published({"procurement": {"notices": []}}))


# ---------------------------------------------------------------- which files may be carried

class Carriable(HomeCase):

    def test_each_record_with_its_index_entry_and_its_texts(self):
        held = self.first()
        carry = dk_fetch.carriable(held, changes.pipeline_version())
        self.assertEqual(set(carry), {"rev-a", "rev-b"})
        for rid, one in carry.items():
            self.assertEqual(set(one), {"record", "doc", "texts"})
            self.assertEqual(one["record"]["id"], rid)
            self.assertEqual(one["doc"]["id"], rid)
            self.assertTrue(one["texts"])
            for text in one["texts"]:
                self.assertEqual(text["record_id"], rid)

    def test_nothing_without_a_home_or_its_text_manifest(self):
        tool = changes.pipeline_version()
        self.assertEqual(dk_fetch.carriable(None, tool), {})
        held = self.first()
        self.assertEqual(dk_fetch.carriable(dict(held, normalized=None), tool), {})

    def test_nothing_from_another_extractor_version(self):
        held = self.first()
        held["state"] = dict(held["state"], tool="another version")
        self.assertEqual(dk_fetch.carriable(held, changes.pipeline_version()), {})

    def test_only_a_record_with_one_file_and_an_index_entry(self):
        held = self.first()
        manifest = json.loads(json.dumps(held["manifest"]))
        for record in manifest["documents"]:
            if record["id"] == "rev-a":
                record["files"] = record["files"] + [dict(record["files"][0], filename="x.txt")]
        index = dict(held["index"],
                     documents=[d for d in held["index"]["documents"] if d["id"] != "rev-b"])
        carry = dk_fetch.carriable(dict(held, manifest=manifest, index=index),
                                   changes.pipeline_version())
        self.assertEqual(carry, {})


# ---------------------------------------------------------------- the hosts' word

class Unchanged(HomeCase):

    def doc(self, held, rid):
        return dk_fetch.carriable(held, changes.pipeline_version())[rid]["doc"]

    def test_dalux_by_revision_name_and_address(self):
        held = self.first()
        doc = self.doc(held, "rev-a")
        same = dalux_files()[0]
        self.assertIs(docsource.unchanged("dalux", same, doc), True)
        self.assertIs(dalux.unchanged(same, doc), True)
        for moved in (dict(same, id="rev-a2"), dict(same, name="a2.txt"),
                      dict(same, download="https://node1.field.dalux.com/f/other")):
            self.assertIs(docsource.unchanged("dalux", moved, doc), False, moved)
            self.assertIs(dalux.unchanged(moved, doc), False, moved)

    def test_ibinder_the_same(self):
        files = [entry("v-a", "a.txt", download="https://my.ibinder.com/preview/a?version=1"),
                 entry("v-b", "b.txt", download="https://my.ibinder.com/preview/b?version=1")]
        held = self.first("ibinder", files, {"v-a": ALPHA, "v-b": BETA})
        doc = self.doc(held, "v-a")
        self.assertIs(docsource.unchanged("ibinder", files[0], doc), True)
        self.assertIs(ibinder.unchanged(files[0], doc), True)
        for moved in (dict(files[0], id="v-a2"), dict(files[0], name="a2.txt"),
                      dict(files[0], download="https://my.ibinder.com/preview/a?version=2")):
            self.assertIs(docsource.unchanged("ibinder", moved, doc), False, moved)
            self.assertIs(ibinder.unchanged(moved, doc), False, moved)

    def test_ethics_by_id_name_and_a_known_size(self):
        files = [entry("e-a", "a.txt", bytes=len(ALPHA)), entry("e-b", "b.txt", bytes=len(BETA))]
        held = self.first("ethics", files, {"e-a": ALPHA, "e-b": BETA})
        doc = self.doc(held, "e-a")
        self.assertIs(docsource.unchanged("ethics", files[0], doc), True)
        self.assertIs(ethics.unchanged(files[0], doc), True)
        unknown = {k: v for k, v in files[0].items() if k != "bytes"}
        for moved in (unknown, dict(files[0], bytes=len(ALPHA) + 1), dict(files[0], id="e-x"),
                      dict(files[0], name="a2.txt")):
            self.assertIs(docsource.unchanged("ethics", moved, doc), False, moved)
            self.assertIs(ethics.unchanged(moved, doc), False, moved)

    def test_every_other_host_says_no(self):
        held = self.first()
        doc = self.doc(held, "rev-a")
        for platform in ("eu-supply", "api.udbud.dk", "mercell"):
            self.assertIs(docsource.unchanged(platform, dalux_files()[0], doc), False, platform)

    def test_comdia_a_held_entry_with_the_same_id(self):
        doc = {"id": "zip:144703/Udbud/a.txt", "name": "a.txt"}
        held_entry = {"id": doc["id"], "name": "a.txt", "folder": "Udbud", "held": True}
        self.assertIs(comdia.unchanged(held_entry, doc), True)
        self.assertIs(docsource.unchanged("comdia", held_entry, doc), True)
        not_held = {k: v for k, v in held_entry.items() if k != "held"}
        self.assertIs(comdia.unchanged(not_held, doc), False)
        self.assertIs(comdia.unchanged(dict(held_entry, id="zip:other"), doc), False)


# ---------------------------------------------------------------- store

class Store(HomeCase):

    def test_without_a_carry_every_file_is_downloaded_and_written(self):
        os.makedirs(self.home)
        files = [entry("1", "a.txt"), entry("2", "b.txt", folder="")]
        contents = {"1": ALPHA, "2": BETA}
        with mock.patch.object(docsource, "download",
                               side_effect=lambda p, e: (contents[e["id"]], None)):
            records, withheld, nbytes, carried = dk_fetch.store(self.home, "api.udbud.dk", files)
        self.assertEqual([r["title"] for r in records], ["Udbud/a.txt", "b.txt"])
        self.assertEqual(withheld, [])
        self.assertEqual(nbytes, len(ALPHA) + len(BETA))
        self.assertFalse(carried)
        for record in records:
            self.assertEqual(len(record["files"]), 1)
            one = record["files"][0]
            path = os.path.join(self.home, "originals", one["filename"])
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(), contents[record["id"]])
            self.assertEqual(one["sha256"], sha(contents[record["id"]]))

    def test_a_host_that_says_unchanged_is_carried_without_a_download(self):
        held = self.first()
        carry = dk_fetch.carriable(held, changes.pipeline_version())
        with mock.patch.object(docsource, "download", side_effect=AssertionError("downloaded")):
            records, withheld, nbytes, carried = dk_fetch.store(self.home, "dalux", dalux_files(),
                                                                carry)
        self.assertEqual(set(carried), {"rev-a", "rev-b"})
        self.assertEqual(nbytes, 0)
        self.assertEqual(self.originals(), [])
        for record in records:
            self.assertEqual(record["files"][0]["filename"], self.held_filename(held, record["id"]))

    def test_a_new_file_never_takes_the_name_of_a_held_one(self):
        held = self.first()
        carry = dk_fetch.carriable(held, changes.pipeline_version())
        files = dalux_files() + [entry("rev-c", "a.txt", folder="Bilag")]
        with mock.patch.object(docsource, "download", return_value=(b"Gamma\n", None)):
            records, _, nbytes, carried = dk_fetch.store(self.home, "dalux", files, carry)
        self.assertEqual(set(carried), {"rev-a", "rev-b"})
        self.assertEqual(nbytes, len(b"Gamma\n"))
        new = [r for r in records if r["id"] == "rev-c"][0]["files"][0]["filename"]
        self.assertNotIn(new, {self.held_filename(held, "rev-a"), self.held_filename(held, "rev-b")})
        self.assertEqual(self.originals(), [new])


# ---------------------------------------------------------------- a fetch with a held home

class FetchAgain(HomeCase):

    def test_an_unchanged_dalux_tender_downloads_nothing_and_is_unchanged(self):
        held = self.first()
        done, asked = self.fetch("dalux", dalux_files(), {}, held=held)
        self.assertEqual(asked, [])
        self.assertEqual(done["carried"], 2)
        self.assertEqual(done["bytes"], 0)
        self.assertEqual(done["documents"], 2)
        self.assertEqual(self.originals(), [])
        self.assertEqual(changes.diff(held["state"], done["state"])["status"], "unchanged")
        self.assertEqual({d["id"] for d in self.read_json("index.json")["documents"]},
                         {"rev-a", "rev-b"})

    def test_the_carried_texts_are_in_the_text_manifest(self):
        held = self.first()
        self.fetch("dalux", dalux_files(), {}, held=held)
        normalized = self.read_json("normalized", "manifest_normalized.json")
        texts = [d for d in normalized["documents"] if d.get("record_id") in ("rev-a", "rev-b")]
        self.assertEqual({d["record_id"] for d in texts}, {"rev-a", "rev-b"})
        for text in texts:
            key = changes.document_key(text["original_sha256"], text["source"])
            self.assertEqual(text["doc"], "doc/%s.md" % key)

    def test_a_host_that_cannot_say_downloads_and_carries_by_digest(self):
        files = [entry("1", "a.txt"), entry("2", "b.txt")]
        contents = {"1": ALPHA, "2": BETA}
        held = self.first("api.udbud.dk", files, contents)
        done, asked = self.fetch("api.udbud.dk", files, contents, held=held)
        self.assertEqual(sorted(asked), ["1", "2"])
        self.assertEqual(done["carried"], 2)
        self.assertEqual(done["bytes"], len(ALPHA) + len(BETA))
        self.assertEqual(self.originals(), [])
        self.assertEqual(changes.diff(held["state"], done["state"])["status"], "unchanged")

    def test_a_moved_address_with_the_same_bytes_is_carried_by_digest(self):
        held = self.first()
        files = dalux_files()
        files[0]["download"] = "https://node1.field.dalux.com/f/elsewhere"
        done, asked = self.fetch("dalux", files, {"rev-a": ALPHA}, held=held)
        self.assertEqual(asked, ["rev-a"])
        self.assertEqual(done["carried"], 2)
        self.assertEqual(done["bytes"], len(ALPHA))
        self.assertEqual(self.originals(), [])

    def test_a_changed_file_is_stored_under_its_own_name_and_reported(self):
        files = [entry("1", "a.txt"), entry("2", "b.txt")]
        held = self.first("api.udbud.dk", files, {"1": ALPHA, "2": BETA})
        changed = b"Alpha, amended: the deadline moved.\n"
        done, asked = self.fetch("api.udbud.dk", files, {"1": changed, "2": BETA}, held=held)
        self.assertEqual(done["carried"], 1)
        self.assertEqual(done["bytes"], len(changed) + len(BETA))
        self.assertEqual(self.originals(), [self.held_filename(held, "1")])
        move = changes.diff(held["state"], done["state"])
        self.assertEqual(move["status"], "changed")
        self.assertTrue(move["documents_added"])

    def test_an_added_file_is_reported_and_the_rest_carried(self):
        held = self.first()
        files = dalux_files() + [entry("rev-c", "c.txt", download="https://node1.field.dalux.com/f/c")]
        done, asked = self.fetch("dalux", files, {"rev-c": b"Gamma: an addendum.\n"}, held=held)
        self.assertEqual(asked, ["rev-c"])
        self.assertEqual(done["carried"], 2)
        self.assertEqual(done["documents"], 3)
        move = changes.diff(held["state"], done["state"])
        self.assertEqual(move["status"], "changed")
        self.assertTrue(move["documents_added"])

    def test_a_renamed_file_is_not_carried(self):
        held = self.first()
        files = dalux_files()
        files[0]["name"] = "a-renamed.txt"
        done, asked = self.fetch("dalux", files, {"rev-a": ALPHA}, held=held)
        self.assertEqual(asked, ["rev-a"])
        self.assertEqual(done["carried"], 1)
        self.assertEqual(len(self.originals()), 1)

    def test_another_extractor_version_downloads_everything(self):
        held = self.first()
        held["state"] = dict(held["state"], tool="another version")
        done, asked = self.fetch("dalux", dalux_files(), {"rev-a": ALPHA, "rev-b": BETA},
                                 held=held)
        self.assertEqual(sorted(asked), ["rev-a", "rev-b"])
        self.assertEqual(done["carried"], 0)
        self.assertEqual(done["bytes"], len(ALPHA) + len(BETA))

    def test_without_a_held_home_nothing_is_carried(self):
        done, asked = self.fetch("dalux", dalux_files(), {"rev-a": ALPHA, "rev-b": BETA})
        self.assertEqual(sorted(asked), ["rev-a", "rev-b"])
        self.assertEqual(done["carried"], 0)


class WithCarried(HomeCase):

    def test_carried_texts_are_added_with_their_doc(self):
        held = self.first()
        carry = dk_fetch.carriable(held, changes.pipeline_version())
        out = dk_fetch.with_carried({"documents": [], "unreadable_files": []}, carry,
                                    ["rev-a", "rev-b"])
        for key in ("entries", "markdown", "unsupported", "chars", "carried"):
            self.assertIn(key, out)
        texts = out["documents"]
        self.assertEqual({t["record_id"] for t in texts}, {"rev-a", "rev-b"})
        for text in texts:
            key = changes.document_key(text["original_sha256"], text["source"])
            self.assertEqual(text["doc"], "doc/%s.md" % key)

    def test_only_the_carried_ids_are_added(self):
        held = self.first()
        carry = dk_fetch.carriable(held, changes.pipeline_version())
        out = dk_fetch.with_carried({"documents": [], "unreadable_files": []}, carry, ["rev-a"])
        self.assertEqual({t["record_id"] for t in out["documents"]}, {"rev-a"})


# ---------------------------------------------------------------- Comdia, by its vendor page

MARKER = '<span id="ctl00_x_lblFileNotDownloaded" class="fileNotDownloaded">Not downloaded</span>'


def group_row(name):
    return '<tr><td class="group1" colspan="4">%s</td></tr>' % name


def file_row(n, name, info="text", date="20-11-2026<br />13:05", img="/x.png", aside=""):
    return ('<tr><td><a id="ctl00_x_gvDocument_ctl%02d_lbDownload" '
            'href="javascript:__doPostBack(&#39;%s&#39;,&#39;&#39;)"><img src="%s" />%s</a>'
            '<div style="float: right; font-style: italic;">%s</div><br /></td>'
            '<td>%s</td><td><small class="kt-font-brand">%s</small><br />text</td>'
            '<td class="l date">%s</td></tr>' % (n, per_file(n), img, name, aside, MARKER, info,
                                                 date))


def doc_table(*rows):
    return ('<table class="table table-striped" id="ctl00_x_gvDocument">'
            '<tr><th scope="col">Name</th><th scope="col">State</th><th scope="col">Info</th>'
            '<th scope="col">Date</th></tr>%s</table>' % "".join(rows))


ROWS = (group_row("Udbud"), file_row(2, "Udbudsbetingelser.pdf"), group_row("Tegninger"),
        file_row(3, "Plan.dwg"))


def with_table(text, table):
    if "</body>" in text:
        return text.replace("</body>", table + "</body>", 1)
    return text + table


class ListingSignature(unittest.TestCase):

    def sig(self, *rows):
        return comdia.listing_signature("<html><body>%s</body></html>" % doc_table(*rows))

    def test_a_digest_of_the_table(self):
        first = self.sig(*ROWS)
        self.assertIsInstance(first, str)
        self.assertTrue(first)
        self.assertEqual(self.sig(*ROWS), first)

    def test_what_is_left_out_of_the_name_cell(self):
        first = self.sig(*ROWS)
        moved = (ROWS[0], file_row(2, "Udbudsbetingelser.pdf", img="/y.png", aside="new"),
                 ROWS[2], ROWS[3])
        self.assertEqual(self.sig(*moved), first)

    def test_a_name_a_group_or_a_later_cell_moves_it(self):
        first = self.sig(*ROWS)
        cases = [
            (ROWS[0], file_row(2, "Udbudsbetingelser v2.pdf"), ROWS[2], ROWS[3]),
            (group_row("Bilag"), ROWS[1], ROWS[2], ROWS[3]),
            (ROWS[0], file_row(2, "Udbudsbetingelser.pdf", info="other"), ROWS[2], ROWS[3]),
            (ROWS[0], file_row(2, "Udbudsbetingelser.pdf", date="21-11-2026<br />09:00"),
             ROWS[2], ROWS[3]),
            ROWS + (file_row(4, "Bilag 1.pdf"),),
            (ROWS[0], ROWS[1]),
        ]
        for rows in cases:
            self.assertNotEqual(self.sig(*rows), first, rows)

    def test_no_table_or_no_file_rows_is_none(self):
        self.assertIsNone(comdia.listing_signature("<html><body><p>nothing</p></body></html>"))
        self.assertIsNone(self.sig())
        self.assertIsNone(self.sig(group_row("Udbud")))


class ComdiaHeld(ComdiaCase):

    def setUp(self):
        super().setUp()
        offline(self)
        self.vendor = with_table(page([DOWNLOAD_ALL2]), doc_table(*ROWS))
        self.signature = comdia.listing_signature(self.vendor)

    def fake(self):
        return self.serve(FakeComdia(vendor_page=self.vendor))

    def index_of(self, found, **kw):
        index = {"documents_listing": found["listing"], "documents_available": "public",
                 "documents_note": "the note kept from the first night",
                 "documents": [{"id": f["id"], "name": f["name"], "folder": f.get("folder"),
                                "download": f.get("download")} for f in found["files"]]}
        index.update(kw)
        return index

    def first(self):
        self.fake()
        found = comdia.listing([TENDER_URL])
        self.reset_state()
        return found

    def test_the_listing_carries_the_signature(self):
        self.assertIsNotNone(self.signature)
        found = self.first()
        self.assertEqual(found["listing"], self.signature)
        self.assertTrue(found["files"])

    def test_an_unchanged_page_is_not_downloaded(self):
        index = self.index_of(self.first())
        for listed in (lambda: comdia.listing([TENDER_URL], None, held=index),
                       lambda: docsource.listing([TENDER_URL], None, held=index)):
            self.reset_state()
            fake = self.fake()
            found = listed()
            self.assertNotIn(DOWNLOAD_ALL2, fake.targets)
            self.assertIs(found["unchanged"], True)
            self.assertEqual(found["note"], index["documents_note"])
            self.assertEqual([f["id"] for f in found["files"]],
                             [d["id"] for d in index["documents"]])
            for f, doc in zip(found["files"], index["documents"]):
                self.assertTrue(f.get("held"))
                self.assertIs(comdia.unchanged(f, doc), True)

    def test_otherwise_download_all_is_pressed(self):
        found = self.first()
        cases = (self.index_of(found, documents_listing="another table"),
                 self.index_of(found, documents_listing=None),
                 self.index_of(found, documents_available="partial"),
                 self.index_of(found, documents=[]))
        for index in cases:
            self.reset_state()
            fake = self.fake()
            again = comdia.listing([TENDER_URL], None, held=index)
            self.assertIn(DOWNLOAD_ALL2, fake.targets, index)
            self.assertFalse(again.get("unchanged"))


class ComdiaFetch(HomeCase):

    FILES = [entry("zip:144703/Udbud/a.txt", "a.txt", download=VENDOR_URL),
             entry("zip:144703/Udbud/b.txt", "b.txt", download=VENDOR_URL)]
    CONTENTS = {"zip:144703/Udbud/a.txt": ALPHA, "zip:144703/Udbud/b.txt": BETA}

    def listing(self, held_listing, fresh):
        def answer(urls, facts=None, held=None):
            return held_listing if held is not None else fresh
        return answer

    def fresh(self):
        return {"host": "www.comdia.com", "platform": "comdia", "access": "public",
                "files": [dict(f) for f in self.FILES], "gated": [], "listing": "sig"}

    def held_listing(self):
        return {"host": "www.comdia.com", "platform": "comdia", "access": "public",
                "files": [dict(f, held=True) for f in self.FILES], "gated": [],
                "listing": "sig", "unchanged": True, "note": "kept"}

    def test_held_files_are_carried_and_the_index_is_handed_to_the_listing(self):
        held = self.first("comdia", self.FILES, self.CONTENTS)
        t, doc = target([TENDER_URL])
        with mock.patch.object(docsource, "listing",
                               side_effect=self.listing(self.held_listing(), self.fresh())) as lister, \
                mock.patch.object(docsource, "download", side_effect=AssertionError("downloaded")):
            done = dk_fetch.fetch(t, self.out, doc, held=held)
        self.assertEqual(lister.call_args_list[0].kwargs.get("held"), held["index"])
        self.assertEqual(lister.call_count, 1)
        self.assertEqual(done["carried"], 2)
        self.assertEqual(done["bytes"], 0)

    def test_held_files_that_cannot_be_carried_are_listed_again_without_the_index(self):
        held = self.first("comdia", self.FILES, self.CONTENTS)
        held["state"] = dict(held["state"], tool="another version")
        t, doc = target([TENDER_URL])
        with mock.patch.object(docsource, "listing",
                               side_effect=self.listing(self.held_listing(), self.fresh())) as lister, \
                mock.patch.object(docsource, "download",
                                  side_effect=lambda p, e: (self.CONTENTS[e["id"]], None)) as down:
            done = dk_fetch.fetch(t, self.out, doc, held=held)
        self.assertIsNone(lister.call_args_list[-1].kwargs.get("held"))
        self.assertEqual(down.call_count, 2)
        self.assertEqual(done["documents"], 2)
        self.assertEqual(done["carried"], 0)


# ---------------------------------------------------------------- the delivery

class FillCarried(unittest.TestCase):

    ROOT = "Tenders/DK/tenders/" + PROCEDURE

    def setUp(self):
        offline(self)
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        os.makedirs(os.path.join(self.home, "doc"))
        with open(os.path.join(self.home, "doc", "k1.md"), "w", encoding="utf-8") as fh:
            fh.write("on disk")
        self.current = {"documents": {"k1": {}, "k2": {}, "k3": {}}}
        self.asked = []

    def archive(self, members):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, "w") as z:
            for name, text in members.items():
                z.writestr(name, text)
        return raw.getvalue()

    def drive(self, answers):
        def bytes_at(drive, path, tok):
            self.asked.append(path)
            return answers.get(path)
        return bytes_at

    def read(self, key):
        with open(os.path.join(self.home, "doc", key + ".md"), encoding="utf-8") as fh:
            return fh.read()

    def fill(self, answers):
        with mock.patch.object(deliver_graph, "bytes_at", side_effect=self.drive(answers)):
            return deliver_dk.fill_carried(self.home, PROCEDURE, self.ROOT, self.current,
                                           "drive", "tok")

    def test_from_the_archive_then_one_by_one(self):
        zipped = self.archive({"doc/k1.md": "from the archive", "doc/k2.md": "k2 text"})
        missing = self.fill({self.ROOT + "/" + PROCEDURE + ".zip": zipped,
                             self.ROOT + "/doc/k3.md": b"k3 text"})
        self.assertEqual(missing, 0)
        self.assertEqual(self.asked[0], self.ROOT + "/" + PROCEDURE + ".zip")
        self.assertEqual(self.read("k1"), "on disk")
        self.assertEqual(self.read("k2"), "k2 text")
        self.assertEqual(self.read("k3"), "k3 text")
        self.assertNotIn(self.ROOT + "/doc/k1.md", self.asked)
        self.assertNotIn(self.ROOT + "/doc/k2.md", self.asked)

    def test_without_an_archive_each_is_asked_and_the_missing_counted(self):
        missing = self.fill({self.ROOT + "/doc/k2.md": b"k2 text"})
        self.assertEqual(missing, 1)
        self.assertEqual(self.read("k2"), "k2 text")
        self.assertFalse(os.path.exists(os.path.join(self.home, "doc", "k3.md")))
        self.assertEqual(self.read("k1"), "on disk")


if __name__ == "__main__":
    unittest.main()
