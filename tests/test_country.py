#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One run, one country: never a default, never the wrong one, never `work/DK/DK`.

Also the CLI's reading of `--targets`, which is where a watched procedure id enters a run.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import country
import eis_tool
import policy


class Resolve(unittest.TestCase):

    def test_no_country_is_refused(self):
        with self.assertRaises(country.Mismatch):
            country.resolve(None, {})
        with self.assertRaises(country.Mismatch):
            country.resolve("  ", {})

    def test_a_country_with_no_reader_is_refused(self):
        for code in ("LV", "LT", "EE", "FI", "SE"):
            with self.assertRaises(country.Mismatch):
                country.resolve(code, {})

    def test_not_a_two_letter_code_is_refused(self):
        for code in ("DNK", "D", "D1", "dk-"):
            with self.assertRaises(country.Mismatch):
                country.resolve(code, {})

    def test_denmark_in_any_case(self):
        self.assertEqual(country.resolve("DK", {}), "DK")
        self.assertEqual(country.resolve(" dk ", {}), "DK")

    def test_from_the_environment(self):
        self.assertEqual(country.resolve(None, {"EIS_COUNTRY": "dk"}), "DK")
        with self.assertRaises(country.Mismatch):
            country.resolve(None, {"EIS_COUNTRY": "LV"})

    def test_the_flag_wins_over_the_environment(self):
        self.assertEqual(country.resolve("DK", {"EIS_COUNTRY": "LV"}), "DK")

    def test_describe_and_parser_files(self):
        self.assertEqual(country.describe("DK")["portal"], "udbud.dk")
        self.assertEqual(country.parser_files("DK"), ("dk_page.py",))
        with self.assertRaises(country.Mismatch):
            country.source("LV")


class Destination(unittest.TestCase):

    def test_the_country_is_appended(self):
        self.assertEqual(country.destination("Shared/Automations/work", "DK"),
                         "Shared/Automations/work/DK")
        self.assertEqual(country.destination("/work/", "dk"), "work/DK")

    def test_a_root_ending_in_a_country_code_is_refused(self):
        for root in ("Shared/work/DK", "Shared/work/dk", "Shared/work/LV/", "DK"):
            with self.assertRaises(country.Mismatch, msg=root):
                country.destination(root, "DK")

    def test_no_root_is_refused(self):
        for root in (None, "", " / "):
            with self.assertRaises(country.Mismatch):
                country.destination(root, "DK")

    def test_the_wrong_country_is_refused(self):
        with self.assertRaises(country.Mismatch):
            country.destination("Shared/work", "LV")


class ReadTargets(unittest.TestCase):

    def test_nothing(self):
        self.assertEqual(eis_tool.read_targets(None), [])
        self.assertEqual(eis_tool.read_targets(""), [])

    def test_a_comma_list(self):
        self.assertEqual(eis_tool.read_targets("DK:7C03C120-69C0-4112-AF76-3D30B1AAB18E, abc ,def"),
                         ["7c03c120-69c0-4112-af76-3d30b1aab18e", "abc", "def"])

    def test_deduplicated_in_order(self):
        self.assertEqual(eis_tool.read_targets("b,DK:A,a,dk:b,c"), ["b", "a", "c"])

    def test_a_file_one_per_line(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "targets.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("DK:7c03c120-69c0-4112-af76-3d30b1aab18e\n\nED2A934C-C8EB-4539-8E74-501F4F70AAA0\n"
                     "dk:7C03C120-69C0-4112-AF76-3D30B1AAB18E\n")
        self.assertEqual(eis_tool.read_targets(path),
                         ["7c03c120-69c0-4112-af76-3d30b1aab18e",
                          "ed2a934c-c8eb-4539-8e74-501f4f70aaa0"])


class PolicyName(unittest.TestCase):
    """README: "The real policy arrives in the `DK_POLICY` secret"; the CLI's `--policy` help:
    "JSON, a path to one, or DK_POLICY from the environment"."""

    FIXTURE = '{"recall_title_terms": ["alfa"]}'

    def test_dk_policy_from_the_environment_is_read(self):
        clean = {k: "" for k in ("DK_POLICY", "FI_POLICY", "EIS_POLICY", "LT_POLICY", "EE_POLICY")}
        clean["DK_POLICY"] = self.FIXTURE
        with mock.patch.dict(os.environ, clean):
            self.assertIsNotNone(policy.load_policy(None),
                                 "DK_POLICY is set and load_policy() read %s instead"
                                 % policy.POLICY_ENV)


if __name__ == "__main__":
    unittest.main()
