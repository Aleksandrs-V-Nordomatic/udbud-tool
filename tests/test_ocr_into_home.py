#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scans, read by OCR, reach the home: `dk_fetch.adopt_ocr` turns the lane's texts into
`doc/ocr-<sha256[:16]>.md` and names them in `index.json`; the lane skips a file that is not on
the runner's disk; a held scan nobody has read is downloaded again so the lane can read it once
(`dk_fetch.needs_ocr`); the delivery sends every `doc/ocr-*.md`; `eis_tool.py scans` adopts after
the lane.

`adopt_ocr` is tested on a home written by hand in the shapes the brief gives. The carry tests use
`test_carry_over.HomeCase`: the home is made by a first `dk_fetch.fetch`, here with a one-page PDF
that has no text layer, so its index and text manifest are the tool's own. The delivery tests make
the day as `test_index_moved.py` does and fake the drive the same way. The lane tests use the pack
of `test_assist.py`. `net.open_url` fails loudly everywhere. Written without running it: no tool in
the room executes code.

Open questions (QUESTIONS.md is being edited elsewhere today, so they stand here):

1. **The name in `# <file name>`**: the lane document's `file`, or the index entry's `name`? The
   tests give both the same value.
2. **The second line**: "OCR transcription of a scan (Tesseract and its languages), to be checked
   against the file before it is quoted". The tests check only that it holds `ocr` and `tesseract`,
   in any case of letters. Are the languages written `dan+eng`, or "Danish and English"? Are there
   blank lines between the heading, that line and the text? The tests allow them.
3. **`chars`**: the length in characters of `llm/<sha256>.md` as read, or stripped, or the lane
   manifest's `chars`? The tests make all three equal: ASCII text with no space at either end.
4. **The count** when a text is read but its index entry already has a `doc` (left alone), or when
   no index document has that sha256: is it counted, and is `doc/ocr-....md` still written? Not
   tested; the count test only uses texts that match an entry without a `doc`.
5. **Adopting twice**: does a second `adopt_ocr` answer 0 (every entry now has a `doc`), or the same
   count again? Not tested.
6. **An `unread` entry**: does it get `chars` too, or keep its own? Only `ocr` is checked. Nor is it
   stated what happens when the same sha256 is both in `documents` and in `skipped_files`.
7. **`needs_ocr` and the text entries**: the brief names `kind` and `note`. Which of them says
   `no text layer`, and is it a match of the start, or anywhere? The tests take the text manifest from
   the tool's own extractor run on a blank PDF and do not build that entry by hand. A blank
   one-page PDF is taken to be what the extractor names `no text layer`. If it names it otherwise,
   the carry tests fail in their preconditions, not in what they test.
8. **`ocr: "unread"` and `needs_ocr`**: the README says a file "whose index entry has no `doc` and
   no `ocr`" is downloaded, so an `unread` scan is carried and not tried again. The tests say so.
   Is that what is meant (a file the lane got nothing from is never tried again while it is held)?
9. **A scan downloaded again whose bytes are the record's**: is its file name the held one? Not
   tested; the tests check only that `originals/` holds its bytes. Is it counted as `carried`? The
   tests say it is not, because "not carried ... by its digest".
10. **"A tender that moved"** in the delivery: the tests use a new home (no `state.json` on the
    drive). A procurement that is `changed` is not tested, because the shape of `state.json` that
    would make the fingerprint move is not stated.
11. **The order of uploads** of an unmoved tender: the tests check `doc/ocr-*.md` comes before
    `index.json`. Must it also be before `runs/<date>.json` and `seen.json`? Not tested. For a home
    that moved, the order is not stated and not tested.
12. **`eis_tool.py scans`**: the arguments `read_scans` is called with are not stated, so the tests
    only check it was called, with the lane manifest already in the home. Where the home is found
    (`<out>/DK/tenders/<pid>`, or a field of the day row) is not stated; the tests use a day made by
    `dk_day.run`. The exit code is not stated and not checked. A home with a lane manifest but no
    text manifest is taken to be neither read nor adopted.
13. **`source-not-on-disk`**: is it written to `skipped_files` with the entry's `file` and
    `sha256`? The tests check `skipped` and `sha256`.
14. **The same Comdia rule for a scan whose host says no and whose listing was not `held`**: a Comdia
    file downloaded from the archive is like any other host's. Not tested beyond the `held` case.
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
if HERE not in sys.path:
    sys.path.insert(1, HERE)

import assist
import changes
import deliver_dk
import deliver_graph
import dk_day
import dk_fetch
import dk_page
import dk_recon
import dk_targets
import docsource
import eis_tool
import homes
import net
from test_assist import Recorder, pack_with, scan
from test_carry_over import ALPHA, GRAPH, HomeCase, entry, sha
from test_dk_day_newest import DATE, OLD, P1, POLICY, detail, no_network
from test_dk_fetch import PROCEDURE, target
from test_docsource import TENDER_URL, VENDOR_URL

BASE = "Tenders/DK"
HOME = BASE + "/tenders/" + P1

A = "0123456789abcdef" * 4
B = "fedcba9876543210" * 4
C = "1111222233334444" * 4
D = "aaaabbbbccccdddd" * 4

TEXT_A = "Udbudsbetingelser\n\n1. Ordregiver: Eksempel Kommune\n2. Frist: 2. oktober 2026"
TEXT_C = "Tilbudsliste\n\nPos. 1 Ventilation"


def blank_pdf(width=595):
    """A one-page PDF with nothing on the page: no text layer."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d 842] >>" % width]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1,
                                                                             xref)
    return bytes(out)


SCAN = blank_pdf()


def ocr_name(digest):
    return "ocr-%s.md" % digest[:16]


def write_json(path, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(body, fh)


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_lane(home, read=(), skipped=()):
    """The lane's manifest and its texts, as `assist.run` leaves them in `<home>/llm/`.
    `read` is (file, sha256, text); `skipped` is (file, sha256, reason skipped)."""
    documents = []
    for name, digest, text in read:
        path = os.path.join(home, "llm", digest + ".md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(text.encode("utf-8"))
        documents.append({"file": name, "sha256": digest, "chars": len(text),
                          "markdown": "llm/%s.md" % digest, "source": "tesseract",
                          "model": "dan+eng"})
    skipped_files = [{"file": name, "bytes": 1000, "sha256": digest,
                      "reason": "no text layer — a scan or a vector drawing", "skipped": why}
                     for name, digest, why in skipped]
    write_json(os.path.join(home, "llm", "manifest_llm.json"),
               {"provider": "tesseract", "model": "dan+eng", "extraction": "ocr-fallback",
                "documents": documents, "skipped_files": skipped_files,
                "read": len(documents)})


def index_doc(rid, name, digest, **kw):
    body = {"id": rid, "name": name, "sha256": digest, "chars": 0}
    body.update(kw)
    return body


def no_drive(case):
    env = mock.patch.dict(os.environ)
    env.start()
    case.addCleanup(env.stop)
    for name in GRAPH:
        os.environ.pop(name, None)
    opener = mock.patch.object(net, "open_url", side_effect=no_network)
    opener.start()
    case.addCleanup(opener.stop)


# ---------------------------------------------------------------- into the home

class Adopt(unittest.TestCase):

    def setUp(self):
        no_drive(self)
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        self.index = {"pid": PROCEDURE, "documents_available": "public",
                      "notice_document": "doc/notice.md",
                      "documents": [index_doc("s-a", "Udbudsbetingelser.pdf", A),
                                    index_doc("s-b", "Tegning.pdf", B),
                                    index_doc("t-1", "Bilag.docx", D, doc="doc/k1.md", chars=17)]}
        write_json(os.path.join(self.home, "index.json"), self.index)

    def index_now(self):
        return read_json(os.path.join(self.home, "index.json"))

    def entry_now(self, rid):
        for one in self.index_now()["documents"]:
            if one["id"] == rid:
                return one
        self.fail("no index document %s" % rid)

    def ocr_text(self, digest):
        with open(os.path.join(self.home, "doc", ocr_name(digest)), encoding="utf-8") as fh:
            return fh.read()

    def ocr_files(self):
        where = os.path.join(self.home, "doc")
        if not os.path.isdir(where):
            return []
        return sorted(n for n in os.listdir(where) if n.startswith("ocr-"))

    def test_a_read_text_becomes_its_ocr_document(self):
        write_lane(self.home, read=[("Udbudsbetingelser.pdf", A, TEXT_A)])
        dk_fetch.adopt_ocr(self.home)
        self.assertEqual(self.ocr_files(), [ocr_name(A)])
        self.assertEqual(ocr_name(A), "ocr-0123456789abcdef.md")
        lines = self.ocr_text(A).split("\n")
        self.assertEqual(lines[0], "# Udbudsbetingelser.pdf")
        rest = [line for line in lines[1:] if line.strip()]
        self.assertIn("ocr", rest[0].lower())
        self.assertIn("tesseract", rest[0].lower())
        body = "\n".join(lines[1:])
        self.assertIn(TEXT_A, body)
        self.assertGreater(body.index(TEXT_A), body.lower().index("tesseract"))

    def test_the_index_document_gets_doc_chars_and_ocr_read(self):
        write_lane(self.home, read=[("Udbudsbetingelser.pdf", A, TEXT_A)])
        dk_fetch.adopt_ocr(self.home)
        adopted = self.entry_now("s-a")
        self.assertEqual(adopted["doc"], "doc/" + ocr_name(A))
        self.assertEqual(adopted["chars"], len(TEXT_A))
        self.assertEqual(adopted["ocr"], "read")
        self.assertEqual((adopted["id"], adopted["name"], adopted["sha256"]),
                         ("s-a", "Udbudsbetingelser.pdf", A))

    def test_the_rest_of_the_index_is_kept(self):
        write_lane(self.home, read=[("Udbudsbetingelser.pdf", A, TEXT_A)])
        dk_fetch.adopt_ocr(self.home)
        now = self.index_now()
        for key in ("pid", "documents_available", "notice_document"):
            self.assertEqual(now[key], self.index[key])
        self.assertEqual([d["id"] for d in now["documents"]], ["s-a", "s-b", "t-1"])
        self.assertEqual(self.entry_now("s-b"), self.index["documents"][1])

    def test_a_scan_the_provider_got_nothing_from_is_unread(self):
        write_lane(self.home, skipped=[("Tegning.pdf", B, "provider-error: provider refused "
                                                           "(500): boom")])
        dk_fetch.adopt_ocr(self.home)
        unread = self.entry_now("s-b")
        self.assertEqual(unread["ocr"], "unread")
        self.assertNotIn("doc", unread)
        self.assertEqual(self.ocr_files(), [])

    def test_any_provider_reason_is_unread(self):
        write_lane(self.home, skipped=[("Udbudsbetingelser.pdf", A, "provider-empty"),
                                       ("Tegning.pdf", B, "provider-error: timeout")])
        dk_fetch.adopt_ocr(self.home)
        self.assertEqual(self.entry_now("s-a")["ocr"], "unread")
        self.assertEqual(self.entry_now("s-b")["ocr"], "unread")

    def test_a_scan_the_lane_did_not_try_is_left_alone(self):
        for why in ("source-not-on-disk", "over-the-run-limit", "source-not-retained",
                    "drawing-not-sent", "reason-not-selected"):
            write_json(os.path.join(self.home, "index.json"), self.index)
            write_lane(self.home, skipped=[("Tegning.pdf", B, why)])
            dk_fetch.adopt_ocr(self.home)
            self.assertEqual(self.entry_now("s-b"), self.index["documents"][1], why)

    def test_an_index_document_with_a_doc_of_its_own_is_left_alone(self):
        write_lane(self.home, read=[("Bilag.docx", D, "Bilag, read by OCR")],
                   skipped=[])
        dk_fetch.adopt_ocr(self.home)
        self.assertEqual(self.entry_now("t-1"), self.index["documents"][2])
        write_json(os.path.join(self.home, "index.json"), self.index)
        write_lane(self.home, skipped=[("Bilag.docx", D, "provider-error: boom")])
        dk_fetch.adopt_ocr(self.home)
        self.assertEqual(self.entry_now("t-1"), self.index["documents"][2])

    def test_it_answers_how_many_texts_it_adopted(self):
        self.index["documents"].append(index_doc("s-c", "Tilbudsliste.pdf", C))
        write_json(os.path.join(self.home, "index.json"), self.index)
        write_lane(self.home, read=[("Udbudsbetingelser.pdf", A, TEXT_A),
                                    ("Tilbudsliste.pdf", C, TEXT_C)],
                   skipped=[("Tegning.pdf", B, "provider-error: boom")])
        self.assertEqual(dk_fetch.adopt_ocr(self.home), 2)
        self.assertEqual(self.ocr_files(), sorted([ocr_name(A), ocr_name(C)]))
        self.assertEqual(self.entry_now("s-c")["doc"], "doc/" + ocr_name(C))
        self.assertEqual(self.entry_now("s-c")["chars"], len(TEXT_C))

    def test_nothing_without_a_lane_manifest(self):
        path = os.path.join(self.home, "index.json")
        with open(path, "rb") as fh:
            before = fh.read()
        self.assertEqual(dk_fetch.adopt_ocr(self.home), 0)
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), before)
        self.assertEqual(self.ocr_files(), [])

    def test_an_empty_lane_adopts_nothing(self):
        write_lane(self.home)
        self.assertEqual(dk_fetch.adopt_ocr(self.home), 0)
        self.assertEqual(self.index_now()["documents"], self.index["documents"])
        self.assertEqual(self.ocr_files(), [])


# ---------------------------------------------------------------- read once: the lane

class LaneOnDisk(unittest.TestCase):

    def test_a_file_absent_from_the_disk_is_skipped_and_the_next_is_read(self):
        gone, kept = "c" * 64, "a" * 64
        pack = pack_with([scan(name="gone.pdf", digest=gone), scan(name="kept.pdf", digest=kept)],
                         [("gone.pdf", gone, b"%PDF-1.4 carried"),
                          ("kept.pdf", kept, b"%PDF-1.4 here")])
        self.addCleanup(shutil.rmtree, pack, True)
        os.remove(os.path.join(pack, "documents", "current", "gone.pdf"))
        provider = Recorder()
        doc = assist.run(pack, send_fn=provider, pace=0, provider="tesseract")
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]["bytes"], len(b"%PDF-1.4 here"))
        self.assertEqual([d["sha256"] for d in doc["documents"]], [kept])
        skipped = [s for s in doc["skipped_files"] if s["sha256"] == gone]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["skipped"], "source-not-on-disk")
        self.assertFalse(os.path.exists(os.path.join(pack, "llm", gone + ".md")))
        written = read_json(os.path.join(pack, "llm", "manifest_llm.json"))
        self.assertIn("source-not-on-disk", [s["skipped"] for s in written["skipped_files"]])

    def test_only_a_file_absent_is_not_an_error(self):
        gone = "c" * 64
        pack = pack_with([scan(name="gone.pdf", digest=gone)],
                         [("gone.pdf", gone, b"%PDF-1.4 carried")])
        self.addCleanup(shutil.rmtree, pack, True)
        os.remove(os.path.join(pack, "documents", "current", "gone.pdf"))
        provider = Recorder()
        doc = assist.run(pack, send_fn=provider, pace=0, provider="tesseract")
        self.assertEqual(provider.calls, [])
        self.assertEqual(doc["documents"], [])
        self.assertEqual([s["skipped"] for s in doc["skipped_files"]], ["source-not-on-disk"])


# ---------------------------------------------------------------- read once: the carry

def scan_files():
    return [entry("rev-a", "a.txt", download="https://node1.field.dalux.com/f/rev-a"),
            entry("rev-s", "scan.pdf", download="https://node1.field.dalux.com/f/rev-s")]


class ReadOnce(HomeCase):

    def scan_home(self, platform="dalux", files=None, contents=None):
        held = self.first(platform, files or scan_files(),
                          contents or {"rev-a": ALPHA, "rev-s": SCAN})
        carry = dk_fetch.carriable(held, changes.pipeline_version())
        sid = [f["id"] for f in (files or scan_files()) if f["name"] == "scan.pdf"][0]
        self.assertIn(sid, carry, "precondition: the scan has an index entry and one file")
        self.assertFalse(carry[sid]["doc"].get("doc"), "precondition: nothing read from the scan")
        self.assertNotIn("ocr", carry[sid]["doc"])
        return held, carry, sid

    def set_index(self, held, rid, **fields):
        held = copy.deepcopy(held)
        for one in held["index"]["documents"]:
            if one["id"] == rid:
                one.update(fields)
        return held

    def original_bytes(self):
        out = {}
        for name in self.originals():
            with open(os.path.join(self.home, "originals", name), "rb") as fh:
                out[name] = fh.read()
        return out

    def index_entry(self, rid):
        for one in self.read_json("index.json")["documents"]:
            if one["id"] == rid:
                return one
        self.fail("no index document %s" % rid)

    def test_needs_ocr_for_a_held_scan_nobody_read(self):
        held, carry, sid = self.scan_home()
        self.assertIs(dk_fetch.needs_ocr(carry[sid]), True)

    def test_a_file_with_text_needs_no_ocr(self):
        held, carry, sid = self.scan_home()
        self.assertIs(dk_fetch.needs_ocr(carry["rev-a"]), False)

    def test_a_scan_with_a_doc_or_an_ocr_mark_needs_no_ocr(self):
        held, carry, sid = self.scan_home()
        one = carry[sid]
        for doc in (dict(one["doc"], ocr="unread"),
                    dict(one["doc"], ocr="read", doc="doc/" + ocr_name(sha(SCAN)), chars=12),
                    dict(one["doc"], doc="doc/k.md")):
            self.assertIs(dk_fetch.needs_ocr(dict(one, doc=doc)), False, doc)

    def test_the_hosts_word_does_not_carry_it(self):
        held, carry, sid = self.scan_home()
        self.assertIs(docsource.unchanged("dalux", scan_files()[1], carry[sid]["doc"]), True,
                      "precondition: Dalux says the scan is the same")
        done, asked = self.fetch("dalux", scan_files(), {"rev-s": SCAN}, held=held)
        self.assertEqual(asked, ["rev-s"])
        self.assertEqual(done["carried"], 1)
        self.assertEqual(done["bytes"], len(SCAN))
        self.assertEqual(list(self.original_bytes().values()), [SCAN])
        self.assertEqual({d["id"] for d in self.read_json("index.json")["documents"]},
                         {"rev-a", "rev-s"})

    def test_store_downloads_and_writes_it(self):
        held, carry, sid = self.scan_home()
        with mock.patch.object(docsource, "download", return_value=(SCAN, None)) as down:
            records, withheld, nbytes, carried = dk_fetch.store(self.home, "dalux",
                                                                scan_files(), carry)
        self.assertEqual([c.args[1]["id"] for c in down.call_args_list], ["rev-s"])
        self.assertEqual(set(carried), {"rev-a"})
        self.assertEqual(nbytes, len(SCAN))
        stored = [r for r in records if r["id"] == "rev-s"][0]["files"][0]
        self.assertEqual(stored["sha256"], sha(SCAN))
        with open(os.path.join(self.home, "originals", stored["filename"]), "rb") as fh:
            self.assertEqual(fh.read(), SCAN)

    def test_its_digest_does_not_carry_it(self):
        files = [entry("1", "a.txt"), entry("s", "scan.pdf")]
        held, carry, sid = self.scan_home("api.udbud.dk", files, {"1": ALPHA, "s": SCAN})
        done, asked = self.fetch("api.udbud.dk", files, {"1": ALPHA, "s": SCAN}, held=held)
        self.assertEqual(sorted(asked), ["1", "s"])
        self.assertEqual(done["carried"], 1)
        self.assertEqual(list(self.original_bytes().values()), [SCAN])

    def test_a_scan_the_lane_got_nothing_from_is_carried(self):
        held, carry, sid = self.scan_home()
        held = self.set_index(held, sid, ocr="unread")
        done, asked = self.fetch("dalux", scan_files(), {}, held=held)
        self.assertEqual(asked, [])
        self.assertEqual(done["carried"], 2)
        self.assertEqual(self.originals(), [])

    def test_a_carried_scan_keeps_what_the_lane_made(self):
        held, carry, sid = self.scan_home()
        made = {"doc": "doc/" + ocr_name(sha(SCAN)), "chars": 1234, "ocr": "read"}
        held = self.set_index(held, sid, **made)
        done, asked = self.fetch("dalux", scan_files(), {}, held=held)
        self.assertEqual(asked, [])
        self.assertEqual(done["carried"], 2)
        kept = self.index_entry(sid)
        for key, value in made.items():
            self.assertEqual(kept[key], value, key)

    def test_a_carried_unread_scan_keeps_its_mark(self):
        held, carry, sid = self.scan_home()
        held = self.set_index(held, sid, ocr="unread")
        self.fetch("dalux", scan_files(), {}, held=held)
        self.assertEqual(self.index_entry(sid)["ocr"], "unread")

    def test_a_comdia_file_handed_over_from_the_index_is_still_carried(self):
        files = [entry("zip:144703/Udbud/a.txt", "a.txt", download=VENDOR_URL),
                 entry("zip:144703/Udbud/scan.pdf", "scan.pdf", download=VENDOR_URL)]
        contents = {files[0]["id"]: ALPHA, files[1]["id"]: SCAN}
        held, carry, sid = self.scan_home("comdia", files, contents)
        self.assertIs(dk_fetch.needs_ocr(carry[sid]), True)
        held_listing = {"host": "www.comdia.com", "platform": "comdia", "access": "public",
                        "files": [dict(f, held=True) for f in files], "gated": [],
                        "listing": "sig", "unchanged": True, "note": "kept"}
        fresh = {"host": "www.comdia.com", "platform": "comdia", "access": "public",
                 "files": [dict(f) for f in files], "gated": [], "listing": "sig"}

        def answer(urls, facts=None, held=None):
            return held_listing if held is not None else fresh

        t, doc = target([TENDER_URL])
        with mock.patch.object(docsource, "listing", side_effect=answer), \
                mock.patch.object(docsource, "download", side_effect=AssertionError("downloaded")):
            done = dk_fetch.fetch(t, self.out, doc, held=held)
        self.assertEqual(done["carried"], 2)
        self.assertEqual(done["bytes"], 0)
        self.assertEqual(self.originals(), [])


# ---------------------------------------------------------------- a day with a home on disk

class DayCase(unittest.TestCase):

    def setUp(self):
        no_drive(self)
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.out = os.path.join(self.root, "DK")
        os.makedirs(self.out)
        page = {"resultatElementDtoList": [OLD], "totaltAntalResultater": 1}
        with mock.patch.object(dk_page, "search", return_value=page), \
                mock.patch.object(dk_page, "detail",
                                  side_effect=lambda nid, v, npn, timeout=60: detail(P1)), \
                mock.patch.object(dk_targets, "procedure",
                                  side_effect=lambda ref: [dk_page.notice(OLD)]), \
                mock.patch.object(dk_targets, "one", side_effect=lambda ref: None), \
                mock.patch.object(dk_recon, "ted_numbers",
                                  side_effect=lambda d: {"600001-2026"} if d == DATE else set()), \
                mock.patch.object(homes, "held", return_value=None):
            day, _ = dk_day.run(DATE, self.out, policy=POLICY, run_id="test")
        self.assertEqual([t["pid"] for t in day["tenders"]], [P1])
        self.home = os.path.join(self.out, "tenders", P1)

    def write_ocr(self, digest, text):
        path = os.path.join(self.home, "doc", ocr_name(digest))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return "doc/" + ocr_name(digest)


def as_text(data):
    if isinstance(data, (bytes, bytearray)):
        return data.decode("utf-8")
    if isinstance(data, str):
        return data
    return json.dumps(data)


class Delivered(DayCase):

    def setUp(self):
        super().setUp()
        self.state = read_json(os.path.join(self.home, "state.json"))

    def deliver(self, drive, run_id="run-2"):
        self.uploads, self.order = {}, []

        def json_at(d, path, tok):
            return copy.deepcopy(drive.get(path))

        def bytes_at(d, path, tok):
            return None

        def upload(d, dest, data, tok):
            self.order.append(dest)
            self.uploads[dest] = data

        with mock.patch.object(deliver_graph, "json_at", side_effect=json_at), \
                mock.patch.object(deliver_graph, "bytes_at", side_effect=bytes_at), \
                mock.patch.object(deliver_graph, "upload", side_effect=upload):
            return deliver_dk.deliver(self.out, DATE, run_id, "drive", BASE, "tok")

    def delivered_index(self):
        self.deliver({HOME + "/state.json": self.state}, run_id="run-1")
        self.assertIn(HOME + "/index.json", self.uploads, sorted(self.uploads))
        return json.loads(as_text(self.uploads[HOME + "/index.json"]))

    def name_in_index(self, rel, digest):
        path = os.path.join(self.home, "index.json")
        index = read_json(path)
        index["documents"] = list(index.get("documents") or []) + [
            index_doc("scan-1", "scan.pdf", digest, doc=rel, chars=len(TEXT_A), ocr="read")]
        write_json(path, index)

    def assert_sent(self, digest, text):
        dest = HOME + "/doc/" + ocr_name(digest)
        self.assertIn(dest, self.uploads, sorted(self.uploads))
        self.assertEqual(as_text(self.uploads[dest]).replace("\r\n", "\n"), text)
        return dest

    def test_an_unmoved_tender_sends_its_ocr_texts(self):
        drive = {HOME + "/state.json": self.state, HOME + "/index.json": self.delivered_index()}
        self.write_ocr(A, TEXT_A)
        self.write_ocr(C, TEXT_C)
        self.deliver(drive)
        self.assert_sent(A, TEXT_A)
        self.assert_sent(C, TEXT_C)

    def test_an_unmoved_tender_sends_them_before_its_index(self):
        drive = {HOME + "/state.json": self.state, HOME + "/index.json": self.delivered_index()}
        rel = self.write_ocr(A, TEXT_A)
        self.name_in_index(rel, A)
        self.assertEqual(changes.diff(self.state, read_json(os.path.join(self.home, "state.json")))
                         ["status"], "unchanged", "precondition: the fingerprint did not move")
        self.deliver(drive)
        sent = self.assert_sent(A, TEXT_A)
        self.assertIn(HOME + "/index.json", self.uploads, sorted(self.uploads))
        self.assertLess(self.order.index(sent), self.order.index(HOME + "/index.json"))
        record = json.loads(as_text(self.uploads[HOME + "/runs/%s.json" % DATE]))
        self.assertIn("documents", record["index_moved"])

    def test_a_tender_that_moved_sends_its_ocr_texts_with_the_home(self):
        rel = self.write_ocr(A, TEXT_A)
        self.name_in_index(rel, A)
        self.deliver({})
        self.assert_sent(A, TEXT_A)

    def test_only_ocr_texts_on_disk_are_sent(self):
        drive = {HOME + "/state.json": self.state, HOME + "/index.json": self.delivered_index()}
        self.deliver(drive)
        self.assertFalse([d for d in self.uploads if "/doc/ocr-" in d], sorted(self.uploads))


# ---------------------------------------------------------------- eis_tool.py scans

class Scans(DayCase):

    def setUp(self):
        super().setUp()
        normalized = os.path.join(self.home, "normalized", "manifest_normalized.json")
        if not os.path.exists(normalized):
            write_json(normalized, {"documents": [], "unreadable_files": [
                {"file": "scan.pdf", "bytes": 1000, "sha256": A, "reason": "no text layer"}]})
        path = os.path.join(self.home, "index.json")
        index = read_json(path)
        index["documents"] = list(index.get("documents") or []) + [
            index_doc("scan-1", "scan.pdf", A)]
        write_json(path, index)
        write_lane(self.home, read=[("scan.pdf", A, TEXT_A)])

    def scans(self):
        with mock.patch.object(eis_tool, "read_scans", return_value=0) as lane:
            try:
                eis_tool.main(["scans", "--out", self.root, "--date", DATE, "--country", "DK"])
            except SystemExit:
                pass
        return lane

    def scan_entry(self):
        for one in read_json(os.path.join(self.home, "index.json"))["documents"]:
            if one["id"] == "scan-1":
                return one
        self.fail("no scan in the index")

    def test_the_lane_runs_and_its_texts_are_adopted(self):
        lane = self.scans()
        self.assertTrue(lane.called)
        self.assertTrue(os.path.exists(os.path.join(self.home, "doc", ocr_name(A))))
        adopted = self.scan_entry()
        self.assertEqual(adopted["doc"], "doc/" + ocr_name(A))
        self.assertEqual(adopted["ocr"], "read")

    def test_a_home_without_a_text_manifest_is_neither_read_nor_adopted(self):
        os.remove(os.path.join(self.home, "normalized", "manifest_normalized.json"))
        lane = self.scans()
        self.assertFalse(lane.called)
        self.assertFalse(os.path.exists(os.path.join(self.home, "doc", ocr_name(A))))
        self.assertNotIn("ocr", self.scan_entry())


if __name__ == "__main__":
    unittest.main()
