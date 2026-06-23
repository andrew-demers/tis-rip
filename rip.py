#!/usr/bin/env python3
from selenium import webdriver
import time
import os.path
import xml.etree.ElementTree as ET
import shutil
from bs4 import BeautifulSoup
import os
import sys
import re
import base64
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def mkfilename(s):
    fn = ""
    for x in s:
        if x.isalnum() or x == " ":
            fn += x
        else:
            fn += "_"
    return fn

def fix_links(fn):
    modified = False
    doc = open(fn, 'r').read()
    soup = BeautifulSoup(doc, 'lxml')
    for link in soup.find_all("a"):
        href = link.get('href')
        if href is None:
            continue
        
        if '?' in href:
            href = href.split('?')[0]
        
        if not href.startswith('/t3Portal/document'):
            continue
        
        new_path = os.path.basename(href)
        if href != new_path:
            link['href'] = new_path
            modified = True
    
    if modified:
        print("Writing ", fn)
        with open(fn, 'w') as fh:
            fh.write(soup.prettify())

def _ewd_download_pdf(driver, url, dest_path):
    """Download an EWD PDF. Tries requests first; falls back to Chrome download."""
    # -- fast path: requests with session cookies --
    try:
        cookies = {c['name']: c['value'] for c in driver.get_cookies()}
        r = requests.get(url, cookies=cookies, headers={
            'Referer': 'https://techinfo.toyota.com/t3Portal/ewdappu/index.jsp',
            'User-Agent': driver.execute_script("return navigator.userAgent"),
            'Accept': 'application/pdf,*/*',
        }, verify=False, timeout=60)
        if r.status_code == 200 and r.content[:4] == b'%PDF':
            with open(dest_path, 'wb') as f:
                f.write(r.content)
            return True
        # Diagnostic so we know what went wrong
        if r.status_code != 200:
            print(f"    requests HTTP {r.status_code}, trying Chrome download...")
        else:
            print(f"    requests got non-PDF ({r.content[:30]!r}), trying Chrome download...")
    except Exception as e:
        print(f"    requests error ({e}), trying Chrome download...")

    # -- fallback: let Chrome download the file --
    # Clear the download dir so we can detect any new file unambiguously.
    for f in os.listdir("download"):
        try:
            os.remove(os.path.join("download", f))
        except OSError:
            pass

    driver.get(url)

    # Wait up to 20 s for Chrome to create any download file
    for _ in range(20):
        if os.listdir("download"):
            break
        time.sleep(1)

    # Wait for any in-progress .crdownload to finish (up to 5 min for large files)
    for _ in range(150):
        if not any(f.endswith('.crdownload') for f in os.listdir("download")):
            break
        time.sleep(2)

    # Pick up whatever PDF Chrome saved (Content-Disposition may rename it)
    pdfs = [f for f in os.listdir("download") if f.lower().endswith('.pdf')]
    if not pdfs:
        return False

    shutil.move(os.path.join("download", pdfs[0]), dest_path)
    return True


def _ewd_print_to_pdf(driver, ewd, ewd_code, dest_path):
    """Print an EWD document to PDF, stripping the viewer nav panel."""
    base = f"https://techinfo.toyota.com/t3Portal/external/en/ewdappu/{ewd}"

    # Attempt 1: load the XHTML source directly (same dir as termdata.xml).
    # This gives clean content without the viewer nav panel or chrome.
    xhtml_url = f"{base}/xhtml/{ewd_code}.xhtml"
    driver.get(xhtml_url)
    for _ in range(20):
        if driver.execute_script("return document.readyState") == 'complete':
            break
        time.sleep(1)
    time.sleep(2)

    xhtml_ok = (
        driver.current_url == xhtml_url
        and driver.execute_script("""
            var body = document.body;
            if (!body || body.innerHTML.trim().length < 500) return false;
            var text = body.textContent.toLowerCase();
            // Reject TIS error / session-expiry pages
            if (text.indexOf('no documents') !== -1) return false;
            if (text.indexOf('session expired') !== -1) return false;
            if (text.indexOf('please log') !== -1) return false;
            // Require actual document structure
            return !!(document.querySelector('h1, h2, h3, table, svg, p'));
        """)
    )

    if xhtml_ok:
        # Scale any embedded circuit SVG to fill the page
        has_svg = driver.execute_script("""
            var svg = document.querySelector('svg');
            if (!svg) return false;
            if (!svg.getAttribute('viewBox')) {
                var w = parseFloat(svg.getAttribute('width') || '1200');
                var h = parseFloat(svg.getAttribute('height') || '800');
                svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
            }
            svg.setAttribute('width', '100%');
            svg.setAttribute('height', '100%');
            svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
            svg.style.cssText = 'display:block;width:100%;height:100%;';
            document.body.style.cssText = 'margin:0;padding:0;';
            return true;
        """)
        margin = 0.15 if has_svg else 0.3
        scale  = 1.0  if has_svg else 0.9

    else:
        # Attempt 2: load the full viewer, extract circuit SVG into a blob page
        viewer_url = (
            f"https://techinfo.toyota.com/t3Portal/ewdappu/index.jsp"
            f"?ewdNo={ewd}&t3id={ewd}_{ewd_code}&systemcode={ewd_code}&locale=en"
        )
        driver.get(viewer_url)
        for _ in range(30):
            if driver.execute_script("return document.readyState") == 'complete':
                break
            time.sleep(1)
        time.sleep(5)

        blob_url = driver.execute_script("""
            function findSVGBlob(win, depth) {
                if (depth > 3) return null;
                try {
                    var svg = win.document.querySelector('svg');
                    if (svg) {
                        if (!svg.getAttribute('viewBox')) {
                            var w = parseFloat(svg.getAttribute('width') || '1200');
                            var h = parseFloat(svg.getAttribute('height') || '800');
                            svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
                        }
                        svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
                        var html = '<!DOCTYPE html><html><head><style>'
                            + 'html,body{margin:0;padding:0;width:100%;height:100%}'
                            + 'svg{width:100%;height:100%;display:block}'
                            + '</style></head><body>' + svg.outerHTML + '</body></html>';
                        return URL.createObjectURL(new Blob([html], {type:'text/html'}));
                    }
                } catch(e) {}
                for (var i = 0; i < win.frames.length; i++) {
                    try {
                        var r = findSVGBlob(win.frames[i], depth + 1);
                        if (r) return r;
                    } catch(e) {}
                }
                return null;
            }
            return findSVGBlob(window, 0);
        """)

        if blob_url:
            driver.get(blob_url)
            for _ in range(10):
                if driver.execute_script("return document.readyState") == 'complete':
                    break
                time.sleep(1)
            time.sleep(1)
            margin = 0.15
            scale  = 1.0
        else:
            print(f"    no SVG found — printing full viewer page")
            margin = 0.3
            scale  = 0.9

    try:
        result = driver.execute_cdp_cmd("Page.printToPDF", {
            "printBackground": True,
            "landscape": True,
            "paperWidth": 11.69,
            "paperHeight": 8.27,
            "marginTop": margin,
            "marginBottom": margin,
            "marginLeft": margin,
            "marginRight": margin,
            "scale": scale,
        })
        data = result.get("data") if result else None
        if data:
            with open(dest_path, 'wb') as f:
                f.write(base64.b64decode(data))
            return True
    except Exception as e:
        print(f"    printToPDF failed: {e}")
    return False


def _download_ewd_new(driver, ewd, root):
    seen = set()
    documents = []
    for para in root.findall('paradata'):
        linkkey = para.get('linkkey', '')
        parts = dict(kv.split('=', 1) for kv in linkkey.rstrip(';').split(';') if '=' in kv)
        ewd_type = parts.get('ewd_type', '')
        ewd_code = parts.get('ewd', '')
        if not ewd_type or not ewd_code or (ewd_type, ewd_code) in seen:
            continue
        seen.add((ewd_type, ewd_code))
        name = (para.text or '').strip().split(';')[0]
        documents.append((ewd_type, ewd_code, name))

    print(f"Found {len(documents)} documents across {len(set(d[0] for d in documents))} sections")

    for i, (ewd_type, ewd_code, name) in enumerate(documents, 1):
        section_dir = os.path.join(ewd, ewd_type)
        if not os.path.exists(section_dir):
            os.makedirs(section_dir)

        fn = os.path.join(section_dir, ewd_code + ".pdf")
        if os.path.exists(fn):
            continue

        print(f"[{i}/{len(documents)}] {ewd_type}/{ewd_code}: {name}...")
        if not _ewd_print_to_pdf(driver, ewd, ewd_code, fn):
            print(f"  Failed to capture: {ewd_type}/{ewd_code}")


def _download_ewd_legacy(driver, ewd):
    SYSTEMS = ["system", "routing", "overall"]

    for s in SYSTEMS:
        fn = os.path.join(ewd, s, "index.xml")
        d = os.path.join(ewd, s)
        if not os.path.exists(d):
            os.makedirs(d)

        if os.path.exists(fn):
            continue

        url = "https://techinfo.toyota.com/t3Portal/external/en/ewdappu/" + ewd + "/ewd/contents/" + s + "/title.xml"
        print("Loading", url)
        result = driver.execute_async_script("""
            var callback = arguments[arguments.length - 1];
            fetch(arguments[0]).then(r => r.ok ? r.text() : Promise.resolve(null)).then(callback);
        """, url)
        if result is None:
            print("  Not found, skipping", s)
            continue
        with open(fn, 'w') as fh:
            fh.write(result)

    for s in SYSTEMS:
        idx = os.path.join(ewd, s, "index.xml")
        if not os.path.exists(idx):
            continue
        tree = ET.parse(idx)
        root = tree.getroot()
        for child in root:
            name = child.findall('name')[0].text
            fig = child.findall('fig')[0].text
            fn = os.path.join(ewd, s, mkfilename(fig + " " + name) + ".pdf")

            if os.path.exists(fn):
                continue

            print("Downloading", name, "...")
            url = "https://techinfo.toyota.com/t3Portal/external/en/ewdappu/" + ewd + "/ewd/contents/" + s + "/pdf/" + fig + ".pdf"
            if not _ewd_download_pdf(driver, url, fn):
                print("Didn't download", url, "!")


def _collect_td_candidates(driver, depth=0):
    """Recursively collect _tdCandidates from the current frame and all child frames."""
    candidates = []
    try:
        candidates = driver.execute_script("return window._tdCandidates || [];") or []
    except Exception:
        pass

    # Also check inline page source for embedded termdata
    try:
        src = driver.page_source
        if '<paradata' in src or ('<termdata' in src and '<termdata>' not in src[:30]):
            import re as _re
            m = _re.search(r'(<termdata\b[^>]*>.*?</termdata>)', src, _re.DOTALL)
            if m:
                candidates.append({'url': 'inline@' + driver.current_url, 'body': m.group(1)})
    except Exception:
        pass

    if depth < 3:
        try:
            frame_count = driver.execute_script("return window.frames.length;")
        except Exception:
            frame_count = 0
        for i in range(frame_count):
            try:
                driver.switch_to.frame(i)
                candidates.extend(_collect_td_candidates(driver, depth + 1))
                driver.switch_to.parent_frame()
            except Exception:
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass

    return candidates


def _intercept_termdata(driver, ewd):
    """Load the EWD viewer page and capture the termdata.xml the page fetches itself."""
    script_id = None
    try:
        # Inject fetch/XHR hooks into every frame before any page scripts run.
        # The viewer uses synchronous XHR (open(..., false)), so we check responseText
        # immediately after send() returns rather than relying on addEventListener('load').
        result = driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
            window._tdCandidates = [];
            function _tdCheck(url, text) {
                if (text && (text.indexOf('<paradata') !== -1 || text.indexOf('<termdata') !== -1)) {
                    window._tdCandidates.push({url: url, body: text});
                }
            }
            var _f = window.fetch;
            window.fetch = function() {
                var url = typeof arguments[0] === 'string' ? arguments[0]
                        : (arguments[0] && arguments[0].url) || '';
                var p = _f.apply(this, arguments);
                p.then(function(r) { return r.clone().text(); })
                 .then(function(t) { _tdCheck(url, t); })
                 .catch(function(){});
                return p;
            };
            var _xo = XMLHttpRequest.prototype.open;
            XMLHttpRequest.prototype.open = function(m, url) {
                this._tdUrl = url || '';
                return _xo.apply(this, arguments);
            };
            var _xs = XMLHttpRequest.prototype.send;
            XMLHttpRequest.prototype.send = function() {
                var x = this;
                x.addEventListener('load', function() { _tdCheck(x._tdUrl, x.responseText); });
                var r = _xs.apply(this, arguments);
                // Synchronous XHR: readyState is already 4 after send() returns
                if (x.readyState === 4) { _tdCheck(x._tdUrl, x.responseText); }
                return r;
            };
            """
        })
        script_id = result.get("identifier")

        viewer_url = f"https://techinfo.toyota.com/t3Portal/ewdappu/index.jsp?ewdNo={ewd}"
        print(f"Loading EWD viewer (intercepting termdata.xml)...")
        driver.get(viewer_url)
        time.sleep(10)  # wait for full page load + async requests

        candidates = _collect_td_candidates(driver)
        try:
            driver.switch_to.default_content()
        except Exception:
            pass

        if not candidates:
            return None

        for c in candidates:
            print(f"  Candidate: {c.get('url', '?')} ({len(c['body'])} chars)")

        best = max(candidates, key=lambda c: len(c['body']))
        print(f"  Using: {best.get('url', '?')}")
        return best['body']
    finally:
        if script_id:
            try:
                driver.execute_cdp_cmd("Page.removeScriptToEvaluateOnNewDocument",
                                       {"identifier": script_id})
            except Exception:
                pass
        try:
            driver.switch_to.default_content()
        except Exception:
            pass


def download_ewd(driver, ewd):
    if not os.path.exists(ewd):
        os.makedirs(ewd)

    termdata_path = os.path.join(ewd, "termdata.xml")

    if not os.path.exists(termdata_path):
        # The viewer's Ewdappu.js builds the URL as:
        #   sourcePath + "/" + locale + appPath + "/" + pubBindID + termdataPath
        # = ".../external/en/ewdappu/{ewd}/xhtml/termdata.xml"
        direct_url = f"https://techinfo.toyota.com/t3Portal/external/en/ewdappu/{ewd}/xhtml/termdata.xml"

        # Navigate to the viewer first to establish session, then try the direct URL.
        viewer_url = f"https://techinfo.toyota.com/t3Portal/ewdappu/index.jsp?ewdNo={ewd}"
        print(f"Loading EWD viewer for {ewd}...")
        driver.get(viewer_url)
        time.sleep(3)

        print(f"Fetching termdata.xml...")
        result = driver.execute_async_script("""
            var cb = arguments[arguments.length - 1];
            fetch(arguments[0])
                .then(function(r) { return r.ok ? r.text() : Promise.resolve(null); })
                .then(cb).catch(function() { cb(null); });
        """, direct_url)

        # If the direct URL failed, fall back to intercepting the viewer's own XHR.
        if result is None:
            print(f"  Direct URL failed, trying XHR interceptor...")
            result = _intercept_termdata(driver, ewd)

        if result is not None:
            print(f"  Got termdata.xml ({len(result)} chars)")
            with open(termdata_path, 'w') as fh:
                fh.write(result)
        else:
            print(f"  termdata.xml not found — falling back to legacy format")
            print(f"  Tip: manually save termdata.xml to {termdata_path} to skip this step")

    if os.path.exists(termdata_path):
        try:
            tree = ET.parse(termdata_path)
        except ET.ParseError as e:
            with open(termdata_path, 'r', errors='replace') as fh:
                snippet = fh.read(300)
            print(f"  termdata.xml parse error ({e}) — content preview:\n{snippet}")
            os.remove(termdata_path)
        else:
            root = tree.getroot()
            if root.get('legacy') != 'yes':
                _download_ewd_new(driver, ewd, root)
                return

    print("Using legacy EWD format...")
    _download_ewd_legacy(driver, ewd)

def toc_parse_items(base, items):
    if len(items) == 0:
        return ""
    
    wrap = "<ul>"

    for i in items:
        wrap += "<li>"
        name = i.findall("name")[0].text
        wrap += name

        if "href" in i.attrib and i.attrib["href"] != "":
            bn = os.path.splitext(os.path.basename(i.attrib["href"]))[0]
            html_path = os.path.join(base, "html", bn + ".html")

            if os.path.exists(html_path):
                wrap += " [<a href=\"html/" + bn + ".html\">HTML</a>] "

        wrap += toc_parse_items(base, i.findall("item"))
        wrap += "</li>"

    wrap += "</ul>"
    return wrap

def build_toc_index(base):
    if not os.path.exists(base):
        return False
    toc_path = os.path.join(base, "toc.xml")
    if not os.path.exists(toc_path):
        print("toc.xml missing in ", base)
        return False

    print("Building TOC index from ", toc_path, "...")
    
    tree = ET.parse(toc_path)
    root = tree.getroot()

    body = toc_parse_items(base, root.findall("item"))
    index_out = os.path.join(base, "index.html")
    with open(index_out, "w") as fh:
        fh.write("<!doctype html>\n")
        fh.write("<html><head><title>" + base + "</title></head><body>")
        fh.write(body)
        fh.write("</body></html>")

def download_manual(driver, t, id):
    if not os.path.exists(os.path.join(id, "html")):
        os.makedirs(os.path.join(id, "html"))
    toc_path = os.path.join(id, "toc.xml")
    if not os.path.exists(toc_path):
        print("Downloading the TOC for", id)
        url = "https://techinfo.toyota.com/t3Portal/external/en/" + t + "/" + id + "/toc.xml"
        driver.get(url)
        xml_src = driver.execute_script('return document.getElementById("webkit-xml-viewer-source-xml").innerHTML')
        with open(toc_path, 'w') as fh:
            fh.write(xml_src)

    tree = ET.parse(toc_path)
    root = tree.getroot()
    n = 0
    c = 0

    for i in root.iter("item"):
        if not 'href' in i.attrib or i.attrib['href'] == '':
            continue
        c += 1

    for i in root.iter("item"):
        if not 'href' in i.attrib or i.attrib['href'] == '':
            continue
        href = i.attrib['href']
        url = "https://techinfo.toyota.com" + href
        n += 1
        
        print("Downloading", href, " (", n, "/", c, ")...")
        # all are html files, load them all up one at a time and then save them
        f_parts = href.split('/')
        f_p = os.path.join(id, "html", f_parts[len(f_parts)-1])

        if os.path.exists(f_p):
            continue
        driver.get(url)
        page_source = driver.page_source

        if "location='/t3Portal" in page_source:
            print("\tPDF redirect found!")
            match = re.search(r"location\s*=\s*['\"]?(/t3Portal[^'\">\s]+)", page_source)
            if not match:
                print("\tCould not parse redirect URL, skipping.")
                continue
            redirect_url = "https://techinfo.toyota.com" + match.group(1)
            cookies = {c['name']: c['value'] for c in driver.get_cookies()}
            r = requests.get(redirect_url, cookies=cookies, headers={
                'Referer': url,
                'User-Agent': driver.execute_script("return navigator.userAgent"),
            }, verify=False)
            if r.status_code == 200 and r.content.startswith(b'%PDF'):
                # Direct PDF — save it as HTML is not applicable; skip for build.py to handle
                print("\tDirect PDF, skipping (run build.py to convert)")
                continue
            # Server returned HTML — navigate Selenium to it and save like a normal page
            driver.get(redirect_url)

        print("\tInjecting scripts...")
        driver.execute_script("""var s=window.document.createElement('script');\
        s.src='https://cdnjs.cloudflare.com/ajax/libs/jquery/3.4.1/jquery.min.js';\
        window.document.head.appendChild(s);""")

        src = None
        try:
            src = driver.execute_script(open("injected.js", "r").read())
        except:
            time.sleep(1)
            src = driver.execute_script(open("injected.js", "r").read())

        with open(f_p, 'w') as fh:
            fh.write(src)

        fix_links(f_p)

        print("\tDone")
    
    build_toc_index(id)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("You must pass the documents you wish to download as arguments to this script!")
        sys.exit(1)
    
    EWDS = []
    REPAIR_MANUALS = []
    COLLISION_MANUALS = []

    for arg in sys.argv[1:]:
        if arg.startswith('EM'):
            EWDS.append(arg)
        elif arg.startswith('RM'):
            REPAIR_MANUALS.append(arg)
        elif arg.startswith('BM'):
            COLLISION_MANUALS.append(arg)
        else:
            print("Unknown document type for '" + arg + "'!")
            sys.exit(1)
    
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("user-data-dir=./user-data")
    chrome_options.add_experimental_option("prefs", {
        "download.default_directory": os.path.abspath("download"),
        "download.prompt_for_download": False,
        "plugins.always_open_pdf_externally": True,
    })

    shutil.rmtree("download", True)
    os.makedirs("download")

    driver = webdriver.Chrome(options=chrome_options)

    driver.get("https://techinfo.toyota.com")
    input("Please login and press enter to continue...")

    # for each in ewd download
    print("Downloading electrical wiring diagrams...")
    for ewd in EWDS:
        download_ewd(driver, ewd)

    # download all collision manuals
    print("Downloading collision repair manuals...")
    for cr in COLLISION_MANUALS:
        download_manual(driver, "cr", cr)

    # download all repair manuals
    print("Downloading repair manuals...")
    for rm in REPAIR_MANUALS:
        download_manual(driver, "rm", rm)

    driver.close()
