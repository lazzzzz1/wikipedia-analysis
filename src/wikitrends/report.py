"""One-page PDF report builder.

Uses reportlab, which is pure Python with no system graphics libraries
(no cairo/pango, unlike e.g. WeasyPrint) -- that keeps the skill
reproducible across arbitrary agent sandboxes where such system packages
usually aren't installed and can't be assumed.

reportlab's built-in fonts (Helvetica etc.) only cover Latin-1 -- they
render Cyrillic (e.g. Ukrainian article titles) as solid black boxes and
mangle Czech/Polish diacritics. Since comparing across language editions is
the whole point of this skill, a Unicode TTF font is registered and used
for every piece of text instead. Rather than bundling a font file of our
own, this reuses the DejaVu Sans copy matplotlib already ships (matplotlib
is a hard dependency for charting anyway), which covers Latin Extended and
Cyrillic -- so both the exact example topics in this task (Polish, Czech,
Ukrainian) render correctly with no extra file to maintain.
"""
from __future__ import annotations

import datetime as dt
import os
import re
from xml.sax.saxutils import escape

import matplotlib

from .chart import display_label
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, ListFlowable, ListItem, KeepInFrame,
)

_FONT_REGULAR = "Unicode"
_FONT_BOLD = "Unicode-Bold"
_fonts_registered = False


def _ensure_unicode_fonts_registered() -> None:
    global _fonts_registered
    if _fonts_registered:
        return
    ttf_dir = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
    pdfmetrics.registerFont(TTFont(_FONT_REGULAR, os.path.join(ttf_dir, "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont(_FONT_BOLD, os.path.join(ttf_dir, "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFontFamily(_FONT_REGULAR, normal=_FONT_REGULAR, bold=_FONT_BOLD)
    _fonts_registered = True

DEFAULT_LIMITATIONS = [
    "Wikipedia pageviews measure reading interest, not willingness to pay or convert -- "
    "treat this as a directional signal, not demand validation.",
    "Data covers 'user' traffic only (bots/spiders excluded) from the Wikimedia Pageviews "
    "API, available from 2015-07 onward.",
    "Different language editions have very different audience sizes and growth rates; "
    "where shown, 'share of edition traffic' controls for this better than raw views.",
    "Short spikes (news events, social media mentions) can distort raw counts; the trend "
    "line uses a spike-resistant estimator, and detected spikes are flagged separately.",
]

# Fixed report text per language; the agent's own findings/recommendations
# are passed in already written in the user's language.
STRINGS = {
    "en": {
        "title": "Wikipedia interest", "generated": "generated", "source": "Source: Wikimedia Pageviews API + Wikidata.",
        "header": ["Edition / article", "Views/day", "Raw /yr", "Share /yr", "Confidence", "Direction"],
        "findings": "Findings", "recommendations": "Recommendations",
        "limitations": "Assumptions &amp; limitations", "limitations_list": DEFAULT_LIMITATIONS,
        "values": {},
    },
    "uk": {
        "title": "Інтерес у Wikipedia", "generated": "створено", "source": "Джерело: Wikimedia Pageviews API + Wikidata.",
        "header": ["Розділ / стаття", "Перегл. /день", "Зміна /рік", "Частка /рік", "Довіра", "Напрям"],
        "findings": "Висновки", "recommendations": "Рекомендації",
        "limitations": "Припущення та обмеження",
        "limitations_list": [
            "Перегляди Wikipedia показують інтерес до читання, а не готовність платити -- "
            "це сигнал напряму, а не підтвердження попиту.",
            "Враховано лише трафік користувачів (боти виключені) з Wikimedia Pageviews API; "
            "дані доступні з 2015-07.",
            "Мовні розділи дуже різні за розміром і динамікою; стовпець «Частка /рік» "
            "(частка в трафіку розділу) враховує це краще, ніж сирі перегляди.",
            "Короткі сплески (новини, соцмережі) спотворюють сирі числа; лінія тренду стійка "
            "до сплесків, а самі сплески позначено окремо.",
        ],
        "values": {"high": "висока", "medium": "середня", "low": "низька", "growing": "зростає",
                   "declining": "спадає", "flat": "стабільно", "insufficient_data": "мало даних"},
    },
}


def _inline_markup(text: str) -> str:
    """Escape agent text for reportlab, rendering only **bold**."""
    return re.sub(r"\*\*(.+?)\*\*", rf"<font name='{_FONT_BOLD}'>\1</font>", escape(text))


def build_report(
    out_path: str,
    title: str,
    date_range: str,
    rows: list[dict],
    chart_paths: list[str],
    findings: str,
    recommendations: str,
    extra_limitations: list[str] | None = None,
    lang: str = "en",
) -> str:
    _ensure_unicode_fonts_registered()
    t = STRINGS[lang]
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontName=_FONT_BOLD, fontSize=16, spaceAfter=4)
    meta = ParagraphStyle("meta", parent=styles["Normal"], fontName=_FONT_REGULAR, fontSize=9, textColor=colors.grey)
    body = ParagraphStyle("body", parent=styles["Normal"], fontName=_FONT_REGULAR, fontSize=9.5, leading=13)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName=_FONT_BOLD, fontSize=11, spaceBefore=8, spaceAfter=4)
    small = ParagraphStyle("small", parent=styles["Normal"], fontName=_FONT_REGULAR, fontSize=8, leading=11, textColor=colors.grey)

    doc = SimpleDocTemplate(
        out_path, pagesize=A4,
        topMargin=1.5 * cm, bottomMargin=1.3 * cm, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
    )
    story = [
        Paragraph(escape(display_label(title)), h1),
        Paragraph(
            f"{date_range.replace(' to ', ' – ')} &middot; {t['generated']} {dt.datetime.now():%Y-%m-%d %H:%M} &middot; {t['source']}",
            meta,
        ),
        Spacer(1, 8),
    ]

    cell = ParagraphStyle("cell", parent=styles["Normal"], fontName=_FONT_REGULAR, fontSize=8.5, leading=10.5)
    head_cell = ParagraphStyle("head_cell", parent=cell, fontName=_FONT_BOLD, textColor=colors.white)

    if rows:
        header = [Paragraph(h, head_cell) for h in t["header"]]
        data = [header]
        for r in rows:
            trend = r.get("pct_change_per_year")
            trend_s = f"{trend:+.0f}%" if trend is not None else "n/a"
            share = r.get("share_pct_change_per_year")
            share_s = f"{share:+.0f}%" if share is not None else "n/a"
            # "Confidence" is for the raw trend; flag the share's own tier
            # when it differs, or a -5% share next to "high" reads as certain.
            share_conf = r.get("share_confidence")
            if share is not None and share_conf and share_conf != r.get("confidence"):
                share_s += f" ({t['values'].get(share_conf, share_conf)})"
            # Paragraph, so long titles wrap instead of overflowing the cell.
            data.append([
                Paragraph(escape(display_label(r.get("label", ""))), cell), f"{r.get('median_daily_views', 0):,.0f}",
                trend_s, share_s, t["values"].get(r.get("confidence", ""), r.get("confidence", "")),
                t["values"].get(r.get("direction", ""), r.get("direction", "")),
            ])
        table = Table(data, colWidths=[5.4 * cm, 1.9 * cm, 2.5 * cm, 2.7 * cm, 2.2 * cm, 2.3 * cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
            ("FONTNAME", (0, 1), (-1, -1), _FONT_REGULAR),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f7")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(table)
        story.append(Spacer(1, 10))

    for path in chart_paths:
        story.append(Image(path, width=17 * cm, height=17 * cm * 4.2 / 8))
        story.append(Spacer(1, 6))

    if findings:
        story.append(Paragraph(t["findings"], h2))
        story.append(Paragraph(_inline_markup(findings), body))
    if recommendations:
        story.append(Paragraph(t["recommendations"], h2))
        story.append(Paragraph(_inline_markup(recommendations), body))

    story.append(Paragraph(t["limitations"], h2))
    limitations = t["limitations_list"] + (extra_limitations or [])
    story.append(ListFlowable(
        [ListItem(Paragraph(escape(item), small)) for item in limitations],
        bulletType="bullet", leftIndent=10, bulletFontName=_FONT_REGULAR,
    ))

    # The report is promised to be one page: scale everything down to fit
    # rather than spill a few lines onto a second page.
    doc.build([KeepInFrame(doc.width, doc.height, story, mode="shrink")])
    return out_path
