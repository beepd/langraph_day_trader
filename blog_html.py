"""
Turns a blog post (markdown) into the HTML that Blogger (or any blog platform) wants.

    python blog_html.py blog_draft_daily_2026-10-09.md      writes blog_draft_daily_2026-10-09.html
    python blog_html.py 2026-10-09                          the same, but reads the saved draft of that date from the database

Open the .html file, copy everything, and paste it into a Blogger post in "HTML view" to see how a real post will look.
The publisher will use the same function (to_html), so what you see here is what will be published.

Only the post BODY is produced: the title is a separate field on the blog platform. Needs:  pip install markdown
"""
import html
import re
import sys

import markdown


def clean_markdown(text: str) -> tuple:
    """(title, body) from a draft file: drops the '<!-- ... -->' comment lines at the top and the '# title' line."""
    lines = text.replace("\r\n", "\n").split("\n")
    while lines and (lines[0].strip().startswith("<!--") or not lines[0].strip()):
        lines.pop(0)
    title = None
    if lines and lines[0].startswith("# "):
        title = lines.pop(0)[2:].strip()
    return title, "\n".join(lines).strip()


INK, ACCENT, LINE, HEAD_BG, ROW_BG = "#1B1F23", "#0F766E", "#CFC8B8", "#EDE9DF", "#F8F6F0"
MONO = "'IBM Plex Mono',ui-monospace,Menlo,Consolas,monospace"
TABLE = f"border-collapse:collapse;width:100%;font-size:15px;line-height:1.4;border:1px solid {LINE};font-variant-numeric:tabular-nums"
TH = f"padding:9px 12px;border:1px solid {LINE};border-bottom:2px solid {INK};background:{HEAD_BG};color:{INK};font-family:{MONO};font-size:13px;font-weight:600;text-align:left;vertical-align:bottom"
TD = f"padding:8px 12px;border:1px solid {LINE};text-align:left;vertical-align:top"
H2 = f"font-family:{MONO};font-size:1.25em;margin:2em 0 .6em;padding-bottom:5px;border-bottom:2px solid {ACCENT}"
HR = f"border:0;border-top:1px solid {LINE};margin:2em 0"
NOTICE = f"font-size:14px;line-height:1.55;color:#555;background:{HEAD_BG};padding:12px 14px;border-left:3px solid {ACCENT};margin:0"


def _merge(tag: str, base: str):
    """Add inline style to every <tag>, keeping any style already there (the markdown column alignment)."""
    def repl(m):
        existing = (m.group(1) or "").strip().rstrip(";")
        return f'<{tag} style="{base}{";" + existing if existing else ""}">'
    return repl


def style_html(out: str) -> str:
    """Inline styles, so the post looks the same on any blog platform and no theme CSS is needed: bordered tables with
    aligned numbers, banded rows, a scroll box for phones, styled headings, divider and simulation notice."""
    out = re.sub(r"<th(?: style=\"([^\"]*)\")?>", _merge("th", TH), out)
    out = re.sub(r"<td(?: style=\"([^\"]*)\")?>", _merge("td", TD), out)

    def band(m):
        count = 0
        def row(_):
            nonlocal count
            count += 1
            return f'<tr style="background:{ROW_BG}">' if count % 2 == 0 else "<tr>"
        return re.sub(r"<tr>", row, m.group(0))
    out = re.sub(r"<tbody>.*?</tbody>", band, out, flags=re.S)
    out = out.replace("<table>", f'<div style="overflow-x:auto;margin:1.5em 0"><table style="{TABLE}">').replace("</table>", "</table></div>")
    out = out.replace("<h2>", f'<h2 style="{H2}">').replace("<hr>", f'<hr style="{HR}">').replace("<hr />", f'<hr style="{HR}">')
    return out.replace("<p><em>Simulation notice", f'<p style="{NOTICE}"><em>Simulation notice')


def to_html(body_markdown: str) -> str:
    """Markdown to styled HTML. Any raw HTML in the text is escaped first, so a post can never carry a script or a stray tag."""
    safe = html.escape(body_markdown, quote=False)
    return style_html(markdown.markdown(safe, extensions=["tables", "sane_lists"], output_format="html"))


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python blog_html.py <draft.md | YYYY-MM-DD>")
    arg = sys.argv[1]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", arg):
        from storage import get_client
        rows = get_client().table("blog_posts").select("title, body_markdown").eq("market_date", arg).limit(1).execute().data
        if not rows:
            raise SystemExit(f"No saved post for {arg}.")
        title, body, out = rows[0]["title"], rows[0]["body_markdown"], f"blog_post_{arg}.html"
    else:
        title, body = clean_markdown(open(arg, encoding="utf-8").read())
        out = re.sub(r"\.md$", "", arg) + ".html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(to_html(body) + "\n")
    print(f"Saved {out}. Title for the Blogger title box: {title}")
    print("Open the file, copy everything, and paste it into a Blogger post in HTML view.")


if __name__ == "__main__":
    main()
