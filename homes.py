"""What a tender's home already holds, before tonight's fetch writes over it.

WHY A FETCH HAS TO ASK. A watched tender is read again every night, and on 25 Nov 2026 nine of them
were 4.6 GB of the night's 4.7 GB -- 35 of its 38 fetch minutes -- for homes the delivery then
called unchanged. A file the home already holds, unchanged on its host, is not downloaded again;
to know that, the fetch needs what the home holds: its index, its manifest, its text manifest, its
facts and its state.

WHERE THAT IS. On a workstation, in the home itself, left by the previous run. On a runner, whose
disk is new every night, only on the drive the delivery writes to -- the same files, read with the
same credentials the delivery holds. Without either, the answer is None, and the fetch downloads
everything, as it always did. Nothing here can make a fetch fail: an unreadable drive is a slower
night, never a lost one.

    held = homes.held("work/DK", pid)   # {"index", "manifest", "normalized", "procurement",
                                        #  "state", "where"} or None
"""
import json
import os

FILES = (("index", "index.json"), ("manifest", "manifest.json"),
         ("normalized", "normalized/manifest_normalized.json"),
         ("procurement", "procurement.json"), ("state", "state.json"))

GRAPH_ENV = ("GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET", "GRAPH_DRIVE_ID",
             "GRAPH_DEST_ROOT")

_DRIVE = {"tried": False, "drive": None, "base": None, "tok": None}


def _local(home):
    found = {}
    for key, rel in FILES:
        try:
            with open(os.path.join(home, rel), encoding="utf-8") as fh:
                found[key] = json.load(fh)
        except (OSError, ValueError):
            found[key] = None
    return found


def _drive():
    """`(drive, base, tok)` when this run may read the drive, else None. Asked once per run."""
    if not _DRIVE["tried"]:
        _DRIVE["tried"] = True
        if all((os.environ.get(name) or "").strip() for name in GRAPH_ENV):
            try:
                import country
                import deliver_graph as graph
                code = country.resolve(os.environ.get("EIS_COUNTRY") or "DK", os.environ)
                _DRIVE.update(drive=graph.env("GRAPH_DRIVE_ID"),
                              base=country.destination(graph.env("GRAPH_DEST_ROOT"), code),
                              tok=graph.graph_token())
            except BaseException:              # deliver_graph exits on a failed request
                _DRIVE.update(drive=None, base=None, tok=None)
    if _DRIVE["tok"] is None:
        return None
    return _DRIVE["drive"], _DRIVE["base"], _DRIVE["tok"]


def _remote(pid):
    where = _drive()
    if where is None:
        return None
    drive, base, tok = where
    import deliver_graph as graph
    found = {}
    # The state first: a tender nobody has delivered has none, and costs one request, not five.
    for key, rel in sorted(FILES, key=lambda f: f[0] != "state"):
        try:
            found[key] = graph.json_at(drive, "%s/tenders/%s/%s" % (base, pid, rel), tok)
        except BaseException:
            found[key] = None
        if key == "state" and found[key] is None:
            return None
    return found


def held(out_root, pid):
    """What the home of `pid` holds, or None when there is no home anywhere this run can see.

    A home counts when its index and its state are both there: the index lists the documents, the
    state is what tomorrow compares against, and either alone is a home that did not finish.
    """
    pid = str(pid)
    local = _local(os.path.join(out_root, "tenders", pid))
    if local.get("index") and local.get("state"):
        return dict(local, where="disk")
    remote = _remote(pid)
    if remote and remote.get("index") and remote.get("state"):
        return dict(remote, where="drive")
    return None


def newest_published(held_home):
    """The publication date of the newest notice the home has carried, or None."""
    if not held_home:
        return None
    procurement = held_home.get("procurement") or {}
    dates = [n.get("published") for n in procurement.get("notices") or [] if n.get("published")]
    if procurement.get("published"):
        dates.append(procurement["published"])
    return max(dates) if dates else None
