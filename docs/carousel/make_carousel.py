"""
Simple carousel PDF — 6 square slides (1080x1080 pt).
"""

from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, white
from reportlab.lib.utils import simpleSplit
import os

SLIDE_W = SLIDE_H = 1080
OUT = os.path.join(os.path.dirname(__file__), "local_agent_carousel.pdf")

BG     = HexColor("#0F1117")
CARD   = HexColor("#1A1F2B")
BLUE   = HexColor("#4F8EF7")
GREEN  = HexColor("#3FB950")
MUTED  = HexColor("#8B949E")
WHITE  = white


def wrap(c, text, x, y, w, font, size, color, leading=None, align="left"):
    """Draw wrapped text, return y below last line."""
    if leading is None:
        leading = size * 1.5
    c.setFont(font, size)
    c.setFillColor(color)
    for line in simpleSplit(text, font, size, w):
        if align == "center":
            c.drawCentredString(x + w / 2, y, line)
        else:
            c.drawString(x, y, line)
        y -= leading
    return y


def rule(c, y, color=BLUE, x=80, w=None):
    w = w or (SLIDE_W - 160)
    c.setFillColor(color)
    c.rect(x, y, w, 4, fill=1, stroke=0)


def tag(c, x, y, text, fg=BLUE):
    c.setFont("Helvetica-Bold", 20)
    c.setFillColor(fg)
    c.drawString(x, y, text)


def number(c, n, total=6):
    c.setFont("Helvetica", 20)
    c.setFillColor(MUTED)
    c.drawRightString(SLIDE_W - 60, 44, f"{n} / {total}")


def base(c, accent=BLUE):
    c.setFillColor(BG)
    c.rect(0, 0, SLIDE_W, SLIDE_H, fill=1, stroke=0)
    c.setFillColor(accent)
    c.rect(0, SLIDE_H - 8, SLIDE_W, 8, fill=1, stroke=0)


# ── slides ────────────────────────────────────────────────────────────────────

def s1(c):
    base(c, BLUE)
    tag(c, 80, 940, "LOCAL AI")
    wrap(c, "Hosting coding agents locally",
         80, 840, 920, "Helvetica-Bold", 66, WHITE, align="center")
    wrap(c, "on your home machine or a\npowerful enough laptop",
         80, 720, 920, "Helvetica-Bold", 66, WHITE, leading=80, align="center")
    wrap(c, "is possible.",
         80, 590, 920, "Helvetica-Bold", 66, GREEN, align="center")
    rule(c, 520)
    wrap(c, "But there are trade-offs worth knowing.",
         80, 470, 920, "Helvetica", 30, MUTED, align="center")
    number(c, 1)
    c.showPage()


def s2(c):
    base(c, BLUE)
    tag(c, 80, 940, "TUNING THE FIT")
    wrap(c, "Model size, context length,\nand quantisation",
         80, 860, 920, "Helvetica-Bold", 58, WHITE, leading=74, align="center")
    wrap(c, "need to be finely tuned",
         80, 730, 920, "Helvetica-Bold", 58, BLUE, align="center")
    rule(c, 670, GREEN)
    wrap(c,
         "The goal: keep the model largely within GPU memory "
         "and limit CPU spillover — otherwise inference becomes painfully slow.",
         80, 620, 920, "Helvetica", 30, MUTED, leading=46, align="center")
    number(c, 2)
    c.showPage()


def s3(c):
    base(c, BLUE)
    tag(c, 80, 940, "STITCHING THE INSTRUCTIONS")
    wrap(c, "Tool-calls API\ncompatibility",
         80, 850, 920, "Helvetica-Bold", 72, WHITE, leading=88, align="center")
    rule(c, 700)
    wrap(c,
         "The system prompt and tool-call format need to be carefully "
         "stitched together.  Frontends expect OpenAI-style tool_calls; "
         "local models often emit XML or bare JSON — a proxy shim bridges the gap.",
         80, 650, 920, "Helvetica", 29, MUTED, leading=46, align="center")
    number(c, 3)
    c.showPage()


def s4(c):
    base(c, GREEN)
    tag(c, 80, 940, "REALITY CHECK", fg=GREEN)
    wrap(c, "Bigger model → excruciatingly slow.",
         80, 870, 920, "Helvetica-Bold", 40, WHITE)
    wrap(c, "Faster runtime → lower reliability.",
         80, 810, 920, "Helvetica-Bold", 40, WHITE)
    rule(c, 770, GREEN)
    wrap(c, "There may be a sweet spot for your machine.",
         80, 720, 920, "Helvetica", 34, MUTED, align="center")
    wrap(c, "For mine:",
         80, 640, 920, "Helvetica", 30, MUTED, align="center")

    # highlight box
    c.setFillColor(CARD)
    c.roundRect(120, 520, 840, 90, radius=14, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 36)
    c.setFillColor(BLUE)
    c.drawCentredString(SLIDE_W / 2, 553, "Qwen 2.5  8B  ·  64 K context")

    wrap(c, "More details →",
         80, 460, 920, "Helvetica", 26, MUTED, align="center")
    wrap(c, "github.com/techaarvam/aarvam_lca/blob/main/PROJECT_REPORT.md",
         80, 415, 920, "Helvetica", 24, BLUE, align="center")
    number(c, 4)
    c.showPage()


def s5(c):
    base(c, BLUE)
    tag(c, 80, 940, "GET STARTED")
    wrap(c, "Setup instructions",
         80, 840, 920, "Helvetica-Bold", 72, WHITE, align="center")

    c.setFillColor(CARD)
    c.roundRect(80, 680, 920, 110, radius=16, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 24)
    c.setFillColor(GREEN)
    c.drawString(120, 752, "INSTALL.md")
    c.setFont("Helvetica", 22)
    c.setFillColor(BLUE)
    c.drawString(120, 714, "github.com/techaarvam/aarvam_lca/blob/main/INSTALL.md")

    wrap(c,
         "Step-by-step guide to replicate the stack on your own machine.",
         80, 620, 920, "Helvetica", 30, MUTED, leading=46, align="center")
    number(c, 5)
    c.showPage()


def s6(c):
    base(c, GREEN)
    tag(c, 80, 940, "SEE IT LIVE", fg=GREEN)
    wrap(c, "Transcripts of a\nreal local run",
         80, 850, 920, "Helvetica-Bold", 68, WHITE, leading=84, align="center")
    rule(c, 700)
    wrap(c, "Real prompts.  Real completions.  Unfiltered.",
         80, 650, 920, "Helvetica", 30, MUTED, align="center")

    c.setFillColor(CARD)
    c.roundRect(80, 530, 920, 90, radius=14, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 24)
    c.setFillColor(GREEN)
    c.drawString(120, 588, "logs/")
    c.setFont("Helvetica", 22)
    c.setFillColor(BLUE)
    c.drawString(120, 553, "github.com/techaarvam/aarvam_lca/tree/main/logs")

    number(c, 6)
    c.showPage()


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    cv = canvas.Canvas(OUT, pagesize=(SLIDE_W, SLIDE_H))
    cv.setTitle("Local Coding Agent — Carousel")
    cv.setAuthor("techaarvam")
    for fn in (s1, s2, s3, s4, s5, s6):
        fn(cv)
    cv.save()
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    main()
