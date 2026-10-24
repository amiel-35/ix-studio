# The studio's interface

A page that drives the whole studio without a terminal: learn the brand (keep or discard each visual, choose the
logo), correct the prefilled brief, read and correct the instructions the agents will get, follow the divergence,
pick a series, correct each image prompt, follow the image, compose, check, decide.

**First version: the steps are simulated.** The local server answers the API with a simulated studio
(`backend_stub.py`, the fictional brand of `examples/marrowbay`): nothing is generated, no model is called, the
long steps follow the clock. The interface is built on the API only, so the real backend replaces the simulated one
without touching it.

## Run it

```bash
python3 app/server.py
```

Then open http://127.0.0.1:8765/. Stdlib only, Python 3.10+.

The interface uses a brand design system that is not published with this repository: put its files in
`app/static/ds/` (`tokens.css`, `components/bundle.css`, `components/bundle.js`, `components/lib/react*.js`,
`fonts/`). Without them the page has no style and no components.

## How it is built

- `API.md`: the routes and their shapes. The interface knows nothing else.
- `server.py`: serves `static/` and answers `/api/*`; `authenticate` is the single place where an authentication
  plugs in (`STUDIO_AUTH=none` locally, `STUDIO_AUTH=token` with `STUDIO_TOKEN` as a first step; a central server
  replaces it with its own).
- `backend_stub.py`: the simulated studio. The real backend keeps its methods and drives `scripts/studio` and
  `scripts/brandkit`.
- `static/api.js`: the client, the only file that calls the server; it carries a token when there is one.

## Tomorrow, on a central server

The same routes, behind a proxy that terminates TLS, with an authentication in `authenticate`, a backend that runs
the studio's commands (one folder per project), and the jobs in a queue instead of the clock. Nothing in the
interface changes but the address of the API.
