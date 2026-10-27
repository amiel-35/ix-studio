# The studio's interface

A page that drives the whole studio without a terminal: learn a brand (keep or discard each visual, choose or drop the
logo, write its brief, confirm what the studio deduced), then, for each project of the brand, correct the prefilled brief,
read and correct the instructions the agents will get, follow the divergence, pick a series, correct each image prompt,
follow the image, compose, check, decide.

The levels are columns, side by side, from the widest to the most precise: the studio (what waits everywhere and what the machine
lacks at the top, the brands and the judge in the middle, the settings at the bottom) / a brand (what waits, its identity, its projects) /
its identity and assets, or a project (what waits, its seven steps, "Ses pièces") / the detail of a step already done, or of steps 5 to 7
as soon as they have begun ("x sur y pièces"), or the page of what the project made: its series as thumbnails, its texts, its film. What is
selected fades towards the left and grows stronger towards the right: the deepest column is where you are. Every column has its "+"
(a brand, a project, a piece to judge) and its "Modifier". One rule: a row opens a column on its right, nothing unfolds under it.
Any column but the deepest folds into a thin strip that keeps its name, by hand (its "‹" in the top corner) or when the columns do
not fit side by side; a click on a strip unfolds that column alone, and what was folded or unfolded by hand is kept in the browser.
When room runs out, the columns nobody unfolded fold first, from the left. What is changed and not saved yet (names, personas, competitors, files, research, logos, texts, the film, a form, the settings,
and in a task its brief, instructions, prompt, words or comment) is never lost by a gesture in silence: a gesture that would take it
off the screen asks first ("Rester", the default, or "Quitter sans enregistrer"); what the gesture itself saved does not count, the
forms' own "Annuler" do not ask, and closing or reloading the tab gets the browser's own question. Resizing the window is not a
gesture: a column it folds loses what it held. A task is the core: the columns are strips beside it, a
strip opens its column next to the task, and "Revenir aux colonnes", Escape or the left arrow bring the columns back as they were left. Keyboard: up and down
in a column, right to go deeper, left or Escape to come back, Cmd/Ctrl+K for the palette, which reaches everything. Under 760 px,
one column at a time, with a way back. A page opened before the interface changed on disk says so and offers to reload (`build` in
`/api/health`).

The interface holds to ten rules, so that every screen reads the same way:
1. a row opens a column on its right, nothing unfolds under it;
2. a column is a list (rows that open what follows) or a page (forms, editors, images), never both: a project lists its steps and
   opens "Ses pièces", as a brand opens its identity;
3. one head everywhere: the sort of thing, its name, where it stands, "Modifier" in the same place; a strip bears that same name, and a
   task's head is drawn the same way;
4. the same order in every column: the head, what waits there, then the content; a "+" in the heading of the list it adds to;
5. one shape per sort of thing: what waits is a box of task lines, never rows of a list, and the same gesture has the same button
   everywhere (in a page's blocks: keep, write, propose, save are secondary, drop is quiet; "Télécharger", "Composer tout" and
   "Relancer" are secondary wherever they stand, the size following the place, except the relaunch of a failed job, the one
   gesture of its task; a link in a sentence stays a link only in the middle of the text);
6. the studio's column keeps its places: what waits and what is missing at the top, the settings at the bottom, the middle alone scrolls;
7. a task is the one time the screen changes shape, and leaving it gives back the columns as they were;
8. one filled button per column, and one per task;
9. no machine message: a failure says in French what happened and what to do, what the machine said (a known cause, or what reads
   as a program's output: English, paths, traces) unfolds under "Le détail
   technique"; no format key in a title ("post 4×5", not "post-4x5");
10. the screen does not jump: a column shows its head at once, before its data, and a block keeps its place while it loads.

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

**The judge.** Once a piece is composed and checked, a judge reads it (its image and its words, the brief, the brand's voice): five
headings in words, never a score (the target, what works, what catches, what has no source, the brand), shown in the decision screen
beside the mechanical checks. It blocks nothing: you keep or send back without waiting for it. "Juger une pièce", in the studio's
column, opens the judge's column: the past judgements, and its "+" to judge a piece on its own: drop a png or jpg (10 MB at most), write the brief it answers, choose a brand if it has one; the
verdict comes with a flat page to download, and the judgement stays listed in that column (`STUDIO_HOME/jugements/`). The real judge
is `claude -p` reading the picture in a folder of its own; the simulated one gives a fixed verdict.

## What the real studio asks of the machine

- Python 3.10+ (the studio and brandkit scripts), Node.js and Chrome (`scripts/collect` reads the site with the Chrome
  already installed; `studio compose` takes its screenshot with it: set `CHROME=/path/to/chrome` if it is not found).
- ffmpeg and ffprobe (`brandkit keep` measures the colours of the visuals you keep; without them the colours are not
  measured and the page says so).
- Claude Code, signed in (`claude -p`, run by `scripts/agents`: model `claude-fable-5-1` for the judge and the readers, `sonnet` for the others, changed by `STUDIO_MODEL_<COMMAND>`). The key `ANTHROPIC_API_KEY` is not passed to it unless
  `STUDIO_CLAUDE_USE_API_KEY=1`: the plan pays.
- Codex, signed in, for the images (or `OPENAI_API_KEY` / `OPENROUTER_API_KEY`; `STUDIO_IMAGE_ENGINE` forces one).
- The first real run is yours: the tests never call `claude`, `codex` or the network.

When Chrome, Claude Code or an image engine is missing, the studio's column says so, with what to install (`GET /api/machine`). To see that line without removing anything:
`STUDIO_BACKEND=stub STUDIO_STUB_MISSING=chrome,image python3 app/server.py`.

The interface uses a brand design system that is not published with this repository: put its files in
`app/static/ds/` (`tokens.css`, `components/bundle.css`, `components/bundle.js`, `components/lib/react*.js`,
`fonts/`). Without them the server answers `ds/...` with `static/ds-public/`, a neutral look (system fonts, greys, one
blue, the four components the interface uses and React 18.3.1): the studio works on a new machine, it is just not dressed
in the brand.

## How it is built

- `API.md`: the routes and their shapes. The interface knows nothing else.
- `server.py`: serves `static/` and answers `/api/*`; `authenticate` is the single place where an authentication
  plugs in (`STUDIO_AUTH=none` locally, `STUDIO_AUTH=token` with `STUDIO_TOKEN` as a first step; a central server
  replaces it with its own).
- `workflow.py`: the steps, who holds the hand on each, what waits for the person: written once, fed with plain data
  by both backends.
- `backend_studio.py`: the real studio (drives `scripts/studio`, `scripts/brandkit`, `scripts/collect`, `scripts/agents`),
  state on disk, commands through an injected runner (the tests give it a fake one).
- `backend_stub.py`: the simulated studio.
- `static/api.js`: the client, the only file that calls the server; it carries a token when there is one.

## Tomorrow, on a central server

The same routes, behind a proxy that terminates TLS, with an authentication in `authenticate` (and a way for a picture
to carry it: `/files` is behind the same hook), and the jobs in a queue instead of threads. Nothing in the interface
changes but the address of the API.
