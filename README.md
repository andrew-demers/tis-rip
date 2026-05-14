# TIS Document Ripper

Downloads electrical wiring diagrams, collision/body repair manuals, and repair manuals from Toyota's TIS using a Selenium-controlled Chrome browser.

## Setup

**1. Install dependencies:**

```
pip install -r requirements.txt
```

**2. Initialize a Chrome profile** (run once, then close the window that opens):

```
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --user-data-dir=./user-data
```

No ChromeDriver download needed — Selenium 4 manages it automatically.

## Downloading manuals (rip.py)

```
./rip.py EM12345 RM12345 BM12345
```

- `EM` — Electrical Wiring Diagrams
- `RM` — Repair Manuals
- `BM` — Collision/Body Repair Manuals

The script opens Chrome, navigates to Toyota TIS, and prompts you to log in before continuing. Each manual downloads into its own directory named after the document ID.

**Two-pass workflow:** Run the script twice on the same arguments.

- First run downloads all HTML pages
- Second run generates PDFs from those HTML pages

### Finding document IDs

Search for your vehicle on TIS and look at the document URLs. The ID is the alphanumeric code in the URL (e.g. `RM41R0U`).

NOTE: Some older vehicles (e.g., 2008 Corolla) have body repair manuals starting with `BRM` that do not share the same document ID as the `RM` or `EM`.

### Output structure

```
RM41R0U/
  toc.xml         — table of contents from TIS
  index.html      — browsable HTML index
  html/           — individual HTML pages
  pdf/            — PDFs generated from HTML pages
```

Electrical diagrams are downloaded as PDFs directly for the `system`, `overall`, and `routing` categories.

## Building section PDFs (build.py)

After downloading HTML pages with `rip.py`, convert and combine them into per-section PDFs:

```
./build.py RM41R0U
```

Output: one PDF per top-level section, e.g.:
```
RM41R0U_General.pdf
RM41R0U_Preparation.pdf
RM41R0U_Engine_Mechanical.pdf
...
```

Each section PDF includes:
- A cover page with the section name and table of contents
- Dot leaders and page numbers for every entry
- Clickable TOC links that jump to the correct page
- A PDF outline (navigation panel in Preview, Acrobat, etc.)

Converted PDFs are cached in `RM41R0U/pdf/` — re-runs skip files that are already converted. Pages not yet downloaded are skipped gracefully; run `rip.py` again to fill gaps, then re-run `build.py`.

