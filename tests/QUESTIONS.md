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
