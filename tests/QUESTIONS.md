# Open questions — `docsource/comdia.py` under an account

These are behaviours the README section "Comdia, under an account" and the brief leave open. The
tests in `test_docsource.py` don't assert any of them; each one needs an answer before it can be tested.

## The replaced test
- The old `Comdia.test_no_request_and_gated` in `test_docsource.py` tested the retired stub
  ("no request, always gated"). The account contract replaces it, so the class was rewritten to the
  new behaviour **because the brief said to**. It was not weakened by choice. The rest of that file
  is unchanged. `ModuleFor` still maps `https://www.comdia.com/tender/1` to `comdia`. That link
  has no `Id=`, so under the new module it lists as `unknown`.

## Sign-in and session
1. **`session(fresh=True)` after a remembered refusal.** The brief says "every later call raises
   SignInFailed without trying again" and also "`fresh=True` signs in again". Which one wins once
   `_SESSION["failed"]` is set? (This matters to `listing`: if the retry after an ended session is
   refused, does a *later* tender in the same run try again?)
2. **Is `COMDIA_USER` passed to `sign_in` stripped?** The spec only says the user is stripped when
   deciding whether there is an account. The test sets no padding, so it doesn't decide this.
3. **Captcha on the login page itself.** Must `sign_in` stop *before* posting the password when the
   GET page already shows a challenge? The tests only check that it raises.
4. **What does `SignInFailed`'s message hold** when a request raises? Notes and `main` must mask the
   account. The tests check the account is absent, and only check for `<account>` on the
   "Comdia step failed" path.

## Page readers
5. **`hidden_fields` values.** Are values HTML-unescaped like the names (`value="a&amp;b"` → `a&b`)?
   ASP.NET posts the unescaped value, so unescaping seems right, but the brief only says names.
6. **`hidden_fields` attribute order.** Must it read `<input value=… name=… type="hidden">` (any order,
   any quoting)? The fixtures only use `type, name, id, value`.
7. **`controls` order and duplicates.** Is the list in page order, and does it keep duplicates?
   "The first DOWNLOAD_ALL control" depends on page order. The tests assume page order there only.
8. **`tender_id` edge cases:** `?TenderId=5` (a different parameter whose name ends in `Id`),
   `?Id=12abc`, `?Id=` (empty), and `None`/`""` as the url.

## Postback
9. **`_postback`'s return value and URL.** Is it `_send`'s triple? Is the press posted to the page's
   final URL or the URL first asked for? (For example, is Download all posted to `vendor_url`?)
10. Does a refused target raise **before** the `PAUSE` sleep as well as before the request?

## Archive
11. **`id` of a file:** is it `"zip:" + <member path>` (unique) or `"zip:" + <basename>` (can repeat
    across groups)? The tests only check the prefix and that ids are unique.
12. **Sort key** when names are re-decoded (cp437 → utf-8/cp1252): the raw member name or the
    decoded one?
13. Is `bytes` the size the archive *claims* (`file_size`)? The tests assume so.
14. **Access when the page lists more files than the archive holds**: the brief says `public` with
    a note that gives both counts. The README's table has `partial` for "some were read, some are
    behind the platform's account". Should it be `partial`? The tests follow the brief and expect
    `public`, and check only that both numbers appear in the note.
15. **Over the 1 GiB limit:** is the limit applied to the sum of claimed sizes or to each member? The
    tests check one member over the limit and two members whose sum is over it.
16. Is `ARCHIVE_TIMEOUT` the `timeout` passed to `_send` for Download all? And `tries`? Not tested.

## Notes and the check tool
17. Exact wording of the notes (no account, no Download all, not an archive, too large, the counts):
    the tests only check that a note exists, plus the two prefixes the brief names.
18. `main` usage: printed to stdout or stderr? The tests accept either.
19. `tools/comdia_check.py` isn't tested: no test imports `tools/`, and the brief gives only its
    one line (`main(["--check"])`). Should it get a test, and how should it be imported?

# Open questions — the Dalux client version, notices only TED holds, host failures

For `test_dalux_refused.py`, `test_dk_ted.py`, `test_dk_recon_ted.py` and `test_dk_day_ted.py`.
The tests were written without running them: no tool in the room executes code.

## Existing tests to look at (none contradicts the spec)
1. `test_dk_day.py`, **`test_a_ted_difference_makes_the_day_incomplete`**: the new TED lookup will
   meet `net.open_url` raising `AssertionError`. The test passes only if a lookup raising anything
   leaves the day incomplete rather than crashing it. Is that the intended breadth of "does not
   hand over"? And **`test_a_watched_procedure_with_no_live_notice_is_a_watch_hole`** patches
   `dk_targets.one` only, so a procedure lookup there is answered with the whole window.

## What the tests assume, for want of a statement
2. **What `net.get_text` returns** (text, or text with headers like `get_json`) is not stated. The
   tests take the shape from the real function, called with `opener=` as `test_net.py` calls
   `net.get_json`. If `get_text` takes no `opener`, `setUp` of the two TED files must change.
3. **`ref` of a TED notice** is taken to be the padded number, as on a udbud.dk EU row
   (`test_dk_page.py`).
4. **`published`** is taken to be the date without its offset, as on a udbud.dk row.
5. **`read_from_ted`** is taken to sit beside `only_ted` in the day's entry of `report["ted"]`.
6. **No procedure id** is taken to follow "Three ids": `int-<buyer>-<internal id>`, then
   `notice-<noticeId>`. Two notices with the same buyer *and* the same internal id would share a
   home by that rule, while the brief says two notices with no procedure id must not. Which wins?
   And what keys a notice with no `notice-identifier` either? Neither is tested.
7. **TED's search answer** is taken to be `{"notices": [...], "totalNoticeCount": n}`, as in
   `test_dk_recon.py`. Does `dk_ted.search` page? Not tested. The day tests' TED stand-in finds a
   record by its unpadded number or its procedure id appearing in the query.
8. **`titles`** of a TED notice is taken to be the Danish then the English title, as on a row.
9. `day_verdict.main` is taken to exit 0 when the verdict is ok.

## Dalux
10. Does a refused retry leave the version it named in `CLIENT["version"]`? Only the number of
    requests and the raise are tested.
11. Is a not-public message raised or returned by `_call`? Only the listing is tested.
12. The numeric `result` of a not-public answer is not stated; the tests use 3.

## TED
13. `target["record"]` and `document["record"]`: the raw record, or the number? Only the key is
    tested, and that a gated row does not carry it.
14. `procedure_id` as printed, or lower-cased? `link_verified` true or false? `notice_version` `1`
    or `"01"`? `form_code` values? Only that the keys are there.
15. **A date without a time**: `2027-01-22` or `2027-01-22+01:00`? The tests only refuse an hour.
16. Fewer times than dates (two lots, one time): which date gets it? Not tested.
17. `form-type` values other than competition and result (planning, change, dir-awa-pre,
    cont-modif, consultation): the README's table? Not tested.
18. `text` when the rendering fails: `""` or `None`? The tests accept either.
19. Does `procedure` raise or answer `(None, None)` when TED cannot be reached? For a watched
    tender, is that a watch hole or an incomplete day?

## The day
20. A **TED-only award or plan**: does it go to `closed` / `plans`, and count in `from_ted`?
21. A TED-only notice whose procedure already has a row in the window: is it one home, with the
    older notice under `superseded`?
22. Does `from_ted` count a watched tender read from TED? Not tested.
23. Do host failures make `day["complete"]` false, or only the verdict? Not tested.
24. Is `host_failures` present and `[]` when there are none? The tests accept absent.
25. `taken`'s `numbers` with leading zeros: normalised? The tests pass the unpadded form.
26. The wording of the verdict's lines for a host failure is not stated; only that there are some.

## A window read late

For `test_dk_day_newest.py`, written without running it: no tool in the room executes code.

1. **A watched tender in the window.** The README says "every competition past the gate"; the brief
   says a watched tender is not changed. The test follows the brief: the watch lookup answers the
   window's notice, the procedure holds a later one, and the window's is fetched. When the watch
   lookup answers a newer notice than the window's, is the window's named under `superseded`? Not
   tested. Nor is whether a watched tender's procedure is asked for at all: only what is fetched.
2. **The newest later notice is unusable** (no detail, another procedure's identifier, or its detail
   raises) and an older one, still later than the window's, is usable. Does the day fall back to it,
   or keep the window's notice? Not tested.
3. **Notices between** the window's and the newest: are they named under `superseded` too? The test
   only checks that the window's own is.
4. **Two notices of one procedure in the window and a later one outside it:** are both of the
   window's named under `superseded`? Not tested.
5. **A newer notice whose title and description would not pass the gate:** still fetched? Not tested.
6. **A competition with no procedure id** (`int-…` or `notice-…` key): is a lookup made? Not tested.
7. **A notice only TED holds:** is udbud.dk asked for a newer notice of its procedure? Not tested.
8. **A later notice of the same procedure that the portal prints with no readable date:** not tested.
9. Which exceptions count as "the portal raising"? The tests raise `net.Unreachable` only.
10. **Existing tests:** `test_dk_day.py` and `test_dk_day_ted.py` do not patch `dk_targets.procedure`.
    In `test_dk_day.py` the lookup is answered with the whole window, where every row has the same
    date, so nothing there should win. None contradicts the spec.
