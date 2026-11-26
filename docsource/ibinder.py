"""iBinder: a tender's public view, read as an anonymous visitor.

    https://<my|bookshelf>.ibinder.com/etendering/<organisation>/tenders/<tender>/public

The link in a notice opens the tender as "Viewing tender as Anonymous": every folder, every file
name, and a viewer that shows the file. No account, nothing registered, and the buyer is told
nothing. The page is a script over a JSON API, and this module asks the same questions of it, with
the organisation in the `x-ibinder-tenantid` header:

    GET  api/etendering/tenders/<tender>                      the tender's name
    GET  .../configuration                                    its folders, and whether the link is public
    POST .../version/latest/procurementSections/<s>/documents one folder's files, a page at a time
    GET  .../procurementSections/<s>/documents/<d>/versions/<v>/preview
                                                              a short-lived link to what the viewer shows

THE PREVIEW IS WHAT IS READ, NOT THE ORIGINAL. The public view offers no download, so neither does
this module: it takes the PDF the viewer takes, for a pdf, docx, xlsx or dwg alike, and a file
whose original is not a PDF is stored as `<name>.pdf`. A file with no preview (zip, xml, xlsm) is
named and not read. The API also answers with the buyer's staff -- names, addresses, telephone
numbers -- on calls this module never makes.

A folder's `enabled` says nothing about what a visitor sees: the folders of a tender read on
24 Nov 2026 were all `enabled: false` and all open on the page. The ESPD folder is skipped: it
holds a form for the bidder.

Measured 24 Nov 2026 on four tenders: 344 of 349 files outside the ESPD folder have a preview.
"""
import json
import re
import urllib.error
import urllib.parse

from docsource import common

NAME = "ibinder"
LINK = re.compile(r"^https://((?:my|bookshelf)\.ibinder\.com)/etendering/"
                  r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})/tenders/([\w-]+)", re.I)
PAGE_SIZE = 250
MAX_PAGES = 40

# Where a preview link may lead. Anything else is not followed.
PREVIEW_HOST = re.compile(r"^[a-z0-9]+\.blob\.core\.windows\.net$")


def _ask(url, organisation, body=None, context=None):
    """One question to the API. Only the four above are built anywhere in this file."""
    headers = {"Accept": "application/json", "x-ibinder-tenantid": organisation}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    if context is not None:
        headers["x-ibinder-context"] = json.dumps(context)
    return json.loads(common.fetch(url, data=data, headers=headers).decode("utf-8"))


def folders(sections, path=()):
    """Every folder that can hold files, as `(section, path)`, in the buyer's order."""
    for section in sections or []:
        here = path + (str(section.get("name") or "").strip(),)
        if section.get("type") not in ("Navigation", "Espd"):
            yield section, here
        yield from folders(section.get("subTabs"), here)


def _filters(tender, name, section):
    return {"MetadataFilters": [
        {"required": True, "isDocumentMetadata": True, "value": name, "valueId": tender,
         "metadataElementId": "GLOBAL_TenderId"},
        {"required": True, "isDocumentMetadata": True, "value": section.get("name"),
         "valueId": section["id"], "metadataElementId": "GLOBAL_TenderSectionId"}], "SortBy": []}


def documents(base, organisation, tender, name, section):
    """One folder's files, every page of them."""
    rows, page = [], 1
    while page <= MAX_PAGES:
        answer = _ask("%s/version/latest/procurementSections/%s/documents?pageSize=%d&pageNumber=%d"
                      % (base, section["id"], PAGE_SIZE, page), organisation,
                      body=_filters(tender, name, section))
        got = answer.get("data") or []
        rows += got
        if not got or len(rows) >= (answer.get("totalCount") or 0):
            return rows
        page += 1
    raise ValueError("the folder %s has more than %d pages" % (section["id"], MAX_PAGES))


def _entry(base, organisation, tender, section, path, row):
    """The listing's entry for one file, or None when the viewer cannot show it."""
    preview = (row.get("files") or {}).get("preview") or {}
    version = re.search(r"/versions/([0-9a-f-]{36})/preview", str(preview.get("url") or ""))
    if not version:
        return None
    released = [m.get("valueId") for m in row.get("metadata") or []
                if m.get("metadataElementId") == "GLOBAL_TenderVersionId" and m.get("valueId")]
    name = str(row.get("name") or row["id"])
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return {"id": row["id"], "name": name, "folder": "/".join(p for p in path if p),
            "download": "%s/procurementSections/%s/documents/%s/versions/%s/preview"
                        % (base, section["id"], row["id"], version.group(1)),
            "organisation": organisation, "tender": tender,
            "released": released[0] if released else None}


def listing(urls):
    """The tender's folders and the files the public view can show."""
    link = LINK.match(urls[0] or "")
    if not link:
        return {"access": "unknown", "files": [], "gated": [],
                "note": "the iBinder link names no public tender"}
    host, organisation, tender = link.group(1).lower(), link.group(2), link.group(3)
    base = "https://%s/api/etendering/tenders/%s" % (host, tender)
    try:
        name = _ask(base, organisation).get("name")
        settings = _ask(base + "/configuration", organisation)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404, 410):
            return {"access": "gated", "files": [], "gated": [], "tender_id": tender,
                    "note": "iBinder answered %d: the tender has no public view" % exc.code}
        raise
    if settings.get("publicLinkEnabled") is not True:
        return {"access": "gated", "files": [], "gated": [], "tender_id": tender,
                "note": "iBinder says the tender's public link is off"}
    files, unseen = [], []
    for section, path in folders(settings.get("procurementSections")):
        for row in documents(base, organisation, tender, name, section):
            if row.get("deleted"):
                continue
            entry = _entry(base, organisation, tender, section, path, row)
            if entry:
                files.append(entry)
            else:
                unseen.append("/".join([p for p in path if p] + [str(row.get("name") or row["id"])]))
    access = ("public" if files and not unseen else "partial" if files
              else "gated" if unseen else "none")
    note = "iBinder's public view shows no preview of %d file(s)" % len(unseen) if unseen else ""
    return {"access": access, "files": files, "gated": unseen, "tender_id": tender, "note": note}


def unchanged(entry, held):
    """The same file at the same version: the version is in the preview address."""
    return (str(entry.get("id")) == str(held.get("id")) and entry.get("name") == held.get("name")
            and entry.get("download") == held.get("download"))


def download(entry):
    """The PDF the public viewer shows for one file."""
    context = {"domain": "etendering", "resourceid": entry["tender"],
               "subresource": "tenderversions", "subresourceid": entry.get("released")}
    try:
        answer = _ask(entry["download"], entry["organisation"], context=context)
    except Exception as exc:
        return None, "the preview was not offered: %s" % type(exc).__name__
    link = str((answer.get("url") if isinstance(answer, dict) else None) or "")
    parts = urllib.parse.urlparse(link)
    if parts.scheme != "https" or not PREVIEW_HOST.match(parts.netloc.lower()):
        return None, "the preview led to a host that is not iBinder's store"
    # The link carries its own short-lived key, so nothing of it may reach a message.
    try:
        data = common.fetch(link, timeout=common.TIMEOUT)
    except Exception as exc:
        return None, "the preview could not be downloaded: %s" % type(exc).__name__
    if not data.startswith(b"%PDF"):
        return None, "the preview is not a PDF, %d bytes" % len(data)
    return data, None
