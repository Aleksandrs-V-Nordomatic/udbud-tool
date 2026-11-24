#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dalux refuses a client older than it wants, and a refusal is not a tender that is not public.

The host is a stand-in for `docsource.common.fetch`; `net.open_url` fails loudly, and the
client version the module keeps for a run is put back after every test.
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import docsource
import net
from docsource import common, dalux

URL = "https://node1.build.dalux.com/da-dk/public/tender/TID-4711"
OURS = 2026070
NEWER = 2026080

FOLDER = {"files": [{"areaFileRevisionID": 11,
                     "properties": [{"matchName": "FileName", "value": "Udbudsbrev.pdf"}]}],
          "childrenVector": []}

HEALTHY = {"IsTenderPublic": {"result": 0, "value": True},
           "GetFileList": {"result": 0, "value": {"folder": FOLDER}}}

NOT_PUBLIC = {"result": 3, "message": "Tender cannot be accessed publicly"}
OTHER = {"result": 5, "message": "Something else went wrong"}


def refusal(version):
    return {"result": 9, "message": "Versions below %d not supported" % version}


def no_network(*args, **kwargs):
    raise AssertionError("a test reached the network: %r" % (args[:1],))


class Host(unittest.TestCase):

    def setUp(self):
        for patcher in (mock.patch.object(net, "open_url", side_effect=no_network),
                        mock.patch.dict(dalux.CLIENT, {"version": OURS}),
                        mock.patch.object(common, "fetch", side_effect=self.fetch)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sent = []
        # What the host says to a request, before its healthy answer: (command, version) -> answer.
        self.say = lambda command, version: None

    def fetch(self, url, data=None, headers=None, **kwargs):
        body = json.loads(data.decode("utf-8"))
        self.sent.append((body["command"], body["version"]))
        answer = self.say(body["command"], body["version"])
        if answer is None:
            answer = HEALTHY.get(body["command"], {"result": 0, "value": None})
        return json.dumps(answer).encode("utf-8")

    def wants(self, version):
        self.say = lambda command, sent: refusal(version) if sent < version else None

    def answers(self, command, answer):
        self.say = lambda asked, version: answer if asked == command else None

    def asked(self, command):
        return [version for name, version in self.sent if name == command]

    def names(self, found):
        return [f["name"] for f in found["files"]]


class ANewerVersion(Host):

    def test_the_version_is_adopted_and_the_files_are_listed(self):
        self.wants(NEWER)
        found = dalux.listing([URL])
        self.assertEqual(found["access"], "public")
        self.assertEqual(self.names(found), ["Udbudsbrev.pdf"])
        self.assertEqual(dalux.CLIENT["version"], NEWER)

    def test_one_retry_and_no_more(self):
        self.wants(NEWER)
        dalux._call("IsTenderPublic", {}, "TID-4711")
        self.assertEqual(self.sent, [("IsTenderPublic", OURS), ("IsTenderPublic", NEWER)])

    def test_the_answer_of_the_retry_is_the_answer(self):
        self.wants(NEWER)
        self.assertIs(dalux._call("IsTenderPublic", {}, "TID-4711")["value"], True)

    def test_it_is_kept_for_the_next_call(self):
        self.wants(NEWER)
        dalux._call("IsTenderPublic", {}, "TID-4711")
        del self.sent[:]
        dalux._call("GetFileList", {}, "TID-4711")
        self.assertEqual(self.sent, [("GetFileList", NEWER)])

    def test_it_is_kept_for_the_next_tender(self):
        self.wants(NEWER)
        dalux.listing([URL])
        del self.sent[:]
        dalux.listing([URL])
        self.assertTrue(self.sent)
        self.assertEqual({version for _, version in self.sent}, {NEWER})

    def test_a_refusal_first_met_at_the_file_list(self):
        self.say = lambda command, version: (
            refusal(NEWER) if command == "GetFileList" and version < NEWER else None)
        found = dalux.listing([URL])
        self.assertEqual(found["access"], "public")
        self.assertEqual(self.names(found), ["Udbudsbrev.pdf"])
        self.assertEqual(self.asked("GetFileList"), [OURS, NEWER])

    def test_through_docsource_it_is_not_a_failure(self):
        self.wants(NEWER)
        found = docsource.listing([URL])
        self.assertEqual(found["access"], "public")
        self.assertFalse(found.get("failed"))

    def test_a_host_that_takes_our_version_is_asked_once_per_command(self):
        dalux.listing([URL])
        self.assertEqual(self.asked("IsTenderPublic"), [OURS])
        self.assertEqual(self.asked("GetFileList"), [OURS])
        self.assertEqual(dalux.CLIENT["version"], OURS)


class ARefusalThatStands(Host):

    def test_our_own_version_named_does_not_loop(self):
        self.say = lambda command, version: refusal(OURS)
        with self.assertRaises(dalux.Refused):
            dalux._call("IsTenderPublic", {}, "TID-4711")
        self.assertEqual(self.sent, [("IsTenderPublic", OURS)])
        self.assertEqual(dalux.CLIENT["version"], OURS)

    def test_an_older_version_named_is_never_adopted(self):
        self.say = lambda command, version: refusal(OURS - 10)
        with self.assertRaises(dalux.Refused):
            dalux._call("IsTenderPublic", {}, "TID-4711")
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(dalux.CLIENT["version"], OURS)

    def test_a_retry_refused_again_raises(self):
        self.say = lambda command, version: refusal(version + 10)
        with self.assertRaises(dalux.Refused):
            dalux._call("IsTenderPublic", {}, "TID-4711")
        self.assertEqual(len(self.sent), 2, "one retry, never a loop")

    def test_any_other_result_raises_from_either_command(self):
        for command in ("IsTenderPublic", "GetFileList"):
            with self.subTest(command=command):
                self.answers(command, OTHER)
                del self.sent[:]
                with self.assertRaises(dalux.Refused):
                    dalux._call(command, {}, "TID-4711")
                self.assertEqual(len(self.sent), 1)

    def test_the_listing_does_not_swallow_it(self):
        for command in ("IsTenderPublic", "GetFileList"):
            with self.subTest(command=command):
                self.answers(command, OTHER)
                with self.assertRaises(dalux.Refused):
                    dalux.listing([URL])

    def test_refused_is_a_runtime_error(self):
        self.assertTrue(issubclass(dalux.Refused, RuntimeError))


class ThroughDocsource(Host):

    def assert_failed(self, found):
        self.assertEqual(found["access"], "unknown")
        self.assertIs(found["failed"], True)
        self.assertEqual(found["files"], [])
        self.assertEqual(found["gated"], [])
        self.assertEqual(found["host"], "node1.build.dalux.com")
        self.assertEqual(found["platform"], "dalux")
        self.assertTrue(found["note"])

    def test_a_version_not_newer_than_ours(self):
        self.say = lambda command, version: refusal(OURS)
        self.assert_failed(docsource.listing([URL]))

    def test_a_retry_refused_again(self):
        self.say = lambda command, version: refusal(version + 10)
        self.assert_failed(docsource.listing([URL]))

    def test_any_other_result_from_is_tender_public(self):
        self.answers("IsTenderPublic", OTHER)
        self.assert_failed(docsource.listing([URL]))

    def test_any_other_result_from_the_file_list(self):
        self.answers("GetFileList", OTHER)
        self.assert_failed(docsource.listing([URL]))


class NotPublic(Host):
    """The host saying so in words is an answer, so the tender is gated and nothing failed."""

    def test_said_by_either_command_is_gated(self):
        for command in ("IsTenderPublic", "GetFileList"):
            with self.subTest(command=command):
                self.answers(command, NOT_PUBLIC)
                found = dalux.listing([URL])
                self.assertEqual(found["access"], "gated")
                self.assertEqual(found["files"], [])

    def test_through_docsource_it_is_gated_and_not_failed(self):
        for command in ("IsTenderPublic", "GetFileList"):
            with self.subTest(command=command):
                self.answers(command, NOT_PUBLIC)
                found = docsource.listing([URL])
                self.assertEqual(found["access"], "gated")
                self.assertFalse(found.get("failed"))

    def test_a_false_value_is_still_gated(self):
        self.answers("IsTenderPublic", {"result": 0, "value": False})
        found = docsource.listing([URL])
        self.assertEqual(found["access"], "gated")
        self.assertFalse(found.get("failed"))


if __name__ == "__main__":
    unittest.main()
