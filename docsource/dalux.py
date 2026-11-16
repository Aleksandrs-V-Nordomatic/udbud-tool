"""Dalux: the construction platform, and the one most of our tenders would sit on.

The public tender page is an Angular app that talks to one RPC endpoint with a signed envelope.
Four commands answer an anonymous caller with read-only data, and this module sends those four
and nothing else:

    IsTenderPublic, GetTenderInformation, GetTenderShardUrl, GetFileList

THE SAME ENDPOINT ACCEPTS WRITE COMMANDS FROM AN ANONYMOUS CALLER. AddFilesToTender and
RemoveFilesFromTender were callable on 16 Nov 2026 -- they answered "Server error" and changed
nothing, and that was disclosed. `_call` refuses any command outside the four, so no edit to
this file can send one by accident.

    GetFileList {"tenderLinkIdentifier": "TID-..."}  -> value.folder: files[] + childrenVector[]
    GET https://node1.field.dalux.com/service/web/downloadfile/{TID}/areafilerevision-{id}/

THE DOWNLOAD HOST IS `node1.field`, NOT `node1.build`. The same path on `node1.build` answers
200 with the app's HTML shell. Measured 16 Nov 2026: 1 622 of 1 622 files of the eleven public
tenders; one tender of twelve answered "Tender cannot be accessed publicly".
"""
import datetime
import json
import re

from docsource import common

NAME = "dalux"
RPC = "https://node1.field.dalux.com/service/EntryPoints/Web/PublicPage/PublicService.aspx"
CALLER = "https://node1.build.dalux.com/da-dk/public/tender/%s"
FILE = "https://node1.field.dalux.com/service/web/downloadfile/%s/areafilerevision-%s/"
READ_ONLY = frozenset({"IsTenderPublic", "GetTenderInformation", "GetTenderShardUrl", "GetFileList"})
TID = re.compile(r"(TID-\d+)")


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat(
        timespec="milliseconds")


def _envelope(command, params, tid):
    """The envelope the public page sends: a version, the calling page, a client block, and a
    `time` whose last two digits are a checksum of the body."""
    now = _now() + "Z"
    body = {"version": 2026050, "command": command, "callingUrl": CALLER % tid,
            "constructor": {"request": {"client": {"appVersion": "1.0.0", "build": "1.0.0",
                                                   "deviceID": None, "deviceOS": "Win32",
                                                   "devicePlatform": "web(angular)_Chrome_128.0.0.0",
                                                   "utcTime": now, "localTime": now},
                                        "session": {"auth": None, "flags": []}, "view": None}},
            "parameters": params}
    encoded = json.dumps(body, separators=(",", ":"))
    check = sum(ord(c) for c in encoded[:100000]) % 100
    return ('{"time":"%s%02dZ",' % (_now(), check) + encoded[1:]).encode("utf-8")


def _call(command, params, tid):
    if command not in READ_ONLY:
        raise PermissionError("Dalux command %r is not one of the four read-only ones" % command)
    raw = common.fetch(RPC, data=_envelope(command, params, tid),
                       headers={"Content-Type": "application/json",
                                "Accept": "application/json, text/plain, */*",
                                "Origin": "https://node1.build.dalux.com"})
    return json.loads(raw.decode("utf-8"))


def _walk(folder, path=()):
    for f in folder.get("files") or []:
        yield path, f
    for child in folder.get("childrenVector") or []:
        name = None
        for p in child.get("properties") or []:
            if p.get("matchName") in ("FolderName", "Name"):
                name = p.get("value")
        yield from _walk(child, path + ((name or child.get("name") or ""),))


def listing(urls):
    m = TID.search(urls[0])
    if not m:
        return {"access": "unknown", "note": "no TID in the link"}
    tid = m.group(1)
    public = _call("IsTenderPublic", {"tenderLinkIdentifier": tid}, tid).get("value")
    if public is not True:
        return {"access": "gated", "tender_id": tid,
                "note": "Dalux says this tender cannot be accessed publicly"}
    answer = _call("GetFileList", {"tenderLinkIdentifier": tid}, tid)
    folder = (answer.get("value") or {}).get("folder")
    if not folder:
        return {"access": "unknown", "tender_id": tid,
                "note": "GetFileList returned no folder: %s" % json.dumps(answer)[:120]}
    files = []
    for path, f in _walk(folder):
        props = {p.get("matchName"): p.get("value") for p in f.get("properties") or []}
        rev = f.get("areaFileRevisionID")
        files.append({"id": str(rev), "name": props.get("FileName") or "file-%s" % rev,
                      "folder": "/".join(p for p in path if p),
                      "size_text": props.get("FileSize"),
                      "download": FILE % (tid, rev)})
    return {"access": "public" if files else "none", "files": files, "tender_id": tid}


def download(entry):
    return common.plain_download(entry)
