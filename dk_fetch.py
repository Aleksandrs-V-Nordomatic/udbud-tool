"""Transport for Denmark: one notice, and whatever of its documents can be read, into a home.

THE NOTICE IS ALWAYS THERE, AND FOR MOST TENDERS IT IS ALL THERE IS. On 16 Nov 2026, across the
174 competition notices of 3-14 Nov, every file came down anonymously on 30% of tenders and on
42% of the construction ones. The rest sit on EU-Supply, Mercell and Comdia behind a supplier
account. So `doc/notice.md` -- the facts, the buyer's description, and the whole notice as
udbud.dk renders it -- is written into every home, and a card judged on it can quote it.

`documents_available` SAYS WHICH KIND OF JUDGEMENT A CARD IS:
    public     every file the platform lists was read
    partial    some were read, some are behind the account
    gated      the platform holds documents we could not read; `documents_gated` names the host
    none       the notice names no documents, or the platform says there are none
    unknown    no reader for the host; a person opens `documents_link`

    python3 dk_fetch.py <procedureId | noticeId> --out work/DK
"""
import argparse
import hashlib
import io
import json
import os
import sys
import time

import dk_page
import dk_targets
import docsource

try:
    import changes as changes_mod
except Exception:                          # the fingerprint is optional for a bare fetch
    changes_mod = None


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _safe(name):
    """A file name that cannot climb out of the home it is written into."""
    name = str(name or "").replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ord(ch) >= 32 and ch not in '<>:"|?*').strip().lstrip(".")
    return name[-150:] or "unnamed"


def _write(home, name, payload):
    with open(os.path.join(home, name), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def carriable(held, tool):
    """The files of a home that may be carried over, by record id, or {} when none may.

    Carried means: not downloaded, not stored, not read again -- the record, the index entry and
    the text entries are the home's own. Only from a home whose text was made by the extractor
    this run would use: text left by another version is text the delivery has to refresh, and a
    refreshed text needs its file.
    """
    if not held or not tool or (held.get("state") or {}).get("tool") != tool:
        return {}
    normalized = held.get("normalized")
    if not normalized:
        return {}
    texts = {}
    for entry in normalized.get("documents") or []:
        texts.setdefault(str(entry.get("record_id")), []).append(entry)
    index_docs = {str(d.get("id")): d for d in (held.get("index") or {}).get("documents") or []}
    out = {}
    for record in (held.get("manifest") or {}).get("documents") or []:
        rid = str(record.get("id"))
        if rid in index_docs and len(record.get("files") or []) == 1:
            out[rid] = {"record": record, "doc": index_docs[rid], "texts": texts.get(rid, [])}
    return out


def store(home, platform, files, carry=None):
    """Every public file the platform serves, written under `originals/`, one request at a time.

    A file the home already holds is carried instead (`carry`, from `carriable`): not downloaded
    when the host says it is the same file (`docsource.unchanged`), and not stored when it was
    downloaded and its sha256 is the one the home holds. Returns `(records, withheld, bytes,
    carried ids)`; the bytes count only what was downloaded.
    """
    carry = carry or {}
    originals = os.path.join(home, "originals")
    os.makedirs(originals, exist_ok=True)
    records, withheld, seen, total, carried = [], [], set(), 0, []
    # A carried file keeps its name, so the names of the listed files the home holds are taken
    # before anything new is named; one that turns out changed gives its name back below.
    listed = {str(entry["id"]) for entry in files}
    for rid, held in carry.items():
        if rid in listed:
            seen.add(held["record"]["files"][0]["filename"].casefold())
    for entry in files:
        title = "/".join(p for p in (entry.get("folder"), entry["name"]) if p)
        held = carry.get(str(entry["id"]))
        if held is not None and held["record"].get("title") != title:
            seen.discard(held["record"]["files"][0]["filename"].casefold())
            held = None                        # moved to another folder: a change, read it
        if held is not None and docsource.unchanged(platform, entry, held["doc"]):
            records.append(held["record"])
            carried.append(str(entry["id"]))
            continue
        data, reason = docsource.download(platform, entry)
        if data is None:
            withheld.append({"id": entry["id"], "title": title, "reason": reason,
                             "download": entry["download"], "files": []})
            continue
        total += len(data)
        digest = _sha256(data)
        if held is not None and held["record"]["files"][0].get("sha256") == digest:
            records.append(held["record"])
            carried.append(str(entry["id"]))
            continue
        if held is not None:
            seen.discard(held["record"]["files"][0]["filename"].casefold())
        filename = _safe(entry["name"])
        stem, dot, ext = filename.rpartition(".")
        n = 1
        while filename.casefold() in seen:
            n += 1
            filename = "%s (%d)%s%s" % (stem or filename, n, dot, ext)
        seen.add(filename.casefold())
        with open(os.path.join(originals, filename), "wb") as fh:
            fh.write(data)
        records.append({
            "id": entry["id"], "title": title, "type_code": entry.get("type"),
            "subtype": None, "section": "current", "publish_date": None,
            "catalogued": True, "member": None, "download": entry["download"],
            "files": [{"filename": filename, "path": "originals/%s" % filename,
                       "original_name": entry["name"], "sha256": digest,
                       "bytes": len(data)}],
        })
    return records, withheld, total, carried


def extract(home):
    """The originals as Markdown under `doc/<digest>.md`, through the family's `normalize.py`."""
    try:
        import normalize
    except ImportError as exc:
        return {"documents": [], "unreadable_files": [], "skipped": "normalize unavailable: %s" % exc}
    out = os.path.join(home, "normalized")
    stdout = sys.stdout
    try:
        sys.stdout = io.StringIO()             # the extractor narrates; a fetch does not
        normalize.main(["--in", home, "--out", out])
    finally:
        sys.stdout = stdout
    with open(os.path.join(out, "manifest_normalized.json"), encoding="utf-8") as fh:
        normalized = json.load(fh)
    doc_dir = os.path.join(home, "doc")
    os.makedirs(doc_dir, exist_ok=True)
    for entry in normalized.get("documents", []):
        if entry.get("also_listed_under") or not entry.get("markdown_path"):
            continue
        source = os.path.join(out, entry["markdown_path"])
        if not os.path.exists(source):
            continue
        key = (changes_mod.document_key(entry.get("original_sha256"), entry.get("source"))
               if changes_mod else (entry.get("original_sha256") or "")[:16])
        with open(source, encoding="utf-8") as fh:
            text = fh.read()
        with open(os.path.join(doc_dir, "%s.md" % key), "w", encoding="utf-8") as fh:
            fh.write(text)
        entry["doc"] = "doc/%s.md" % key
    return normalized


def with_carried(normalized, carry, carried):
    """The text manifest of what was read tonight, joined by the home's own entries for the files
    carried over, with the unreadable list and the totals made again over both -- as the extractor
    would have written them had it read everything."""
    fresh = list((normalized or {}).get("documents") or [])
    kept = []
    for rid in carried:
        for entry in carry[rid]["texts"]:
            entry = dict(entry)
            if entry.get("markdown_path") and not entry.get("also_listed_under"):
                key = (changes_mod.document_key(entry.get("original_sha256"), entry.get("source"))
                       if changes_mod else (entry.get("original_sha256") or "")[:16])
                entry["doc"] = "doc/%s.md" % key
            kept.append(entry)
    entries = fresh + kept
    gaps = list((normalized or {}).get("unreadable_files") or [])
    known = {g.get("sha256") or g.get("file") for g in gaps}
    for entry in kept:
        if entry.get("kind") != "unsupported":
            continue
        key = entry.get("sha256") or entry.get("source")
        if key in known:
            continue
        known.add(key)
        gaps.append({"file": entry.get("source"), "bytes": entry.get("bytes", -1),
                     "sha256": entry.get("sha256", ""), "reason": entry.get("note", "")})
    gaps.sort(key=lambda g: -(g.get("bytes") or 0))
    unique = [e for e in entries if not e.get("also_listed_under")]
    out = dict(normalized or {}, documents=entries, unreadable_files=gaps,
               entries=len(entries),
               markdown=sum(1 for e in unique if e.get("preferred_for_agent")),
               unsupported=sum(1 for e in unique if e.get("kind") == "unsupported"),
               chars=sum(e.get("markdown_chars", 0) for e in unique),
               carried=len(kept))
    out.setdefault("schema", 2)
    return out


def _with_text(documents, normalized):
    by_sha = {}
    for entry in normalized.get("documents", []):
        if entry.get("doc"):
            by_sha.setdefault(entry.get("original_sha256"), []).append(entry)
    return [dict(row, doc=(by_sha.get(row["sha256"]) or [{}])[0].get("doc"),
                 chars=sum(t.get("markdown_chars", 0) for t in by_sha.get(row["sha256"], [])) or None)
            for row in documents]


def _available(found, records, withheld):
    access = found.get("access")
    if access in ("none", "unknown"):
        return access
    if records and not withheld and not found.get("gated"):
        return "public"
    if records:
        return "partial"
    return "gated"


FACT_FIELDS = ("pid", "procedure_id", "intern_id", "notice_id", "notice_version", "npn", "ref",
               "kind", "form_code", "form", "subtype", "subtype_code", "eu", "title", "titles",
               "description", "buyer", "buyers", "buyer_id", "published", "deadline", "deadlines",
               "deadline_tender", "deadline_request", "value", "currency", "cpv_main", "cpv",
               "cpv_name", "expected_start", "lots", "nuts", "place", "source_kind", "link",
               "link_verified", "documents_url", "documents_urls", "documents_host")


def fetch(target, out_root, document=None, with_text=True, previous=None, held=None):
    """One notice into `<out_root>/tenders/<pid>/`. `index.json` last, then `state.json`.

    `document` is the detail already read by the caller, so a day does not ask for it twice.
    `previous` is the procurement.json already on the drive, whose notice history is carried on.
    `held` is what the home already holds (`homes.held`); a file it holds unchanged is carried
    over rather than downloaded and read again.
    """
    pid = str(target["pid"])
    home = os.path.join(out_root, "tenders", pid)
    os.makedirs(os.path.join(home, "doc"), exist_ok=True)

    tool = changes_mod.pipeline_version() if changes_mod is not None else None
    carry = carriable(held, tool) if with_text else {}
    found = docsource.listing(target.get("documents_urls"), target,
                              held=(held or {}).get("index") if carry else None)
    if found.get("unchanged") and any(str(f["id"]) not in carry for f in found["files"]):
        # The host vouched for files the home cannot carry: list it again and read them.
        found = docsource.listing(target.get("documents_urls"), target)
    records, withheld, total, carried = ([], [], 0, [])
    if found.get("files"):
        records, withheld, total, carried = store(home, found["platform"], found["files"], carry)
    fresh = [r for r in records if str(r["id"]) not in set(carried)]
    available = _available(found, records, withheld)
    listed = len(found.get("files") or []) + len(found.get("gated") or [])

    procurement = {k: target.get(k) for k in FACT_FIELDS}
    # EVERY NOTICE THAT HAS CARRIED THIS PROCEDURE, so an amendment lands in the same home and a
    # reader can see the history without asking the portal again.
    history = list((previous or {}).get("notices") or [])
    this = {"notice_id": target["notice_id"], "version": target["notice_version"],
            "npn": target.get("npn"), "kind": target.get("kind"), "published": target.get("published")}
    if this not in history:
        history.append(this)
    procurement["notices"] = history
    procurement["documents_available"] = available
    procurement["documents_gated"] = available in ("gated", "partial")
    procurement["document_host"] = found.get("host")
    procurement["document_platform"] = found.get("platform")
    procurement["attachments_listed"] = listed

    if document is not None:
        _write(home, "notice.json", {k: v for k, v in document.items() if k != "htmlEN"})

    manifest = {"pid": pid, "procurement_id": target.get("procedure_id"), "reference": target.get("ref"),
                "archive": None, "archive_sha256": None, "archive_bytes": 0,
                "documents": records,
                "withheld_records": [dict(w, files=[]) for w in withheld]
                + [{"id": "gated-%d" % n, "title": name, "reason": "behind %s's supplier account"
                    % (found.get("platform") or "the platform"), "download": target.get("documents_url"),
                    "files": []} for n, name in enumerate(found.get("gated") or [])]}
    _write(home, "procurement.json", procurement)
    # The extractor reads what `manifest.json` names, and a carried file is not on this disk: it
    # is shown only the files read tonight, and the whole manifest is written after it.
    _write(home, "manifest.json", dict(manifest, documents=fresh))

    with open(os.path.join(home, dk_page.NOTICE_DOCUMENT), "w", encoding="utf-8") as fh:
        fh.write(dk_page.notice_markdown(target, document))

    index = {
        "schema": "index/1", "pid": pid, "ref": target.get("ref"), "country": "DK",
        "kind": target.get("kind"), "source": target.get("source") or "udbud.dk",
        "notice_type": target.get("subtype"),
        "link": target.get("link"), "link_verified": target.get("link_verified"),
        "documents_link": target.get("documents_url"),
        "documents_available": available,
        "documents_gated": procurement["documents_gated"],
        "documents_host": found.get("host"),
        "document_platform": found.get("platform"),
        "documents_note": found.get("note") or None,
        # The names a gated platform shows anonymously -- what a person would be asking for
        # if they opened the tender with an account.
        "gated_documents": found.get("gated") or [],
        "title": target.get("title"),
        # THE DESCRIPTION IS EVIDENCE, NOT DECORATION: for most Danish cards it is, with the
        # notice, the whole of what a judgement can be made on.
        "description": target.get("description"),
        "titles": target.get("titles"),
        "buyer": target.get("buyer"), "buyer_id": target.get("buyer_id"),
        "published": target.get("published"), "deadline": target.get("deadline"),
        "status": target.get("form_code"), "status_text": target.get("kind"),
        "procedure_text": target.get("subtype"),
        "value": target.get("value"), "currency": target.get("currency"),
        "cpv_main": target.get("cpv_main"), "cpv": target.get("cpv"), "cpv_name": target.get("cpv_name"),
        "eu": target.get("eu"), "npn": target.get("npn"), "lots": target.get("lots"),
        "nuts": target.get("nuts"),
        "catalogued_documents": listed,
        "withheld_documents": len(withheld) + len(found.get("gated") or []),
        "documents": [{
            "id": r["id"], "name": r["files"][0]["original_name"], "title": r["title"],
            "sha256": r["files"][0]["sha256"], "bytes": r["files"][0]["bytes"],
            "original": "originals/%s" % r["files"][0]["filename"], "type_code": r["type_code"],
            "changed_at": None, "catalogued": True, "download": r["download"], "access": "public",
        } for r in records],
        "notice_document": dk_page.NOTICE_DOCUMENT,
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if found.get("listing"):
        # What the host's own listing looked like, where it gives one worth keeping (Comdia's
        # vendor page): the next run compares it before it downloads anything.
        index["documents_listing"] = found["listing"]
    _write(home, "index.json", index)

    normalized = extract(home) if (with_text and fresh) else {"documents": [], "unreadable_files": []}
    if carried:
        normalized = with_carried(normalized, carry, carried)
        os.makedirs(os.path.join(home, "normalized"), exist_ok=True)
        _write(home, "normalized/manifest_normalized.json", normalized)
    _write(home, "manifest.json", manifest)
    if normalized.get("documents"):
        index["documents"] = _with_text(index["documents"], normalized)
        index["text_documents"] = sum(1 for e in normalized["documents"] if e.get("markdown_path"))
        index["chars"] = normalized.get("chars", 0)
        _write(home, "index.json", index)

    state = None
    if changes_mod is not None:
        import country as country_mod
        state = changes_mod.fingerprint(
            pid, procurement, manifest, normalized,
            tool=changes_mod.pipeline_version(),
            parser=changes_mod.parser_version(files=country_mod.parser_files("DK")))
        _write(home, "state.json", state)

    return {"pid": pid, "ref": target.get("ref"), "kind": target.get("kind"), "home": home,
            "documents": len(records), "catalogued": listed, "carried": len(carried),
            "withheld": len(withheld) + len(found.get("gated") or []), "uncatalogued": 0,
            "documents_available": available, "documents_host": found.get("host"),
            "host_failed": found.get("note") if found.get("failed") else None,
            "link_verified": target.get("link_verified"), "bytes": total, "index": index,
            "state": state, "title": target.get("title"), "buyer": target.get("buyer"),
            "deadline": target.get("deadline"), "value": target.get("value"),
            "cpv_main": target.get("cpv_main")}


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    ap.add_argument("reference")
    ap.add_argument("--out", default="work/DK")
    args = ap.parse_args(argv)
    target = dk_targets.one(args.reference)
    if target is None:
        print("no live notice for %s" % args.reference, file=sys.stderr)
        return 1
    document = dk_page.detail(target["notice_id"], target["notice_version"], target["npn"])
    done = fetch(target, args.out, document)
    print("%s (%s): %d of %d document(s), %.1f MB, documents %s on %s -> %s"
          % (done["ref"], done["pid"], done["documents"], done["catalogued"],
             done["bytes"] / 1048576.0, done["documents_available"], done["documents_host"], done["home"]))
    if done["index"].get("documents_note"):
        print("  the host said: %s" % done["index"]["documents_note"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
