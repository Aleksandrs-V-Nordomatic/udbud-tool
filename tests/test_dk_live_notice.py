#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One tender read by hand: the portal first, TED when the portal knows nothing about it.

`dk_targets.one`, `dk_targets.procedure`, `dk_page.detail` and `dk_ted.procedure` are replaced;
`net.open_url` fails loudly, so anything that slipped through would be an error.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dk_day
import dk_page
import dk_targets
import dk_ted
import net

REFERENCE = "DK:88888888-8888-4888-8888-888888888888"
PROCEDURE = "88888888-8888-4888-8888-888888888888"


def target(notice_id, npn="", ref=""):
    return {"pid": PROCEDURE, "ref": ref or npn, "notice_id": notice_id, "notice_version": "02",
            "npn": npn}


def no_network(*args, **kwargs):
    raise AssertionError("a test reached the network")


class LiveNotice(unittest.TestCase):

    def setUp(self):
        self.portal = target("n-portal", npn="00600001-2026")
        self.portal_detail = {"htmlDA": "<p>udbud.dk</p>", "htmlEN": "", "opsummeringDA": {}}
        self.from_ted = target("n-ted", npn="00699999-2026")
        self.ted_document = {"record": {}, "text": "TED"}
        self.one = self.replace(dk_targets, "one", None)
        self.procedure = self.replace(dk_targets, "procedure", [])
        self.detail = self.replace(dk_page, "detail", self.portal_detail)
        self.ted = self.replace(dk_ted, "procedure", (None, None))
        patcher = mock.patch.object(net, "open_url", side_effect=no_network)
        patcher.start()
        self.addCleanup(patcher.stop)

    def replace(self, module, name, answer):
        patcher = mock.patch.object(module, name, autospec=True, return_value=answer)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def live(self):
        """The portal holds a live notice of the procedure."""
        self.one.return_value = self.portal
        self.procedure.return_value = [self.portal]

    def test_the_portals_live_notice_comes_with_its_detail(self):
        self.live()
        found, document = dk_day.live_notice(REFERENCE)
        self.assertEqual(found["notice_id"], "n-portal")
        self.assertEqual(found["pid"], PROCEDURE)
        self.assertEqual(document, self.portal_detail)
        self.one.assert_called_once_with(REFERENCE)
        self.detail.assert_called_once_with("n-portal", "02", "00600001-2026")

    def test_a_live_notice_of_the_portal_is_not_asked_of_ted(self):
        self.live()
        self.ted.return_value = (self.from_ted, self.ted_document)
        found, document = dk_day.live_notice(REFERENCE)
        self.assertEqual(found["notice_id"], "n-portal")
        self.ted.assert_not_called()

    def test_one_the_portal_knows_nothing_about_is_read_from_ted(self):
        self.ted.return_value = (self.from_ted, self.ted_document)
        found, document = dk_day.live_notice(REFERENCE)
        self.assertEqual(found, self.from_ted)
        self.assertEqual(document, self.ted_document)
        self.ted.assert_called_once_with(REFERENCE)
        self.detail.assert_not_called()

    def test_one_the_portal_knows_but_not_live_is_not_looked_for_on_ted(self):
        self.procedure.return_value = [target("n-result", npn="00590000-2026")]
        self.ted.return_value = (self.from_ted, self.ted_document)
        self.assertEqual(dk_day.live_notice(REFERENCE), (None, None))
        self.procedure.assert_called_with(REFERENCE)
        self.ted.assert_not_called()

    def test_one_neither_holds_is_none(self):
        self.assertEqual(dk_day.live_notice(REFERENCE), (None, None))
        self.ted.assert_called_once_with(REFERENCE)
        self.detail.assert_not_called()

    def test_an_error_of_the_portals_lookup_is_raised(self):
        self.ted.return_value = (self.from_ted, self.ted_document)
        for lookup in (self.one, self.procedure):
            with self.subTest(lookup=lookup):
                lookup.side_effect = net.Unreachable("gave up")
                with self.assertRaises(net.Unreachable):
                    dk_day.live_notice(REFERENCE)
                lookup.side_effect = None
        self.ted.assert_not_called()

    def test_an_error_of_the_portals_detail_is_raised(self):
        self.live()
        self.detail.side_effect = net.Unreachable("gave up")
        with self.assertRaises(net.Unreachable):
            dk_day.live_notice(REFERENCE)
        self.ted.assert_not_called()

    def test_an_error_of_ted_is_raised(self):
        self.ted.side_effect = net.Unreachable("gave up")
        with self.assertRaises(net.Unreachable):
            dk_day.live_notice(REFERENCE)


if __name__ == "__main__":
    unittest.main()
