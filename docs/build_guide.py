# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Build docs/guide.html from docs/guide.md: one self-contained page (no network needed), with a
contents sidebar, light and dark themes and highlighted Toast code.

  python3 docs/build_guide.py          # writes docs/guide.html
  python3 docs/build_guide.py --check  # exit 1 if guide.html is out of date

Handles the Markdown the guide uses: headings, paragraphs, lists, tables, fenced code, inline
code, bold and links. No dependencies.
"""

import base64
import html
import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent
sys.path.insert(0, str(DOCS.parent))

from toast.compiler import BUILTINS  # noqa: E402
from toast.version import VERSION  # noqa: E402

KEYWORDS = set(
    "def return if elif else for in while break continue and or not import from as pass is "
    "True False None".split()
)
TYPES = {"float", "int", "bool", "vec2", "vec3", "vec4", "quat", "mat4", "list", "math"}
TOKEN_RE = re.compile(
    r"""(?P<comment>\#[^\n]*)
      |(?P<string>"[^"\n]*"|'[^'\n]*')
      |(?P<attr>@[A-Za-z_]\w*)
      |(?P<number>\b\d+\.?\d*(?:[eE][-+]?\d+)?\b)
      |(?P<name>[A-Za-z_]\w*)
      |(?P<other>.)""",
    re.X | re.S,
)


def highlight(code):
    out = []
    for m in TOKEN_RE.finditer(code):
        kind, text = m.lastgroup, m.group()
        esc = html.escape(text, quote=False)
        if kind == "name":
            if text in KEYWORDS:
                kind = "kw"
            elif text in TYPES:
                kind = "type"
            elif text in BUILTINS:
                kind = "fn"
            else:
                kind = None
        elif kind == "other":
            kind = None
        out.append(f'<span class="{kind}">{esc}</span>' if kind else esc)
    return "".join(out)


def slug(text, used):
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"
    s, k = base, 2
    while s in used:
        s, k = f"{base}-{k}", k + 1
    used.add(s)
    return s


def inline(text):
    """Inline code, bold and links. Code spans are cut out first so their content stays literal."""
    parts = re.split(r"(`[^`]+`)", text)
    out = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            out.append(f"<code>{html.escape(part[1:-1], quote=False)}</code>")
            continue
        t = html.escape(part, quote=False)
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
        out.append(t)
    return "".join(out)


RUN_OVER_LABEL = {"points": "Points", "faces": "Faces", "edges": "Edges", "corners": "Face Corners",
                  "curves": "Curves", "instances": "Instances", "geometry": "Geometry"}  # fmt: skip


def code_block(lang, info, code):
    if lang == "toast":
        label = f"Toast · Run Over {RUN_OVER_LABEL.get(info or 'points', info)}"
    else:
        label = {"python": "Toast library" if "def " in code else "Python"}.get(lang, lang or "")
    body = highlight(code) if lang in ("toast", "python") else html.escape(code, quote=False)
    return (f'<figure class="code"><figcaption><span>{html.escape(label)}</span>'
            f'<button class="copy" type="button" aria-label="Copy code">Copy</button></figcaption>'
            f"<pre><code>{body}</code></pre></figure>")  # fmt: skip


def table(rows):
    cells = [[c.strip() for c in r.strip().strip("|").split(" | ")] for r in rows]
    head, body = cells[0], cells[2:]
    out = ['<div class="table"><table><thead><tr>']
    out += [f"<th>{inline(c)}</th>" for c in head]
    out.append("</tr></thead><tbody>")
    for r in body:
        out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def convert(md):
    """Markdown -> (title, intro html, body html, contents [(level, id, text)])."""
    lines = md.splitlines()
    out, toc, used = [], [], set()
    title = "Toast guide"
    i = 0

    def flush_para(buf):
        if buf:
            out.append(f"<p>{inline(' '.join(buf))}</p>")
            buf.clear()

    para = []
    while i < len(lines):
        line = lines[i]
        fence = re.match(r"```(\w*)(?: (\w+))?\s*$", line)
        if fence:
            flush_para(para)
            j = i + 1
            while not lines[j].startswith("```"):
                j += 1
            out.append(code_block(fence.group(1), fence.group(2), "\n".join(lines[i + 1:j])))
            i = j + 1
            continue
        heading = re.match(r"(#{1,3}) (.*)", line)
        if heading:
            flush_para(para)
            level, text = len(heading.group(1)), heading.group(2)
            if level == 1:
                title = text
            else:
                hid = slug(re.sub(r"`", "", text), used)
                toc.append((level, hid, text))
                out.append(f'<h{level} id="{hid}"><a class="anchor" href="#{hid}">{inline(text)}</a></h{level}>')
            i += 1
            continue
        if line.startswith("|"):
            flush_para(para)
            j = i
            while j < len(lines) and lines[j].startswith("|"):
                j += 1
            out.append(table(lines[i:j]))
            i = j
            continue
        item = re.match(r"(- |\d+\. )(.*)", line)
        if item:
            flush_para(para)
            ordered = item.group(1)[0].isdigit()
            items = []
            while i < len(lines):
                m = re.match(r"(- |\d+\. )(.*)", lines[i])
                if m and bool(m.group(1)[0].isdigit()) == ordered:
                    items.append([m.group(2)])
                elif lines[i].startswith("  ") and lines[i].strip() and items:
                    items[-1].append(lines[i].strip())
                else:
                    break
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(' '.join(x))}</li>" for x in items) + f"</{tag}>")
            continue
        if not line.strip():
            flush_para(para)
        else:
            para.append(line.strip())
        i += 1
    flush_para(para)

    # The first paragraph and code block (before the first section) are the introduction.
    first = next(k for k, h in enumerate(out) if h.startswith("<h2"))
    return title, "".join(out[:first]), "\n".join(out[first:]), toc


CSS = r"""
:root {
  --bg: #faf7f2; --bg-soft: #f3ede4; --panel: #ffffff; --text: #2b241d; --muted: #6f6357;
  --line: #e6ddd0; --accent: #b8621b; --accent-soft: #f6e6d4; --link: #9a4f12;
  --code-bg: #f6f1ea; --code-text: #3a2f25; --inline-bg: #f1e9de;
  --tk-kw: #a1356b; --tk-fn: #1f6f8b; --tk-type: #6b4fbb; --tk-attr: #b8621b; --tk-num: #2f7d4a;
  --tk-str: #8a6a12; --tk-com: #8f8478;
  --shadow: 0 1px 2px rgba(60, 40, 20, .06), 0 4px 16px rgba(60, 40, 20, .05);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #15120f; --bg-soft: #1c1814; --panel: #1f1a16; --text: #ebe3d9; --muted: #a59988;
    --line: #2f2822; --accent: #f0a050; --accent-soft: #3a2a1a; --link: #f3b26e;
    --code-bg: #1a1612; --code-text: #e6ddd2; --inline-bg: #2a231d;
    --tk-kw: #f28fbf; --tk-fn: #6cc3df; --tk-type: #b9a2ff; --tk-attr: #f0a050;
    --tk-num: #8fd19e; --tk-str: #e6c66e; --tk-com: #857a6e;
    --shadow: 0 1px 2px rgba(0, 0, 0, .3), 0 6px 20px rgba(0, 0, 0, .25);
  }
}
:root[data-theme="dark"] {
  --bg: #15120f; --bg-soft: #1c1814; --panel: #1f1a16; --text: #ebe3d9; --muted: #a59988;
  --line: #2f2822; --accent: #f0a050; --accent-soft: #3a2a1a; --link: #f3b26e;
  --code-bg: #1a1612; --code-text: #e6ddd2; --inline-bg: #2a231d;
  --tk-kw: #f28fbf; --tk-fn: #6cc3df; --tk-type: #b9a2ff; --tk-attr: #f0a050;
  --tk-num: #8fd19e; --tk-str: #e6c66e; --tk-com: #857a6e;
  --shadow: 0 1px 2px rgba(0, 0, 0, .3), 0 6px 20px rgba(0, 0, 0, .25);
}
* { box-sizing: border-box; }
html { scroll-padding-top: 24px; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 16px/1.65 system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
}
code, pre { font-family: ui-monospace, "JetBrains Mono", "SF Mono", Menlo, Consolas, monospace; }
a { color: var(--link); text-decoration-thickness: 1px; text-underline-offset: 2px; }

.layout { display: grid; grid-template-columns: 272px minmax(0, 1fr); min-height: 100vh; }
.sidebar {
  position: sticky; top: 0; height: 100vh; overflow-y: auto; padding: 28px 18px 40px 24px;
  border-right: 1px solid var(--line); background: var(--bg-soft);
}
.brand { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
.brand img { width: 32px; height: 32px; flex: none; }
.brand strong { font-size: 20px; letter-spacing: -.01em; }
.version { color: var(--muted); font-size: 13px; margin: 0 0 22px 40px; }
.toc { list-style: none; margin: 0; padding: 0; font-size: 14px; }
.toc a {
  display: block; padding: 4px 10px; border-radius: 6px; color: var(--muted); text-decoration: none;
  border-left: 2px solid transparent;
}
.toc a:hover { color: var(--text); background: var(--accent-soft); }
.toc a.active { color: var(--accent); border-left-color: var(--accent); background: var(--accent-soft); }
.toc .l2 > a { color: var(--text); font-weight: 600; margin-top: 10px; }
.toc .l2 > a.active { color: var(--accent); }
.toc .l3 > a { padding-left: 22px; font-size: 13.5px; }
.theme {
  margin-top: 26px; display: inline-flex; border: 1px solid var(--line); border-radius: 8px;
  overflow: hidden; background: var(--panel);
}
.theme button {
  border: 0; background: none; color: var(--muted); font: inherit; font-size: 12.5px;
  padding: 5px 10px; cursor: pointer;
}
.theme button[aria-pressed="true"] { background: var(--accent-soft); color: var(--accent); }

main { padding: 48px 56px 120px; max-width: 900px; width: 100%; }
.hero {
  padding: 34px 36px; border-radius: 16px; margin-bottom: 40px; background:
  radial-gradient(120% 140% at 0% 0%, var(--accent-soft) 0%, transparent 60%), var(--panel);
  border: 1px solid var(--line); box-shadow: var(--shadow);
}
.hero { position: relative; }
.hero-icon { position: absolute; top: 22px; right: 28px; width: 104px; height: 104px;
  filter: drop-shadow(0 6px 14px rgba(120, 60, 10, .25)); }
.hero h1 { margin: 0 0 6px; font-size: 40px; line-height: 1.1; letter-spacing: -.02em; }
.hero h1, .hero > p { padding-right: 120px; }
.hero p { font-size: 17.5px; color: var(--muted); margin: 0 0 22px; max-width: 640px; }
.hero figure.code { margin-bottom: 0; }

h2 {
  font-size: 28px; letter-spacing: -.015em; margin: 56px 0 14px; padding-top: 18px;
  border-top: 1px solid var(--line);
}
h3 { font-size: 19.5px; margin: 34px 0 8px; }
h2 a.anchor, h3 a.anchor { color: inherit; text-decoration: none; }
h2 a.anchor:hover::after, h3 a.anchor:hover::after { content: " #"; color: var(--accent); }
p, ul, ol { margin: 10px 0 14px; }
li { margin: 5px 0; }
li::marker { color: var(--accent); }
strong { font-weight: 650; }
:not(pre) > code {
  background: var(--inline-bg); padding: 1px 6px; border-radius: 5px; font-size: .88em;
  white-space: nowrap;
}

figure.code {
  margin: 18px 0 22px; border-radius: 12px; overflow: hidden; border: 1px solid var(--line);
  background: var(--code-bg); box-shadow: var(--shadow);
}
figure.code figcaption {
  display: flex; justify-content: space-between; align-items: center; padding: 7px 10px 7px 16px;
  font-size: 12.5px; color: var(--muted); border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--code-bg) 70%, var(--line));
}
.copy {
  border: 1px solid var(--line); background: var(--panel); color: var(--muted); border-radius: 6px;
  font: inherit; font-size: 12px; padding: 2px 9px; cursor: pointer;
}
.copy:hover { color: var(--accent); border-color: var(--accent); }
pre { margin: 0; padding: 14px 18px; overflow-x: auto; font-size: 14px; line-height: 1.6;
  color: var(--code-text); tab-size: 4; }
.kw { color: var(--tk-kw); font-weight: 600; }
.fn { color: var(--tk-fn); }
.type { color: var(--tk-type); }
.attr { color: var(--tk-attr); font-weight: 600; }
.number { color: var(--tk-num); }
.string { color: var(--tk-str); }
.comment { color: var(--tk-com); font-style: italic; }

.table { overflow-x: auto; margin: 16px 0 22px; border: 1px solid var(--line); border-radius: 12px;
  background: var(--panel); box-shadow: var(--shadow); }
table { border-collapse: collapse; width: 100%; font-size: 14.5px; }
th, td { text-align: left; padding: 9px 14px; vertical-align: top; border-bottom: 1px solid var(--line); }
th { background: var(--bg-soft); font-weight: 650; font-size: 13px; text-transform: uppercase;
  letter-spacing: .04em; color: var(--muted); }
tr:last-child td { border-bottom: 0; }
td:first-child code { white-space: normal; }

.menu { display: none; }
footer { margin-top: 72px; padding-top: 20px; border-top: 1px solid var(--line); color: var(--muted);
  font-size: 13.5px; }

@media (max-width: 900px) {
  .layout { display: block; }
  .sidebar { position: fixed; inset: 0 25% 0 0; max-width: 320px; z-index: 10; transform: translateX(-102%);
    transition: transform .2s ease; box-shadow: var(--shadow); }
  body.nav-open .sidebar { transform: none; }
  .menu {
    display: inline-flex; position: sticky; top: 12px; z-index: 5; margin: 12px 16px 0;
    border: 1px solid var(--line); background: var(--panel); color: var(--text); border-radius: 8px;
    padding: 6px 12px; font: inherit; font-size: 14px; box-shadow: var(--shadow);
  }
  main { padding: 20px 16px 80px; }
  .hero { padding: 24px 20px; }
  .hero h1 { font-size: 32px; }
  .hero-icon { width: 64px; height: 64px; top: 18px; right: 16px; }
  .hero h1, .hero > p { padding-right: 0; }
  .hero h1 { padding-right: 72px; }
  h2 { font-size: 24px; }
}
@media print {
  .sidebar, .menu, .copy, .theme { display: none !important; }
  .layout { display: block; }
  main { max-width: none; padding: 0; }
}
"""

JS = r"""
(function () {
  var root = document.documentElement;
  function setTheme(t) {
    if (t === "auto") { root.removeAttribute("data-theme"); } else { root.setAttribute("data-theme", t); }
    document.querySelectorAll(".theme button").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.theme === t));
    });
    try { localStorage.setItem("toast-guide-theme", t); } catch (e) {}
  }
  var saved = "auto";
  try { saved = localStorage.getItem("toast-guide-theme") || "auto"; } catch (e) {}
  setTheme(saved);
  document.querySelectorAll(".theme button").forEach(function (b) {
    b.addEventListener("click", function () { setTheme(b.dataset.theme); });
  });

  document.querySelectorAll(".copy").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var text = btn.closest("figure").querySelector("pre").innerText;
      function done() { btn.textContent = "Copied"; setTimeout(function () { btn.textContent = "Copy"; }, 1400); }
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(done, function () {});
      } else {
        var ta = document.createElement("textarea");
        ta.value = text; document.body.appendChild(ta); ta.select();
        try { document.execCommand("copy"); done(); } catch (e) {}
        ta.remove();
      }
    });
  });

  var menu = document.querySelector(".menu");
  menu.addEventListener("click", function () { document.body.classList.toggle("nav-open"); });
  document.querySelectorAll(".toc a").forEach(function (a) {
    a.addEventListener("click", function () { document.body.classList.remove("nav-open"); });
  });

  var links = {};
  document.querySelectorAll(".toc a").forEach(function (a) { links[a.getAttribute("href").slice(1)] = a; });
  var headings = Array.prototype.slice.call(document.querySelectorAll("main h2[id], main h3[id]"));
  function spy() {
    var current = null;
    for (var k = 0; k < headings.length; k++) {
      if (headings[k].getBoundingClientRect().top < 120) { current = headings[k]; } else { break; }
    }
    document.querySelectorAll(".toc a.active").forEach(function (a) { a.classList.remove("active"); });
    if (current && links[current.id]) {
      links[current.id].classList.add("active");
      var box = document.querySelector(".sidebar");
      var r = links[current.id].getBoundingClientRect();
      if (r.top < 80 || r.bottom > window.innerHeight - 40) { links[current.id].scrollIntoView({block: "nearest"}); }
    }
  }
  document.addEventListener("scroll", spy, {passive: true});
  spy();
})();
"""

IMAGES = DOCS.parent / "images"


def data_uri(name):
    """An image of images/ inlined, so the page stays one file that works offline."""
    return "data:image/png;base64," + base64.b64encode((IMAGES / name).read_bytes()).decode()


def build(md_text):
    title, intro, body, toc = convert(md_text)
    icon = data_uri("toast_icon_128.png")
    toc_html = []
    for level, hid, text in toc:
        toc_html.append(f'<li class="l{level}"><a href="#{hid}">{inline(text)}</a></li>')
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Toast guide</title>
<meta name="description" content="Toast: Python-syntax kernels for Blender geometry nodes, compiled to native code.">
<link rel="icon" type="image/png" href="{data_uri("toast_icon_32.png")}">
<style>{CSS}</style>
</head>
<body>
<button class="menu" type="button" aria-label="Contents">☰ Contents</button>
<div class="layout">
<nav class="sidebar" aria-label="Contents">
<div class="brand"><img src="{icon}" alt=""><strong>Toast</strong></div>
<p class="version">Guide · version {VERSION}</p>
<ul class="toc">{"".join(toc_html)}</ul>
<div class="theme" role="group" aria-label="Theme">
<button type="button" data-theme="light">Light</button><button type="button" data-theme="auto">Auto</button><button type="button" data-theme="dark">Dark</button>
</div>
</nav>
<main>
<header class="hero"><img class="hero-icon" src="{icon}" alt="Toast"><h1>{html.escape(title)}</h1>{intro}</header>
{body}
<footer>Toast {VERSION} · GPL-2.0-or-later · generated from <code>docs/guide.md</code></footer>
</main>
</div>
<script>{JS}</script>
</body>
</html>
"""


def main():
    md = (DOCS / "guide.md").read_text()
    page = build(md)
    target = DOCS / "guide.html"
    if "--check" in sys.argv:
        if not target.exists() or target.read_text() != page:
            print("docs/guide.html is out of date: run python3 docs/build_guide.py")
            sys.exit(1)
        return
    target.write_text(page)
    print(f"Wrote {target}")


if __name__ == "__main__":
    main()
