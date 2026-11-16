"""Mercell (permalink.mercell.com, now Acentio in Denmark): the names and sizes, no files.

The permalink page lists each file in a `rpFiles_ctl<N>_tdDownload` cell. The files open after
"Show interest", which the buyer sees. Measured 16 Nov 2026: 180 names on 14 tenders.
"""
import html as htmlmod
import re

from docsource import common

NAME = "mercell"


def listing(urls):
    page = common.fetch(urls[0]).decode("utf-8", "replace")
    names = [htmlmod.unescape(re.sub(r"<[^>]+>", " ", n)).strip()
             for n in re.findall(r'_tdDownload">\s*(.*?)\s*</td>', page, re.S)]
    names = [re.sub(r"\s+", " ", n) for n in names if n]
    return {"access": "gated" if names else "unknown", "files": [], "gated": names,
            "note": "" if names else "the page listed no files"}


def download(entry):
    return None, "Mercell serves files after Show interest, under an account"
