#!/usr/bin/env python3
"""Download real BTS T-100 Segment data from TranStats.

    python3 -m etl.fetch_t100 --year 2024

T-100 Segment (All Carriers) is the table this whole system is built on: every
nonstop segment flown by US and foreign carriers, with passengers, seats,
departures and distance. It is free and public domain, but BTS publishes it
through an ASP.NET form rather than an API, so this script drives the form:
fetch the page for its viewstate tokens, post the selection back, receive a ZIP.

If BTS changes the form this will break. That is the cost of there being no
API. The fallback is always the browser: transtats.bts.gov -> Aviation ->
Air Carriers -> T-100 Segment (All Carriers), then drop the CSV at
data/raw/t100_segment.csv.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import io
import os
import re
import sys
import urllib.parse
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api import config  # noqa: E402

# TranStats obfuscates table ids in the query string. FMG is
# "T-100 Segment (All Carriers)" -- the one with seats and departures.
TABLE_ID = "FMG"
BASE = "https://www.transtats.bts.gov/DL_SelectFields.aspx"
URL = f"{BASE}?gnoyr_VQ={TABLE_ID}&QO_fu146_anzr=Nv4%20Pn44vr45"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")


def _hidden(page: str, name: str) -> str:
    m = re.search(rf'name="{name}"[^>]*value="([^"]*)"', page)
    return m.group(1) if m else ""


def fetch(year: int, period: str = "All", timeout: int = 300) -> bytes:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", UA), ("Referer", URL)]

    print(f"  requesting the form ({TABLE_ID})...")
    page = opener.open(URL, timeout=60).read().decode("utf-8", "replace")

    form = {
        "__EVENTTARGET": "", "__EVENTARGUMENT": "",
        "__VIEWSTATE": _hidden(page, "__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": _hidden(page, "__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": _hidden(page, "__EVENTVALIDATION"),
        "cboGeography": "All", "cboYear": str(year), "cboPeriod": period,
        "chkAllVars": "on", "chkDownloadZip": "on", "btnDownload": "Download",
    }
    if not form["__VIEWSTATE"]:
        raise SystemExit("  the form did not return a viewstate; BTS may have changed it")

    print(f"  downloading {year} (this is tens of MB, give it a minute)...")
    req = urllib.request.Request(URL, data=urllib.parse.urlencode(form).encode(),
                                 method="POST")
    resp = opener.open(req, timeout=timeout)
    ctype = resp.headers.get("Content-Type", "")
    body = resp.read()
    if "zip" not in ctype.lower() or body[:2] != b"PK":
        raise SystemExit(f"  expected a ZIP, got {ctype} ({len(body)} bytes). "
                         f"Download it by hand from {URL}")
    return body


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2024",
                    help="comma separated, e.g. 2019,2023,2024")
    ap.add_argument("--period", default="All")
    args = ap.parse_args()

    os.makedirs(config.RAW_DIR, exist_ok=True)
    years = [int(y) for y in str(args.years).replace(" ", "").split(",") if y]

    for year in years:
        out = os.path.join(config.RAW_DIR, f"t100_segment_{year}.csv")
        if os.path.exists(out) and os.path.getsize(out) > 1_000_000:
            print(f"  {year}: already downloaded, skipping")
            continue
        blob = fetch(year, args.period)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            names = [n for n in z.namelist()
                     if n.lower().endswith(".csv") and "documentation" not in n.lower()]
            if not names:
                raise SystemExit("  no data CSV inside the archive")
            with z.open(names[0]) as src, open(out, "wb") as dst:
                dst.write(src.read())
        print(f"  {year}: wrote {out} ({os.path.getsize(out):,} bytes)")

    print("\n  now run:  python3 -m etl.build")


if __name__ == "__main__":
    main()
