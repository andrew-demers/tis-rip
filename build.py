#!/usr/bin/env python3
"""
Convert HTML pages from a downloaded Toyota TIS manual to PDFs.
Creates one combined PDF per top-level section (e.g. General, Preparation, Engine).

Converted PDFs are cached in <manual_dir>/pdf/ so re-runs skip already-converted files.

Usage: ./build.py <manual_dir>
Output: <manual_dir>_output/<N>_<SectionName>.pdf for each section
"""

import sys
import os
import re
import subprocess
import xml.etree.ElementTree as ET
import io
from pypdf import PdfWriter, PdfReader
from pypdf.annotations import Link
from pypdf.generic import Fit
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas as rl_canvas


CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PAGE_W, PAGE_H = letter
EWD_SYSTEMS = ["system", "routing", "overall"]
EWD_TYPES_ORDERED = ["intro", "system", "routing", "relay", "fuselist", "connlist"]
EWD_TYPE_DISPLAY = {
    "intro":     "Introduction",
    "system":    "System Circuit",
    "routing":   "Location and Routing",
    "relay":     "Relay Location",
    "fuselist":  "Fuse List",
    "connlist":  "Connector List",
}
MARGIN = 54
LINE_H = 14
FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
PG_COL_W = 36


def mkfilename(s):
    fn = ""
    for x in s:
        if x.isalnum() or x == " ":
            fn += x
        else:
            fn += "_"
    return fn


def is_ewd(manual_dir):
    if os.path.exists(os.path.join(manual_dir, "termdata.xml")):
        return True
    return any(
        os.path.exists(os.path.join(manual_dir, s, "index.xml"))
        for s in EWD_SYSTEMS
    )


def get_basename(href):
    return os.path.splitext(os.path.basename(href))[0]


def collect_items(node, depth=0, result=None):
    if result is None:
        result = []
    for item in node.findall("item"):
        name_el = item.find("name")
        name = (name_el.text or "").strip() if name_el is not None else ""
        href = item.get("href", "")
        result.append((name, href, depth))
        collect_items(item, depth + 1, result)
    return result


def sanitize_filename(name):
    safe = re.sub(r"[^\w\s-]", "", name).strip()
    return re.sub(r"\s+", "_", safe)


def html_to_pdf(html_path, pdf_path):
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Suppress Chrome's print header/footer by zeroing the @page margins,
    # then restore content padding so text doesn't run to the edge.
    css = "<style>@page{margin:16px 0 16px 0}body{padding:12px}</style>"
    if "</head>" in html:
        html = html.replace("</head>", css + "</head>", 1)
    else:
        html = css + html

    tmp_path = html_path + ".tmp.html"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(html)

    try:
        subprocess.run(
            [
                CHROME,
                "--print-to-pdf=" + os.path.abspath(pdf_path),
                "--print-to-pdf-no-header",
                "--no-gpu",
                "--headless",
                "file://" + os.path.abspath(tmp_path),
            ],
            capture_output=True,
        )
    finally:
        os.remove(tmp_path)


def render_toc(section_name, toc_items, href_to_final_page):
    """
    Render a TOC as a PDF.
    Returns (pdf_bytes, link_list) where link_list is
    [(toc_page_idx, rect, dest_page), ...].
    """
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=letter)
    links = []
    page_idx = 0
    y = PAGE_H - MARGIN

    c.setFont(FONT_BOLD, 16)
    c.drawString(MARGIN, y, section_name)
    y -= LINE_H * 1.5
    c.setFont(FONT_BOLD, 11)
    c.drawString(MARGIN, y, "Table of Contents")
    y -= LINE_H * 2
    c.setFont(FONT, 9)

    for name, href, depth in toc_items:
        if y < MARGIN + LINE_H:
            c.showPage()
            page_idx += 1
            y = PAGE_H - MARGIN
            c.setFont(FONT, 9)

        indent = depth * 12
        x = MARGIN + indent
        name_max_w = PAGE_W - MARGIN - x - PG_COL_W

        display = name
        while display and c.stringWidth(display, FONT, 9) > name_max_w:
            display = display[:-1]
        if display != name:
            display = display[:-1] + "…"

        c.drawString(x, y, display)

        dest_page = href_to_final_page.get(href) if href else None
        if dest_page is not None:
            pg_str = str(dest_page + 1)
            c.drawRightString(PAGE_W - MARGIN, y, pg_str)

            name_end = x + c.stringWidth(display, FONT, 9) + 4
            dots_end = PAGE_W - MARGIN - PG_COL_W
            dot_x = name_end
            while dot_x + 5 < dots_end:
                c.drawString(dot_x, y, ".")
                dot_x += 5

            text_w = c.stringWidth(display, FONT, 9)
            links.append((page_idx, (x, y - 2, x + text_w, y + 10), dest_page))

        y -= LINE_H

    c.save()
    return buf.getvalue(), links


def build_section(section_name, toc_items, html_dir, pdf_dir, output_path):
    seen = set()
    unique_hrefs = []
    for _, href, _ in toc_items:
        if href and href not in seen:
            seen.add(href)
            unique_hrefs.append(href)

    if not unique_hrefs:
        print(f"  Skipping — no pages")
        return False

    total = len(unique_hrefs)
    content_writer = PdfWriter()
    href_to_content_page = {}
    content_page = 0
    converted = 0
    cached = 0
    missing = 0

    for n, href in enumerate(unique_hrefs, 1):
        base = get_basename(href)
        html_path = os.path.join(html_dir, base + ".html")
        pdf_path = os.path.join(pdf_dir, base + ".pdf")

        if not os.path.exists(html_path):
            missing += 1
            continue

        if not os.path.exists(pdf_path):
            print(f"  [{n}/{total}] Converting {base}.html ...")
            html_to_pdf(html_path, pdf_path)
            if not os.path.exists(pdf_path):
                print(f"  Warning: conversion failed for {base}.html")
                missing += 1
                continue
            converted += 1
        else:
            cached += 1

        try:
            reader = PdfReader(pdf_path)
            href_to_content_page[href] = content_page
            for page in reader.pages:
                content_writer.add_page(page)
            content_page += len(reader.pages)
        except Exception as e:
            print(f"  Warning: could not read {pdf_path}: {e}")
            missing += 1

    if not href_to_content_page:
        print(f"  Skipping — no PDFs available")
        return False

    print(f"  {converted} converted, {cached} cached, {missing} missing — {content_page} pages")

    try:
        # Draft TOC to measure its page count
        draft_bytes, _ = render_toc(section_name, toc_items, {})
        toc_page_count = len(PdfReader(io.BytesIO(draft_bytes)).pages)

        href_to_final_page = {
            href: toc_page_count + p
            for href, p in href_to_content_page.items()
        }

        toc_bytes, link_list = render_toc(section_name, toc_items, href_to_final_page)

        final_writer = PdfWriter()

        for page in PdfReader(io.BytesIO(toc_bytes)).pages:
            final_writer.add_page(page)

        content_buf = io.BytesIO()
        content_writer.write(content_buf)
        content_buf.seek(0)
        for page in PdfReader(content_buf).pages:
            final_writer.add_page(page)

        for toc_page_idx, rect, dest_page in link_list:
            annotation = Link(
                rect=rect,
                target_page_index=dest_page,
                fit=Fit.fit(),
            )
            final_writer.add_annotation(page_number=toc_page_idx, annotation=annotation)

        outline_stack = {}
        for name, href, depth in toc_items:
            dest_page = href_to_final_page.get(href) if href else None
            if dest_page is None:
                continue
            parent = outline_stack.get(depth - 1)
            ref = final_writer.add_outline_item(name, dest_page, parent=parent)
            outline_stack[depth] = ref

        with open(output_path, "wb") as f:
            final_writer.write(f)

        print(f"  Saved: {output_path}")
        return True

    except Exception as e:
        print(f"  ERROR combining section '{section_name}': {e}")
        import traceback
        traceback.print_exc()
        return False


def _build_ewd_section_new(section_name, toc_items, pdf_dir, output_path):
    content_writer = PdfWriter()
    href_to_content_page = {}
    content_page = 0
    missing = 0

    for name, fn, _ in toc_items:
        pdf_path = os.path.join(pdf_dir, fn)
        if not os.path.exists(pdf_path):
            print(f"  Missing: {fn}")
            missing += 1
            continue
        try:
            reader = PdfReader(pdf_path)
            href_to_content_page[fn] = content_page
            for page in reader.pages:
                content_writer.add_page(page)
            content_page += len(reader.pages)
        except Exception as e:
            print(f"  Warning: could not read {fn}: {e}")
            missing += 1

    if not href_to_content_page:
        print("  Skipping — no PDFs available")
        return False

    print(f"  {len(href_to_content_page)} diagrams, {missing} missing — {content_page} pages")

    try:
        draft_bytes, _ = render_toc(section_name, toc_items, {})
        toc_page_count = len(PdfReader(io.BytesIO(draft_bytes)).pages)
        href_to_final_page = {href: toc_page_count + p for href, p in href_to_content_page.items()}
        toc_bytes, link_list = render_toc(section_name, toc_items, href_to_final_page)

        final_writer = PdfWriter()
        for page in PdfReader(io.BytesIO(toc_bytes)).pages:
            final_writer.add_page(page)

        content_buf = io.BytesIO()
        content_writer.write(content_buf)
        content_buf.seek(0)
        for page in PdfReader(content_buf).pages:
            final_writer.add_page(page)

        for toc_page_idx, rect, dest_page in link_list:
            final_writer.add_annotation(
                page_number=toc_page_idx,
                annotation=Link(rect=rect, target_page_index=dest_page, fit=Fit.fit()),
            )

        for name, href, _ in toc_items:
            dest_page = href_to_final_page.get(href)
            if dest_page is not None:
                final_writer.add_outline_item(name, dest_page)

        with open(output_path, "wb") as f:
            final_writer.write(f)

        print(f"  Saved: {output_path}")
        return True

    except Exception as e:
        print(f"  ERROR combining section '{section_name}': {e}")
        import traceback
        traceback.print_exc()
        return False


def build_ewd_section(section_name, index_path, pdf_dir, output_path):
    tree = ET.parse(index_path)
    root = tree.getroot()

    items = []
    for child in root:
        name_els = child.findall("name")
        fig_els = child.findall("fig")
        if not name_els or not fig_els:
            continue
        name = (name_els[0].text or "").strip()
        fig = (fig_els[0].text or "").strip()
        items.append((name, fig))

    if not items:
        print("  Skipping — no diagrams found")
        return False

    toc_items = [(name, mkfilename(fig + " " + name) + ".pdf", 0) for name, fig in items]

    content_writer = PdfWriter()
    href_to_content_page = {}
    content_page = 0
    missing = 0

    for name, fig in items:
        fn = mkfilename(fig + " " + name) + ".pdf"
        pdf_path = os.path.join(pdf_dir, fn)
        if not os.path.exists(pdf_path):
            print(f"  Missing: {fn}")
            missing += 1
            continue
        try:
            reader = PdfReader(pdf_path)
            href_to_content_page[fn] = content_page
            for page in reader.pages:
                content_writer.add_page(page)
            content_page += len(reader.pages)
        except Exception as e:
            print(f"  Warning: could not read {fn}: {e}")
            missing += 1

    if not href_to_content_page:
        print("  Skipping — no PDFs available")
        return False

    print(f"  {len(href_to_content_page)} diagrams, {missing} missing — {content_page} pages")

    try:
        draft_bytes, _ = render_toc(section_name, toc_items, {})
        toc_page_count = len(PdfReader(io.BytesIO(draft_bytes)).pages)

        href_to_final_page = {href: toc_page_count + p for href, p in href_to_content_page.items()}
        toc_bytes, link_list = render_toc(section_name, toc_items, href_to_final_page)

        final_writer = PdfWriter()

        for page in PdfReader(io.BytesIO(toc_bytes)).pages:
            final_writer.add_page(page)

        content_buf = io.BytesIO()
        content_writer.write(content_buf)
        content_buf.seek(0)
        for page in PdfReader(content_buf).pages:
            final_writer.add_page(page)

        for toc_page_idx, rect, dest_page in link_list:
            final_writer.add_annotation(
                page_number=toc_page_idx,
                annotation=Link(rect=rect, target_page_index=dest_page, fit=Fit.fit()),
            )

        for name, href, _ in toc_items:
            dest_page = href_to_final_page.get(href)
            if dest_page is not None:
                final_writer.add_outline_item(name, dest_page)

        with open(output_path, "wb") as f:
            final_writer.write(f)

        print(f"  Saved: {output_path}")
        return True

    except Exception as e:
        print(f"  ERROR combining section '{section_name}': {e}")
        import traceback
        traceback.print_exc()
        return False


def _build_ewd_new(manual_dir, root, output_dir):
    seen = set()
    sections = {t: [] for t in EWD_TYPES_ORDERED}

    for para in root.findall('paradata'):
        linkkey = para.get('linkkey', '')
        parts = dict(kv.split('=', 1) for kv in linkkey.rstrip(';').split(';') if '=' in kv)
        ewd_type = parts.get('ewd_type', '')
        ewd_code = parts.get('ewd', '')
        if not ewd_type or not ewd_code or (ewd_type, ewd_code) in seen:
            continue
        seen.add((ewd_type, ewd_code))
        name = (para.text or '').strip().split(';')[0]
        if ewd_type in sections:
            sections[ewd_type].append((name, ewd_code + ".pdf", 0))

    present = [t for t in EWD_TYPES_ORDERED if sections[t]]
    total = len(present)

    for i, ewd_type in enumerate(present, 1):
        toc_items = sections[ewd_type]
        section_name = EWD_TYPE_DISPLAY.get(ewd_type, ewd_type.capitalize())
        pdf_dir = os.path.join(manual_dir, ewd_type)
        output_path = os.path.join(output_dir, f"{i:02d}_{ewd_type}.pdf")

        print(f"\n[{i}/{total}] {section_name} ({len(toc_items)} diagrams)")

        if not os.path.isdir(pdf_dir):
            print(f"  Directory {pdf_dir} not found, skipping")
            continue

        _build_ewd_section_new(section_name, toc_items, pdf_dir, output_path)


def build_ewd(manual_dir):
    output_dir = manual_dir.rstrip("/") + "_output"
    os.makedirs(output_dir, exist_ok=True)

    termdata_path = os.path.join(manual_dir, "termdata.xml")
    if os.path.exists(termdata_path):
        tree = ET.parse(termdata_path)
        root = tree.getroot()
        if root.get('legacy') != 'yes':
            _build_ewd_new(manual_dir, root, output_dir)
            return

    total = len(EWD_SYSTEMS)
    for i, s in enumerate(EWD_SYSTEMS, 1):
        index_path = os.path.join(manual_dir, s, "index.xml")
        print(f"\n[{i}/{total}] {s}")
        if not os.path.exists(index_path):
            print("  index.xml not found, skipping")
            continue
        output_path = os.path.join(output_dir, f"{i:02d}_{s}.pdf")
        build_ewd_section(s.capitalize(), index_path, os.path.join(manual_dir, s), output_path)


def main():
    if len(sys.argv) < 2:
        print("Usage: ./build.py <manual_dir>")
        sys.exit(1)

    manual_dir = sys.argv[1].rstrip("/")

    if is_ewd(manual_dir):
        build_ewd(manual_dir)
        return

    toc_path = os.path.join(manual_dir, "toc.xml")
    html_dir = os.path.join(manual_dir, "html")
    pdf_dir = os.path.join(manual_dir, "pdf")

    if not os.path.exists(toc_path):
        print(f"Error: {toc_path} not found")
        sys.exit(1)
    if not os.path.isdir(html_dir):
        print(f"Error: {html_dir} not found — run rip.py first")
        sys.exit(1)

    os.makedirs(pdf_dir, exist_ok=True)

    output_dir = manual_dir.rstrip("/") + "_output"
    os.makedirs(output_dir, exist_ok=True)

    tree = ET.parse(toc_path)
    root = tree.getroot()

    # Group top-level items by section name, preserving order.
    # Older manuals repeat the same section name across many top-level items
    # (e.g. 105 "General" entries) — these get merged into one PDF.
    section_order = []
    section_items = {}
    for section in root.findall("item"):
        name_el = section.find("name")
        section_name = (name_el.text or "Section").strip() if name_el is not None else "Section"
        if section_name not in section_items:
            section_order.append(section_name)
            section_items[section_name] = []
        collect_items(section, depth=0, result=section_items[section_name])

    print(f"Found {len(section_order)} sections")

    for i, section_name in enumerate(section_order, 1):
        safe_name = sanitize_filename(section_name)
        output_path = os.path.join(output_dir, f"{i:02d}_{safe_name}.pdf")

        print(f"\n[{i}/{len(section_order)}] {section_name}")

        build_section(section_name, section_items[section_name], html_dir, pdf_dir, output_path)


if __name__ == "__main__":
    main()
