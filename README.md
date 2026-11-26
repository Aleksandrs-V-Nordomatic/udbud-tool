# udbud-tool

The Danish reader for the tender radar. It fetches a window of [udbud.dk](https://udbud.dk) into
the delivery shape every country tool in this family produces, proves the window arrived whole,
and says which of its tenders it could actually read.

Latvia is `eis-tool`, Lithuania `epps-tool`, Estonia `rhr-tool`, Finland `hilma-tool`. One
repository per portal, one country per repository, and the same `day.json` beside the same
folders in every one of them.

**Proprietary. All rights reserved; no licence is granted and no use is permitted — see
[LICENSE](LICENSE).** This includes copying, running, modifying and AI training. Contributions
are not accepted.

## One country

`--country DK` has no default. The destination folder is derived from the country, and
`country.py` refuses any code it has no reader for; `deliver_dk.py` refuses any country that is
not Denmark even though `country.py` already did — the two guards answer different questions.

The CLI is `eis_tool.py`, the family's name, not `udbud_tool.py`: a person who has driven one
country's tool has driven this one.

## Use

```bash
python3 eis_tool.py probe --country DK                         # does this address get Denmark whole
python3 eis_tool.py discover --date 2026-09-02 --country DK    # the window, fetching nothing
python3 eis_tool.py reconcile --date 2026-09-02 --country DK   # the coverage controls alone
python3 eis_tool.py day 2026-09-02 --country DK --out work --policy policy.json
python3 eis_tool.py day 2026-08-24 --to 2026-09-02 --country DK --out work --policy policy.json
python3 eis_tool.py fetch 7c03c120-69c0-4112-af76-3d30b1aab18e --country DK --out work
python3 eis_tool.py scans --date 2026-09-02 --country DK       # read what no decoder could
```

Dates are **Danish calendar dates**. udbud.dk filters and prints `publiceringsdato` as a date in
Copenhagen, and the nightly default is yesterday in Copenhagen.

## The route

```
POST https://udbud.dk/soegning/public/soegeresultat     the window, 100 rows a page
GET  https://udbud.dk/soegning/visning/{noticeId}/{ver}?noticePublicationNumber={npn}
```

The portal's own search backend. No account, no key. udbud.dk's terms allow
`udbudsformidlere` to read it round the clock. The official ERST API
(`api.udbud.dk/udbud/ekstern-data/...`) answers 401 without a registered client and is the
fallback if this route ever changes.

The search row carries the title in Danish and English, the buyer, the main CPV code with its
name, the deadlines and the buyer's own description — everything the recall gate reads. The
detail adds what the row does not: the procedure id, the documents link
(`opsummeringDA.udbudsDokumenter`), lots, place, and the whole notice rendered as HTML.

`noticePublicationNumber` must be exactly what the notice carries: the TED number on an EU
notice, empty on a national one. Anything else is a 404. The page a person opens
(`/detaljevisning?...`) answers 200 with the same shell for a notice that exists and one that does
not, so links are checked through the detail call, never by status.

## Three ids

| field | identifies | |
|---|---|---|
| `procedureId` | the tender, across every notice it ever gets | **the key** — `tenders/<procedureId>/` |
| `noticeId` + `noticeVersion` | one notice | an amendment has its own |
| `noticePublicationNumber` | the TED number, `00604959-2026` | empty on national notices |

`procedureId` is eForms BT-04, printed only in the detail's notice as *Identifikator for
proceduren*. Over 474 competition notices in forty days, 51 procedures carried more than one
notice. Keyed on `noticeId`, one tender would become two homes. Where a notice prints no procedure
the home falls back to `int-<buyer>-<internal id>`, then `notice-<noticeId>`.

**A plan or a market consultation that prints no procedure is keyed `notice-<noticeId>`**, never
`int-`. Measured over the 35 plans of 9–25 Nov 2026: none printed a procedure, and the internal id
is whatever the buyer typed — Holbæk Kommune's is `Holbæk Kommune`, and two plans of one fund both
carry `KYC#1` — so `int-` would put two plans in one home. A plan that does print a procedure is
keyed on it like a competition. udbud.dk and TED key a plan the same way, so both open one home.

A card is **held by its procedure id**. The search's free text matches a procedure id and a
notice id exactly and does not match a TED number, so `--targets` and `fetch` take a procedure id
(`DK:<uuid>` or the bare uuid); a notice id is followed to its procedure's newest live notice. A
plan's card is held by its home's name, `DK:notice-<noticeId>` or `notice-<noticeId>`: the lookup
searches for the notice id (lower-cased), keeps only the notice that carries exactly that id, in any case — the free text also
matches a notice that merely mentions it (measured: Amgros' plan `a183b490-…` came back under an
unrelated competition) — and answers that plan while it is live.

Where a procedure holds both, the lookup answers a competition before a plan, whichever is newer —
also when it was asked for a plan that prints that procedure —
and the day's newest-notice check (below) never puts a plan in place of a competition. A plan that
prints a procedure is replaced by a newer competition of that procedure, which takes over the home;
a plan keyed on its notice stays a home of its own, and the competition it announces arrives later
as another.

## What a day fetches

Every row in the window gets its detail — about forty requests on a busy day — because the
procedure is only in the detail, and an award without its procedure cannot close the card it
answers.

| `formulartypeKode` | kind | what happens |
|---|---|---|
| `competition` | `tender` (`amendment` when `erAendring`) | through the gate; fetched |
| `change` | `amendment` | through the gate; fetched |
| `result`, `dir-awa-pre` | `award` | recorded in `changes.json` as a close |
| `cont-modif` | `modification` | recorded as a close |
| `planning`, `preplanning`, `consultation` | `plan` / `consultation` | through the gate; fetched |

A plan or a market consultation is a live notice like a competition: it passes the same recall gate,
gets its detail, a home and its documents, and is listed under `tenders` (or `gated`) with its own
`kind`. A plan whose detail answers 404 is lost like a competition and makes the day incomplete.
`changes.json` `plans` (and `counts.plans`, `coverage.plans`) still names every plan and consultation
the window held, fetched or gated, so the count of them stays readable.

Two notices of one procedure in one window make one home; the older is named under `superseded`.

**A home never goes back to an older notice, across runs either.** Before a tender is fetched, the
newest notice its home has carried (`homes.newest_published(held)`) is compared with the `published`
of the notice the run is about to read. When the home's is later, the tender is not fetched and the
home is left as it is: the notice is named under `superseded` in `changes.json`, with `kept_home`
set to the home's later `published`, and it is not among the day's `tenders`. A watched tender kept
that way is also listed in `day.json`'s `lost` with `watched: true` and a reason that says the home
holds a newer notice; a tender of the window is not lost, because the window was read whole. Seen on
24 Nov 2026: reading 17 Nov after 23 Nov put a tender's first notice back over its amendment. The
portal's newest-notice lookup (under *Coverage proof*, "A window read late") closes that inside one run; the home's
own history closes it when the portal does not answer, and for a notice TED handed over.

## Where the documents are

udbud.dk holds none. Each notice links the platform the buyer runs the tender on. `docsource/`
has one module per host, each answering `listing(urls)` and `download(entry)`:

| module | host | what is read |
|---|---|---|
| `ethics` | ethics.dk | every public file; records marked `accessRequired` are named |
| `dalux` | dalux.com | every file of a public tender; four read-only RPC commands only |
| `udbuddk` | api.udbud.dk | every file; the path is quoted (names carry `ø`) |
| `byggeweb` | byggeweb.dk | every file, in two steps |
| `eusupply` | eu-supply.com | names only — public ones too, see below |
| `mercell` | permalink.mercell.com | names only |
| `comdia` | comdia.com | every file, under our supplier account — see below |
| `ibinder` | my.ibinder.com, bookshelf.ibinder.com | what the public view shows — see below |

Measured over the 174 competition notices of 3–14 Nov 2026: all files on 30% of tenders, 42% of
the construction ones. ethics 481 of 481, Dalux 1 622 of 1 622, api.udbud.dk 18 of 18, Byggeweb 24
of 24.

**A host that needs an account is a module that names files and downloads none.** When an
account arrives for EU-Supply, Mercell or Comdia, that module is the only file that changes.
Comdia's arrived on 23 Nov 2026; Mercell's terms forbid automated download, so Mercell stays a
names-only module and a person opens the tender page.

### Comdia, under an account

Comdia shows "Documents 0" to everyone, signed in or not. The files open to a supplier that
presses **Access to tender** on the tender page. `docsource/comdia.py`, in plain HTTP:

1. **Signs in once per run** on `/login.aspx` with `COMDIA_USER` / `COMDIA_PASSWORD`. A refused
   account is not asked again that run; a session that ends mid-run gets one fresh sign-in.
2. **Opens the tender page** (`…/tenderinformationshow.aspx?Id=N`). If the company has no access
   yet, it presses **Access to tender** (`lbRegisterTender`), then **Go to tender**
   (`lbGoToTender`), which leads to the vendor page `/Site/vendor/user/tenderentity/show.aspx`.
   A tender with **prequalification** offers **Access to prequalification**
   (`lbRegisterPreQual`) instead. It is pressed only for building work or for a watched card
   (below); the press itself leads to the vendor page, and the tender page keeps offering it, so
   the same press opens the tender on every later run.
3. **Presses Download all** (`lbDownloadAll<k>`) and gets one ZIP of the tender.
4. **Lists each member as a file**, its folder the group the buyer filed it under (the archive's
   own top folder, the tender, is dropped), and serves each member's bytes from the archive held
   in memory. `dk_fetch` asks its usual two questions and stores them as from any host. Video,
   bitmaps and inspection data (`comdia.MEDIA`: mp4, avi, mov, wmv, mkv, mpg, mpeg, m4v, bmp, dat,
   evtdat, in any case of letters) are left out, because nothing reads them: they are not listed,
   not counted against the 4 GB, and the note says how many of each extension there were, for
   example `left out, nothing reads them: 223 .bmp, 41 .mp4`. A tender whose archive holds nothing
   else is `none`.

**Which prequalification tenders.** `docsource.listing(urls, facts)` hands the notice's record to
Comdia, and no other module. Access to prequalification is pressed when `facts["watched"]` is true,
or when a CPV code in `facts["cpv_main"]` or `facts["cpv"]` starts with one of
`comdia.BUILDING_CPV` (`comdia.building_work(codes)`): construction in general, buildings,
installation and completion, repair of building installations, and their design and supervision.
Roads, pipelines and water works, surveys and environmental consultancy are not building work.
Without `facts` it is not pressed. A tender where it is not pressed stays `gated`, and the note says
that it has prequalification and is not building work. Where a tender page offers Go to tender or
Access to tender, that is taken and Access to prequalification is not pressed.

**The buyer sees it.** Access registers the company (SIA "Nordomatic") on the tender, the tender
lands in My Comdia → My Tender/offer, and the vendor page marks each file downloaded. That was
decided on 23 Nov 2026, and for prequalification on 24 Nov 2026. It happens only for tenders that
reach the fetch — recall-gate survivors and watched cards. Opening a prequalification files no
application. **Show interest and Subscribe are never pressed**: the module refuses to post back any
control but the sign-in, Access to tender, Go to tender and Download all, and Access to
prequalification only on a call that says `prequalify=True`.

When it cannot read a tender — no account, a refused sign-in, a tender page that offers no Access
to tender, an answer that is not an archive, an archive over 4 GB unpacked — the tender stays
`gated` and the reason is the listing's note, in the home's `index.json` (`documents_note`).
When the vendor page lists more files than the archive holds, the note says both counts. A link
with no `Id=` is `unknown`. The module prints nothing: the run's log is public.

`python3 tools/comdia_check.py` signs in and presses nothing else.

### iBinder, as an anonymous visitor

A notice links `https://<my|bookshelf>.ibinder.com/etendering/<organisation>/tenders/<tender>/public`,
which opens the tender as "Anonymous": every folder, every file name, and a viewer. Nothing is
registered and no account is used. `docsource/ibinder.py` asks the page's own API, with the
organisation in the `x-ibinder-tenantid` header:

1. **Reads the tender and its configuration.** A 401, 403, 404 or 410 is `gated` with the code in the
   note; any other error is raised, so the night says the host failed. When `publicLinkEnabled` is
   not true, the tender is `gated` and no folder is asked for.
2. **Walks the folders** (`procurementSections`, and their `subTabs` to any depth). A `Navigation`
   folder holds no files of its own; an `Espd` folder is a form for the bidder; neither is asked for,
   and a `Navigation` folder's sub-folders are. `enabled` is ignored: it does not say what a visitor
   sees. A file's folder is the path of folder names.
3. **Lists each folder's files**, 250 to a page, until `totalCount` is reached or a page comes back
   empty. Files marked `deleted` are skipped.
4. **Downloads the preview**, the PDF the viewer shows, never the original: the preview call answers a
   short-lived link, which is followed only to `https://<name>.blob.core.windows.net`. What arrives
   must be a PDF. A file whose name does not end in `.pdf` is stored as `<name>.pdf`.

A file with no preview (zip, xml, xlsm) is not read: its path is listed under `gated`, and the note
says how many there are. With files read and none unread the tender is `public`; with some unread,
`partial`; with none read and some unread, `gated`; with no files at all, `none`. A link of another
shape is `unknown`. No reason or note holds a preview link, because it carries its own key. Nothing
but the tender, its configuration, the file lists and the previews is asked for: other calls answer
with the buyer's staff.

Per-host rules that came from running it, kept beside the code:

- **Dalux** exposes write commands to anonymous callers. `docsource/dalux.py` refuses any command
  outside `IsTenderPublic`, `GetTenderInformation`, `GetTenderShardUrl`, `GetFileList`. Files come
  from `node1.field.dalux.com`; the same path on `node1.build` is an HTML shell under a 200. Dalux
  refuses a client older than it wants (`result` 9, `Versions below 2026070 not supported`): the
  call takes the version the refusal names, keeps it in `CLIENT["version"]` for the run, and asks
  once more. Any other answer with a non-zero `result` raises `Refused` and is never read as a
  tender that is not public; a message saying *cannot be accessed publicly* is, and is `gated`.
- **EU-Supply** serves its public files from `/app/docmgmt`, which its robots.txt disallows, so
  nothing is downloaded there. It also drew 502 on six parallel requests; requests go one at a
  time with a cookie session. Its documents page is single-byte, but every file name on it is led
  by a UTF-8 non-breaking space, which read as latin-1 is `Â` and a non-breaking space (45 homes
  carried `Â ` on every gated name until 26 Nov 2026). `eusupply.clean_name(text)` unescapes HTML
  entities, turns that pair and any other non-breaking space into a space, collapses runs of
  spaces and trims the ends, and `�` with them; every public and gated name goes through it.
- **ethics.dk** lists records with no file (ESPD, response templates); they are skipped.
- Every download is checked by what arrived: an HTML page under a 200 is not the file.

## What a home holds

```
work/DK/
  tenders/<procedureId>/
    procurement.json   the facts, every notice that has carried this procedure, documents_available
    notice.json        the detail as udbud.dk served it (Danish)
    manifest.json      sha256 per file; the gated names as withheld records
    doc/notice.md      the notice: labelled facts, the description, the whole notice in Danish
    doc/<digest>.md    one file per readable document
    index.json         written LAST
    originals/         the downloaded files; never delivered
    state.json
  <date>/
    day.json           the window, the coverage report, what could not be proved
    changes.json       what moved, what the gate cut, the closes, every plan the window held
```

`documents_available` on every home and every day row:

| value | meaning |
|---|---|
| `public` | every listed file was read |
| `partial` | some were read, some are behind the platform's account |
| `gated` | the platform holds documents we could not read; `gated_documents` names what it shows |
| `none` | no documents link, or the platform says there are none |
| `unknown` | no reader for the host; a person opens `documents_link` |

**`doc/notice.md` is in every home.** For most Danish tenders the notice is the readable
artefact, and a card's quote is verified against the home's `doc/*.md` and nothing else. It holds
the facts as labelled lines, then the buyer's description exactly as `index.json` holds it, then
the whole notice as udbud.dk renders it.

## A home read again

A watched tender is read every night. On 25 Nov 2026 nine watched tenders were 4.6 GB of the night's
4.7 GB and about 35 of its 38 fetch minutes, for homes the delivery then called `unchanged`. So a file
the home already holds, unchanged, is **carried over**: not downloaded, not stored, not read again.

**What the home holds.** `homes.held(out_root, pid)` answers a dict with `index`, `manifest`,
`normalized` (the text manifest), `procurement`, `state`, and `where` (`disk` or `drive`), or None.
It reads `tenders/<pid>/` on the local disk first; a home counts only when its `index.json` and
`state.json` are both there. Otherwise, when all five `GRAPH_*` variables are set, it reads the same
files from the drive the delivery writes to (`<GRAPH_DEST_ROOT>/DK/tenders/<pid>/`), asking for
`state.json` first and nothing more when it is absent. It never raises: a drive that does not answer
is None, and the fetch downloads everything. `homes.newest_published(held)` is the latest
`published` among `procurement["notices"]` and `procurement["published"]`, or None. The night's
fetch step and `dk-fetch`'s fetch step are given the `GRAPH_*` secrets to read with; neither writes.

**Which files may be carried.** `dk_fetch.carriable(held, tool)` answers `{record id: {"record",
"doc", "texts"}}` — the home's manifest record, its index entry with the same id, and the text
manifest's entries whose `record_id` is that id. It answers `{}` when there is no home, no text
manifest, or when the home's `state["tool"]` is not `tool`, the extractor version of this run
(`changes.pipeline_version()`): text made by another version must be refreshed, and that needs the
file. A record is carriable only with exactly one file and an index entry.

**When a file is the same.** `dk_fetch.store(home, platform, files, carry)` answers `(records,
withheld, bytes, carried ids)`. For each listed file whose id is carriable and whose title
(`folder/name`) is the record's title:

- the host is asked first, `docsource.unchanged(platform, entry, held_doc)`. **Dalux** says yes when
  the id (the file's revision), the name and the download address equal the index entry's;
  **iBinder** the same (the version is in the preview address); **ethics.dk** when the id, the name
  and a known `bytes` equal it. Every other host says no. A yes carries the record without a
  download.
- otherwise the file is downloaded, and when its sha256 is the record's, the record is carried and
  nothing is written to `originals/`.

A carried record keeps its file name; a new file is never given the name of a listed file the home
holds, and a changed file reuses its own. `bytes` counts only what was downloaded.

**Comdia, by its vendor page.** `comdia.listing_signature(page)` is a digest of the vendor page's
document table (`…gvDocument`): for each row, the group it is filed under, the file name (the text of
its `lbDownload` link only) and the cells after the "Not downloaded" marker; the marker and anything
else in the name cell are left out. A page with no such table, or no file rows, is None. The listing
carries it as `listing`, and the home's `index.json` keeps it as `documents_listing`. When
`docsource.listing(urls, facts, held=index)` is handed the home's index, its `documents_listing`
equals the page's signature, its `documents_available` is `public` and it lists documents, the
archive is **not downloaded**: the files are the index's own, each marked `held`, with
`unchanged: True` on the listing and the index's note kept, and `comdia.unchanged` answers yes for a
`held` entry with the same id. When a `held` file is not carriable, `dk_fetch` lists the tender
again without the index.

**The text.** The extractor is shown only the files read tonight; `dk_fetch.with_carried(normalized,
carry, carried)` adds the carried files' own text entries, each with its `doc` (`doc/<key>.md`, the
key as `changes.document_key`), makes the unreadable list again over both without repeating a file,
and sets `entries`, `markdown`, `unsupported`, `chars` and `carried`. The fingerprint and the index
are made from that, so a tender whose files did not move is `unchanged` and an added or replaced file
is reported as before. `dk_fetch.fetch(..., held=held)` returns `carried`; each day row carries
`carried`, `day.json`'s counts carry `carried`, and the run's log prints the megabytes downloaded and
the documents carried.

**The delivery.** A carried text is on the drive and not on the runner. A procurement that moved
(and is not `new`) rebuilds `<pid>.zip`, so `deliver_dk.fill_carried(home, pid, home_root, current,
drive, tok)` takes each `doc/<key>.md` of the state that is not on disk out of the home's archive on
the drive, then one by one, and answers how many it could not find.

**An index that moved is delivered, even when the tender did not.** A procurement whose fingerprint
did not move writes only `seen.json` and `runs/<date>.json` — but its `index.json` can still have
moved: a new note from the host on a gated home, the vendor page's `documents_listing`. So the
delivery reads the home's `index.json` from the drive and compares it with the one it would write.
`deliver_dk.index_moves(old, new)` answers the sorted names of the top-level fields whose values
differ, leaving out what the delivery itself stamps: `written_at`, `date`, `run_id` and `run_file`,
which move every run, and `home`, `archive` and `index_file`, the home's address; with no old index,
every other field of the new one. When any field moved, `index.json` is uploaded on its own, the
run's record (`runs/<date>.json`) carries `index_moved` with those names, and so does the tender's
row in `changes.json`. Its `status` stays `unchanged`: what the buyer published did not move.

## Coverage proof

Two controls, both hard. `day.json` carries the report and `tools/day_verdict.py` prints it.

| | control |
|---|---|
| 1 | rows held == `totaltAntalResultater`, and every row inside the window asked for |
| 2 | per day, the TED publication numbers with a Danish buyer == udbud.dk's EU numbers, both ways |

A notice only TED holds is read from TED (`dk_ted.py`) and joins the day's targets: the same key
(`procedure-identifier`), the same gate, the same home, `source` `ted.europa.eu`. Control 2 then
names it in `only_ted` and in `read_from_ted`, and it is no longer a problem; one TED does not hand
over still is. `coverage.from_ted` counts them and `coverage.rows_held` stays udbud.dk's. A watched
tender is looked up on TED only when udbud.dk holds no notice of its procedure at all. Measured on
2026-11-23: udbud.dk 28, TED 30, both read from TED.

A window read late never puts an old notice over a newer one. For every competition past the gate
the day asks udbud.dk for the newest live notice of its procedure that may take its place (a plan
never takes a competition's); when one was published later, that
one is fetched, the gate is not asked again, and the window's own is named under `superseded`. For a
watched tender the newer notice is the one the watch lookup answers. An award never takes a competition
out of the window, and a portal that does not answer keeps the window's notice.

A platform that fails while its listing is asked leaves the tender `unknown`, is named in
`day.json` `host_failures` (`ref`, `pid`, `host`, `note`), and makes `tools/day_verdict.py` exit 1.

Rows are counted as distinct notices (`noticeId` with `noticeVersion`): between pages the portal
repeats some rows of one date and leaves others out, and the sum still equals the total. A window
over several days that holds a repeat is read again day by day; a single day short because of repeats
is asked up to four times in all, adding what each pass brings, and then raises `Truncated`. Fewer
rows than the total, with no repeat, raises at once.

Measured: 2026-09-02 42 = 42 rows, EU 40 = TED 40; 2026-11-13 39 = 39, 36 = 36; Sunday 2026-08-30
0 = 0. A national notice has no TED number; control 1 holds it.

An empty window over a weekday is a broken crawl until shown otherwise; an empty weekend is a
normal empty day. A public holiday reads as a failed discovery, which is the honest direction to be
wrong in.

## The recall gate

`policy.py` is the family's file, unchanged. It reads four texts — the Danish title, both titles
together, the description and the CPV name — folded so that a term written with spaces around it
matches only on a token boundary. So short abbreviations are written spaced (` cts `, ` bms `,
` aba `), and **no term contains a hyphen**: `el-installation` in a title folds to
`el installation`.

The real policy arrives in the `DK_POLICY` secret and is never committed. `dk_policy.example.json`
is an unrelated illustration, and the nightly workflow refuses to fall back to it.

## Running it

`dk-day.yml` is the night: one runner, no shards. `egress-map` drew eight runner addresses at once
on 2026-11-16 and every one got the workstation's numbers from udbud.dk, TED and every anonymous
document host. No schedule — the routine that reads the day starts it.

`dk-fetch.yml` reads one tender by its procedure id, past the gate. A procedure udbud.dk knows
nothing about is read from TED, as a watched one is; one udbud.dk knows and no longer lists as live
is not looked for on TED. The lookup is `dk_day.live_notice(reference)`, which answers
`(target, document)` or `(None, None)`.

Secrets: `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET`, `GRAPH_DRIVE_ID`,
`GRAPH_DEST_ROOT`, `DK_POLICY`, `COMDIA_USER`, `COMDIA_PASSWORD` (without the last two, Comdia
tenders stay `gated` with a note). Variable: `TOOLCHAIN_IMAGE`, built by `image.yml`.

## Tests

```bash
python3 -m unittest discover -s tests -t tests
```

None touch the network.
