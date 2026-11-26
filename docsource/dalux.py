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

# DALUX RAISES THE OLDEST CLIENT IT ANSWERS, WITHOUT NOTICE. 2026050 worked on 16 Nov 2026 and was
# refused on 24 Nov: `{"result": 9, "message": "Versions below 2026070 not supported"}`. The refusal
# names the version it wants, so the call takes it and asks once more.
CLIENT = {"version": 2026070}
TOO_OLD = re.compile(r"Versions below (\d+) not supported")
NOT_PUBLIC = re.compile(r"cannot be accessed publicly", re.I)


class Refused(RuntimeError):
    """Dalux answered, and the answer was an error rather than a fact about the tender."""


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat(
        timespec="milliseconds")


def _envelope(command, params, tid):
    """The envelope the public page sends: a version, the calling page, a client block, and a
    `time` whose last two digits are a checksum of the body."""
    now = _now() + "Z"
    body = {"version": CLIENT["version"], "command": command, "callingUrl": CALLER % tid,
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
    answer = _send(command, params, tid)
    wanted = TOO_OLD.search(str(answer.get("message") or ""))
    if wanted and int(wanted.group(1)) > CLIENT["version"]:
        CLIENT["version"] = int(wanted.group(1))
        answer = _send(command, params, tid)
    # AN ERROR IS NOT "NOT PUBLIC". Read as one, a refused client turns every Dalux tender into a
    # gated one and the night stays green.
    message = str(answer.get("message") or "")
    if answer.get("result") and not NOT_PUBLIC.search(message):
        raise Refused("Dalux answered %s: %s" % (answer.get("result"), message[:120]))
    return answer


def _send(command, params, tid):
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
        return {"access": "gated", "files": [], "tender_id": tid,
                "note": "Dalux says this tender cannot be accessed publicly"}
    answer = _call("GetFileList", {"tenderLinkIdentifier": tid}, tid)
    if NOT_PUBLIC.search(str(answer.get("message") or "")):
        return {"access": "gated", "files": [], "tender_id": tid,
                "note": "Dalux says this tender cannot be accessed publicly"}
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


def unchanged(entry, held):
    """The same file revision: Dalux gives a replaced file a new `areaFileRevisionID`, and the
    revision is both the id and part of the download address."""
    return (str(entry.get("id")) == str(held.get("id")) and entry.get("name") == held.get("name")
            and entry.get("download") == held.get("download"))


def download(entry):
    return common.plain_download(entry)
