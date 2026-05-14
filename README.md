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

## Workflow

### Step 1 — Download (rip.py)

```
./rip.py EM12345 RM12345 BM12345
```

- `EM` — Electrical Wiring Diagrams
- `RM` — Repair Manuals
- `BM` — Collision/Body Repair Manuals

The script opens Chrome, navigates to Toyota TIS, and prompts you to log in before continuing. Each manual is saved as HTML into its own directory named after the document ID. Run it again at any time to pick up pages that were missed.

### Step 2 — Build (build.py)

```
./build.py RM41R0U
```

Converts HTML pages to PDFs using headless Chrome and combines them into one PDF per top-level section:

```
RM41R0U_01_General.pdf
RM41R0U_02_Preparation.pdf
RM41R0U_03_Engine_Mechanical.pdf
...
```

Each section PDF includes:
- A cover page with the section name and table of contents
- Dot leaders and page numbers for every entry
- Clickable TOC links that jump to the correct page
- A PDF outline (navigation panel in Preview, Acrobat, etc.)

Converted PDFs are cached in `RM41R0U/pdf/` — re-runs only convert new files.

### Output structure

```
RM41R0U/
  toc.xml       — table of contents from TIS
  index.html    — browsable HTML index
  html/         — downloaded HTML pages
  pdf/          — per-page PDFs (cache used by build.py)
```

Electrical diagrams (`EM`) are downloaded directly as PDFs in `system`, `overall`, and `routing` subdirectories.

## Finding document IDs

Search for your vehicle on TIS and look at the document URLs. The ID is the alphanumeric code in the URL (e.g. `RM41R0U`).

NOTE: Some older vehicles (e.g., 2008 Corolla) have body repair manuals starting with `BRM` that do not share the same document ID as the `RM` or `EM`.
