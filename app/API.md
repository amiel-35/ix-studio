# The studio's API

The interface talks to the studio through this API only. Two backends answer it with the same methods and the same
shapes, and the interface does not have to know which one runs (`STUDIO_BACKEND`):

- `studio` (default): `backend_studio.py` drives `scripts/brandkit`, `scripts/studio` and `scripts/collect`, and asks
  `claude -p` to write. A project is a folder of `STUDIO_HOME`; the state lives on that disk.
- `stub`: `backend_stub.py` is a simulated studio: nothing is generated, nothing calls a model.

What waits for the person, which step holds the hand and the order of the steps are written once, in `workflow.py`,
which both backends feed with plain data. Tomorrow the same routes can run on a central server, behind an authentication.

Every route answers JSON. Every route but `GET /api/health` goes through the authentication hook
(`server.py`, `authenticate`): `STUDIO_AUTH=none` (default, local) lets everything through; `STUDIO_AUTH=token`
asks for `Authorization: Bearer <STUDIO_TOKEN>`. A central server replaces that hook with its own (sessions, SSO).

## Shapes

- **project**: `{id, name, brand, can_learn, steps: [step], pieces: [piece], waiting: [ask], jobs: [job], now}`. `can_learn`: the studio can search the
  brand (the real backend needs the brand's site for that; without it `learn` mode answers 400 and the interface says so). `jobs` lists the running jobs
  (`{id, kind, piece, progress, message, since}`); `now` is the server's clock (epoch seconds), to date `since` without
  trusting the browser's.
- **step**: `{key, label, status, hand, since, job}`. `key` is one of `brand`, `brief`, `mandates`, `diverge`,
  `image`, `piece`, `check`, `decide`. `status`: `todo`, `running`, `waiting` (waits for the person), `done`.
  `hand`: who holds it now, `studio` or `person`. `since`: when the hand last changed on this step (epoch seconds, or null).
  `job`: the running job's id, or null.
- **ask**: what waits for the person, `{step, piece, kind, title, question}`. `kind` names the task (`brand-how`, `brand-sort`,
  `brief`, `mandates`, `diverge-launch`, `diverge-pick`, `prompt`, `compose`, `decide`, and `job-failed`); `title` is its short name for a list.
  `job-failed` stands in for the task the failed job belonged to: `question` is the reason in one line, and running the step again (same route as
  before) makes it go away. Its `step` and `piece` say what to run again.
- **task**: an ask seen across projects, `{id, project, project_name, brand, step, piece, piece_label, kind, title, question, since}`. `id` is
  `project:step:piece`: it stays the same as long as the task waits. `since` is when the hand came to the person (epoch seconds).
- **job**: `{id, kind, status, progress, message, result}`; `kind` is `learn`, `mandates` (the real backend: an agent proposes the instructions), `diverge`
  or `image`; `status` is `running`, `done` or `failed`; `progress` goes from 0 to 1 (the real backend estimates it on an expected duration per kind
  and never shows more than 0.95 while the job runs). A failed job's `message` is the reason (the end of the failing command's output); the real
  backend also gives `error` and `eta`, and keeps the whole output in `<project>/logs/<job>.log`.
- **piece**: `{id, variant, format, size, status, image, prompt, composed, check, decision}`.

## Routes

| Method and path | What it does |
| --- | --- |
| `GET /api/health` | `{ok, backend, auth}`, no authentication |
| `GET /api/tasks` | `{tasks, jobs, projects, now}`: what waits for the person in every project (the oldest first), the running jobs of every project (`{id, project, kind, piece, progress, message, since, eta}`, `eta` in seconds), and the projects (`{id, name, brand, pieces, waiting}`) |
| `GET /api/projects` | the projects |
| `POST /api/projects` `{name, brand?, site?, from?}` | a new project. The real backend wants `brand` (the brand's name) and takes an optional `site` (a public web address: `ftp:` and local or private addresses are refused with 400); `from` starts from another project (a declination, which keeps its brand and brief and needs neither). The simulated one ignores `brand` and `site` |
| `GET /api/projects/{p}` | the project, its steps and what waits for the person |
| `POST /api/projects/{p}/brand/learn` `{mode, answers?}` | learn the brand: `learn` (the studio searches: a job), `answer` (the person tells what they know in `answers`, required), `create` (from nothing) |
| `GET /api/projects/{p}/brand` | the evidence to keep or discard (`proposed`: what the studio would keep), the logo candidates, the measured colours, the person's `answers` |
| `POST /api/projects/{p}/brand/keep` `{kept: [ids], logo}` | the person's choices |
| `GET /api/projects/{p}/brief` / `PUT` `{fields}` | the brief, prefilled; the person corrects it. `GET` also gives `formats` (what the studio can make), `chosen` (the formats the brief asks for that it can make) and `left_out` (the ones it puts aside, a film for instance) |
| `GET /api/projects/{p}/mandates` / `PUT` `{mandates, common}` | the instructions the agents will get, read and corrected before any run |
| `POST /api/projects/{p}/diverge` | write the variants: a job |
| `GET /api/projects/{p}/variants` | the variants |
| `POST /api/projects/{p}/pick` `{variants: [ids]}` | the kept variants: one piece per variant and per format |
| `GET /api/projects/{p}/pieces/{i}` | a piece |
| `PUT /api/projects/{p}/pieces/{i}/prompt` `{prompt}` | the image prompt, corrected before the image |
| `POST /api/projects/{p}/pieces/{i}/image` | draw the image: a job |
| `POST /api/projects/{p}/pieces/{i}/compose` | compose the piece and check it |
| `POST /api/projects/{p}/pieces/{i}/decide` `{verdict, words}` | `keep`, or `again` with what is wrong |
| `GET /api/jobs/{j}` | a job's progress |
| `GET /files/{p}/{path}` | a file of the project's `brand/` or `piece/` folders (the pictures the shapes point to: `preview`, `image`, `composed`). Anything that leaves those folders answers 404. Same authentication as the API: with `STUDIO_AUTH=token` a page cannot load an `<img>` this way (a picture cannot send a header), which the central server's own hook has to solve. Served with `Content-Security-Policy: sandbox`. The simulated backend has none |

Errors answer `{error}` with 400 (bad input, or the studio's own message when its tool refuses: a brief with an unknown
layout, a screenshot that cannot be taken), 401 (authentication), 404 (unknown) or 409 (not now: the step it needs
is not done, or the job is already running).

## The real backend, step by step

Each long step is a job (a thread running sub-processes, the output kept in `logs/`); a restart marks the jobs that were
running as failed. The commands, with `<p>` the project's folder and `<piece>` its `piece/`:

| Route | Commands |
| --- | --- |
| `brand/learn` `learn` | `brandkit init <p>/brand --name <brand> --lang fr`, `node scripts/collect/collect.mjs <site> <p>/brand/collect/web-<host>`, `brandkit infer-site <p>/brand <that folder>`, `brandkit review-html <p>/brand --no-previews` |
| `brand/learn` `answer`, `create` | `brandkit init` if needed, then (`answer`) `brandkit answer <p>/brand identity.one_liner "<words>"`; the words stay in `project.json` too |
| `brand/keep` | `brandkit keep <p>/brand <kept ids> <site page ids> [--logo <id>]` (`--none` with nothing to keep), `studio brand <piece> --from-dossier <p>/brand --include-unconfirmed --force`, the colours that `brand.md` lacks are completed from the measured ones and marked `(à confirmer)`, `studio brand <piece>` |
| `PUT brief` | writes `<piece>/brief.md`, `studio brief <piece>` (its refusal is the 400), then starts the `mandates` job |
| `mandates` job | `claude -p <prompt> --model sonnet --no-session-persistence --restricted --tools ""`: the proposal, or a default one when the call fails |
| `diverge` | one `claude -p <prompt> --model sonnet --no-session-persistence --restricted --tools=Read,Write --permission-mode=acceptEdits --permission-prompts=none` per mandate, in parallel, each in its own folder `<piece>/work/<id>/`; then `studio diverge <piece>` |
| `pick` | `studio pick <piece> <ids>` |
| `pieces/{i}/image` | `studio image <piece>/pieces/<…> --engine auto --force` (`STUDIO_IMAGE_ENGINE` changes the engine) |
| `pieces/{i}/compose` | `studio compose <piece>/pieces/<…>`, `studio check <piece>/pieces/<…>` |
| `pieces/{i}/decide` | `studio decide <piece>/pieces/<…> keep|again "<words>"` |

Environment: `STUDIO_BACKEND` (`studio` or `stub`), `STUDIO_HOME` (the projects, default `~/ix-studio-projets`), `STUDIO_IMAGE_ENGINE`
(`auto`, `openai`, `codex`, `none`), `STUDIO_CLAUDE_BIN` (the `claude` command), `STUDIO_CLAUDE_USE_API_KEY=1` (keep `ANTHROPIC_API_KEY` for
`claude -p`; without it the key is dropped from its environment so that the plan pays), `STUDIO_AUTH`, `STUDIO_TOKEN`, `STUDIO_PORT`.
