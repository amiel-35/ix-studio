# The studio's API

The interface talks to the studio through this API only. Today a local server answers it with a simulated
studio (`backend_stub.py`): nothing is generated, nothing calls a model. Tomorrow the same routes run on a central
server, behind an authentication, with a backend that drives `scripts/studio` and `scripts/brandkit`.

Every route answers JSON. Every route but `GET /api/health` goes through the authentication hook
(`server.py`, `authenticate`): `STUDIO_AUTH=none` (default, local) lets everything through; `STUDIO_AUTH=token`
asks for `Authorization: Bearer <STUDIO_TOKEN>`. A central server replaces that hook with its own (sessions, SSO).

## Shapes

- **project**: `{id, name, brand, steps: [step], pieces: [piece], waiting: [ask], jobs: [job], now}`. `jobs` lists the running jobs
  (`{id, kind, piece, progress, message, since}`); `now` is the server's clock (epoch seconds), to date `since` without
  trusting the browser's.
- **step**: `{key, label, status, hand, since, job}`. `key` is one of `brand`, `brief`, `mandates`, `diverge`,
  `image`, `piece`, `check`, `decide`. `status`: `todo`, `running`, `waiting` (waits for the person), `done`.
  `hand`: who holds it now, `studio` or `person`. `since`: when the hand last changed on this step (epoch seconds, or null).
  `job`: the running job's id, or null.
- **ask**: what waits for the person, `{step, piece, kind, title, question}`. `kind` names the task (`brand-how`, `brand-sort`,
  `brief`, `mandates`, `diverge-launch`, `diverge-pick`, `prompt`, `compose`, `decide`); `title` is its short name for a list.
- **task**: an ask seen across projects, `{id, project, project_name, brand, step, piece, piece_label, kind, title, question, since}`. `id` is
  `project:step:piece`: it stays the same as long as the task waits. `since` is when the hand came to the person (epoch seconds).
- **job**: `{id, kind, status, progress, message, result}`; `status` is `running`, `done` or `failed`;
  `progress` goes from 0 to 1.
- **piece**: `{id, variant, format, size, status, image, prompt, composed, check, decision}`.

## Routes

| Method and path | What it does |
| --- | --- |
| `GET /api/health` | `{ok, backend, auth}`, no authentication |
| `GET /api/tasks` | `{tasks, jobs, projects, now}`: what waits for the person in every project (the oldest first), the running jobs of every project (`{id, project, kind, piece, progress, message, since, eta}`, `eta` in seconds), and the projects (`{id, name, brand, pieces, waiting}`) |
| `GET /api/projects` | the projects |
| `POST /api/projects` `{name, from?}` | a new project; `from` starts it from another one (a declination) |
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

Errors answer `{error}` with 400 (bad input), 401 (authentication), 404 (unknown) or 409 (not now: the step
it needs is not done).
