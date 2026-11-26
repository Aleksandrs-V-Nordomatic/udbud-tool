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
15. **Over the 4 GB limit** (`comdia.MAX_UNPACKED`; the README says "an archive over 4 GB
    unpacked"): is the limit applied to the sum of claimed sizes or to each member? The tests check
    one member over the limit and two members whose sum is over it.
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

## Rows counted as distinct notices

For `test_dk_targets_distinct.py`, written without running it: no tool in the room executes code.

1. **A single day short with no repeat** (an empty page before the total): is it asked four times
   too, or does it raise at once? The README's "a single day that is still short is asked up to four
   times" reads as four times. **Existing tests that conflict with that reading:**
   `test_dk_targets.py`, `test_fewer_rows_than_the_count_is_truncated`, and `test_dk_day.py`,
   `test_a_truncated_window_is_a_failed_discovery_with_its_reason`. Both script two calls for a
   single day (`side_effect` with two answers), so a second pass meets `StopIteration`. The new test
   asserts only the raise, not the number of passes. Neither existing test was changed.
2. **A window over several days short with no repeat:** does it raise at once, or fall back to single
   days? The README names the fallback only for a window "that holds a repeat". Not tested.
3. **A repeat although every distinct row is held** (more rows handed out than the total): is the
   window whole, or is it read again? Not tested.
4. **More distinct rows than the total:** accepted, or `Truncated`? Not tested.
5. **The total changes** between the pages or the passes of one read: which total is the proof, and
   which is returned? Not tested; every stand-in holds one total per window.
6. **The single days' totals do not add up to the window's total** after the fallback: `Truncated`,
   or the days' word? In the tests they always add up, except that a day stays short.
7. **Rows of the first, wide read in the fallback:** are they added to the days' rows, so that a row
   a day leaves out but the wide read held completes it? "Read again day by day" does not say. In
   the tests the missing row is missing from the wide read too.
8. **In the fallback, a row inside the window but not of the single day asked:** `OutsideWindow`? The
   tests use a row outside both.
9. **The order of the returned rows** after a repeat is not stated; the tests compare them sorted.
10. **Which copy is kept** when two rows share `noticeId` and `noticeVersion` but differ elsewhere
    (for example in `noticePublicationNumber`)? Not tested.

## Comdia: prequalification and media

For `test_docsource_prequal.py`, written without running it: no tool in the room executes code. No
existing test was found to contradict the README.

1. **45000000 "main only".** The brief marks it so; the README makes no difference between
   `cpv_main` and `cpv`. Does `45000000` standing only in `cpv` count? The tests use it as `cpv_main`
   and in `building_work(["45000000"])`, not in `cpv` alone. And does "main only" mean only the
   bare division code, so that other 45000000-like codes (4500xxxx) are not building work?
2. **The exact prefixes of `BUILDING_CPV`** are not stated, so codes outside the brief's list are
   not tested (451 site preparation, 713 other than those named, 71400000, 71500000). Nor is a code
   with its check digit (`45210000-7`).
3. **The note of a tender not pressed:** the tests take "the note says that it has prequalification
   and is not building work" to mean it holds `prequalification` and `not building work` in any case
   of letters. The same note is expected without `facts`, where it is not known whether it is.
4. **The press that leads back to the tender page, which now offers Go to tender:** is Go to tender
   pressed, or is it `gated`? Not tested; the tests lead to the home page and to the same page with
   no Go to tender. The wording of that note is not stated; only that there is one.
5. **Access to tender pressed, and the page it leads to offers only Access to prequalification:** is
   that pressed for building work? Not tested.
6. **The session ends on the answer to the press** rather than on the tender page: fresh sign-in?
   Not tested.
7. **`watched` values other than true and false** (`1`, `"yes"`, `"false"`): not tested.
8. **The order in the "left out" note:** by extension, or by count? The README's example fits both.
   The tests check each count and extension only. How it is joined to another note (the two counts
   of the vendor page) is not stated either.
9. **The keys of `left_out`** are taken to be lower case without a dot, as in `MEDIA`.
10. **An archive of media only:** does the note still name what was left out? Only `none` and no
    files are tested.
11. **A name that is an extension and nothing else** (`.bmp`): media, or a member with no extension?
    Not tested. Nor is a folder entry named like media (`144703/Film.mp4/`) in `left_out`.
12. **The top folder that is dropped:** is it found over every member, or over those kept (an archive
    whose media lie outside the tender's folder)? Not tested.
13. **Two further readings of "an archive over 4 GB":** is the limit asked of the archive's own size,
    with media in it, as well? The tests use small archives whose members claim a size.

## iBinder, as an anonymous visitor

For `test_docsource_ibinder.py`, written without running it: no tool in the room executes code. No
existing test mentions iBinder, and none in `test_docsource.py` was found to contradict the README.

1. **A name ending in `.PDF`.** "A file whose name does not end in `.pdf` is stored as `<name>.pdf`"
   does not say whether the case of letters counts. The test accepts `b.PDF` and `b.PDF.pdf`.
2. **401, 403, 404 or 410 from a folder's file list.** The README says so of the first step, "the
   tender and its configuration". Is the whole tender `gated`, is the folder passed over, or is it
   raised? Not tested. Any other error from a file list is tested to be raised.
3. **The sub-folders of an `Espd` folder:** asked for, or not? Not tested.
4. **A subdomain other than `my` and `bookshelf`** is wired to the module, but the README's link shape
   names those two hosts. The test takes such a link to be of another shape: `unknown`, asked nothing.
5. **Near misses of the link's shape:** a trailing slash, a query or fragment, no `/public`, capitals
   in the host. Not tested. Nor is a notice with several links (which one is read).
6. **Does `totalCount` count deleted rows?** The tests do not check which pages are asked for when a
   folder holds deleted rows.
7. **A `totalCount` that is absent**, or that changes between pages: not tested.
8. **A row without `GLOBAL_TenderVersionId`:** read with an empty `subresourceid`, or gated? Not tested.
9. **`"preview": {}`, or a preview whose `url` is null or of another shape:** no preview, or an error?
   Not tested; only `preview`, or `files`, being null or `files` absent.
10. **A `/` in a folder's or a file's name** within the joined path: not tested.
11. **`gated` paths** are taken to be the folder names and the file's own name joined with `/`, with no
    `.pdf` added.
12. **"must be a PDF"** is tested with an HTML page, a zip and an empty body. Whether bytes before
    `%PDF` are accepted is not tested.
13. **May a reason name the store's host and path?** The tests forbid the whole link and any part of
    its query.
14. **The notes of `public`, `none`, `unknown` and a tender whose link is not public** are not stated,
    so only the notes with a code or a count are checked.
15. **The number of requests per call** is not tested where a call fails, since `tries` belongs to
    `common.fetch`.

## One tender fetched by hand

For `test_dk_live_notice.py`, written without running it: no tool in the room executes code. No
existing test was found to contradict the README.

1. **A live notice of the portal whose detail is gone** (`dk_page.detail` answers `None`): `(None,
   None)`, the target with `None`, or an error? Not tested.
2. **Errors.** That an error of the portal and of TED is raised comes from the brief; the README does
   not say so. The tests raise `net.Unreachable` only, and take it that a portal that raises does
   not "know nothing", so TED is not asked.
3. **`dk_targets.one` answers `None` while `dk_targets.procedure` lists a live notice** (its detail
   is unreadable): the portal knows it, so TED is not looked at? The test lists an award only.
4. **A procedure only TED holds whose newest notice there is an award or a plan:** is it fetched by
   hand? `dk_ted.procedure` decides it, or `live_notice`? Not tested.
5. **An empty reference**, and the `DK:` prefix: the tests take the reference to be passed on as
   given to all the lookups, as the brief's interface prints them.
6. **Is the target handed back unchanged?** The tests compare TED's target whole, and the portal's by
   `notice_id` and `pid` only. A mark such as `watched` is not stated.
7. **`dk-fetch.yml` and the command it runs** when the answer is `(None, None)`: not tested.

# Open questions — plans and market consultations judged like competitions

For `test_dk_page.py` (`KindOf`, `PlanKey`, `Supersedes`), `test_dk_day.py`, `test_dk_day_plans.py`,
`test_dk_day_newest.py` (the plan tests at its end), `test_dk_targets_plans.py` and
`test_dk_ted_plans.py`. These were written without running them: no tool in the room runs code.

## Existing tests rewritten to the new rule (the brief asked for it)
- `test_dk_page.KindOf.test_live_and_close_kinds` used to assert that `plan` and `consultation` are
  not live. It now asserts that they are, and that `award`, `modification` and `other` are not.
- `test_dk_day.Day.test_plans_are_recorded_and_counted` used to assert that the plan is not fetched.
  It now asserts that the plan is fetched, is listed under `tenders` with `kind` `plan`, and is
  still named and counted in `plans`.
- `test_dk_day.Day.test_competition_rows_are_fetched_into_their_procedure_home`: the fetched pids are
  now `{P1, P4}`, where P4 is the window's plan "Alfa plan", which passes the gate. Both homes are
  checked. The order is compared sorted because nothing states it.
- `test_dk_day.Day.test_two_notices_of_one_procedure_make_one_home`: two fetches. P1's one fetch is
  `n-a2`, `n-a1` is superseded, and the homes are `{P1, P4}`.
- None of these was weakened: each still checks what it checked before for the competition.
- Earlier question 6 under "notices only TED holds" is now answered **for plans only**
  (`notice-<noticeId>`). For competitions with the same buyer and the same internal id it stays
  open, and `test_dk_ted.NoProcedure` was left unchanged.
- Earlier question 17 under TED is answered for `planning`. `test_dk_ted_plans.py` tests only that
  value. Whether TED's `consultation` and `preplanning` map as in `dk_page.KINDS` is not tested.

## Left open
1. **The order** of `tenders`, of the fetches and of `plans` in a window that holds a plan is not
   stated. The tests compare sorted lists or look an entry up by `pid`.
2. **A watched plan that prints a procedure.** The card is `DK:notice-<uuid>`, but the home is the
   procedure's. Does the day count the watch as answered? And is a later competition of that
   procedure fetched in its place? Not tested.
3. **`one("DK:notice-<uuid>")` where the plan prints procedure P, and P holds a newer plan and an
   older competition.** "Its newest notice that `supersedes` the found one" picks the newer plan
   (plan over plan is True). "A competition is answered before a plan, whichever is newer" picks the
   competition. Which wins? Not tested. The competition-first test asks for P directly.
4. **The case of the uuid** after `notice-`: is it searched as written or lower-cased? The tests use
   a lower-case uuid and only vary the case of `DK:` and `notice-`.
5. **What a gated plan entry holds**, `kind` for instance. The tests check `pid`, `notice_id` and
   `title` only.
6. **A lost plan.** The tests find it in `day["lost"]` by `ref` (its `noticeId`, since it is
   national). Its `pid`, and whether it counts in `coverage.failed`, are not tested.
7. **`supersedes(newer, older)` when `older` is a close** (a tender over an award), and two notices of
   different procedures: not stated, not tested.
8. **Does a plan whose detail is gone still count in `plans` / `counts.plans`?** "Every plan the
   window held" suggests yes. Not tested.
9. **TED-only plans** (earlier question 20 under "The day"): do they count in `plans` and in
   `from_ted`? Not tested.
10. **How the internal id is cleaned** in an `int-` key (`#`, spaces, `/`). `test_dk_page.py` shows
    `TS 2385/59` → `TS_2385_59`. The plan tests avoid relying on it, except to check that no
    `int-` home appears.
11. **`dk_page.PAGE`** is assumed to exist, as the brief's `procedure` signature names it.
12. **`_newest` and the plans of `test_dk_day.py`:** that file does not patch `dk_targets.procedure`,
    so the plan's lookup (P4 prints a procedure) gets the whole window as its answer. Every row has
    the same date, so nothing should win. This is the same as earlier question 10 under "A window
    read late".

## Second pass (`test_dk_targets_plan_lookup.py`)
- **Questions 3 and 4 above are answered.** 3: the competition wins; among the newer notices of P
  that `supersedes` the found plan, a bid-kind one comes before a plan-kind one, the newest first
  in each group. 4: the uuid is lower-cased before the search, and the notices that come back are
  compared to it without regard to case. Both are tested in the new file. So is the new rule that a
  `notice-<uuid>` reference keeps only the rows whose `noticeId` is that uuid.
- No existing test contradicts the new rule. The `notice-…` references in `test_dk_targets.py`
  (`notice-1`, `notice-9`) are not followed by a uuid, so they are not filtered, and the rows in
  `test_dk_targets_plans.py` that a home name finds all carry that uuid.

Still open from this pass, and not tested:
13. **A competition of P published before the plan that was asked for.** Is it among "the newer
    notices of P"? "Whichever is newer" suggests it would be answered too. In the tests every
    competition of P comes after the plan that was asked for.
14. **P holds nothing that `supersedes` the plan** (only an award after it, say). Is the plan itself
    answered with `pid` P, or None? Not tested.
15. **Two rows that both carry the uuid** (two versions of the plan) after the filter: both kept,
    newest first? Not tested.
16. **The `noticeId` the answer carries** when the reference's case differs from the portal's: the
    tests take it as the portal prints it.

# Open questions — a home read again, an index that moved, a home kept, EU-Supply names

For `test_carry_over.py`, `test_index_moved.py`, `test_dk_day_kept_home.py` and
`test_eusupply_names.py`, written without running them: no tool in the room executes code. They
follow the README sections "A home read again", "What a day fetches" (the paragraph "A home never
goes back to an older notice") and the EU-Supply bullet under "Where the documents are". No existing
test was found to contradict those sections.

## A home read again (`test_carry_over.py`)

1. **How the drive is read is not tested.** The README says `homes.held` reads
   `<GRAPH_DEST_ROOT>/DK/tenders/<pid>/` when all five `GRAPH_*` variables are set, asks for
   `state.json` first and nothing more when it is absent, and answers None when the drive does not
   answer. The tests clear the variables and only check that four of the five do not reach the
   network. Which call reads the drive (`deliver_graph.json_at`?), the order of the other four files,
   what `where` is then, and whether a home on disk with only one of `index.json` / `state.json`
   falls through to the drive, are all open.
2. **`homes.newest_published(None)`.** The README says what it answers for a home, not for no home.
   None, or an error? Not tested; the tests pass a dict with `procurement`. Nor is a `procurement`
   that is absent, or `published` values of another shape (with a time, or `None` in a notice).
3. **What the Comdia signature does when the "Not downloaded" marker changes.** The README leaves
   out "the marker and anything else in the name cell" and keeps "the cells after the marker". After
   the first night the vendor page marks each file downloaded, so the marker's own cell may read
   otherwise. Does that cell count? If it does, every watched Comdia tender is downloaded again on
   the second night. The tests keep the same marker in every row and change only the name cell's
   image and aside, the name, the group, the cells after the marker, and the rows.
4. **What a Comdia index entry contains.** The tests build the handed index with `id`, `name`,
   `folder` and `download` per document, and check of the held files only their ids (in the index's
   order) and `held`. Which further fields a `held` file carries (`bytes`, `folder`, the index
   entry's own `download`) is not stated.
5. **Where the carried files' unreadable entries come from.** `with_carried` "makes the unreadable
   list again over both without repeating a file". Are a carried record's unreadable entries taken
   from the home's text manifest (`unreadable_files` with that `record_id`?), and is a file that is
   unreadable tonight and carried counted once? Not tested: every carried file in the tests is
   readable text, and `with_carried` is given `unreadable_files: []`.
6. **The `carried` count in day rows and in `day.json`.** Only `dk_fetch.fetch`'s `carried` is
   tested, and taken to be a number (`2`), while `store` answers carried *ids*. Whether `carried` in
   `with_carried`'s answer is a count or a list, and the key of `day.json`'s counts (`counts.carried`?)
   are not tested. Nor is the run's log line (megabytes downloaded, documents carried).
7. **What the tests assume of the interfaces:**
   - `dk_fetch.store(home, platform, files)` works without `carry`, and `carried` is falsy then.
   - `dk_fetch.fetch` hands the home's index to `docsource.listing` as the keyword `held=`, and
     "lists the tender again without the index" means a second call whose `held` is absent or None.
   - `docsource.unchanged`, `dalux.unchanged`, `ibinder.unchanged`, `ethics.unchanged` and
     `comdia.unchanged` answer exactly `True` or `False` (`assertIs`).
   - A record's title is `folder/name`, and `name` alone when the folder is empty.
   - `deliver_dk.fill_carried` reads the drive with `deliver_graph.bytes_at(drive, path, tok)`, the
     archive at `<home_root>/<pid>.zip` with members `doc/<key>.md`, then `<home_root>/doc/<key>.md`
     one by one, and the keys are those of the state's `documents`.
8. **A carriable record whose title matches but whose file is now listed under another id**, and a
   `held` Comdia file whose id is not in the carry: not tested.

## An index that moved (`test_index_moved.py`)

1. **Does the delivery stamp fields besides the seven named?** The README names `written_at`, `date`,
   `run_id`, `run_file`, `home`, `archive` and `index_file`. The tests assert that the delivered
   index equals the home's own outside those seven, so a further stamped field would fail them.
2. **A field the new index no longer has** (present in the old one only): is it named as moved?
   "The top-level fields whose values differ" suggests yes. Not tested, except for the stamped ones.
3. **How values are compared** (lists in another order, `1` against `1.0`, nested key order): plain
   equality is assumed.
4. **`index_moved` when nothing moved**: absent, or `[]`? The tests accept either (falsy).
5. **A procurement that did move** (or is `new`): does its run record and its row carry `index_moved`
   too? Not tested; only `unchanged` tenders are.
6. **A drive that fails when `index.json` is asked for** (raises, rather than answering None): the
   tests only give "no index on the drive", which is taken as no old index, so every field moved.
7. **What the tests assume of the interfaces:** `deliver_dk.deliver(out, date, run_id, drive, base,
   tok)`; the drive read with `deliver_graph.json_at` and `bytes_at`, written with `upload`; the
   index at `<base>/tenders/<pid>/index.json`; and the result's keys `files`, `bytes`, `tally`,
   `sent`, `carried`, `tenders`. None of these is in the README; they are taken from the delivery as
   it stood.

## A home kept (`test_dk_day_kept_home.py`)

1. **Which key holds the reason in a watched tender's `lost` entry.** The README says "a reason that
   says the home holds a newer notice". The tests find the entry by the procedure id anywhere in it
   and check only `watched: true`; neither the key (`reason`? `note`?) nor its wording is tested.
2. **Is a kept tender also left out of `changes.json`'s `tenders`?** The README says "it is not among
   the day's `tenders`". The tests check `day["tenders"]` and `day.json`'s `tenders`, not
   `changes.json`'s.
3. **A home of the same day.** "When the home's is later" is read strictly: a home whose newest
   notice is the same date as the notice about to be read is fetched.
4. **The portal answers a newer notice and the home is later still.** The tests check that the newer
   notice is named with `kept_home`, and that every kept entry carries the home's date. Is the
   window's own notice named as well, and with `kept_home` or without? Not tested.
5. **A kept watched tender and the day.** Does it make the day incomplete, or count as a watch hole?
   Only a kept tender of the window is tested to leave the day complete.
6. **A notice TED handed over and a later home**: the README names it, the tests do not.
7. **How dates are compared.** The tests use plain `YYYY-MM-DD` strings. A `published` with a time or
   an offset on one side only is not tested.
8. **Counts.** Does a kept tender count anywhere in `coverage` or the counts? Not tested.
9. `homes.held` is taken to be called with `(out_root, pid)` in that order, positionally or not, and
   `dk_fetch.fetch` to be given the held home as the keyword `held=` (the same object).
10. `homes.newest_published(None)`: see question 2 under "A home read again".

## EU-Supply names (`test_eusupply_names.py`)

### Two tests corrected after the first draft (not weakened)
- **The purchase page address.** The first draft expected the first request at another address. The
  README names no address for the purchase page, so the test was corrected to the address the module
  builds, `eusupply.PURCHASE % pid`
  (`https://eu.eu-supply.com/ctm/Supplier/PublicPurchase/123456/0/0?returnUrl=&b=`). The assertion is
  as exact as before, and still checks that `/app/docmgmt` is never asked.
- **`gated` holds the public names too.** The first draft expected `gated` to hold only the names after
  "Available after expression of interest". EU-Supply is "names only — public ones too" and nothing is
  downloaded there, so a public file is not read either; the test now expects `gated` to hold both and
  `public_names` the public ones alone. It still compares whole lists.

### Left open
1. **The order of `gated`.** Public names first, page order, or gated first? The test compares
   `gated` sorted where both kinds are on one page; with gated names only it takes page order.
2. **A name listed both as public and as gated**: once in `gated`, or twice? Not tested.
3. **What "and `�` with them" means for `clean_name`.** Is the replacement character removed, turned
   into a space like the pair, or only removed where it leads a name (a broken pair)? Not tested.
4. **The page's encoding.** "Single-byte" is read as latin-1, as the README's `Â` suggests. Bytes
   0x80–0x9F, which cp1252 reads otherwise, are not tested.
5. **A space before the extension** is kept after collapsing (`Bilag 1 .pdf`); the README says only
   runs of spaces collapse and the ends are trimmed.
6. **The listing's further keys** `public_names` and `tender_id` are not in the README; the tests
   take them from the module, and accept a name as a string or as a dict with `name`.
