"""Dark theme with neon accents. The colours for charts live here too, so everything matches."""
import html

NEON = {"cyan": "#00F5FF", "green": "#39FF14", "pink": "#FF2BD6", "yellow": "#FFE600",
        "red": "#FF3860", "violet": "#B026FF", "orange": "#FF9100"}
TONES = {"good": NEON["green"], "bad": NEON["red"], "neutral": NEON["cyan"], "warn": NEON["yellow"]}

CSS = """
<style>
[data-testid="stAppViewContainer"] {
  background:
    radial-gradient(1100px 600px at 8% -10%, rgba(176,38,255,.20), transparent 60%),
    radial-gradient(900px 500px at 100% 0%, rgba(0,245,255,.15), transparent 55%),
    #070B14;
}
[data-testid="stHeader"] { background: transparent; }
h1 { color:#00F5FF; text-shadow: 0 0 6px rgba(0,245,255,.85), 0 0 24px rgba(0,245,255,.45); letter-spacing:.5px; }
h2, h3 { color:#E8F1FF; text-shadow: 0 0 10px rgba(176,38,255,.6); }
.neon-card {
  background: linear-gradient(145deg, rgba(14,22,38,.96), rgba(9,15,27,.96));
  border: 1px solid var(--tone); border-radius: 14px; padding: 14px 18px; margin-bottom: 10px;
  box-shadow: 0 0 14px color-mix(in srgb, var(--tone) 35%, transparent), inset 0 0 18px rgba(176,38,255,.08);
}
.neon-card .label { color:#9FB3D1; text-transform:uppercase; letter-spacing:.09em; font-size:.72rem; }
.neon-card .value { color: var(--tone); font-size:1.7rem; font-weight:700; line-height:1.25;
                    text-shadow: 0 0 10px color-mix(in srgb, var(--tone) 70%, transparent); }
.neon-card .sub   { color:#9FB3D1; font-size:.78rem; }
button[data-baseweb="tab"] { color:#9FB3D1; }
button[data-baseweb="tab"][aria-selected="true"] { color:#00F5FF; text-shadow:0 0 8px rgba(0,245,255,.85); }
a { color:#FF2BD6 !important; }
#MainMenu, footer { visibility:hidden; }
</style>
"""


def card(label: str, value: str, sub: str = "", tone: str = "neutral") -> str:
    """HTML for one glowing number card. Every piece of text is escaped."""
    return (f'<div class="neon-card" style="--tone:{TONES.get(tone, TONES["neutral"])}">'
            f'<div class="label">{html.escape(label)}</div><div class="value">{html.escape(value)}</div>'
            f'<div class="sub">{html.escape(sub) if sub else "&nbsp;"}</div></div>')


def md_escape(text) -> str:
    """Text from the web or from the model must never act as formatting or links on a public page."""
    out = []
    for ch in str(text):
        out.append("\\" + ch if ch in "\\`*_{}[]()<>#+-.!|~$&" else ch)
    return "".join(out)


def safe_link(title, url) -> str:
    title = md_escape(title)
    url = str(url or "")
    return f"[{title}]({url.replace(' ', '%20').replace('(', '%28').replace(')', '%29')})" if url.startswith(("http://", "https://")) else title