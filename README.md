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

## Combining into a single PDF (combine.py)

After downloading, combine all PDFs into one file with a linked table of contents:

```
./combine.py RM41R0U
```

Output: `RM41R0U_combined.pdf`

The combined PDF includes:
- A table of contents at the front with dot leaders and page numbers
- Clickable links on every TOC entry that jump to the correct page
- A PDF outline (navigation panel in Preview, Acrobat, etc.)

Pages not yet downloaded are skipped gracefully. Run `rip.py` again to fill in any gaps, then re-run `combine.py`.
