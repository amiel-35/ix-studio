"""ui: the one stylesheet and the one page shell shared by the five step pages.

Pages are static files opened with a browser. Images are linked relatively.
"""

import html
import os
import shlex
from pathlib import Path

e = html.escape

PAGES = {1: "1-brand.html", 2: "2-brief.html", 3: "3-divergence.html", 4: "4-piece.html", 5: "5-check.html"}
STEPS = {"en": {1: "brand", 2: "brief", 3: "divergence", 4: "piece", 5: "check"},
         "fr": {1: "marque", 2: "brief", 3: "divergence", 4: "pièce", 5: "vérification"}}
T = {"en": {"step": "step", "of": "of", "look": "What to look at, what to answer", "prev": "previous", "next": "next",
            "cmd": "Next command"},
     "fr": {"step": "étape", "of": "sur", "look": "Ce qu'il faut regarder, ce qu'il faut répondre", "prev": "précédente",
            "next": "suivante", "cmd": "Commande suivante"}}

# These tokens are the only place to change the look of the tool. Nothing below :root uses a raw colour.
CSS = """
:root{--bg:#f7f5f1;--card:#fff;--ink:#1c1b1a;--mute:#6d6a65;--line:#e4e0d9;--accent:#8a5a3c;--soft:#f0ebe3;
--ok:#2f7a4b;--warn:#a8741a;--fail:#b3341f;--s1:8px;--s2:16px;--s3:24px;--s4:32px;--r:10px;
--font:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
@media (prefers-color-scheme:dark){:root{--bg:#171615;--card:#211f1e;--ink:#ece9e4;--mute:#a09b94;--line:#35322f;
--accent:#d49a76;--soft:#2a2725;--ok:#69c28a;--warn:#e0b04f;--fail:#f0816d}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 var(--font)}
main{max-width:1000px;margin:0 auto;padding:var(--s3) var(--s2) var(--s4)}
header.top{display:flex;gap:var(--s1);flex-wrap:wrap;align-items:baseline;color:var(--mute);font-size:13px;margin-bottom:var(--s2)}
header.top b{color:var(--ink);font-size:18px}
h1{font-size:24px;margin:0 0 var(--s1)}h2{font-size:18px;margin:var(--s3) 0 var(--s1)}
h3{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute);margin:var(--s2) 0 var(--s1)}
.todo{border:1px solid var(--line);border-left:4px solid var(--accent);background:var(--card);border-radius:var(--r);padding:var(--s1) var(--s2);margin:var(--s2) 0}
.todo ul{margin:4px 0 0;padding-left:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:var(--s2);margin:var(--s2) 0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:var(--s2)}
.cols{display:flex;gap:var(--s3);flex-wrap:wrap;align-items:flex-start}.cols>*{flex:1 1 300px;min-width:0}
.cols>.small{flex:0 1 300px}
.mute{color:var(--mute)}.pass{color:var(--ok)}.warn{color:var(--warn)}.fail{color:var(--fail)}
.pill{font-size:11px;padding:1px 8px;border-radius:99px;background:var(--soft);border:1px solid var(--line);white-space:nowrap}
.pill.pass{border-color:var(--ok)}.pill.warn{border-color:var(--warn)}.pill.fail{border-color:var(--fail)}
.sws{display:flex;flex-wrap:wrap;gap:var(--s2)}.sw{width:110px;font-size:12px}
.chip{height:56px;border-radius:6px;border:1px solid var(--line)}
code,pre{font:12px/1.5 ui-monospace,Menlo,monospace}pre{background:var(--soft);border-radius:6px;padding:var(--s1);overflow-x:auto;white-space:pre-wrap;margin:var(--s1) 0}
table{border-collapse:collapse;width:100%}td,th{border-top:1px solid var(--line);padding:6px;text-align:left;vertical-align:top}
.mock{position:relative;container-type:inline-size;border:1px solid var(--line);border-radius:6px;overflow:hidden;width:100%}
.mock .hatch{position:absolute;inset:0}.mock .cap{position:absolute;left:5%;right:5%;font-size:4.2cqw;line-height:1.25;opacity:.8;overflow:hidden;max-height:30%}
.mock .mblk{position:absolute;left:5%;right:5%;padding:5cqw}.mock .mblk b{display:block;font-size:8cqw;line-height:1.05}.mock .mblk small{display:block;font-size:4cqw;margin-top:2cqw}
.picked{outline:3px solid var(--accent)}
.view{position:relative;width:100%;max-width:340px;border:1px solid var(--line);overflow:hidden}.view img,.view iframe{display:block;width:100%;border:0}
.view iframe{position:absolute;left:0;top:0;transform-origin:0 0}
nav.pn,footer{display:flex;justify-content:space-between;gap:var(--s2);flex-wrap:wrap;margin-top:var(--s3);color:var(--mute);font-size:13px}
footer{border-top:1px solid var(--line);padding-top:var(--s2);display:block}
a{color:var(--accent)}
"""

FIT = """<script>document.querySelectorAll('.view[data-w]').forEach(function(v){var f=v.querySelector('iframe');if(!f)return;
function fit(){var s=v.clientWidth/v.dataset.w;f.style.transform='scale('+s+')';v.style.height=(v.dataset.h*s)+'px'}fit();addEventListener('resize',fit)});</script>"""


def cli(d, cmd, *args) -> str:
    """The command a person types, ready to paste."""
    tool = Path(__file__).resolve().parent
    if Path.cwd().resolve().is_relative_to(tool.parent.parent):
        tool = os.path.relpath(tool)  # inside the repository (the example): short and machine-independent
    return " ".join(["python3", shlex.quote(str(tool)), cmd, shlex.quote(str(d)), *args])


def shell(step, title, body, lang, todo, next_cmd, head="") -> str:
    t, names = T[lang], STEPS[lang]
    links = []
    for n, label in ((step - 1, t["prev"]), (step + 1, t["next"])):
        links.append(f'<a href="{PAGES[n]}">{"← " if n < step else ""}{label}: {n} {names[n]}{" →" if n > step else ""}</a>' if n in PAGES else "<span></span>")
    todo_html = "".join(f"<li>{x}</li>" for x in todo)
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>studio · {e(names[step])}</title>{head}<style>{CSS}</style></head><body><main>
<header class="top"><span>studio</span><span>·</span><span>{t['step']} {step} {t['of']} 5</span><span>·</span><b>{e(names[step])}</b><span class="mute">{e(title)}</span></header>
<div class="todo"><b>{t['look']}</b><ul>{todo_html}</ul></div>
{body}
<nav class="pn">{links[0]}{links[1]}</nav>
<footer>{t['cmd']}: <code>{e(next_cmd)}</code></footer>
</main>{FIT}</body></html>
"""


def write_page(d, step, html_text) -> Path:
    p = Path(d) / PAGES[step]
    p.write_text(html_text, encoding="utf-8")
    return p
