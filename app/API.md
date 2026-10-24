# The studio's API

The interface talks to the studio through this API only. Two backends answer it with the same methods and the same
shapes, and the interface does not have to know which one runs (`STUDIO_BACKEND`):

- `studio` (default): `backend_studio.py` drives `scripts/brandkit`, `scripts/studio` and `scripts/collect`, and asks
  `claude -p` to write. A brand and a project are folders of `STUDIO_HOME`; the state lives on that disk.
- `stub`: `backend_stub.py` is a simulated studio: nothing is generated, nothing calls a model. It starts with three brands in
  three stages (Marrowbay Ferments `ready` with two projects at two steps, Atelier Ondine `to_sort` with a project that waits for it,
  Kestrel Bakehouse `to_confirm`); a site whose host contains `fail` makes the reading fail.

**The studio holds brands, a brand holds projects.** A brand is learned once (its site read, its visuals sorted, a brief of the
brand, what was deduced confirmed); its projects use it. What waits for the person, which step holds the hand, the stage of a
brand and the order of the steps are written once, in `workflow.py`, which both backends feed with plain data. Tomorrow the same routes can run on a central server, behind an authentication.

Every route answers JSON. Every route but `GET /api/health` goes through the authentication hook
(`server.py`, `authenticate`): `STUDIO_AUTH=none` (default, local) lets everything through; `STUDIO_AUTH=token`
asks for `Authorization: Bearer <STUDIO_TOKEN>`. A central server replaces that hook with its own (sessions, SSO).

## Shapes

- **brand**: `{id, name, site, description, stage, can_discover, identity, assets, projects, waiting, jobs, now}`.
  - `stage`: `new` (no site, nothing read, no brief), `discovering` (a reading job runs), `to_sort` (the site was read and the
    visuals are not sorted, or no logo is chosen), `to_brief` (the brief of the brand is not done; or it is done and there is no logo
    and nothing to find one in: a site is needed; or it has a logo and fewer than two colours), `to_confirm` (a value is deduced and not
    confirmed, or the brand comes from several projects of the old format and nobody looked at it), `ready` (a logo, **at least two
    colours, one for the background and one for the text**, nothing to confirm: a "ready" brand can always be written into a piece). The first that holds, in that order of
    the list (`workflow.brand_stage`). `can_discover`: it has a site to read.
  - `identity`: six fields, always all there, each `{value, state, source}`: `what` (what it is), `who` (for whom), `voice` (three
    words), `signature` (the exact words), `never` (the words it never says), `colours` (what the person says of them, or else the
    measured colours as hexadecimal). `value` is a string (a list is joined with commas). **One vocabulary of state, for each value**:
    `absent` (`value` and `source` empty), `deduced` (the studio found it; to confirm; `source` says where) or `confirmed`. What the
    person types is `confirmed` (source `tapé`) and wins over what was deduced. The state of `colours` is the state of the measured
    swatches: described in words, they are `confirmed` only once the swatches are.
  - `assets`: `logo` (`{id, preview, state, source}` or null), `colours` (`[{hex, role, state, source}]`), `visuals` (the kept ones,
    `[{id, note, preview}]`), `evidence` (everything the reading found, to sort: `[{id, kind, note, preview, proposed, kept}]`;
    `proposed` is what the studio would keep, `kept` the person's choice, null before it) and `logos` (the candidates,
    `[{id, note, preview}]`).
  - `projects`: `[{id, name, type, rank, step_label, done, waiting}]`: `rank` is the step in progress out of seven (the first of
    `brand, brief, mandates, diverge, image, piece, decide` that is not done), `step_label` its short name, `done` whether all seven are
    done (`rank` alone cannot tell the last step in progress from a finished project), `waiting` the number of the project's own tasks.
  - `waiting`: the brand's tasks (see **task**). `jobs`: its running reading, `[{id, kind, piece, progress, message, since}]`.
- **project**: `{id, name, type, brand, brand_name, brand_stage, brand_waiting, can_learn, steps: [step], pieces: [piece], waiting: [ask], jobs: [job], now}`.
  `brand` is the **id** of the brand (it was the brand's name before the brands existed: the name is `brand_name`), `type` is `campagne`
  (the only one for now), `brand_stage` the brand's stage and `brand_waiting` `[{kind, title}]` what the brand waits for, to say what the
  project waits for. `can_learn`: the brand has a site to read. `jobs` lists the project's running jobs (`{id, kind, piece, progress, message,
  since}`; the brand's reading is in the brand and in step 1's `job`); `now` is the server's clock (epoch seconds), to date `since` without
  trusting the browser's.
- **step**: `{key, label, status, hand, since, job}`. `key` is one of `brand`, `brief`, `mandates`, `diverge`,
  `image`, `piece`, `check`, `decide`. `status`: `todo`, `running`, `waiting` (waits for the person), `done`.
  `hand`: who holds it now, `studio` or `person`. `since`: when the hand last changed on this step (epoch seconds, or null).
  `job`: the running job's id, or null. **Step 1 (`brand`, "la marque de ce projet") has one rule**: it is `done` when the brand is
  `ready`, or once the project's brief is validated (the brand it uses is then fixed in its piece, and a brand that changes
  afterwards does not send it back); otherwise it is `waiting` on the brand's side (`running`, hand `studio`, with the brand's reading as its `job`, while the studio reads
  the site), its tasks are the brand's (sort, brief, confirm: they are in `GET /api/tasks`, not in the project's `waiting`), and step 2 (`brief`)
  is `todo`. No neutral stand-in values: nothing is produced from a brand nobody has looked at.
- **ask**: what waits for the person on a project, `{step, piece, kind, title, question}`. `kind` names the task (`brief`, `mandates`,
  `diverge-launch`, `diverge-pick`, `prompt`, `compose`, `decide`, and `job-failed`); `title` is its short name for a list.
  `job-failed` stands in for the task the failed job belonged to: `question` is the reason in one line, and running the step again (same route as
  before) makes it go away. Its `step` and `piece` say what to run again.
- **task**: an ask seen across the studio, in two scopes.
  - `scope: "project"`: `{id, scope, project, project_name, brand, brand_name, step, piece, piece_label, kind, title, question, since}`. `id` is
    `project:step:piece`: it stays the same as long as the task waits.
  - `scope: "brand"`: `{id, scope, brand, brand_name, project: null, kind, title, question, since}`. `kind` is `brand-sort` (sort the visuals and choose
    the logo), `brand-brief` (write the brief of the brand; or, once it is written, find the logo, or choose the colours), `brand-confirm` (confirm what was deduced: the question lists the values) or `job-failed`
    (the reading failed: run `discover` again). `id` is `@<brand>:<kind>`. A brand's task is listed once, whatever the number of its projects.
  - `since` is when the hand came to the person (epoch seconds). The list is the oldest first, brand and project tasks together.
- **job**: `{id, kind, status, progress, message, result}`; `kind` is `learn` (a brand's reading of its site), `mandates` (the real backend: an agent
  proposes the instructions), `diverge` or `image`; `status` is `running`, `done` or `failed`; `progress` goes from 0 to 1 (the real backend estimates
  it on an expected duration per kind and never shows more than 0.95 while the job runs). A failed job's `message` is the reason (the end of the failing
  command's output); the real backend also gives `error` and `eta`, and keeps the whole output in a log (`logs/<job>.log` of the brand or of the project).
- **piece**: `{id, variant, format, size, status, image, prompt, composed, check, decision}`.

## Routes

| Method and path | What it does |
| --- | --- |
| `GET /api/health` | `{ok, backend, auth}`, no authentication |
| `GET /api/tasks` | `{tasks, jobs, projects, brands, now}`: what waits for the person in every brand and project (the oldest first; see **task**), the running jobs of every brand and project (`{id, project, brand, kind, piece, progress, message, since, eta}`, `project` null for a brand's reading, `eta` in seconds), the projects (`{id, name, brand, brand_name, can_learn, pieces, waiting}`) and the brands (`{id, name, site, stage, projects, waiting}`) |
| `GET /api/brands` | the brands: `[{id, name, site, stage, projects: [{id, name, type, rank, step_label, done, waiting}], waiting}]` (`waiting`: the number of the brand's tasks) |
| `POST /api/brands` `{name, site?}` | a new brand (the name is required; a site is a public web address: `ftp:` and local or private addresses are refused with 400). A site starts the reading (a job, in `jobs` of the answer); no site, the brief of the brand is its first task. Answers the brand |
| `GET /api/brands/{b}` | the whole brand (identity, assets, projects, tasks, jobs) |
| `PUT /api/brands/{b}` `{name?, site?, description?}` | the metadata. A new site does not start a reading by itself. Answers the brand |
| `POST /api/brands/{b}/logo` (the file itself) | **drop a logo**: the body is the image, not JSON; its type is the request's `Content-Type` (`image/png`, `image/jpeg` or `image/svg+xml`, and the first bytes must agree; an svg with a script, an `on…=` attribute or an entity is refused) and its name an `X-Filename` header (only a note). 2 MB at most. 400 for any other type, an empty or false file, a file too big; 404 for an unknown brand. The file becomes a logo candidate (note `Logo déposé, png`), **chosen as the logo at once** and `confirmed` (the person gave it); what was sorted stays as it was, and dropping another replaces the choice (the first stays a candidate). A brand with no site, or whose site gave no logo, cannot be `ready` without it. In the real backend the file goes into the dossier of the brand (`assets/logo-<hash>.<ext>`) as a typed source (`brandkit add`), like any file added to it. Answers the brand |
| `POST /api/brands/{b}/discover` | read the site (a job), again if it was read; what the person said and the choices already made stay, and visuals that were not there before come back to be sorted. 409 without a site, or when the reading already runs |
| `POST /api/brands/{b}/keep` `{kept: [ids], logo}` | the sort of the visuals and the logo (409 before the site is read; 400 for an unknown id). A logo the person chooses is `confirmed`. Answers the brand plus `kept` and `discarded` (counts) |
| `GET /api/brands/{b}/brief` / `PUT` `{fields}` | the brief of the brand: `{fields: identity, done, stage, keys, needs, palette}`, prefilled with what the reading found. `needs` is what the brand still lacks to be ready besides the brief: `logo`, `colours` (a background and a text colour). `palette` is what the pickers start from, `{background, text, accent}`, each a `#rrggbb` or null (a colour that has one of these roles keeps it; of the others the lightest is the background and the one that reads best on it the text; an accent is never guessed). `PUT` takes strings for any of `what, who, voice, signature, never, colours` (400 for another key; `what` is required, typed or already there; `voice` and `never` are cut at commas, semicolons and line breaks). **`colours` may also be a list `[{hex, role}]`**, what the person chose with colour pickers (the interface does not ask for a typed hexadecimal): `role` is `background`, `text` or `accent`, each at most once, `background` and `text` required and different, `hex` as `#rrggbb` (400 otherwise). These become the brand's colours, `confirmed` (source `choisie par toi`), and outrank those measured or read on the site; a string stays the person's words about them. Everything given becomes `confirmed`: a value given back as it was deduced is confirmed with its own source, a different one is typed. Marks the brief done |
| `POST /api/brands/{b}/confirm` `{keys?}` | confirms the values given (any of `what, who, voice, signature, never, colours, logo`; 400 for another, or for one that is `absent`); all that are `deduced` when `keys` is missing. This is the call of the task `brand-confirm` and of the gesture on the page. Answers the brand |
| `POST /api/brands/{b}/projects` `{name, from?}` | a project of type `campagne` in the brand. `from` (a project of the same brand, 400 otherwise) copies the fields of its brief, nothing else. Answers the project |
| `GET /api/projects` | the projects: `[{id, name, brand, brand_name, waiting}]` |
| `POST /api/projects` `{name, brand?, site?, from?}` | kept for the callers that make a project in one go: `brand` is the brand's **name**, found (case apart) or made, with its site read; `from` makes a declination in the same brand (it keeps the brand and copies the brief's fields) and needs no brand |
| `GET /api/projects/{p}` | the project, its steps and what waits for the person |
| `PUT /api/projects/{p}` `{name?}` | the project's metadata (its id does not change) |
| `POST /api/projects/{p}/brand/learn` `{mode, answers?}` | **kept, the interface no longer uses it**: acts on the project's brand. `learn` (read the site, a job), `answer` (what the person says, in `answers`, required, goes to the dossier), `create` (nothing read) |
| `GET /api/projects/{p}/brand` | **kept**: the brand's evidence to keep or discard, the logo candidates, the measured colours (`{hex, status, source}`), the person's `answers` |
| `POST /api/projects/{p}/brand/keep` `{kept: [ids], logo}` | **kept**: the same as the brand's `keep`, answering `{kept, discarded, logo, colours}` |
| `GET /api/projects/{p}/brief` / `PUT` `{fields}` | the project's brief, prefilled; the person corrects it. `PUT` answers 409 while the brand is not `ready`. `GET` also gives `formats` (what the studio can make), `chosen` (the formats the brief asks for that it can make) and `left_out` (the ones it puts aside, a film for instance) |
| `GET /api/projects/{p}/mandates` / `PUT` `{mandates, common}` | the instructions the agents will get, read and corrected before any run |
| `POST /api/projects/{p}/diverge` | write the variants: a job |
| `GET /api/projects/{p}/variants` | the variants |
| `POST /api/projects/{p}/pick` `{variants: [ids]}` | the kept variants: one piece per variant and per format |
| `GET /api/projects/{p}/pieces/{i}` | a piece |
| `PUT /api/projects/{p}/pieces/{i}/prompt` `{prompt}` | the image prompt, corrected before the image |
| `POST /api/projects/{p}/pieces/{i}/image` | draw the image: a job |
| `POST /api/projects/{p}/pieces/{i}/compose` | compose the piece and check it |
| `POST /api/projects/{p}/pieces/{i}/decide` `{verdict, words}` | `keep`, or `again` with what is wrong |
| `GET /api/jobs/{j}` | a job's progress (a brand's or a project's) |
| `GET /files/{p}/piece/{path}`, `GET /files/{p}/brand/{path}` | a file of the project's `piece/` folder; a file of its brand's dossier. |
| `GET /files/_marques/{b}/brand/{path}` | a file of a brand's dossier (the pictures the brand's shapes point to: `preview`). Anything that leaves those folders answers 404 (the first segment, `..` in any spelling, a link that points outside, a folder, a null byte). Same authentication as the API: with `STUDIO_AUTH=token` a page cannot load an `<img>` this way (a picture cannot send a header), which the central server's own hook has to solve. Served with `Content-Security-Policy: sandbox`. The simulated backend has none |

Errors answer `{error}` with 400 (bad input, or the studio's own message when its tool refuses: a brief with an unknown
layout, a screenshot that cannot be taken), 401 (authentication), 404 (unknown) or 409 (not now: the step it needs
is not done, or the job is already running).

## The real backend, step by step

On the disk, in `STUDIO_HOME`: `marques/<b>/marque.json` (name, site, description, the person's choices, the brief's flag, the jobs) and
`marques/<b>/brand/` (the dossier of `scripts/brandkit`), `marques/<b>/projets/<p>/project.json` and `piece/` (the piece of `scripts/studio`).
A project id is unique in the whole studio.

Each long step is a job (a thread running sub-processes, the output kept in `logs/` of the brand or of the project); a restart marks the jobs that were
running as failed. The commands, with `<m>` the brand's folder, `<p>` the project's folder and `<piece>` its `piece/`:

| Route | Commands |
| --- | --- |
| `POST /brands` with a site, `discover` | `brandkit init <m>/brand --name <brand> --lang fr` (only if there is no dossier: an existing one is kept, with what was typed in it), `node scripts/collect/collect.mjs <site> <m>/brand/collect/web-<host>`, `brandkit infer-site <m>/brand <that folder>`, `brandkit review-html <m>/brand --no-previews` |
| `POST /brands/{b}/logo` | the file written to `<m>/brand/assets/logo-<hash>.<ext>`, then `brandkit add <m>/brand <source.json>`: a `typed` source with the file as evidence (`kind: file`, note `logo candidate, déposé`) and as the `logo` value; the evidence id found by its path in `evidence.json` becomes the brand's logo. No `keep`: the sort is not touched |
| `keep` | `brandkit keep <m>/brand <kept ids> <site page ids> [--logo <id>]` (`--none` with nothing to keep) |
| `PUT brief` (the brand's) | per field given: `brandkit answer <m>/brand <path> <value>` (`--json` with a list) when typed, `brandkit confirm <m>/brand <path>` when given back as deduced. The paths: `what` `identity.one_liner`, `who` `audience.who`, `voice` `voice.traits`, `signature` `promise.signature_line`, `never` `voice.banned_words`. `colours` as words has no field in the dossier (its colours are a list): the person's words stay in `marque.json`. `colours` as a list: the previous source labelled `colours: chosen by the person` is removed from `<m>/brand/sources/`, then a typed source with a `colours` item per colour is added (`brandkit add`); a typed colour outranks the inferred ones |
| `confirm` | `brandkit confirm <m>/brand <path>` for each value to confirm (`colours` and `logo` are the dossier's lists, confirmed whole) |
| `PUT /brands/{b}` | a new name is also given to the dossier: `brandkit answer <m>/brand identity.name <name>` |
| `PUT brief` (the project's) | `studio brand <piece> --from-dossier <m>/brand --include-unconfirmed --force`, the colours that `brand.md` lacks are completed from the measured ones and marked `(à confirmer)` (with no colour to take them from, the answer is a 400 that says so: there is no neutral stand-in), `studio brand <piece>`; then writes `<piece>/brief.md`, `studio brief <piece>` (its refusal is the 400), then starts the `mandates` job |
| `mandates` job | `claude -p <prompt> --model sonnet --no-session-persistence --restricted --tools ""`: the proposal, or a default one when the call fails |
| `diverge` | one `claude -p <prompt> --model sonnet --no-session-persistence --restricted --tools=Read,Write --permission-mode=acceptEdits --permission-prompts=none` per mandate, in parallel, each in its own folder `<piece>/work/<id>/`; then `studio diverge <piece>` |
| `pick` | `studio pick <piece> <ids>` |
| `pieces/{i}/image` | `studio image <piece>/pieces/<…> --engine auto --force` (`STUDIO_IMAGE_ENGINE` changes the engine) |
| `pieces/{i}/compose` | `studio compose <piece>/pieces/<…>`, `studio check <piece>/pieces/<…>` |
| `pieces/{i}/decide` | `studio decide <piece>/pieces/<…> keep|again "<words>"` |

**A home in the old format** (`<home>/<p>/project.json` with a `brand_name` and its own `brand/` dossier) is opened into this layout when the backend
starts, once: the brand is the one the project's `brand_name` names (projects that give the same name, by slug, go to the same brand); the dossier of
the project modified most recently (its `project.json` or `brand/brand.json`) becomes the `brand/` of the brand, the other projects keep their
`brand/` where it is, inside their folder, and nothing is deleted; the brand takes that project's choices (visuals kept, logo, the words said of the
brand) and its reading jobs; when several projects shared the name, the brand is `migrated` and is `to_confirm` until the person confirms it; each
project moves to `marques/<b>/projets/<p>/` with `brand` the brand's id and `type` `campagne`, and what the old format kept at the project's level
(`brand`, `learn`, `brand_name`, `site`) set aside under `legacy` in its `project.json`. A project called `marques` becomes `marques-projet`.

Environment: `STUDIO_BACKEND` (`studio` or `stub`), `STUDIO_HOME` (the brands and their projects, default `~/ix-studio-projets`), `STUDIO_IMAGE_ENGINE`
(`auto`, `openai`, `codex`, `none`), `STUDIO_CLAUDE_BIN` (the `claude` command), `STUDIO_CLAUDE_USE_API_KEY=1` (keep `ANTHROPIC_API_KEY` for
`claude -p`; without it the key is dropped from its environment so that the plan pays), `STUDIO_AUTH`, `STUDIO_TOKEN`, `STUDIO_PORT`.
