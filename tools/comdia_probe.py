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
    for tender in sys.argv[1:]:
        status, url, page = get(op, tender)
        shape("tender page", url, page.replace(user, "<account>"))
        for link in sorted(set(htmlmod.unescape(h) for h in re.findall(r'href="([^"]*tenderentity[^"]*)"', page, re.I))):
            status, url, vpage = get(op, urllib.parse.urljoin(tender, link))
            shape("vendor page", url, vpage.replace(user, "<account>"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
