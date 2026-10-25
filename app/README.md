# The studio's interface

A page that drives the whole studio without a terminal: learn a brand (keep or discard each visual, choose or drop the
logo, write its brief, confirm what the studio deduced), then, for each project of the brand, correct the prefilled brief,
read and correct the instructions the agents will get, follow the divergence, pick a series, correct each image prompt,
follow the image, compose, check, decide.

The levels are columns, side by side, from the widest to the most precise: the studio (what waits everywhere, then the brands) /
a brand (its brief, its assets, its projects) / a project (its seven steps, what waits, and once pieces exist the series as thumbnails, each with where it stands) / the detail of a step already done, or of steps 5 to 7 as soon as they have begun ("x sur y pièces"). What is
selected fades towards the left and grows stronger towards the right: the deepest column is where you are. Every column has its "+"
(a brand, a project) and its "Modifier". A task is the core: opening it folds the columns into thin strips that keep their names;
a click on a strip, Escape or the left arrow brings them back. Keyboard: up and down in a column, right to go deeper, left or
Escape to come back, Cmd/Ctrl+K for the palette, which reaches everything. When the columns do not fit side by side (four levels on a 1 280 px screen), those on the left fold into strips that keep their names, as they do in a task, and a click on a strip goes back to that level. Under 760 px, one column at a time, with a way back.

The interface is built on the API only (`API.md`), so it does not know which backend answers. Two exist:

- **the real studio** (default): `backend_studio.py` runs the tools of this repository for each step, in jobs, and
  asks `claude -p` (Claude Code without a screen, on your plan) for the instructions and the variants, and Codex
  (through `studio image`) for the images. The studio holds brands and a brand holds projects: each brand is a folder of `STUDIO_HOME`
  (default `~/ix-studio-projets`) with its projects inside; restart the server and everything is there. A home from before
  the brands (one folder per project) is opened into brands the first time (see `API.md`).
- **the simulated studio** (`STUDIO_BACKEND=stub`): `backend_stub.py`, three fictional brands in three stages (the first is `examples/marrowbay`).
  Nothing is generated, no model is called, the long steps follow the clock. Good to work on the interface.

## Run it

```bash
python3 app/server.py                        # the real studio; projects in ~/ix-studio-projets
STUDIO_HOME=~/mes-projets python3 app/server.py
STUDIO_BACKEND=stub python3 app/server.py    # the simulated one
```

Then open http://127.0.0.1:8765/. Stdlib only, Python 3.10+.

Creating a brand asks for its name and, optionally, its site: the studio reads the site to learn the brand (without a site you
write its brief and drop its logo, a png, jpg or svg of 2 MB at most). A brand is learned once, its projects use it. A step that fails (the site cannot be read, an
agent writes nothing, no image engine) comes back in the list as a task to run again, with the reason; the whole
output of each job is in the `logs/` folder of its brand or project.

## What the real studio asks of the machine

- Python 3.10+ (the studio and brandkit scripts), Node.js and Chrome (`scripts/collect` reads the site with the Chrome
  already installed; `studio compose` takes its screenshot with it: set `CHROME=/path/to/chrome` if it is not found).
- ffmpeg and ffprobe (`brandkit keep` measures the colours of the visuals you keep; without them the colours are not
  measured and the page says so).
- Claude Code, signed in (`claude -p`, model sonnet). The key `ANTHROPIC_API_KEY` is not passed to it unless
  `STUDIO_CLAUDE_USE_API_KEY=1`: the plan pays.
- Codex, signed in, for the images (or `OPENAI_API_KEY` / `OPENROUTER_API_KEY`; `STUDIO_IMAGE_ENGINE` forces one).
- The first real run is yours: the tests never call `claude`, `codex` or the network.

When Chrome, Claude Code or an image engine is missing, the studio's column says so, with what to install (`GET /api/machine`). To see that line without removing anything:
`STUDIO_BACKEND=stub STUDIO_STUB_MISSING=chrome,image python3 app/server.py`.

The interface uses a brand design system that is not published with this repository: put its files in
`app/static/ds/` (`tokens.css`, `components/bundle.css`, `components/bundle.js`, `components/lib/react*.js`,
`fonts/`). Without them the page has no style and no components.

## How it is built

- `API.md`: the routes and their shapes. The interface knows nothing else.
- `server.py`: serves `static/` and answers `/api/*`; `authenticate` is the single place where an authentication
  plugs in (`STUDIO_AUTH=none` locally, `STUDIO_AUTH=token` with `STUDIO_TOKEN` as a first step; a central server
  replaces it with its own).
- `workflow.py`: the steps, who holds the hand on each, what waits for the person: written once, fed with plain data
  by both backends.
- `backend_studio.py`: the real studio (drives `scripts/studio`, `scripts/brandkit`, `scripts/collect`, `claude -p`),
  state on disk, commands through an injected runner (the tests give it a fake one).
- `backend_stub.py`: the simulated studio.
- `static/api.js`: the client, the only file that calls the server; it carries a token when there is one.

## Tomorrow, on a central server

The same routes, behind a proxy that terminates TLS, with an authentication in `authenticate` (and a way for a picture
to carry it: `/files` is behind the same hook), and the jobs in a queue instead of threads. Nothing in the interface
changes but the address of the API.
