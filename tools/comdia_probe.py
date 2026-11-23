"""Temporary: sign in to Comdia with plain HTTP and print the SHAPE of what a signed-in supplier sees.

The run's log is public, so this prints control names, link patterns with digits folded to `9`,
and counts -- never a file name, a title, the account or a cookie.

    COMDIA_USER=... COMDIA_PASSWORD=... python3 tools/comdia_probe.py <tender page url>
"""
import html as htmlmod
import http.cookiejar
import os
import re
import sys
import urllib.parse
import urllib.request

BASE = "https://www.comdia.com"
UA = "Mozilla/5.0 (compatible; eis-tool)"


def opener():
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    return op, jar


def get(op, url, data=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with op.open(req, timeout=60) as resp:
        return resp.status, resp.geturl(), resp.read().decode("utf-8", "replace")


def hidden(page):
    out = {}
    for tag in re.findall(r"<input[^>]+>", page):
        if 'type="hidden"' not in tag:
            continue
        name = re.search(r'name="([^"]+)"', tag)
        value = re.search(r'value="([^"]*)"', tag)
        if name:
            out[htmlmod.unescape(name.group(1))] = htmlmod.unescape(value.group(1)) if value else ""
    return out


def fold(s):
    return re.sub(r"\d+", "9", s)


def shape(label, url, page):
    print("== %s: %s (%d bytes)" % (label, fold(urllib.parse.urlparse(url).path), len(page)))
    print("  login form present:", "txtPassword" in page)
    print("  logout marker:", sorted(set(re.findall(r"(?i)log ?out|log ?ud|logoff|signout", page)))[:6])
    print("  captcha/challenge:", sorted(set(re.findall(r"(?i)captcha|turnstile|cf-chl|challenge-platform", page))))
    targets = sorted(set(htmlmod.unescape(t) for t in re.findall(r"__doPostBack\((?:&#39;|')([^&']+)", page)))
    print("  postback targets (%d):" % len(targets))
    for t in targets:
        print("    ", fold(t))
    hrefs = {}
    for h in re.findall(r'href="([^"]+)"', page):
        h = htmlmod.unescape(h)
        if h.startswith(("javascript", "#", "/Metronic", "http://fonts", "https://fonts")):
            continue
        key = fold(re.sub(r"=[^&]*", "=X", h)) if "?" in h else fold(h)
        hrefs[key] = hrefs.get(key, 0) + 1
    print("  hrefs (%d patterns):" % len(hrefs))
    for k, n in sorted(hrefs.items()):
        print("     %4d  %s" % (n, k[:140]))
    for word in ("Documents", "Dokumenter", "Download", "Not downloaded", "access to the offer",
                 "participate", "Access to tender", "Show interest", "tenderentity"):
        print("  %r: %d" % (word, page.count(word)))
    rows = re.findall(r"<tr[ >]", page)
    print("  table rows:", len(rows))
    for m in re.findall(r'(?:onclick|data-[a-z-]+)="([^"]{0,160})"', page)[:400]:
        if re.search(r"(?i)download|file|doc", m):
            print("    attr:", fold(m)[:160])


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    user, password = os.environ.get("COMDIA_USER", "").strip(), os.environ.get("COMDIA_PASSWORD", "")
    if not (user and password):
        print("no account in the environment")
        return 1
    op, jar = opener()
    status, url, page = get(op, BASE + "/login.aspx")
    shape("login page", url, page)
    form = hidden(page)
    form.update({"__EVENTTARGET": "ctl00$cphInnerContent$lbLogin", "__EVENTARGUMENT": "",
                 "ctl00$cphInnerContent$txtEmail": user,
                 "ctl00$cphInnerContent$txtPassword": password,
                 "ctl00$cphInnerContent$txtBrowserWidth": "1600",
                 "ctl00$cphInnerContent$txtBrowserHeight": "900"})
    status, url, page = get(op, BASE + "/login.aspx", urllib.parse.urlencode(form).encode())
    page = page.replace(user, "<account>")
    print("after sign-in: status %s, landed on %s" % (status, fold(urllib.parse.urlparse(url).path)))
    print("cookies:", sorted(c.name for c in jar))
    shape("after sign-in", url, page)
    for target in sys.argv[1:]:
        status, url, page = get(op, target)
        if "tenderinformationshow" in target:
            go_to_tender(op, url, page)
        else:
            deep(op, url, page)
    return 0


def skeleton(fragment):
    """Tags and their id/class/onclick/href kept, every text node replaced by its length."""
    fragment = re.sub(r"(?s)<script.*?</script>", "<script/>", fragment)
    def text(m):
        t = m.group(1).strip()
        return ">" + ("[%d]" % len(t) if t else "") + "<"
    out = re.sub(r">([^<]*)<", text, fragment)
    out = re.sub(r'\s(title|alt|value|data-original-title)="[^"]*"', r' ="?"', out)
    return fold(out)


def post(op, url, page, target):
    form = hidden(page)
    form.update({"__EVENTTARGET": target, "__EVENTARGUMENT": ""})
    req = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode(),
                                 headers={"User-Agent": UA,
                                          "Content-Type": "application/x-www-form-urlencoded"})
    with op.open(req, timeout=300) as resp:
        return resp.status, resp.geturl(), dict(resp.headers), resp.read()


def report(label, status, url, headers, body):
    disp = headers.get("Content-Disposition", "")
    ext = re.search(r"\.([A-Za-z0-9]{1,5})\"?\s*$", disp)
    print("  %s: status %s -> %s, type %s, disposition %s (ext %s), %d bytes, head %r"
          % (label, status, fold(urllib.parse.urlparse(url).path) + ("?Id=" + url.split("Id=")[-1][:8] if "Id=" in url else ""),
             headers.get("Content-Type"), disp.split(";")[0] if disp else None,
             ext.group(1) if ext else None, len(body), body[:4]))


def zipshape(data):
    import collections, io, zipfile
    z = zipfile.ZipFile(io.BytesIO(data))
    infos = z.infolist()
    files = [i for i in infos if not i.is_dir()]
    print("  zip: %d entries, %d files, %d dir entries, utf8-flagged %d, unpacked %.1f MB"
          % (len(infos), len(files), len(infos) - len(files),
             sum(1 for i in infos if i.flag_bits & 0x800), sum(i.file_size for i in files) / 1048576.0))
    depth = collections.Counter(i.filename.strip("/").count("/") for i in files)
    print("  depth histogram:", dict(depth))
    tops = collections.Counter(i.filename.split("/")[0] for i in files if "/" in i.filename)
    print("  top-level folders: %d, files per folder %s" % (len(tops), sorted(tops.values())))
    ext = collections.Counter(i.filename.rsplit(".", 1)[-1].lower()[:5] for i in files)
    print("  extensions:", dict(ext.most_common(12)))
    nonascii = sum(1 for i in files if any(ord(c) > 127 for c in i.filename))
    print("  names with non-ASCII characters: %d; backslashes: %d" % (nonascii, sum("\\" in i.filename for i in files)))
    print("  top-level folder name lengths:", sorted(len(t) for t in tops)[:30])


def go_to_tender(op, url, page):
    print("== tender page", fold(urllib.parse.urlparse(url).path))
    i = page.find("lbGoToTender")
    print("  around lbGoToTender:", skeleton(page[max(0, i - 600):i + 300]))
    status, url2, headers, body = post(op, url, page, "ctl00$ctl00$cphMain$cphMain$lbGoToTender")
    report("lbGoToTender", status, url2, headers, body)


def deep(op, url, page):
    print("== vendor page", fold(urllib.parse.urlparse(url).path), len(page))
    vs = hidden(page).get("__VIEWSTATE", "")
    print("  viewstate bytes:", len(vs))
    heads = re.findall(r"(?s)<th[^>]*>(.*?)</th>", page)
    print("  table headers:", sorted(set(re.sub(r"<[^>]+>|\s+", " ", h).strip() for h in heads))[:40])
    grids = re.findall(r'id="([^"]*gvDocument)"', page)
    print("  document grids: %d" % len(grids))
    for g in grids[:3]:
        print("    ", fold(g))
    for g in grids[:2]:
        i = page.find('id="%s"' % g)
        print("  grid %s skeleton:" % fold(g))
        print("   ", skeleton(page[max(0, i - 1500):i + 4000]))
    targets = re.findall(r"__doPostBack\((?:&#39;|')([^&']+lbDownload[^&']*)", page)
    print("  per-file download targets:", len(targets))
    alls = sorted(set(re.findall(r"__doPostBack\((?:&#39;|')([^&']+lbDownloadAll[^&']*)", page)))
    print("  download-all targets:", [fold(a) for a in alls])
    for a in alls[:1]:
        i = page.find(a.replace("$", "_"))
        print("  around download-all:", skeleton(page[max(0, i - 800):i + 400]))
    print("  per-file targets unique:", len(set(targets)))
    for a in alls[:1]:
        status, u, h, b = post(op, url, page, a)
        report("download all", status, u, h, b)
        if b[:2] == b"PK":
            zipshape(b)
        if b[:2] != b"PK":
            print("  download-all answer skeleton:", skeleton(b.decode("utf-8", "replace")[:3000]))


if __name__ == "__main__":
    sys.exit(main())
