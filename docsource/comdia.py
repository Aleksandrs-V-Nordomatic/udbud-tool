"""Comdia: nothing without an account, not even the file names.

Comdia carries the municipal tenders -- 9 of the 36 construction tenders of 3-14 Nov 2026 -- and
its tender page shows a login wall to an anonymous reader. No request is made: there is nothing
an anonymous request could learn, and the card carries the link.
"""
NAME = "comdia"


def listing(urls):
    return {"access": "gated", "files": [], "gated": [],
            "note": "Comdia shows nothing without an account"}


def download(entry):
    return None, "Comdia serves nothing without an account"
