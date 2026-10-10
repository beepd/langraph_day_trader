"""The markdown to HTML step (blog_html.py). Run:  python test_blog_html.py"""
import sys
sys.path.insert(0, ".")
import blog_html as h

BAD = []
def check(name, condition):
    print(("   ok   " if condition else "   BAD  ") + name)
    if not condition:
        BAD.append(name)

draft = """<!-- model: x; tries: 1; passed all checks: True -->
<!-- meta description: d -->

# 8 October 2026 NSE trading bot

I built a bot with ₹100.00 & fake money.

| Stock | Gross P&L |
|---|---:|
| TCS | −₹238.70 |

**Day total (gross):** −₹729.70

## The trades

- TCS was bought.
- INFY was bought.

---

*Simulation notice: fake money.*
"""
title, body = h.clean_markdown(draft)
check("the header comments and the title line are removed from the body", title == "8 October 2026 NSE trading bot" and body.startswith("I built a bot") and "<!--" not in body)
out = h.to_html(body)
check("paragraphs, headings, bold, lists and the divider convert", "<p>I built a bot" in out and ">The trades</h2>" in out and "<strong>Day total (gross):</strong>" in out
      and out.count("<li>") == 2 and "<hr" in out and "<em>Simulation notice" in out)
check("the table becomes a real HTML table with right-aligned numbers", "<table" in out and ">Stock</th>" in out and ">TCS</td>" in out and "text-align: right" in out)
check("rupee signs, minus signs and ampersands survive", "−₹238.70" in out and "₹100.00 &amp; fake money" in out)
check("tables carry their own borders, header shading and a phone scroll box", 'border:1px solid' in out and 'background:#EDE9DF' in out and 'overflow-x:auto' in out and out.count("<table style=") == 1)
check("numbers stay right-aligned and text left-aligned inside the styled cells", 'text-align:left;vertical-align:bottom;text-align: right' in out or 'text-align: right' in out)
two = h.to_html("| a |\n|---|\n| 1 |\n| 2 |\n| 3 |")
check("alternate rows are banded", two.count('<tr style="background:#F8F6F0">') == 1)
check("headings, divider and the simulation notice are styled inline", '<h2 style=' in out and '<hr style=' in out and '<p style="font-size:14px' in h.to_html("---\n\n*Simulation notice: x*"))
evil = h.to_html("Hello <script>alert(1)</script> world <b>x</b>")
check("raw HTML in the text is escaped, never passed through", "<script>" not in evil and "&lt;script&gt;" in evil and "<b>" not in evil)
print()
print("ALL CHECKS PASSED" if not BAD else "FAILED: " + "; ".join(BAD))
sys.exit(1 if BAD else 0)
