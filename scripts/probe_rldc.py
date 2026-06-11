#!/usr/bin/env python3
"""Probe RLDC real-time endpoints — run this FROM THE VPS (Indian IP).

Phase 0 recon (docs/sources/README.md): WRLDC's JSON API answered HTTP 200
but `{"d":"[]"}` from a non-Indian IP. This script re-tests WRLDC and tries
the equivalent paths on the other four RLDCs, archiving every response.

Usage:
    python scripts/probe_rldc.py [--outdir docs/sources/probe-vps]

Self-contained on purpose (httpx only) so it runs in the tick container or
any venv. Writes one file per probe + summary.md, prints the summary table.
"""

import argparse
import re
import ssl
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

warnings.filterwarnings("ignore")  # verify=False noise — gov cert chains are broken


def _gov_ssl_context() -> ssl.SSLContext:
    """No verification + legacy renegotiation + SECLEVEL=1.

    RLDC servers (nrldc.in, srldc.in, ...) need legacy TLS renegotiation,
    which OpenSSL 3 disables by default (UNSAFE_LEGACY_RENEGOTIATION_DISABLED),
    and some present cert chains/ciphers below default security level.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
    ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
    return ctx

IST = ZoneInfo("Asia/Kolkata")
UA = "india-grid-map/0.1 (open data project; contact: adityamsawant07@gmail.com)"
TODAY = datetime.now(IST).strftime("%Y-%m-%d")

# (name, method, url, json_payload) — None payload = GET
PROBES = []

# the two WRLDC endpoints from Phase 0 recon, exact payloads
for host in ["https://www.wrldc.in", "https://wrldc.in"]:
    tag = host.removeprefix("https://").replace("www.", "www_").replace(".", "_")
    PROBES += [
        (f"{tag}_statewise", "POST",
         f"{host}/OnlinestateTest1.aspx/GetRealTimeData_state_Wise", {"date": TODAY}),
        (f"{tag}_interregional", "POST",
         f"{host}/InterRegionalLinks_Data.aspx/Get_InterRegionalLinks_Region_Wise", {"date": TODAY}),
    ]

# equivalent paths on the other RLDCs (they have shared platform history),
# plus base-URL liveness checks and the ERLDC PSP-report API from
# electricitymaps (app.erldc.in was dead DNS from outside India)
for host in ["https://nrldc.in", "https://srldc.in", "https://erldc.in",
             "https://nerldc.in", "https://app.erldc.in"]:
    tag = host.removeprefix("https://").replace(".", "_")
    PROBES.append((f"{tag}_home", "GET", f"{host}/", None))
    if host != "https://app.erldc.in":
        PROBES += [
            (f"{tag}_statewise", "POST",
             f"{host}/OnlinestateTest1.aspx/GetRealTimeData_state_Wise", {"date": TODAY}),
            (f"{tag}_interregional", "POST",
             f"{host}/InterRegionalLinks_Data.aspx/Get_InterRegionalLinks_Region_Wise", {"date": TODAY}),
        ]

for host in ["https://app.erldc.in", "https://erldc.in"]:
    tag = host.removeprefix("https://").replace(".", "_")
    PROBES.append((
        f"{tag}_psp_interregional", "GET",
        f"{host}/api/pspreportpsp/Get/pspreport_psp_interregionalexchanges/GetByTwoDate"
        f"?firstDate={TODAY}&secondDate={TODAY}", None))


EMPTY_BODIES = {'{"d":"[]"}', "[]", "{}", "-3", ""}


def classify(status: int | None, body: bytes, error: str) -> str:
    if error or status is None:
        return "error"
    if status != 200:
        return f"http {status}"
    text = body.decode("utf-8", errors="replace").strip()
    if text in EMPTY_BODIES or len(text) < 30:
        return "empty"
    # an HTML error page behind a 200 is still not data for the JSON endpoints
    if text[:1] == "<" and re.search(r"(error|not found|forbidden)", text[:2000], re.I):
        return "error-page"
    return "DATA"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--outdir", default="docs/sources/probe-vps")
    args = ap.parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    results = []
    with httpx.Client(verify=_gov_ssl_context(), headers={"User-Agent": UA}, timeout=30,
                      follow_redirects=True) as client:
        for name, method, url, payload in PROBES:
            error, status, body, ct = "", None, b"", ""
            try:
                resp = client.request(method, url, json=payload)
                status, body = resp.status_code, resp.content
                ct = resp.headers.get("content-type", "")
            except httpx.HTTPError as e:
                error = f"{type(e).__name__}: {e}"
            verdict = classify(status, body, error)
            results.append((name, method, url, status, len(body), verdict, error))
            ext = ".json" if "json" in ct else ".html" if "html" in ct else ".txt"
            (outdir / f"{name}{ext}").write_bytes(body or error.encode())
            print(f"{verdict:>10}  {name:<38} status={status} bytes={len(body)}", file=sys.stderr)
            time.sleep(1.0)

    fetched_at = datetime.now(IST).isoformat(timespec="seconds")
    lines = [
        f"# RLDC probe — {fetched_at}",
        "",
        f"Probed from this host (run `curl ifconfig.me` to record the IP). Date param: {TODAY}.",
        "",
        "| verdict | probe | method | status | bytes | url |",
        "|---|---|---|---|---|---|",
    ]
    for name, method, url, status, nbytes, verdict, error in results:
        lines.append(f"| {verdict} | {name} | {method} | {status} | {nbytes} | {url} |")
    errs = [(r[0], r[6]) for r in results if r[6]]
    if errs:
        lines += ["", "## Errors", ""] + [f"- `{n}`: {e}" for n, e in errs]
    (outdir / "summary.md").write_text("\n".join(lines) + "\n")

    n_data = sum(1 for r in results if r[5] == "DATA")
    print(f"\n{n_data}/{len(results)} probes returned data → {outdir}/summary.md", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
