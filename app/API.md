# The studio's API

The interface talks to the studio through this API only. Two backends answer it with the same methods and the same
shapes, and the interface does not have to know which one runs (`STUDIO_BACKEND`):

- `studio` (default): `backend_studio.py` drives `scripts/brandkit`, `scripts/studio` and `scripts/collect`, and asks
  `claude -p` to write. A brand and a project are folders of `STUDIO_HOME`; the state lives on that disk.
- `stub`: `backend_stub.py` is a simulated studio: nothing is generated, nothing calls a model. It starts with three brands in
  three stages (Marrowbay Ferments `ready` with two projects at two steps, Atelier Ondine `to_sort` with a project that waits for it,
  Kestrel Bakehouse `to_confirm`); a site whose host contains `fail` makes the reading fail. Its judge gives one plausible, fixed verdict; a
  piece dropped to be judged whose name contains `fail` makes the judge fail. Its readers give one fixed reading; a persona whose text contains `fail`
  makes its reader fail; its personas agent gives three plausible, fixed personas; its names agent five plausible, fixed names;
  its competitors agent gives four plausible, fixed, fictional competitors; its texts agent gives four plausible, fixed texts; its storyboard agent gives one
  fixed storyboard of six shots, its film is one small fixed mp4, its research agent gives five fictional results, and its interview agent gives one fixed brief (an answer that contains `fail` makes it fail).

**The studio holds brands, a brand holds projects.** A brand is learned once (its site read, its visuals sorted, a brief of the
brand, what was deduced confirmed); its projects use it. What waits for the person, which step holds the hand, the stage of a
brand and the order of the steps are written once, in `workflow.py`, which both backends feed with plain data. Tomorrow the same routes can run on a central server, behind an authentication.

Every route answers JSON, except the five downloads (a png, two zips, the page of a judgement, the Markdown of a brief). Every route but `GET /api/health` goes through the authentication hook
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
  `diverge-launch`, `diverge-pick`, `prompt`, `compose`, `decide`, and `job-failed`); `title` is its short name for a list. **A `prompt` is
  one task per variant, not per piece**: its formats share the prompt of the image. It also carries `variant` (the variant's id) and `pieces`
  (the ids of the variant's pieces that still wait for their image); `piece` is the first of them (the task's id stays the same as long as it waits).
  `job-failed` stands in for the task the failed job belonged to: `question` is the reason in one line, and running the step again (same route as
  before) makes it go away. Its `step` and `piece` say what to run again (`step: "check"` is the judge of the piece: `POST pieces/{i}/judge`).
- **task**: an ask seen across the studio, in two scopes.
  - `scope: "project"`: `{id, scope, project, project_name, brand, brand_name, step, piece, piece_label, kind, title, question, since}` (a `prompt` task adds `variant` and `pieces`, and its `piece_label` is the variant's id). `id` is
    `project:step:piece`: it stays the same as long as the task waits.
  - `scope: "brand"`: `{id, scope, brand, brand_name, project: null, kind, title, question, since}`. `kind` is `brand-sort` (sort the visuals and choose
    the logo), `brand-brief` (write the brief of the brand; or, once it is written, find the logo, or choose the colours), `brand-confirm` (confirm what was deduced: the question lists the values) or `job-failed`
    (the reading failed: run `discover` again). `id` is `@<brand>:<kind>`. A brand's task is listed once, whatever the number of its projects.
  - `since` is when the hand came to the person (epoch seconds). The list is the oldest first, brand and project tasks together.
- **job**: `{id, kind, status, progress, message, result}`; `kind` is `learn` (a brand's reading of its site), `personas` (an agent proposes a brand's personas), `names` (an agent proposes names for a brand), `competitors` (an agent proposes a brand's competitors), `research` (an agent searches the web for what is said of a brand), `interview` (an agent writes the brief of a project from the person's answers), `logos` (an agent draws a brand's logo tracks), `texts` (an agent proposes the hooks and posts of a project), `storyboard` (an agent writes a project's film script and shots), `film` (the film is rendered by code), `mandates` (the real backend: an agent
  proposes the instructions), `diverge`, `image`, `judge` (the judge reads a piece: one of a project, or one dropped on its own) or `reader` (a persona reads it); `status` is `running`, `done` or `failed`; `progress` goes from 0 to 1 (the real backend estimates
  it on an expected duration per kind and never shows more than 0.95 while the job runs). A failed job's `message` is the reason (the end of the failing
  command's output); the real backend also gives `error` and `eta`, and keeps the whole output in a log (`logs/<job>.log` of the brand or of the project).
- **piece**: `{id, label, variant, format, size, status, image, prompt, headline, subline, composed, check, decision, judge, readers, bans}`. `headline` and `subline` are the words in effect: those of the variant, or the ones the person corrected (`PUT /variants/{v}/text`).
  `judge` is null until the piece is composed (and again once its image is redone or it is sent back), then `{status, verdict, error}`: `status` is
  `running` (the judge reads it), `done` (`verdict`, see **verdict**) or `failed` (`error`, the reason; the project then has a `job-failed` ask of
  step `check` for the piece, beside its decision). `check.notes` keeps the mechanical checks; the judge's notes are in `judge`, not twice.
  `readers` is `[]` until the piece is composed, or when the brief has no persona; then one **reader** per persona of the project's brief.
- **verdict**: what the judge says of a piece, **in words and without a score**: `{target, works, snags, unsourced, brand, missing}`.
  `target` is `{reached, why}`, `reached` being `yes`, `partly`, `no` (the person aimed at is reached, partly, not, from their point of view) or
  `unjudgeable` (the brief does not say who it is for: `why` is then "non jugeable sur la cible : il manque la cible"). `works` (what works),
  `snags` (what catches: a double meaning, a hierarchy that does not read, a cliché, an image that does not answer the headline), `unsourced` (a fact
  one could check, a figure, a label, a guarantee, a dated promise, a ranking, that is in none of the entries: not said false, only nothing was given
  to believe it; the price, the product's name, the town are not aimed at) and `brand` (the voice and the tone; **null when no brand is given**) are
  lists of `{where, say}`, at most eight each: `where` names what it aims at **in words** ("le titre en haut", "le bandeau du bas"), never a drawn
  zone. `missing` is what the brief lacks, in words (any of "l'objectif", "la cible", "le message", "l'appel à l'action"): the rest is judged all
  the same, no question is asked. The judge reads the brief (objective, target, message, call to action, and, optional, what does not move: respect
  the assets or not), the piece (its image and its words) and the brand if there is one (its voice, its tone; colours, type, contrast, banned words,
  hierarchy and signature stay with the mechanical checks). It blocks nothing, nothing starts after it, it does not judge the morals of the brand or
  of its product. Both backends check what their judge writes the same way (`scripts/agents/answers.py`).
- **judgement**: a piece judged on its own, `{id, name, brand, brand_name, brief, image, at, status, verdict, error, missing, job, readers}`. `brief` is
  `{objective, audience, message, cta, fixed, personas}`, `readers` one **reader** per persona (`[]` without), `brand` the id of a brand or null, `image` the address of the piece, `status` `running`, `done`
  or `failed` (with `error`), `job` the running job's id or null.
- **personas**: the people a brand's pieces will meet, `{personas, proposed, can_propose, job, error}`. `personas` are the texts the person kept
  (only these are the brand's), `proposed` the texts the last `personas` job proposed and that the person has not settled yet (`PUT` settles
  them), `can_propose` whether the brief of the brand is done (the agent works from it), `job` the running job or null, `error` the reason of
  the last job when it failed. A proposed text is short, in French, to the second person: its first line is `Hypothèses à corriger, pas des
  faits.`, its second `Besoin principal : …` (each persona its own need), then one line each, prefixed `(dossier)` or `(supposé)`: who it is,
  where and how it meets an ad of the brand, what it already thinks of the brand and of the subject, its own words. At most four
  (`workflow.parse_personas`, the same for both backends). What the person keeps is free text.
- **names**: names for a brand that has only a provisional one, `{name, names, proposed, can_propose, job, error}`. `name` is the brand's
  name today, `names` the names the person kept or wrote, `proposed` what the last `names` job proposed and the person has not settled yet
  (`PUT` settles them), `can_propose`, `job` and `error` as for the personas. Each name is `{name, why}`: `why` is one line, why this name and what it
  evokes (empty for a name written by hand). Eight at most, no name twice (case apart) (`workflow.parse_names`, the same for both backends).
  Nobody checks that a name is free to use.
- **competitors**: the competitors of a brand, `{competitors, proposed, can_propose, job, error}`, the same as **personas**: `competitors` the
  texts the person kept (only these are the brand's), `proposed` those of the last `competitors` job not settled yet. A proposed text is short,
  in French: its first line is `Hypothèse à vérifier, pas un fait.`, then `Nom : … (dossier)` or `Nom : … (supposé)` (named in what the studio
  knows of the brand, or supposed), `Vend : …` (what it sells and to whom, one line), `Se distingue : …` (its angle, its tone, against the
  brand, one line). No figure (share, turnover, ranking). At most six, each its own name (`workflow.parse_competitors`, the same for both
  backends). What the person keeps is free text.
- **research**: what the web says of a brand, `{research, proposed, job, error}`: `research` the results the person kept (only these are the
  brand's), `proposed` those of the last `research` job not settled yet, `job` and `error` as for the personas (there is no `can_propose`: a name is
  enough). A result is `{url, brings, belonging}`: its address (`http` or `https`, no result without one), one sentence on what it brings (colours,
  tone, campaign, logo), and its `belonging`: `officielle` (the domain of the brand), `officielle relayée` (an article that names the brand and its
  agency), `probable`, `incertaine`. Ten at most, no address twice (`workflow.parse_research`, the same for both backends). Nothing found is
  downloaded: the brand keeps the address.
- **texts**: the hooks and posts of a project, `{texts, proposed, can_propose, job, error}`: `texts` those the person kept (only these are the
  project's), `proposed` those of the last `texts` job not settled yet, `can_propose` true once the project's brief is confirmed, `job` and
  `error` as for the personas. A text is free text: a hook is one line (120 signs at most), a post a few lines (700 at most). Six at most, none
  twice, no em dash, and no figure that is not in the brief or in the brand (`answers.parse_texts`, the same for both backends).

- **logos**: the logo tracks of a brand, `{tracks, proposed, can_propose, job, error}`: `tracks` the ones the person kept, `proposed` those of the last
  `logos` job not settled yet, `can_propose` always true (a brand always has a name), `job` and `error` as for the names. A track is
  `{id, idea, svg}`: `idea` one sentence in French, `svg` a drawing made by the agent (no image engine), its root `svg` in the SVG namespace (`xmlns`), on a `viewBox`, with the name of the brand
  in its colours and fonts; its `id` comes from the drawing. Four at most. The drawing is checked before it is shown (`answers.parse_logos`, the
  same for both backends): well formed, no script, no style, no image, no link, nothing external; anything else is a failed job. The front shows
  it as a picture. Nobody checks that a logo is free to use.
- **storyboard**: the script and the shots of a project's film, `{script, shots, saved, can_propose, job, error, film, film_job, film_error}`.
  `shots` are five to eight `{seconds, visual, text, colour, read}`: `seconds` from 1 to 8 (the film makes 15 to 30), `visual` `texte` (the `text`
  is on the screen) or `logo` (the brand's logo alone, `text` empty), `colour` one of the brand's colours (`#rrggbb`), `read` the line one reads over
  the shot. Nothing invented: no figure or promise that is in neither the brief nor the brand. `saved` is false while the person has not read and
  saved what the agent proposed (`PUT` saves, with the same checks, `workflow.parse_storyboard`: a 400 says what does not hold): **the film is not
  rendered before** (409), and saving again drops the film made from the older storyboard. `can_propose` is true once the project's brief is
  confirmed. `film` is `{url, seconds}` once rendered, `film_job` the running render, `error` and `film_error` why the last proposal or render
  failed. One format: 9:16 vertical, 1080 x 1920, no sound.
- **rounds**: the same piece judged three times by the same judge (same command, same model), each round alone. `synthesis` is `{holds, ambiguous, once}`, each a
  list of `{heading, where, say, rounds}` (`heading` one of `works, snags, unsourced, brand`, `rounds` the numbers, from 1, of the rounds that said it):
  `holds` came out in all three rounds, `once` in one only, `ambiguous` in two (the rounds disagree). An agent of `scripts/agents rounds` puts the
  remarks of the rounds side by side (the same idea in different words is one remark); the shelf is decided by the numbers it gives, not by it
  (`workflow.parse_rounds`). The judge blocks nothing: the synthesis is shown beside the piece, the person decides. A round that fails fails the whole
  job (`failed`, its reason), which is run again whole. The simulated backend gives one fixed synthesis (a piece whose name contains `fail` fails).
- **reader**: a persona of the brief reading the piece, `{n, persona, status, reading, error, job}`. **A brief may name one to four personas**
  (`personas`, a list of free texts written by the person: "tu as 55 ans, artisan, …"; empty texts are left out, more than four is a 400). Each
  persona is a reader, **in a call of its own**: it sees the piece (its image and, in a project, its words) and its own persona, not the brief,
  not the brand, not the other readers. The judge does not read the personas: it stays as it is beside them, and without persona nothing changes.
  `n` is its rank in `personas` (from 0), `status` `running`, `done` (`reading`), `failed` (`error`) or `todo` (never read, or its persona changed
  since: run it again), `job` the running job's id or null. `reading` is `{aimed, why, understand, retain, bother, unread, lacks}`, in "I":
  `aimed` is `yes`, `partly` or `no` (does the piece aim at me), `why` why, then what I understand, keep, what bothers me, what I do not read,
  what I miss (`""` when nothing). **It never says whether it would buy**: the studio checks that the piece holds with its brief, it does not
  predict its effect. The readings are shown side by side, without a synthesis. Both backends check what a reader writes the same way
  (`workflow.parse_reading`). A reader blocks nothing and has no task: one that fails is run again alone (`…/readers/{n}/run`).

## Routes

| Method and path | What it does |
| --- | --- |
| `GET /api/health` | `{ok, backend, auth}`, no authentication |
| `GET /api/machine` | what the machine lacks to run the studio for real: `{ok, missing: [{key, label, say}]}`, `key` being `chrome` (reads a site, composes a piece), `claude` (Claude Code, writes the instructions and the variants) or `image` (an image engine: Codex, or `OPENAI_API_KEY` / `OPENROUTER_API_KEY`); `say` is what to install, in one sentence. The tools are looked for (as `studio compose` and `studio image` look for them), never run. The simulated backend lacks nothing, unless `STUDIO_STUB_MISSING=chrome,claude,image` says so |
| `GET /api/engines` | the engines (**engines**): `{image_engine, image_engines, text_engine, text_engines, openrouter_model, key_saved}`. `key_saved` says whether an OpenRouter key is saved: the key itself is never given back, by any route, and never written in a project or in the repository (it lives in `engines.json` of the person's configuration folder, `~/.config/ix-studio`, or `$STUDIO_CONFIG_DIR`, readable by the person alone) |
| `PUT /api/engines/image` | `{engine}`, one of `image_engines` (those of `STUDIO_IMAGE_ENGINE`); answers as `GET /api/engines`. 400 on an engine that does not exist |
| `PUT /api/engines/text` | `{engine, key?, model?}`, `engine` one of `text_engines` (`claude`, or `openrouter`, which uses its key and its model through its API compatible with OpenAI's); a `key` sent is saved, an empty one forgets the saved key, no `key` leaves it; answers as `GET /api/engines`. The agents that only answer (personas, names, competitors, texts, mandates) use the engine; those that read an image or write a file stay on `claude` |
| `GET /api/tasks` | `{tasks, jobs, projects, brands, now}`: what waits for the person in every brand and project (the oldest first; see **task**), the running jobs of every brand and project and of every judgement (`{id, project, brand, kind, piece, progress, message, since, eta, judgement}`, `project` null for a brand's reading, `project` and `brand` null and `judgement` its id for the judge of a piece judged on its own, `eta` in seconds), the projects (`{id, name, brand, brand_name, can_learn, pieces, waiting}`) and the brands (`{id, name, site, stage, projects, waiting}`) |
| `GET /api/brands` | the brands: `[{id, name, site, stage, projects: [{id, name, type, rank, step_label, done, waiting}], waiting}]` (`waiting`: the number of the brand's tasks) |
| `POST /api/brands` `{name, site?}` | a new brand (the name is required; a site is a public web address: `ftp:` and local or private addresses are refused with 400). A site starts the reading (a job, in `jobs` of the answer); no site, the brief of the brand is its first task. Answers the brand |
| `GET /api/brands/{b}` | the whole brand (identity, assets, projects, tasks, jobs) |
| `PUT /api/brands/{b}` `{name?, site?, description?}` | the metadata. A new site does not start a reading by itself. Answers the brand |
| `POST /api/brands/{b}/logo` (the file itself) | **drop a logo**: the body is the image, not JSON; its type is the request's `Content-Type` (`image/png`, `image/jpeg` or `image/svg+xml`, and the first bytes must agree; an svg with a script, an `on…=` attribute or an entity is refused) and its name an `X-Filename` header (only a note). 2 MB at most. 400 for any other type, an empty or false file, a file too big; 404 for an unknown brand. The file becomes a logo candidate (note `Logo déposé, png`), **chosen as the logo at once** and `confirmed` (the person gave it); what was sorted stays as it was, and dropping another replaces the choice (the first stays a candidate). A brand with no site, or whose site gave no logo, cannot be `ready` without it. In the real backend the file goes into the dossier of the brand (`assets/logo-<hash>.<ext>`) as a typed source (`brandkit add`), like any file added to it. Answers the brand |
| `POST /api/brands/{b}/discover` | read the site (a job), again if it was read; what the person said and the choices already made stay, and visuals that were not there before come back to be sorted. 409 without a site, or when the reading already runs |
| `POST /api/brands/{b}/keep` `{kept: [ids], logo}` | the sort of the visuals and the logo (409 before the site is read; 400 for an unknown id). A logo the person chooses is `confirmed`. Answers the brand plus `kept` and `discarded` (counts) |
| `GET /api/brands/{b}/brief` / `PUT` `{fields}` | the brief of the brand: `{fields: identity, done, stage, keys, needs, palette}`, prefilled with what the reading found. `needs` is what the brand still lacks to be ready besides the brief: `logo`, `colours` (a background and a text colour). `palette` is what the pickers start from, `{background, text, accent}`, each a `#rrggbb` or null (a colour that has one of these roles keeps it; of the others the lightest is the background and the one that reads best on it the text; an accent is never guessed). `PUT` takes strings for any of `what, who, voice, signature, never, colours` (400 for another key; `what` is required, typed or already there; `voice` and `never` are cut at commas, semicolons and line breaks). **`colours` may also be a list `[{hex, role}]`**, what the person chose with colour pickers (the interface does not ask for a typed hexadecimal): `role` is `background`, `text` or `accent`, each at most once, `background` and `text` required and different, `hex` as `#rrggbb` (400 otherwise). These become the brand's colours, `confirmed` (source `choisie par toi`), and outrank those measured or read on the site; a string stays the person's words about them. Everything given becomes `confirmed`: a value given back as it was deduced is confirmed with its own source, a different one is typed. Marks the brief done |
| `POST /api/brands/{b}/confirm` `{keys?}` | confirms the values given (any of `what, who, voice, signature, never, colours, logo`; 400 for another, or for one that is `absent`); all that are `deduced` when `keys` is missing. This is the call of the task `brand-confirm` and of the gesture on the page. Answers the brand |
| `GET /api/brands/{b}/personas` | the brand's **personas** (see the shape) |
| `POST /api/brands/{b}/personas/propose` | an agent proposes up to four personas from what the studio knows of the brand (its dossier, its brief): a job of `kind` `personas`, no search on the web. When it ends, they are in `proposed`, never in `personas` by themselves. 409 while the brief of the brand is not done, or while the job runs |
| `PUT /api/brands/{b}/personas` `{personas: [text]}` | the personas the person keeps, corrected or written by hand (the empty ones dropped; 400 for more than four, or for anything but a list of texts). They replace the brand's, and `proposed` is emptied. The person may write them all without the job. Answers the personas |
| `GET /api/brands/{b}/names` | the brand's **names** (see the shape) |
| `POST /api/brands/{b}/names/propose` | an agent proposes up to eight names from the brief of the brand (what it is, for whom, its voice): a job of `kind` `names`, no search on the web. When it ends, they are in `proposed`, never in `names` by themselves. 409 while the brief of the brand is not done, or while the job runs |
| `PUT /api/brands/{b}/names` `{names: [{name, why}], chosen?}` | the names the person keeps, or writes (the empty names and the repeated ones dropped; 400 for more than eight, or for anything but a list of objects). They replace the brand's, and `proposed` is emptied. `chosen`, one of these names (400 otherwise), **becomes the brand's name** (as `PUT /api/brands/{b}` `{name}`: its id does not change). Answers the names |
| `GET /api/brands/{b}/research` | the brand's **research** (see the shape) |
| `POST /api/brands/{b}/research/propose` | an agent searches the web (the search tool of `claude -p`) for the brand's site, its campaigns and what the press says of it: a job of `kind` `research`. When it ends, up to ten results are in `proposed`, never in `research` by themselves. 409 while the job runs |
| `PUT /api/brands/{b}/research` `{research: [result]}` | the results the person keeps (400 for more than ten, a result without an address, a belonging out of the four, or anything but a list; an empty list keeps none). They replace the brand's, and `proposed` is emptied. Answers the research |
| `GET /api/brands/{b}/logo/tracks` | the brand's **logos** (see the shape) |
| `POST /api/brands/{b}/logo/propose` | an agent draws up to four logo tracks in SVG from the name, the colours, the fonts and the brief of the brand: a job of `kind` `logos`. When it ends, they are in `proposed`, never in `tracks` by themselves. 409 while the job runs |
| `PUT /api/brands/{b}/logo/tracks` `{keep: [id]}` | the tracks the person keeps, ids among `tracks` and `proposed` (400 for an unknown id or more than four); the others are dropped and `proposed` is emptied. Answers the logos |
| `POST /api/brands/{b}/logo/choose` `{id}` | a kept track becomes the brand's logo, as a logo dropped by the person (400 when `id` is not a kept track). Answers the logos |
| `GET /api/brands/{b}/competitors` | the brand's **competitors** (see the shape) |
| `POST /api/brands/{b}/competitors/propose` | an agent proposes up to six competitors from what the studio knows of the brand (its dossier, its brief) and what it knows of the market: a job of `kind` `competitors`, no search on the web. When it ends, they are in `proposed`, never in `competitors` by themselves. 409 while the brief of the brand is not done, or while the job runs |
| `POST /api/competitors` `{market}` | **landscape**: the competitive landscape of a market, without a brand. `market` is one or two sentences (400 without). The competitors agent answers at once (not a job): `{competitors: [text]}`, the same texts as a brand's (up to six, `Hypothèse à vérifier, pas un fait.`, `Nom : … (dossier|supposé)`, `Vend : …`, `Se distingue : …` read here as its position in the market); `(dossier)` is a player named in the person's description, any other is `(supposé)`. Nothing is kept: the person keeps or drops each, and attaches the kept ones to a brand with `PUT /api/brands/{b}/competitors`. The simulated backend answers four fixed, fictional players; a failed agent is a 409 that says why |
| `PUT /api/brands/{b}/competitors` `{competitors: [text]}` | the competitors the person keeps, corrected or written by hand (the empty ones dropped; 400 for more than six, or for anything but a list of texts). They replace the brand's, and `proposed` is emptied. The person may write them all without the job. Answers the competitors |
| `GET /api/brands/{b}/export` | **a file, not JSON** (export): the **brand folder**, a zip named `<b>-dossier-de-marque.zip` with `brand.md`, `MOTION.md` (if the dossier has one), the logo (`logo.<ext>`, if it has one) and `brand.json`: `{name, values: [{path, value, status, source}], missing: [paths], logo}`, where `status` is `confirmed`, `to_confirm` or `ask`; what is missing is `ask` with no value, never filled in. 409 while the brand has no dossier. The simulated backend gives one fixed zip |
| `GET /api/projects/{p}/texts` | the project's **texts** (see the shape) |
| `POST /api/projects/{p}/texts/propose` | an agent proposes up to six hooks and posts from the brief of the project and the voice of its brand: a job of `kind` `texts`, no search on the web. When it ends, they are in `proposed`, never in `texts` by themselves. 409 while the brief is not confirmed, or while the job runs |
| `PUT /api/projects/{p}/texts` `{texts: [text]}` | the texts the person keeps, corrected or written by hand (the empty ones dropped; 400 for more than six, or for anything but a list of texts). They replace the project's, and `proposed` is emptied. The person may write them all without the job. Answers the texts |
| `POST /api/brands/{b}/projects` `{name, from?}` | a project of type `campagne` in the brand. `from` (a project of the same brand, 400 otherwise) copies the fields of its brief, nothing else. Answers the project |
| `GET /api/projects` | the projects: `[{id, name, brand, brand_name, waiting}]` |
| `POST /api/projects` `{name, brand?, site?, from?}` | kept for the callers that make a project in one go: `brand` is the brand's **name**, found (case apart) or made, with its site read; `from` makes a declination in the same brand (it keeps the brand and copies the brief's fields) and needs no brand |
| `GET /api/projects/{p}` | the project, its steps and what waits for the person |
| `PUT /api/projects/{p}` `{name?}` | the project's metadata (its id does not change) |
| `POST /api/projects/{p}/brand/learn` `{mode, answers?}` | **kept, the interface no longer uses it**: acts on the project's brand. `learn` (read the site, a job), `answer` (what the person says, in `answers`, required, goes to the dossier), `create` (nothing read) |
| `GET /api/projects/{p}/brand` | **kept**: the brand's evidence to keep or discard, the logo candidates, the measured colours (`{hex, status, source}`), the person's `answers` |
| `POST /api/projects/{p}/brand/keep` `{kept: [ids], logo}` | **kept**: the same as the brand's `keep`, answering `{kept, discarded, logo, colours}` |
| `GET /api/projects/{p}/brief` / `PUT` `{fields}` | the project's brief, prefilled; the person corrects it. `fields.personas` is the list of personas (see **reader**), the other fields are strings. `PUT` answers 409 while the brand is not `ready`. `GET` also gives `formats` (what the studio can make), `chosen` (the formats the brief asks for that it can make) and `left_out` (the ones it puts aside, a film for instance) |
| `GET /api/projects/{p}/interview` | the **interview** of the project: `{questions, proposed, job, error}`. `questions` are the five the person is asked (the same for every project). `proposed` is `null`, or `{fields, missing}` once the last `interview` job ended: `fields` are `objective`, `audience`, `message`, `cta`, `fixed` (texts, empty when the person did not answer the question), `missing` those of `objective` (the goal: awareness, sale, promotion...) and `audience` (the target: a segment or a persona of the brand) that nobody gave. They stay empty and are flagged, never guessed. A proposal is never the brief: the interface opens it in the brief's form, the person corrects it and validates it with `PUT brief` as usual |
| `POST /api/projects/{p}/interview` `{answers}` | the agent writes the brief from the answers (a job of `kind` `interview`, no search on the web): `answers` is a list of texts, one per question, five at most, at least one said (400 otherwise); 409 while an interview runs. The previous proposal is emptied when it starts |
| `GET /api/projects/{p}/mandates` / `PUT` `{mandates, common}` | the instructions the agents will get, read and corrected before any run |
| `GET /api/projects/{p}/storyboard` | the project's **storyboard** (see the shape) |
| `POST /api/projects/{p}/storyboard/propose` | an agent writes the script and the shots from the confirmed brief and the brand: a job of `kind` `storyboard`; 409 while the brief is not confirmed or while it runs |
| `PUT /api/projects/{p}/storyboard` `{script, shots}` | the storyboard the person corrected and saves (`saved` becomes true); 400 when it does not hold |
| `POST /api/projects/{p}/storyboard/render` | render the film of the saved storyboard: a job of `kind` `film`; 409 while it is not saved or while it runs |
| `GET /api/projects/{p}/storyboard/film` | the film, an mp4 as an attachment (409 until it is made) |
| `POST /api/projects/{p}/diverge` | write the variants: a job |
| `GET /api/projects/{p}/variants` | the variants |
| `POST /api/projects/{p}/pick` `{variants: [ids]}` | the kept variants: one piece per variant and per format |
| `PUT /api/projects/{p}/variants/{v}/prompt` `{prompt}` | **the prompt of a variant, shared by its formats**: written in each of its pieces that still waits for its image (those with an image keep theirs, and the one that is being drawn too). Answers those pieces. 400 for an empty prompt, 404 for a variant that is not in the series, 409 when every piece of the variant has its image (redo one of them to change its prompt) |
| `PUT /api/projects/{p}/variants/{v}/text` `{headline, subline?}` | **the words of a variant corrected, before the piece is composed** (what is generated is shown and can be corrected): the headline (required, one line) and the subline (`""` takes it off, left out leaves it as it is), written in each piece of the variant that is not composed yet. Answers those pieces (their `headline` and `subline` are the corrected ones). 400 for an empty headline, 404 for a variant that is not in the series, 409 when every piece of the variant is composed (send one back to change its words) |
| `POST /api/projects/{p}/images` `{variant?}` | **draw every image that is missing**, or those of one `variant`: one job per piece (`{jobs: [job]}`), as many as run together as the studio allows. 400 for a variant that is not in the series, 409 when every piece has its image or is being drawn |
| `POST /api/projects/{p}/compose` | **compose and check every piece that has its image and is not composed**, one after the other: `{composed: [ids], failed: [{piece, error}]}` (a piece that fails does not stop the others; when none can, the reason of the first is the 400). 409 when none waits to be composed |
| `GET /api/projects/{p}/pieces/{i}` | a piece |
| `PUT /api/projects/{p}/pieces/{i}/prompt` `{prompt}` | the image prompt, corrected before the image |
| `POST /api/projects/{p}/pieces/{i}/image` | draw the image: a job |
| `POST /api/projects/{p}/pieces/{i}/compose` | compose the piece and check it; then **the judge reads it** (a `judge` job of the piece: its `judge` is `running`). The answer does not wait for it, and the decision does not either |
| `POST /api/projects/{p}/pieces/{i}/judge` | run the judge of a composed piece again (a job; the call of a `job-failed` ask of step `check`). 409 while the piece is not composed, or while its judge reads it |
| `POST /api/projects/{p}/pieces/{i}/readers/{n}/run` | run reader `n` of a composed piece again, alone (a `reader` job). 404 for a reader that is not there, 409 while the piece is not composed or while that reader reads |
| `POST /api/projects/{p}/pieces/{i}/decide` `{verdict, words}` | `keep`, or `again` with what is wrong |
| `GET /api/projects/{p}/pieces/{i}/download` | **a file, not JSON**: the composed piece as a png at the size of its format (the file `studio compose` made), sent as an attachment (`Content-Disposition`, name `<project>-<piece>.png`). 409 while the piece is not composed. The simulated backend has one picture for all of them |
| `GET /api/projects/{p}/download` | **a file, not JSON**: a zip of every piece **kept** (`<project>-<piece>.png` each, written with the standard library), name `<project>.zip`. 409 while no piece is kept |
| `GET /api/briefs/{r}/export` | **a file, not JSON** (brief_export): the brief of a project, confirmed or not, in Markdown (`text/markdown`, `brief-<name>.md`): objective, target, message, format, what is fixed, call to action, the personas if any, and **what is missing, written as missing**. `{r}` is the project's id (the brief has no id of its own: it is read and written at `projects/{p}/brief`). It exports the brief as saved, not what is being typed. 404 for an unknown project. The real backend runs `scripts/agents export-brief` (no call to claude); the simulated one gives one fixed brief |
| `GET /api/judgements` | the pieces judged on their own, the newest first: `[{id, name, brand, brand_name, status, at}]` |
| `POST /api/judgements` (the file itself) | **judge a piece on its own**: the body is the image, not JSON (`Content-Type` `image/png` or `image/jpeg`, the first bytes must agree; 10 MB at most), its name an `X-Filename` header, and what comes with it an `X-Judge` header, JSON, URL-encoded: `{name?, brand?, brief}` (`brief`: any of `objective, audience, message, cta, fixed`, the same sentence as a project's brief, and `personas`; `brand` the id of a brand, optional). 400 for another type, an empty, false or too big file, an unknown brand, an `X-Judge` that is not JSON. The judge starts at once (a job), and one reader per persona beside it. Answers the judgement. `name` defaults to the file's name |
| `GET /api/judgements/{j}` | a judgement, its verdict once it is `done` |
| `POST /api/judgements/{j}/run` | run its judge again (after a failure, or to read it once more): a job. 409 while it runs |
| `POST /api/judgements/{j}/readers/{n}/run` | run reader `n` of a judgement again, alone (a `reader` job). 404 for a reader that is not there, 409 while it reads |
| `GET /api/judgements/{j}/rounds` | the **rounds** of a judgement (see **rounds**): `{status, synthesis, error, job}`; `status` is `none` (never launched), `running`, `done` or `failed`. 404 for a judgement that is not there |
| `POST /api/judgements/{j}/rounds` | judge the piece **three times**, each round alone, then put the remarks side by side: a `rounds` job (again, once done; the judgement's own verdict is not touched). 409 while it runs |
| `GET /api/judgements/{j}/page` | **a file, not JSON**: the flat page of the verdict (the piece at the top, the list under it; the piece inside the page, so that it stands on its own), `text/html`, name `<j>.html`. 409 before the verdict |
| `GET /api/jobs/{j}` | a job's progress (a brand's, a project's or a judgement's) |
| `GET /files/{p}/piece/{path}`, `GET /files/{p}/brand/{path}` | a file of the project's `piece/` folder; a file of its brand's dossier. |
| `GET /files/_jugements/{j}/piece.png` (or `.jpg`, or `page.html`) | the piece of a judgement, or its page; nothing else of its folder. The simulated backend gives its pieces as `data:` addresses |
| `GET /files/_marques/{b}/brand/{path}` | a file of a brand's dossier (the pictures the brand's shapes point to: `preview`). Anything that leaves those folders answers 404 (the first segment, `..` in any spelling, a link that points outside, a folder, a null byte). Same authentication as the API: with `STUDIO_AUTH=token` a page cannot load an `<img>` this way (a picture cannot send a header), which the central server's own hook has to solve. Served with `Content-Security-Policy: sandbox`. The simulated backend has none |

Errors answer `{error}` with 400 (bad input, or the studio's own message when its tool refuses: a brief with an unknown
layout, a screenshot that cannot be taken), 401 (authentication), 404 (unknown) or 409 (not now: the step it needs
is not done, or the job is already running).

## The real backend, step by step

On the disk, in `STUDIO_HOME`: `marques/<b>/marque.json` (name, site, description, the person's choices, the brief's flag, the personas, the names, the competitors, the jobs) and
`marques/<b>/brand/` (the dossier of `scripts/brandkit`), `marques/<b>/projets/<p>/project.json` and `piece/` (the piece of `scripts/studio`);
`jugements/<j>/` a piece judged on its own (`jugement.json`: its name, brand, brief, verdict and jobs; `piece.png` or `piece.jpg`; once judged,
`judge.md` and `page.html`).
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
| `personas/propose` (the `personas` job) | `scripts/agents personas <inputs.json>` (the brand's name, site, description, the fields of its brief with their state, the person's words, the path of `<m>/brand/brand.json`; written in `<m>/work/personas/`); the command holds the prompt (`claude -p`, model `sonnet`, no tool) and checks the answer (`answers.parse_personas`: anything else is a failed job, with the command's reason); the personas go to `personas_proposed` of `marque.json`. `PUT personas` writes `personas` there |
| `names/propose` (the `names` job) | `scripts/agents names <inputs.json>`, the brand's provisional name, its description, its brief and the person's words; checked by `answers.parse_names` (anything else is a failed job); the names go to `names_proposed` of `marque.json`. `PUT names` writes `names` there; a `chosen` name is then given as `PUT /brands/{b}` gives one |
| `competitors/propose` (the `competitors` job) | `scripts/agents competitors <inputs.json>`, the same inputs as the personas; checked by `answers.parse_competitors` (anything else is a failed job); the competitors go to `competitors_proposed` of `marque.json`. `PUT competitors` writes `competitors` there |
| `POST /api/competitors` (landscape) | `scripts/agents competitors <inputs.json>` with `{market}` in place of a brand (written in a folder of its own under `<home>/paysages/`, removed when the call ends, its log in `<home>/paysages/landscape.log`); checked by `answers.parse_competitors`; the texts are given back, nothing is written |
| `export` | `brandkit pack <m>/brand --out <m>/dossier-de-marque.zip`, no agent: the zip is read back and sent |
| `interview` (the `interview` job) | `scripts/agents interview <inputs.json>`: the answers, the project's language, the brand's name, what it says of whom it is for and its kept personas; it answers `{fields, missing}` (checked by `answers.parse_interview`: a field whose question got no answer is emptied whatever the agent wrote; anything unreadable is a failed job); no inputs but `{}` gives the five questions without asking claude; the proposal is kept in the project (`interview_proposed`), never in its brief |
| `research/propose` (the `research` job) | `scripts/agents research <inputs.json>`, the same inputs as the personas (only the name is needed); the command holds the prompt (`claude -p`, model `sonnet`, the web search tool only) and checks the answer (`answers.parse_research`: anything else is a failed job); the results go to `research_proposed` of `marque.json`. `PUT research` writes `research` there |
| `logo/propose` (the `logos` job) | `scripts/agents logos <inputs.json>`, the brand's name, description, brief, words, colours (hex, from the dossier) and fonts; checked by `answers.parse_logos`; the tracks go to `logo_tracks_proposed` of `marque.json`. `PUT logo/tracks` writes `logo_tracks` there; `logo/choose` adds the drawing as `add_logo` does |
| `texts/propose` (the `texts` job, of a project) | `scripts/agents texts <inputs.json>` (the project's brief, the brand's name and voice, the language; written in `<p>/work/texts/`); checked by `answers.parse_texts` (anything else is a failed job); the texts go to `texts.proposed` of `project.json`. `PUT texts` writes `texts.kept` there |
| `PUT /brands/{b}` | a new name is also given to the dossier: `brandkit answer <m>/brand identity.name <name>` |
| `PUT brief` (the project's) | `studio brand <piece> --from-dossier <m>/brand --include-unconfirmed --force`, the colours that `brand.md` lacks are completed from the measured ones and marked `(à confirmer)` (with no colour to take them from, the answer is a 400 that says so: there is no neutral stand-in), `studio brand <piece>`; then writes `<piece>/brief.md`, `studio brief <piece>` (its refusal is the 400), then starts the `mandates` job |
| `mandates` job | `scripts/agents mandates <inputs.json>` (the piece folder, its language, the person's words): the proposal, or a default one when the command fails |
| `diverge` | one `scripts/agents variant <inputs.json>` per mandate, in parallel, each in its own folder `<piece>/work/<id>/`, which writes `<piece>/variants/<id>.json` once checked; then `studio diverge <piece>` |
| `storyboard/propose` (the `storyboard` job) | `scripts/agents storyboard <inputs.json>` (the brand's name and fields, its colours from `brand.md`, the confirmed brief); checked by `answers.parse_storyboard` (anything else is a failed job); kept in `project.json` as not saved |
| `storyboard/render` (the `film` job) | `scripts/film <piece> <piece>/storyboard.json --out <piece>/film.mp4`: each shot an HTML page animated by code, in the colours, the fonts and the logo of `brand.md`, captured by headless Chrome, assembled by `ffmpeg` (both needed) |
| `pick` | `studio pick <piece> <ids>` |
| `pieces/{i}/image`, `POST images` | `studio image <piece>/pieces/<…> --engine auto --force` (`STUDIO_IMAGE_ENGINE` changes the engine). `images` starts one job per missing image; at most four run at the same time, the others say "en attente d'une place" |
| `variants/{v}/text` | `studio pick <piece>/pieces/<…> <v> --headline <h> --subline <s>` for each piece of the variant that is not composed (it keeps the words in the `pick.json` of the piece; both are always given, since the command rewrites the file); a piece sent back (`again`) keeps its corrected words |
| `variants/{v}/prompt` | for each piece of the variant that waits for its image, the `image_prompt` of its own `variants/<v>.json` is rewritten (no command) |
| `pieces/{i}/compose`, `POST compose` | `studio compose <piece>/pieces/<…>`, `studio check <piece>/pieces/<…>` (`compose` for every piece in turn) |
| `pieces/{i}/decide` | `studio decide <piece>/pieces/<…> keep|again "<words>"` |
| `judge` job (after `compose`, or `pieces/{i}/judge`) | `scripts/agents judge <inputs.json>` (the picture, the brief, the words of the piece, the brand's voice; written in `<p>/work/judge-<i>/`, the command reads them from there and runs in a temporary folder of its own): the command holds the prompt (`claude -p`, model `claude-fable-5-1`, `Read` and `Write` in a temporary folder of its own; on a failure the command writes claude's raw answer to its errors, kept in `logs/commands.log`), reads `verdict.json` and checks it (`answers.parse_verdict`: anything else is a failed job); the verdict goes to `<piece>/pieces/<…>/judge.json` and, as notes, to `judge.md`, then `studio check <piece>/pieces/<…>` again so that `check.json` carries them. A piece that changed while the judge read it keeps no verdict |
| `POST /judgements`, `judgements/{j}/run` | the same command in `jugements/<j>/work/`, without the words of the piece (they are read on the image); the verdict goes to `jugement.json`, `judge.md` and `page.html` |
| `rounds` job (`POST judgements/{j}/rounds`) | `scripts/agents rounds <inputs.json>` (the picture, the brief, the brand's voice; written in `jugements/<j>/work-rounds/`): three judges (the `judge` command's own code and model, `claude-fable-5-1`) side by side, then one call (model `sonnet`, no tool) that puts their remarks side by side; the synthesis is checked (`answers.parse_rounds`) and goes with the three verdicts to `rounds` in `jugement.json` |
| `reader` job (after `compose` and `POST /judgements`, one per persona, beside the judge; `…/readers/{n}/run`) | `scripts/agents reader <inputs.json>` (the picture, its persona and, in a project, the words of the piece; nothing else; written in `<p>/work/reader-<i>-<n>/` or `jugements/<j>/lecteur-<n>/`, the command runs in a temporary folder of its own): the same kind of call as the judge, model `claude-fable-5-1`; the reading is checked (`answers.parse_reading`) and goes to `<piece>/pieces/<…>/reader-<n>.json` (a new image or a new composition removes them) or to `readings` in `jugement.json`, with the persona it read. A piece that changed while it read keeps no reading |

**A home in the old format** (`<home>/<p>/project.json` with a `brand_name` and its own `brand/` dossier) is opened into this layout when the backend
starts, once: the brand is the one the project's `brand_name` names (projects that give the same name, by slug, go to the same brand); the dossier of
the project modified most recently (its `project.json` or `brand/brand.json`) becomes the `brand/` of the brand, the other projects keep their
`brand/` where it is, inside their folder, and nothing is deleted; the brand takes that project's choices (visuals kept, logo, the words said of the
brand) and its reading jobs; when several projects shared the name, the brand is `migrated` and is `to_confirm` until the person confirms it; each
project moves to `marques/<b>/projets/<p>/` with `brand` the brand's id and `type` `campagne`, and what the old format kept at the project's level
(`brand`, `learn`, `brand_name`, `site`) set aside under `legacy` in its `project.json`. A project called `marques` becomes `marques-projet`.

Environment: `STUDIO_BACKEND` (`studio` or `stub`), `STUDIO_HOME` (the brands and their projects, default `~/ix-studio-projets`), `STUDIO_IMAGE_ENGINE`
(`auto`, `openai`, `openrouter`, `codex`, `none`; wins over the settings), `STUDIO_TEXT_ENGINE` (`claude` or `openrouter`; wins over the settings), `STUDIO_CONFIG_DIR` (where `engines.json` lives), `STUDIO_CLAUDE_BIN` (the program the agents run in place of `claude`), `STUDIO_MODEL_<COMMAND>` (the model of one agent: `STUDIO_MODEL_JUDGE`, `_READER`, `_PERSONAS`, `_NAMES`, `_COMPETITORS`, `_RESEARCH`, `_LOGOS`, `_INTERVIEW`, `_MANDATES`, `_VARIANT`; defaults: `claude-fable-5-1` for the judge and the readers, `sonnet` for the others; `scripts/agents <command> --model` too), `STUDIO_STUB_MISSING` (simulated backend: tools it lacks, `chrome,claude,image`), `STUDIO_CLAUDE_USE_API_KEY=1` (keep `ANTHROPIC_API_KEY` for
`claude -p`; without it the key is dropped from its environment so that the plan pays), `STUDIO_AUTH`, `STUDIO_TOKEN`, `STUDIO_PORT`.
