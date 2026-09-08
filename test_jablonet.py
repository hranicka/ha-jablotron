#!/usr/bin/env python3
"""Probe the MyJABLOTRON mobile API with real credentials.

The web endpoints on www.jablonet.net are closed to non-browser clients, so
this script (like the integration itself) uses the mobile-app API on
api.jablonet.net.

Usage:
    python test_jablonet.py <email> <password> [service_id]

What it does (read-only — never triggers PGM outputs):
    1. userAuthorize.json login (api/2.2)
    2. serviceListGet.json — lists all account services
    3. dataUpdate.json on api/2.2, 2.3 and 2.4 — dumps the thermometer
       segments of each (the integration's data source; 2.2 currently
       reports "unknown" values on some accounts — investigating whether a
       newer API minor returns real values)
    4. thermoDevicesGet.json variants (bare + /JA100/ + /JA100F/ paths) —
       a separate endpoint family that openHAB's model shows carrying real
       per-device `temperature` floats
    5. accessTokenGet.json — checks Bearer-token availability (for a
       possible GraphQL data source later); the token itself is not printed
    6. legacy stav.php-shaped summary of the 2.2 response
    7. logout.json
"""
import asyncio
import json
import logging
import sys
from pathlib import Path
from urllib.parse import urlencode

import aiohttp

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
_LOGGER = logging.getLogger(__name__)

API_BASE = "https://api.jablonet.net/api/2.2/"
HEADERS = {
    "User-Agent": "net.jablonet/8.6.1.3887",
    "Accept": "application/json",
    "Accept-Language": "en",
    "Accept-Encoding": "*",
    "x-vendor-id": "JABLOTRON:Jablotron",
    "x-client-version": "MYJ-PUB-IOS-8.6.1.3887",
}
JSON_HEADERS = {**HEADERS, "Content-Type": "application/json"}
FORM_HEADERS = {**HEADERS, "Content-Type": "application/x-www-form-urlencoded"}
SYSTEM = "HomeAssistant"


def load_adapter():
    """Load const.py + v22_adapter.py standalone (no Home Assistant needed).

    The real package __init__.py imports homeassistant, which the probe must
    not require — so the two dependency-free modules are loaded by file path
    under a synthetic package.
    """
    import importlib.util
    import types

    comp_dir = Path(__file__).parent / "custom_components" / "jablotron_web"
    pkg_name = "jablotron_web_probe"
    package = types.ModuleType(pkg_name)
    package.__path__ = [str(comp_dir)]
    sys.modules[pkg_name] = package
    for mod_name in ("const", "v22_adapter"):
        spec = importlib.util.spec_from_file_location(
            f"{pkg_name}.{mod_name}", comp_dir / f"{mod_name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"{pkg_name}.{mod_name}"] = module
        spec.loader.exec_module(module)
    return sys.modules[f"{pkg_name}.v22_adapter"]


def print_section(title: str):
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


async def post_json(session, url, payload):
    async with session.post(url, headers=JSON_HEADERS, json=payload,
                            timeout=aiohttp.ClientTimeout(total=15)) as r:
        text = await r.text()
        return r.status, text


async def post_form(session, url, fields):
    async with session.post(url, headers=FORM_HEADERS,
                            data=urlencode(fields),
                            timeout=aiohttp.ClientTimeout(total=15)) as r:
        text = await r.text()
        return r.status, text


def data_update_fields(service_id: str, extra_data_types=None):
    filter_data = [{"data_type": "section"}, {"data_type": "pgm"},
                   {"data_type": "thermometer"}, {"data_type": "thermostat"}]
    for extra in extra_data_types or []:
        filter_data.append({"data_type": extra})
    request = [{
        "filter_data": filter_data,
        "service_type": "ja100",
        "service_id": int(service_id),
        "data_group": "serviceData",
    }]
    return {"data": json.dumps(request), "system": SYSTEM}


async def probe(username: str, password: str, service_id_arg: str = ""):
    adapter = load_adapter()
    session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar())

    try:
        # --- Step 1: login -------------------------------------------------
        print_section("STEP 1: userAuthorize.json (login)")
        status, text = await post_json(session, f"{API_BASE}userAuthorize.json",
                                       {"login": username, "password": password})
        print(f"HTTP {status}: {text[:400]}")
        payload = json.loads(text) if text.strip() else {}
        if status != 200 or payload.get("http-code", 200) != 200:
            codes = [e.get("code") for e in payload.get("errors", []) if isinstance(e, dict)]
            print(f"\n✗ Login failed (HTTP {status}, codes={codes})")
            return
        print("✓ Login successful")

        # --- Step 2: service list ------------------------------------------
        print_section("STEP 2: serviceListGet.json (account services)")
        status, text = await post_json(session, f"{API_BASE}serviceListGet.json",
                                       {"list-type": "EXTENDED", "visibility": "VISIBLE"})
        print(f"HTTP {status}")
        services = []
        try:
            services = json.loads(text).get("data", {}).get("services", []) or []
        except json.JSONDecodeError:
            print(f"  non-JSON body: {text[:200]}")
        service_id = service_id_arg
        for svc in services:
            print(f"  id={svc.get('service-id')} type={svc.get('service-type')} "
                  f"status={svc.get('status')} name={svc.get('name')!r}")
            if not service_id and str(svc.get("service-type", "")).lower() == "ja100" \
                    and str(svc.get("status", "")).upper() == "ENABLED":
                service_id = str(svc.get("service-id"))
        if not service_id:
            print("\n✗ No service id available (pass one as the third argument)")
            return
        print(f"→ Using service_id={service_id}")

        # --- Step 3: dataUpdate across API versions ------------------------
        # 2.2 powers the integration today but reports thermometer values as
        # "unknown" on this account; 2.3/2.4 exist and accept the same client.
        print_section("STEP 3: dataUpdate.json on api/2.2 vs 2.3 vs 2.4 (thermometer segments)")
        raw_22 = {}
        for ver in ("2.2", "2.3", "2.4"):
            base = f"https://api.jablonet.net/api/{ver}/"
            status, text = await post_form(session, f"{base}dataUpdate.json",
                                           data_update_fields(service_id))
            # a version-scoped session may need its own login
            if status == 401 and ver != "2.2":
                await post_json(session, f"{base}userAuthorize.json",
                                {"login": username, "password": password})
                status, text = await post_form(session, f"{base}dataUpdate.json",
                                               data_update_fields(service_id))
            try:
                ver_raw = json.loads(text)
            except json.JSONDecodeError:
                print(f"  api/{ver}: HTTP {status} non-JSON: {text[:200]}")
                continue
            entry = ((ver_raw.get("data") or {}).get("service_data") or [{}])[0]
            counts = {b.get("data_type"): len((b.get("data") or {}).get("segments") or [])
                      for b in entry.get("data") or []}
            print(f"  api/{ver}: HTTP {status} status={ver_raw.get('status')} block sizes={counts}")
            for block in entry.get("data") or []:
                if block.get("data_type") in ("thermometer", "thermostat"):
                    print(f"    ↳ {block['data_type']} RAW:")
                    print("      " + json.dumps(block, indent=6, ensure_ascii=False).replace("\n", "\n      "))
            if ver == "2.2":
                raw_22 = ver_raw

        # --- Step 4: thermoDevicesGet variants ------------------------------
        # Independent clients (homebridge-jablotron-alarm, ha-cc-jablotron-cloud)
        # read LIVE thermometer values from /{JA100}/thermoDevicesGet.json with
        # connect-device=true — dataUpdate's thermometer segments are stale
        # ("unknown") on some accounts. Both connect-device modes are probed.
        print_section("STEP 4: thermoDevicesGet.json variants (live temperature source?)")
        for connect in (False, True):
            thermo_body = {"connect-device": connect, "list-type": "FULL",
                           "service-id": int(service_id), "service-states": True}
            for name, url in [
                ("bare 2.2", f"{API_BASE}thermoDevicesGet.json"),
                ("under /JA100/", f"{API_BASE}JA100/thermoDevicesGet.json"),
            ]:
                status, text = await post_json(session, url, thermo_body)
                try:
                    body = json.loads(text)
                    dump = json.dumps(body, indent=4, ensure_ascii=False)
                    print(f"  connect-device={connect} {name}: HTTP {status}")
                    print("    " + dump.replace("\n", "\n    ")[:2500])
                except json.JSONDecodeError:
                    print(f"  connect-device={connect} {name}: HTTP {status} non-JSON: {text[:200]}")

        # --- Step 5: access token availability ------------------------------
        print_section("STEP 5: accessTokenGet.json (GraphQL Bearer token availability)")
        status, text = await post_json(session, f"{API_BASE}accessTokenGet.json",
                                       {"force-renew": True})
        try:
            tok = json.loads(text)
            token = ((tok.get("data") or {}).get("access-token")) or ""
            expiration = ((tok.get("data") or {}).get("access-token-expiration")) or ""
            print(f"  HTTP {status}: token {'obtained (' + str(len(token)) + ' chars)' if token else 'NOT obtained'}"
                  f"{', expires ' + str(expiration) if expiration else ''}")
        except json.JSONDecodeError:
            print(f"  HTTP {status} non-JSON: {text[:200]}")

        # --- Step 6: legacy-shape summary ------------------------------------
        print_section("STEP 6: legacy stav.php-shaped dict from 2.2 (what HA platforms see)")
        legacy = adapter.adapt_data_update(raw_22, service_id=service_id,
                                           has_pgm_code=False)
        print(json.dumps(legacy, indent=2, ensure_ascii=False))

        print_section("RESULT")
        print(f"sections:     {len(legacy['sekce'])}")
        print(f"PGMs:         {len(legacy['pgm'])}")
        print(f"thermometers: {len(legacy['teplomery'])}")
        print(f"PIRs:         {len(legacy['pir'])}")
        print("\n✓ Probe complete (no control calls were made)")

        # --- Step 7: logout --------------------------------------------------
        await post_form(session, f"{API_BASE}logout.json", {"system": SYSTEM})

    finally:
        await session.close()


if __name__ == "__main__":
    if len(sys.argv) < 3 or len(sys.argv) > 4:
        print("Usage: python test_jablonet.py <email> <password> [service_id]")
        print("\nExamples:")
        print("  python test_jablonet.py user@example.com mypassword")
        print("  python test_jablonet.py user@example.com mypassword 12345")
        sys.exit(1)

    asyncio.run(probe(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) == 4 else ""))
