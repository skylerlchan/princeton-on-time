#!/usr/bin/env python3
"""Build a designed .docx from a simple Markdown file, ready to become a Google Doc.

Usage:
    ~/.local/py/bin/python build_doc.py input.md [-o out.docx] [--style consulting|mla|apa|chicago]

Front matter (between --- lines at the top) sets the style and title data.
See ../SKILL.md for the full input format.
"""
import argparse
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

# --------------------------------------------------------------------------- themes

CONSULTING = {
    "navy": "051C2C",      # deep navy: titles, table headers
    "accent": "2251FF",    # one accent: labels, rules, callout bars
    "ink": "2B3640",       # body text (dark slate)
    "grey": "6B7885",      # secondary text, sources
    "rule": "D6DEE6",      # hairlines
    "tint": "F0F4F8",      # callout fill (panel)
    "zebra": "F7F9FB",     # alternate table rows
    "head_font": "Georgia",
    "body_font": "Arial",
    "body_pt": 11,
}

ACADEMIC_FONT = "Times New Roman"


def rgb(hex_):
    return RGBColor.from_string(hex_)


# --------------------------------------------------------------------------- xml helpers

def shade(cell_or_par, fill):
    """Background fill for a table cell or paragraph."""
    el = cell_or_par._tc if hasattr(cell_or_par, "_tc") else cell_or_par._p
    pr = el.get_or_add_tcPr() if hasattr(cell_or_par, "_tc") else el.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    pr.append(shd)


def cell_borders(cell, **edges):
    """edges: top/bottom/left/right = (size_eighths_pt, hex) or None for nil."""
    tcPr = cell._tc.get_or_add_tcPr()
    b = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        e = OxmlElement(f"w:{edge}")
        spec = edges.get(edge)
        if spec is None:
            e.set(qn("w:val"), "nil")
        else:
            e.set(qn("w:val"), "single")
            e.set(qn("w:sz"), str(spec[0]))
            e.set(qn("w:color"), spec[1])
            e.set(qn("w:space"), "0")
        b.append(e)
    tcPr.append(b)


def cell_margins(cell, top=80, bottom=80, left=120, right=120):
    tcPr = cell._tc.get_or_add_tcPr()
    m = OxmlElement("w:tcMar")
    for k, v in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
        e = OxmlElement(f"w:{k}")
        e.set(qn("w:w"), str(v))
        e.set(qn("w:type"), "dxa")
        m.append(e)
    tcPr.append(m)


def table_no_borders(table):
    tblPr = table._tbl.tblPr
    b = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), "nil")
        b.append(e)
    tblPr.append(b)


PBDR_SUCCESSORS = ("w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap",
                   "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi",
                   "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing",
                   "w:mirrorIndents", "w:suppressOverlap", "w:jc", "w:textDirection", "w:textAlignment",
                   "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr",
                   "w:pPrChange")


def par_rule(par, hex_, size=6, edge="bottom", space=4):
    """Paragraph border line, inserted in schema order so Google Docs keeps it."""
    pPr = par._p.get_or_add_pPr()
    b = pPr.find(qn("w:pBdr"))
    if b is None:
        b = OxmlElement("w:pBdr")
        pPr.insert_element_before(b, *PBDR_SUCCESSORS)
    e = OxmlElement(f"w:{edge}")
    e.set(qn("w:val"), "single")
    e.set(qn("w:sz"), str(size))
    e.set(qn("w:space"), str(space))
    e.set(qn("w:color"), hex_)
    b.append(e)


def par_bottom_rule(par, hex_, size=6):
    par_rule(par, hex_, size)


def add_field(par, instr, font=None, size=None, color=None):
    """Insert a Word field such as PAGE."""
    def run_with(child):
        r = OxmlElement("w:r")
        if font or size or color:
            rPr = OxmlElement("w:rPr")
            if font:
                f = OxmlElement("w:rFonts")
                for a in ("w:ascii", "w:hAnsi", "w:cs"):
                    f.set(qn(a), font)
                rPr.append(f)
            if color:
                c = OxmlElement("w:color")
                c.set(qn("w:val"), color)
                rPr.append(c)
            if size:
                s = OxmlElement("w:sz")
                s.set(qn("w:val"), str(int(size * 2)))
                rPr.append(s)
            r.append(rPr)
        r.append(child)
        par._p.append(r)

    b = OxmlElement("w:fldChar"); b.set(qn("w:fldCharType"), "begin"); run_with(b)
    t = OxmlElement("w:instrText"); t.set(qn("xml:space"), "preserve"); t.text = f" {instr} "; run_with(t)
    s = OxmlElement("w:fldChar"); s.set(qn("w:fldCharType"), "separate"); run_with(s)
    n = OxmlElement("w:t"); n.text = "1"; run_with(n)
    e = OxmlElement("w:fldChar"); e.set(qn("w:fldCharType"), "end"); run_with(e)


def keep_with_next(par):
    par.paragraph_format.keep_with_next = True


# --------------------------------------------------------------------------- inline markdown

# _italic_ only at word boundaries, so file names and URLs with underscores survive
INLINE = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*|(?<![A-Za-z0-9])_[^_\s][^_]*_(?![A-Za-z0-9])|`[^`]+`)")


def add_inline(par, text, font=None, size=None, color=None, bold=None, italic=None):
    for piece in INLINE.split(text):
        if not piece:
            continue
        b, i = bold, italic
        if piece.startswith("**") and piece.endswith("**"):
            piece, b = piece[2:-2], True
        elif (piece.startswith("*") and piece.endswith("*")) or (piece.startswith("_") and piece.endswith("_")):
            piece, i = piece[1:-1], True
        elif piece.startswith("`") and piece.endswith("`"):
            piece = piece[1:-1]
        r = par.add_run(piece)
        if font:
            r.font.name = font
        if size:
            r.font.size = Pt(size)
        if color:
            r.font.color.rgb = rgb(color)
        if b is not None:
            r.bold = b
        if i is not None:
            r.italic = i
    return par


# --------------------------------------------------------------------------- parsing

def parse(md_text):
    meta, body = {}, md_text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", md_text, re.S)
    if m:
        for line in m.group(1).splitlines():
            line = line.split(" #")[0].rstrip()
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip('"').strip("'")
        body = md_text[m.end():]

    blocks, lines, i = [], body.splitlines(), 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s:
            i += 1
            continue
        if s in ("\\pagebreak", "<pagebreak>", "---pagebreak---"):
            blocks.append(("pagebreak",)); i += 1; continue
        if s.startswith("#"):
            level = len(s) - len(s.lstrip("#"))
            blocks.append(("h", level, s[level:].strip())); i += 1; continue
        m = re.match(r"^>\s*\[!(\w+)\]\s*(.*)$", s)
        if m:  # callout: > [!kind] Title   then > lines
            kind, title, content = m.group(1).lower(), m.group(2), []
            i += 1
            while i < len(lines) and lines[i].strip().startswith(">"):
                content.append(lines[i].strip()[1:].strip()); i += 1
            blocks.append(("callout", kind, title, content)); continue
        if s.startswith(">"):
            content = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                content.append(lines[i].strip()[1:].strip()); i += 1
            blocks.append(("quote", " ".join(c for c in content if c))); continue
        m = re.match(r"^(Exhibit|Table|Figure|Fig\.):\s*(.*)$", s)
        if m:
            blocks.append(("caption", m.group(1), m.group(2))); i += 1; continue
        if re.match(r"^(Source|Sources|Note|Notes):", s):
            blocks.append(("source", s)); i += 1; continue
        m = re.match(r"^!\[(.*?)\]\((.*?)\)(\{width=([\d.]+)\})?$", s)
        if m:
            blocks.append(("image", m.group(1), m.group(2), float(m.group(4)) if m.group(4) else None)); i += 1; continue
        if s.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.match(r"^:?-{2,}:?$", c) for c in cells):
                    rows.append(cells)
                i += 1
            blocks.append(("table", rows)); continue
        if re.match(r"^([-*+]|\d+[.)])\s+", s):
            items = []
            while i < len(lines) and re.match(r"^\s*([-*+]|\d+[.)])\s+", lines[i]):
                raw = lines[i]
                indent = (len(raw) - len(raw.lstrip())) // 2
                ordered = bool(re.match(r"^\s*\d+[.)]", raw))
                items.append((indent, ordered, re.sub(r"^\s*([-*+]|\d+[.)])\s+", "", raw)))
                i += 1
            blocks.append(("list", items)); continue
        para = [s]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#|>|\||[-*+]\s|\d+[.)]\s|!\[|\\pagebreak|(Exhibit|Table|Figure|Fig\.|Source|Sources|Note|Notes):)", lines[i].strip()):
            para.append(lines[i].strip()); i += 1
        blocks.append(("p", " ".join(para)))
    return meta, blocks


# --------------------------------------------------------------------------- base renderer

class Renderer:
    font = ACADEMIC_FONT
    size = 12

    def __init__(self, meta):
        self.meta = meta
        self.doc = Document()
        self.exhibit_n = 0
        self.table_n = 0
        self.fig_n = 0
        sec = self.doc.sections[0]
        sec.page_width, sec.page_height = Inches(8.5), Inches(11)
        for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
            setattr(sec, side, Inches(1))
        sec.header_distance = Inches(0.5)
        sec.footer_distance = Inches(0.5)
        st = self.doc.styles["Normal"]
        st.font.name = self.font
        st.element.rPr.rFonts.set(qn("w:eastAsia"), self.font)
        st.font.size = Pt(self.size)

    def para(self, text="", **kw):
        p = self.doc.add_paragraph()
        if text:
            add_inline(p, text, **kw)
        return p

    def pagebreak(self):
        self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def render(self, blocks):
        self.front()
        pending_caption = None
        for b in blocks:
            kind = b[0]
            if kind == "caption":
                pending_caption = b
                continue
            if kind in ("table", "image"):
                getattr(self, kind)(*b[1:], caption=pending_caption)
                pending_caption = None
                continue
            if pending_caption:
                self.orphan_caption(pending_caption)
                pending_caption = None
            getattr(self, {"h": "heading", "p": "paragraph"}.get(kind, kind))(*b[1:])
        self.back()
        return self.doc

    def front(self): ...
    def back(self): ...

    def orphan_caption(self, cap):
        self.para(f"{cap[1]}: {cap[2]}", italic=True)

    def list(self, items):
        for indent, ordered, text in items:
            style = "List Number" if ordered else "List Bullet"
            if indent:
                style += f" {min(indent + 1, 3)}"
            p = self.doc.add_paragraph(style=style)
            add_inline(p, text, font=self.font, size=self.size)
            self.style_list_par(p)

    def style_list_par(self, p): ...

    def image(self, alt, path, width, caption=None):
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.add_run().add_picture(path, width=Inches(width or 6.5))
        return p


# --------------------------------------------------------------------------- consulting

class Consulting(Renderer):
    t = CONSULTING
    font = CONSULTING["body_font"]
    size = CONSULTING["body_pt"]

    def __init__(self, meta):
        super().__init__(meta)
        t = self.t
        st = self.doc.styles["Normal"]
        st.font.color.rgb = rgb(t["ink"])
        pf = st.paragraph_format
        pf.space_before, pf.space_after = Pt(0), Pt(8)
        pf.line_spacing = 1.15
        sec = self.doc.sections[0]
        sec.left_margin = sec.right_margin = Inches(1)
        sec.top_margin, sec.bottom_margin = Inches(0.9), Inches(0.9)

    # cover / title block
    def front(self):
        t, m = self.t, self.meta
        cover = m.get("cover", "auto")
        eyebrow = m.get("eyebrow") or m.get("kicker") or ""
        p = self.para()
        p.paragraph_format.space_after = Pt(4)
        if cover == "true":
            p.paragraph_format.space_before = Pt(150)
        if eyebrow:
            add_inline(p, eyebrow.upper(), font=t["body_font"], size=9, color=t["accent"], bold=True)
        p = self.para()
        add_inline(p, m.get("title", "Untitled"), font=t["head_font"], size=28 if cover == "true" else 24, color=t["navy"])
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.line_spacing = 1.05
        if m.get("subtitle"):
            p = self.para()
            add_inline(p, m["subtitle"], font=t["body_font"], size=13, color=t["grey"])
            p.paragraph_format.space_after = Pt(10)
        byline = " · ".join(x for x in (m.get("author"), m.get("org"), m.get("date")) if x)
        p = self.para()
        if byline:
            add_inline(p, byline, font=t["body_font"], size=9, color=t["grey"])
        par_bottom_rule(p, t["navy"], size=12)
        p.paragraph_format.space_after = Pt(18)
        if cover == "true":
            self.pagebreak()
        self.footer()

    def footer(self):
        t = self.t
        sec = self.doc.sections[0]
        fp = sec.footer.paragraphs[0]
        fp.text = ""
        label = self.meta.get("footer") or self.meta.get("title", "")
        add_inline(fp, label, font=t["body_font"], size=8, color=t["grey"])
        add_inline(fp, "   |   ", font=t["body_font"], size=8, color=t["rule"])
        add_field(fp, "PAGE", font=t["body_font"], size=8, color=t["grey"])
        fp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        par_rule(fp, t["rule"], size=4, edge="top", space=6)

    def heading(self, level, text):
        t = self.t
        p = self.para()
        pf = p.paragraph_format
        if level == 1:
            add_inline(p, text, font=t["head_font"], size=18, color=t["navy"])
            pf.space_before, pf.space_after = Pt(22), Pt(8)
            pf.line_spacing = 1.1
        elif level == 2:
            add_inline(p, text, font=t["body_font"], size=13, color=t["navy"], bold=True)
            pf.space_before, pf.space_after = Pt(14), Pt(4)
        else:
            add_inline(p, text.upper(), font=t["body_font"], size=9, color=t["accent"], bold=True)
            pf.space_before, pf.space_after = Pt(10), Pt(3)
        keep_with_next(p)

    def paragraph(self, text):
        self.para(text, font=self.font, size=self.size)

    def style_list_par(self, p):
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing = 1.2

    def quote(self, text):
        t = self.t
        p = self.para()
        add_inline(p, text, font=t["head_font"], size=14, color=t["navy"], italic=True)
        p.paragraph_format.left_indent = Inches(0.4)
        p.paragraph_format.space_before = p.paragraph_format.space_after = Pt(10)

    def callout(self, kind, title, content):
        t = self.t
        dark = kind in ("summary", "exec", "executive")
        fill = t["navy"] if dark else t["tint"]
        head_c = "FFFFFF" if dark else t["accent"]
        body_c = "FFFFFF" if dark else t["ink"]
        label = title or {"takeaway": "Key takeaway", "summary": "Executive summary", "note": "Note",
                          "action": "What to do", "todo": "Your turn", "question": "Question",
                          "draft": "Your draft", "answer": "My answer", "risk": "Risk"}.get(kind, kind.title())
        tbl = self.doc.add_table(rows=1, cols=1)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        table_no_borders(tbl)
        c = tbl.cell(0, 0)
        shade(c, fill)
        cell_borders(c, left=(36, t["accent"] if not dark else t["navy"]))
        cell_margins(c, top=160, bottom=160, left=240, right=240)
        p = c.paragraphs[0]
        add_inline(p, label.upper(), font=t["body_font"], size=8.5, color=head_c, bold=True)
        p.paragraph_format.space_after = Pt(4)
        bullet = re.compile(r"^([-*+]|\d+[.)])\s+")
        paras = [("b", bullet.sub("", ln)) if bullet.match(ln) else ("p", ln) for ln in content if ln]
        if not paras and kind in ("draft", "answer", "todo"):
            paras = [("p", " "), ("p", " "), ("p", " ")]
        for k, text in paras:
            q = c.add_paragraph()
            if k == "b":
                add_inline(q, "•  ", font=t["body_font"], size=self.size, color=head_c, bold=True)
                q.paragraph_format.left_indent = Inches(0.18)
                q.paragraph_format.first_line_indent = Inches(-0.18)
            add_inline(q, text, font=t["body_font"], size=self.size, color=body_c)
            q.paragraph_format.space_after = Pt(4)
        self.para().paragraph_format.space_after = Pt(4)

    def exhibit_header(self, caption):
        t = self.t
        if not caption:
            return
        word = caption[1]
        if word in ("Figure", "Fig."):
            word = "Exhibit"
        self.exhibit_n += 1
        p = self.para()
        add_inline(p, f"{word.upper()} {self.exhibit_n}", font=t["body_font"], size=8.5, color=t["accent"], bold=True)
        p.paragraph_format.space_before = Pt(12)
        p.paragraph_format.space_after = Pt(2)
        keep_with_next(p)
        p = self.para()
        add_inline(p, caption[2], font=t["body_font"], size=11, color=t["navy"], bold=True)
        p.paragraph_format.space_after = Pt(6)
        par_bottom_rule(p, t["navy"], size=8)
        keep_with_next(p)

    def table(self, rows, caption=None):
        t = self.t
        self.exhibit_header(caption)
        if not rows:
            return
        ncol = max(len(r) for r in rows)
        tbl = self.doc.add_table(rows=len(rows), cols=ncol)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        table_no_borders(tbl)
        numeric = re.compile(r"^[\s$€£+\-−(]*[\d.,]+[%x×)kKmMbB]*\s*$")
        for r_i, row in enumerate(rows):
            for c_i in range(ncol):
                text = row[c_i] if c_i < len(row) else ""
                cell = tbl.cell(r_i, c_i)
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                cell_margins(cell, top=70, bottom=70, left=110, right=110)
                p = cell.paragraphs[0]
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.line_spacing = 1.1
                if r_i == 0:
                    shade(cell, t["navy"])
                    add_inline(p, text, font=t["body_font"], size=9, color="FFFFFF", bold=True)
                    cell_borders(cell)
                else:
                    if r_i % 2 == 0:
                        shade(cell, t["zebra"])
                    add_inline(p, text, font=t["body_font"], size=9.5, color=t["ink"],
                               bold=True if c_i == 0 else None)
                    cell_borders(cell, bottom=(4, t["rule"]))
                if c_i > 0 and r_i > 0 and numeric.match(text or "x"):
                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                elif c_i > 0 and r_i == 0 and all(
                        numeric.match((rows[k][c_i] if c_i < len(rows[k]) else "") or "x") for k in range(1, len(rows))):
                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        self.para().paragraph_format.space_after = Pt(2)

    def image(self, alt, path, width, caption=None):
        self.exhibit_header(caption)
        p = super().image(alt, path, width)
        p.paragraph_format.space_after = Pt(4)

    def orphan_caption(self, cap):
        self.exhibit_header(cap)

    def source(self, text):
        t = self.t
        p = self.para()
        add_inline(p, text, font=t["body_font"], size=8, color=t["grey"])
        p.paragraph_format.space_after = Pt(14)


# --------------------------------------------------------------------------- academic base

class Academic(Renderer):
    font = ACADEMIC_FONT
    size = 12
    refs_title = "Works Cited"
    refs_bold = False

    def __init__(self, meta):
        super().__init__(meta)
        st = self.doc.styles["Normal"]
        st.font.color.rgb = RGBColor(0, 0, 0)
        pf = st.paragraph_format
        pf.space_before = pf.space_after = Pt(0)
        pf.line_spacing_rule = WD_LINE_SPACING.DOUBLE
        self.in_refs = False
        for name in ("List Bullet", "List Number", "List Bullet 2", "List Number 2"):
            s = self.doc.styles[name]
            s.font.name = self.font
            s.font.size = Pt(self.size)

    def running_head(self, text_before_page):
        hp = self.doc.sections[0].header.paragraphs[0]
        hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        if text_before_page:
            add_inline(hp, text_before_page + " ", font=self.font, size=self.size)
        add_field(hp, "PAGE", font=self.font, size=self.size)

    def body_par(self, text):
        p = self.para(text, font=self.font, size=self.size)
        p.paragraph_format.first_line_indent = Inches(0.5)
        return p

    def paragraph(self, text):
        if self.in_refs:
            p = self.para(text, font=self.font, size=self.size)
            p.paragraph_format.left_indent = Inches(0.5)
            p.paragraph_format.first_line_indent = Inches(-0.5)
            return
        self.body_par(text)

    def is_refs(self, text):
        return text.strip().lower() in ("works cited", "references", "bibliography", "work cited")

    def start_refs(self, text):
        self.in_refs = True
        self.pagebreak()
        p = self.para()
        add_inline(p, self.refs_title if text.lower() != "bibliography" else "Bibliography",
                   font=self.font, size=self.size, bold=self.refs_bold)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    def quote(self, text):  # block quote
        p = self.para(text, font=self.font, size=self.size)
        p.paragraph_format.left_indent = Inches(0.5)

    def callout(self, kind, title, content):  # academic: render as plain paragraphs
        if title:
            self.body_par(f"**{title}**")
        for line in content:
            if line:
                self.body_par(line)

    def source(self, text):
        p = self.para(text, font=self.font, size=self.size)

    def list(self, items):
        super().list(items)


class MLA(Academic):
    """MLA 9: TNR 12, double, 1in, 'Lastname N' header, 4-line heading, centered plain title."""

    def front(self):
        m = self.meta
        last = (m.get("author", "").split() or [""])[-1]
        self.running_head(m.get("running_head", last))
        for line in (m.get("author"), m.get("instructor"), m.get("course"), m.get("date")):
            if line:
                self.para(line, font=self.font, size=self.size)
        p = self.para(m.get("title", ""), font=self.font, size=self.size)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    def heading(self, level, text):
        if self.is_refs(text):
            return self.start_refs(text)
        p = self.para()
        add_inline(p, text, font=self.font, size=self.size, bold=level == 1, italic=level >= 2)
        keep_with_next(p)

    def table(self, rows, caption=None):
        self.table_n += 1
        p = self.para(f"Table {self.table_n}", font=self.font, size=self.size)
        keep_with_next(p)
        if caption:
            p = self.para(caption[2], font=self.font, size=self.size)
            keep_with_next(p)
        self.plain_table(rows)

    def plain_table(self, rows):
        if not rows:
            return
        ncol = max(len(r) for r in rows)
        tbl = self.doc.add_table(rows=len(rows), cols=ncol)
        tbl.style = self.doc.styles["Table Grid"]
        for r_i, row in enumerate(rows):
            for c_i in range(ncol):
                p = tbl.cell(r_i, c_i).paragraphs[0]
                p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.DOUBLE
                p.paragraph_format.space_after = Pt(0)
                add_inline(p, row[c_i] if c_i < len(row) else "", font=self.font, size=self.size)

    def image(self, alt, path, width, caption=None):
        super().image(alt, path, width)
        self.fig_n += 1
        text = caption[2] if caption else alt
        self.para(f"Fig. {self.fig_n}. {text}", font=self.font, size=self.size)


class APA(Academic):
    """APA 7 student paper: title page, page number top right, bold headings, References."""
    refs_title = "References"
    refs_bold = True

    def front(self):
        m = self.meta
        self.running_head(m.get("running_head", "").upper() if m.get("professional") == "true" else "")
        for _ in range(3):
            self.para()
        p = self.para()
        add_inline(p, m.get("title", ""), font=self.font, size=self.size, bold=True)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self.para()
        for line in (m.get("author"), m.get("affiliation"), m.get("course"), m.get("instructor"), m.get("date")):
            if line:
                q = self.para(line, font=self.font, size=self.size)
                q.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self.pagebreak()
        p = self.para()
        add_inline(p, m.get("title", ""), font=self.font, size=self.size, bold=True)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    def heading(self, level, text):
        if self.is_refs(text):
            return self.start_refs(text)
        p = self.para()
        if level == 1:
            add_inline(p, text, font=self.font, size=self.size, bold=True)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif level == 2:
            add_inline(p, text, font=self.font, size=self.size, bold=True)
        else:
            add_inline(p, text, font=self.font, size=self.size, bold=True, italic=True)
        keep_with_next(p)

    def table(self, rows, caption=None):
        self.table_n += 1
        p = self.para(); add_inline(p, f"Table {self.table_n}", font=self.font, size=self.size, bold=True)
        keep_with_next(p)
        p = self.para(); add_inline(p, caption[2] if caption else "", font=self.font, size=self.size, italic=True)
        keep_with_next(p)
        self.rules_table(rows)

    def rules_table(self, rows):
        """APA table: rules above and below the header row and at the bottom, no verticals."""
        if not rows:
            return
        ncol = max(len(r) for r in rows)
        tbl = self.doc.add_table(rows=len(rows), cols=ncol)
        table_no_borders(tbl)
        last = len(rows) - 1
        for r_i, row in enumerate(rows):
            for c_i in range(ncol):
                cell = tbl.cell(r_i, c_i)
                edges = {}
                if r_i == 0:
                    edges = {"top": (8, "000000"), "bottom": (8, "000000")}
                if r_i == last:
                    edges["bottom"] = (8, "000000")
                cell_borders(cell, **edges)
                cell.paragraphs[0].paragraph_format.line_spacing_rule = WD_LINE_SPACING.DOUBLE
                cell.paragraphs[0].paragraph_format.space_after = Pt(0)
                add_inline(cell.paragraphs[0], row[c_i] if c_i < len(row) else "", font=self.font, size=self.size)

    def image(self, alt, path, width, caption=None):
        self.fig_n += 1
        p = self.para(); add_inline(p, f"Figure {self.fig_n}", font=self.font, size=self.size, bold=True)
        keep_with_next(p)
        p = self.para(); add_inline(p, caption[2] if caption else alt, font=self.font, size=self.size, italic=True)
        keep_with_next(p)
        Renderer.image(self, alt, path, width)


class Chicago(Academic):
    """Chicago notes-bibliography student paper: title page, page numbers, Bibliography."""
    refs_title = "Bibliography"

    def front(self):
        m = self.meta
        self.running_head("")
        for _ in range(8):
            self.para()
        p = self.para(m.get("title", ""), font=self.font, size=self.size)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if m.get("subtitle"):
            q = self.para(m["subtitle"], font=self.font, size=self.size)
            q.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for _ in range(6):
            self.para()
        for line in (m.get("author"), m.get("course"), m.get("instructor"), m.get("date")):
            if line:
                q = self.para(line, font=self.font, size=self.size)
                q.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self.pagebreak()

    def heading(self, level, text):
        if self.is_refs(text):
            return self.start_refs(text)
        p = self.para()
        add_inline(p, text, font=self.font, size=self.size, bold=level == 1, italic=level >= 2)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER if level == 1 else WD_ALIGN_PARAGRAPH.LEFT
        keep_with_next(p)

    def paragraph(self, text):
        if self.in_refs:  # single-spaced entries, blank line between, hanging indent
            p = self.para(text, font=self.font, size=self.size)
            p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
            p.paragraph_format.space_after = Pt(12)
            p.paragraph_format.left_indent = Inches(0.5)
            p.paragraph_format.first_line_indent = Inches(-0.5)
            return
        self.body_par(text)

    table = APA.table
    rules_table = APA.rules_table
    image = MLA.image


STYLES = {"consulting": Consulting, "mla": MLA, "apa": APA, "chicago": Chicago}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("-o", "--output")
    ap.add_argument("--style", choices=STYLES)
    a = ap.parse_args()
    src = Path(a.input)
    meta, blocks = parse(src.read_text())
    style = (a.style or meta.get("style", "consulting")).lower()
    if style not in STYLES:
        sys.exit(f"unknown style {style!r}; use one of {', '.join(STYLES)}")
    # resolve image paths relative to the input file
    blocks = [(b[0], b[1], str((src.parent / b[2]).resolve()), b[3]) if b[0] == "image" else b for b in blocks]
    doc = STYLES[style](meta).render(blocks)
    doc.core_properties.title = meta.get("title", "")
    doc.core_properties.author = meta.get("author", "")
    out = Path(a.output) if a.output else src.with_suffix(".docx")
    doc.save(out)
    print(out)


if __name__ == "__main__":
    main()
