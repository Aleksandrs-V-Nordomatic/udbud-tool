#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""An index that moved is delivered, even when the tender did not.

The home is made by a real `dk_day.run` over the window of `test_dk_day_newest` (one competition,
no documents link), so `day.json`, `changes.json`, `state.json` and `index.json` are the tool's
own. The drive is three stand-ins for `deliver_graph.json_at`, `bytes_at` and `upload`; the drive's
`state.json` is the home's own, so the procurement's fingerprint did not move. `net.open_url`
fails loudly and the five GRAPH_* variables are cleared.

The `index.json` on the drive is the delivered one: it carries what the delivery stamps (the run's
fields and the home's address). The tests take it from a first delivery with no index on the drive.
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

import changes
import deliver_dk
import deliver_graph
import dk_day
import dk_page
import dk_recon
import dk_targets
import homes
import net
from test_dk_day_newest import DATE, OLD, P1, POLICY, detail, no_network

GRAPH = ("GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET", "GRAPH_DRIVE_ID",
         "GRAPH_DEST_ROOT")
VOLATILE = ("written_at", "date", "run_id", "run_file")
ADDRESS = ("home", "archive", "index_file")
STAMPED = VOLATILE + ADDRESS

BASE = "Tenders/DK"
HOME = BASE + "/tenders/" + P1


def parsed(data):
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    if isinstance(data, str):
        return json.loads(data)
    return data


def steady(index, left_out=VOLATILE):
    return {k: v for k, v in index.items() if k not in left_out}


# ---------------------------------------------------------------- index_moves

class IndexMoves(unittest.TestCase):

    NEW = {"pid": P1, "documents_available": "gated", "documents_note": "a new note",
           "documents": [{"id": "a"}], "written_at": "2026-11-26T03:00:00Z",
           "date": "2026-11-25", "run_id": "r2", "run_file": "runs/2026-11-25.json",
           "home": "tenders/" + P1, "archive": P1 + ".zip", "index_file": "index.json"}

    def test_the_same_index_moved_nothing(self):
        self.assertEqual(deliver_dk.index_moves(dict(self.NEW), dict(self.NEW)), [])

    def test_the_fields_that_move_every_run_are_left_out(self):
        old = dict(self.NEW, written_at="2026-11-25T03:00:00Z", date="2026-11-24", run_id="r1",
                   run_file="runs/2026-11-24.json")
        self.assertEqual(deliver_dk.index_moves(old, dict(self.NEW)), [])

    def test_the_homes_address_is_left_out(self):
        old = dict(self.NEW, home="tenders/elsewhere", archive="elsewhere.zip",
                   index_file="elsewhere/index.json")
        self.assertEqual(deliver_dk.index_moves(old, dict(self.NEW)), [])
        self.assertEqual(deliver_dk.index_moves(steady(self.NEW, STAMPED), dict(self.NEW)), [])
        self.assertEqual(deliver_dk.index_moves(dict(self.NEW), steady(self.NEW, STAMPED)), [])

    def test_the_names_of_the_fields_that_differ_sorted(self):
        old = dict(self.NEW, documents_note="the old note", documents_available="public",
                   run_id="r1", home="tenders/elsewhere")
        self.assertEqual(deliver_dk.index_moves(old, dict(self.NEW)),
                         ["documents_available", "documents_note"])

    def test_a_field_is_named_by_its_top_level_name(self):
        old = dict(self.NEW, documents=[{"id": "a"}, {"id": "b"}])
        self.assertEqual(deliver_dk.index_moves(old, dict(self.NEW)), ["documents"])

    def test_a_field_the_old_index_lacks_has_moved(self):
        new = dict(self.NEW, documents_listing="signature")
        self.assertEqual(deliver_dk.index_moves(dict(self.NEW), new), ["documents_listing"])

    def test_with_no_old_index_every_field_of_the_new_one(self):
        self.assertEqual(deliver_dk.index_moves(None, dict(self.NEW)),
                         sorted(steady(self.NEW, STAMPED)))

    def test_with_no_old_index_and_no_stamped_fields_every_field(self):
        new = steady(self.NEW, STAMPED)
        self.assertEqual(deliver_dk.index_moves(None, new), sorted(new))


# ---------------------------------------------------------------- the delivery

class Delivered(unittest.TestCase):

    def setUp(self):
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for name in GRAPH:
            os.environ.pop(name, None)
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.out = os.path.join(self.root, "DK")
        os.makedirs(self.out)
        opener = mock.patch.object(net, "open_url", side_effect=no_network)
        opener.start()
        self.addCleanup(opener.stop)
        self.make_day()
        self.state = self.home_json("state.json")
        self.index = self.home_json("index.json")

    def make_day(self):
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

    def home_json(self, name):
        with open(os.path.join(self.out, "tenders", P1, name), encoding="utf-8") as fh:
            return json.load(fh)

    def deliver(self, drive, run_id="run-2"):
        self.asked, self.uploads = [], {}

        def json_at(d, path, tok):
            self.asked.append(path)
            return copy.deepcopy(drive.get(path))

        def bytes_at(d, path, tok):
            self.asked.append(path)
            return None

        def upload(d, dest, data, tok):
            self.uploads[dest] = data

        with mock.patch.object(deliver_graph, "json_at", side_effect=json_at), \
                mock.patch.object(deliver_graph, "bytes_at", side_effect=bytes_at), \
                mock.patch.object(deliver_graph, "upload", side_effect=upload):
            result = deliver_dk.deliver(self.out, DATE, run_id, "drive", BASE, "tok")
        return result

    def delivered_index(self):
        """The index a delivery uploads when the drive holds none: what a former run left."""
        self.deliver({HOME + "/state.json": self.state}, run_id="run-1")
        self.assertIn(HOME + "/index.json", self.uploads, sorted(self.uploads))
        return parsed(self.uploads[HOME + "/index.json"])

    def run_record(self):
        dest = HOME + "/runs/%s.json" % DATE
        self.assertIn(dest, self.uploads, sorted(self.uploads))
        return parsed(self.uploads[dest])

    def row(self):
        dest = "%s/%s/changes.json" % (BASE, DATE)
        self.assertIn(dest, self.uploads, sorted(self.uploads))
        rows = [r for r in parsed(self.uploads[dest])["tenders"] if r["pid"] == P1]
        self.assertEqual(len(rows), 1)
        return rows[0]

    def home_uploads(self):
        return {d[len(HOME) + 1:] for d in self.uploads if d.startswith(HOME + "/")}

    def assert_not_uploaded(self):
        self.assertNotIn(HOME + "/index.json", self.uploads)
        self.assertFalse(self.run_record().get("index_moved"))
        row = self.row()
        self.assertFalse(row.get("index_moved"))
        self.assertEqual(row["status"], "unchanged")
        self.assertTrue(self.home_uploads() <= {"seen.json", "runs/%s.json" % DATE},
                        sorted(self.home_uploads()))

    def test_the_fingerprint_on_the_drive_is_the_homes(self):
        self.assertEqual(changes.diff(self.state, copy.deepcopy(self.state))["status"],
                         "unchanged")

    def test_the_result_has_its_fields(self):
        result = self.deliver({HOME + "/state.json": self.state, HOME + "/index.json": self.index})
        for key in ("files", "bytes", "tally", "sent", "carried", "tenders"):
            self.assertIn(key, result)

    def test_the_delivered_index_carries_what_the_delivery_stamps(self):
        delivered = self.delivered_index()
        for key in STAMPED:
            self.assertIn(key, delivered)
        self.assertEqual(steady(delivered, STAMPED), steady(self.index, STAMPED))

    def test_a_moved_index_is_uploaded_on_its_own(self):
        delivered = self.delivered_index()
        old = dict(delivered, documents_link="https://elsewhere.invalid/old")
        self.deliver({HOME + "/state.json": self.state, HOME + "/index.json": old})
        self.assertIn(HOME + "/index.json", self.asked)
        self.assertIn(HOME + "/index.json", self.uploads)
        uploaded = parsed(self.uploads[HOME + "/index.json"])
        self.assertEqual(steady(uploaded), steady(delivered))
        self.assertEqual(steady(uploaded, STAMPED), steady(self.index, STAMPED))
        self.assertTrue(self.home_uploads() <= {"seen.json", "runs/%s.json" % DATE, "index.json"},
                        sorted(self.home_uploads()))

    def test_the_run_record_and_the_changes_row_name_what_moved(self):
        old = dict(self.delivered_index(), documents_link="https://elsewhere.invalid/old")
        self.deliver({HOME + "/state.json": self.state, HOME + "/index.json": old})
        self.assertEqual(self.run_record()["index_moved"], ["documents_link"])
        row = self.row()
        self.assertEqual(row["index_moved"], ["documents_link"])
        self.assertEqual(row["status"], "unchanged")

    def test_an_index_that_moved_only_in_its_run_fields_is_not_uploaded(self):
        old = dict(self.delivered_index(), written_at="2000-01-01T00:00:00Z", date="2000-01-01",
                   run_id="older", run_file="runs/2000-01-01.json")
        self.deliver({HOME + "/state.json": self.state, HOME + "/index.json": old})
        self.assert_not_uploaded()

    def test_an_index_that_moved_only_in_the_homes_address_is_not_uploaded(self):
        old = dict(self.delivered_index(), home="tenders/elsewhere", archive="elsewhere.zip",
                   index_file="tenders/elsewhere/index.json")
        self.deliver({HOME + "/state.json": self.state, HOME + "/index.json": old})
        self.assert_not_uploaded()

    def test_the_same_delivered_index_is_not_uploaded(self):
        self.deliver({HOME + "/state.json": self.state,
                      HOME + "/index.json": self.delivered_index()})
        self.assert_not_uploaded()

    def test_with_no_index_on_the_drive_it_is_uploaded(self):
        self.deliver({HOME + "/state.json": self.state})
        self.assertIn(HOME + "/index.json", self.uploads)
        uploaded = parsed(self.uploads[HOME + "/index.json"])
        moved = self.run_record()["index_moved"]
        self.assertIn("documents_link", moved)
        self.assertEqual(moved, sorted(moved))
        self.assertEqual(moved, sorted(steady(uploaded, STAMPED)))
        for key in STAMPED:
            self.assertNotIn(key, moved)
        row = self.row()
        self.assertEqual(row["index_moved"], moved)
        self.assertEqual(row["status"], "unchanged")


if __name__ == "__main__":
    unittest.main()
