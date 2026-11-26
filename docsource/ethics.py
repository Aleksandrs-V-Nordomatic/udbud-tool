"""ethics.dk (Mercell's state-sector platform): a public JSON list and a public download.

    GET /ethics/publicTenderDocs/{tenderId}                 -> tenderDocs[]
    GET /ethics/publicTenderDoc/{tenderId}/{_id}/download   -> the file

`tenderId` is the UUID in the link's `#/<uuid>/publicMaterial` fragment. The list carries records
with no file at all (the ESPD form, response templates without a body) -- skipped by having no
`filename` -- and records marked `accessRequired`, which are named and not downloaded.
Measured 16 Nov 2026: 481 of 481 public files downloaded, every size equal to `length`.
"""
import json
import re

from docsource import common

NAME = "ethics"
LIST = "https://www.ethics.dk/ethics/publicTenderDocs/%s"
FILE = "https://www.ethics.dk/ethics/publicTenderDoc/%s/%s/download"
UUID = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.I)


def listing(urls):
    m = UUID.search(urls[0])
    if not m:
        return {"access": "unknown", "note": "no tender id in the link"}
    tender = m.group(1).lower()
    docs = json.loads(common.fetch(LIST % tender, headers={"Accept": "application/json"})
                      .decode("utf-8")).get("tenderDocs") or []
    files, gated = [], []
    for d in docs:
        if not d.get("filename"):
            continue
        if d.get("accessRequired"):
            gated.append(d["filename"])
            continue
        files.append({"id": d.get("_id"), "name": d["filename"], "bytes": d.get("length"),
                      "type": d.get("type"), "download": FILE % (tender, d.get("_id"))})
    access = ("none" if not files and not gated else
              "public" if not gated else "partial" if files else "gated")
    return {"access": access, "files": files, "gated": gated, "tender_id": tender}


def unchanged(entry, held):
    """The same record with the same name and the same `length`; a file without a length is
    downloaded."""
    return (entry.get("id") is not None and str(entry.get("id")) == str(held.get("id"))
            and entry.get("name") == held.get("name")
            and entry.get("bytes") is not None and entry.get("bytes") == held.get("bytes"))


def download(entry):
    return common.plain_download(entry, headers={"Accept": "*/*"})
