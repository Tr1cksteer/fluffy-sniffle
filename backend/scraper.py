"""
Vessel information scraper.
Sources (no API key required):
  1. goradar.ru         — primary
  2. myshiptracking.com — fallback
  3. vesseltracker.com  — fallback
  4. marinetraffic.com  — fallback (partial, HTML)
"""

import re
import json
import asyncio
import logging
from typing import Optional

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

TIMEOUT = httpx.Timeout(30.0)


async def fetch_vessel_info(imo: str) -> Optional[dict]:
    """Try each scraper in order; return first successful result."""
    scrapers = [
        scrape_goradar,
        scrape_myshiptracking,
        scrape_vesseltracker,
        scrape_marinetraffic,
    ]
    for scraper in scrapers:
        try:
            result = await scraper(imo)
            if result and result.get("name"):
                log.info(f"IMO {imo}: got data from {scraper.__name__}")
                return result
        except Exception as e:
            log.warning(f"IMO {imo} — {scraper.__name__} failed: {e}")
        await asyncio.sleep(1)  # polite delay between sources
    log.warning(f"IMO {imo}: all scrapers failed")
    return {"imo": imo, "name": "", "line": "", "current_port": "", "destination": "", "ports": [], "route_ports": [], "last_seen": ""}


# ─── GoRadar.ru ───────────────────────────────────────────────────────────────

async def scrape_goradar(imo: str) -> Optional[dict]:
    """
    GoRadar search: https://goradar.ru/vessels?query=<IMO>
    Then vessel page: https://goradar.ru/vessels/<slug>
    """
    search_url = f"https://goradar.ru/vessels?query={imo}"
    async with httpx.AsyncClient(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True) as client:
        r = await client.get(search_url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # Find link to vessel page
        link = soup.select_one("a[href*='/vessels/']")
        if not link:
            # Try JSON-embedded data
            return _parse_goradar_search_json(r.text, imo)

        vessel_url = "https://goradar.ru" + link["href"] if link["href"].startswith("/") else link["href"]
        r2 = await client.get(vessel_url)
        r2.raise_for_status()
        return _parse_goradar_vessel_page(r2.text, imo)


def _parse_goradar_search_json(html: str, imo: str) -> Optional[dict]:
    """Try to extract JSON data embedded in the page."""
    # Look for Next.js __NEXT_DATA__ or similar
    m = re.search(r'__NEXT_DATA__\s*=\s*(\{.*?\})\s*</script>', html, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
        props = data.get("props", {}).get("pageProps", {})
        vessels = props.get("vessels") or props.get("results") or []
        for v in vessels:
            if str(v.get("imo", "")) == str(imo):
                return _normalize_goradar(v, imo)
    except Exception:
        pass
    return None


def _parse_goradar_vessel_page(html: str, imo: str) -> Optional[dict]:
    soup = BeautifulSoup(html, "html.parser")
    result = {"imo": imo, "name": "", "line": "", "current_port": "", "destination": "", "ports": [], "route_ports": [], "last_seen": ""}

    # Name — usually in h1 or title
    h1 = soup.find("h1")
    if h1:
        result["name"] = h1.get_text(strip=True)

    # Try __NEXT_DATA__ JSON
    nd = soup.find("script", id="__NEXT_DATA__")
    if nd:
        try:
            data = json.loads(nd.string)
            v = _deep_find_vessel(data, imo)
            if v:
                return _normalize_goradar(v, imo)
        except Exception:
            pass

    # Fallback: parse key-value rows
    rows = soup.select("table tr, .info-row, .detail-row, dl dt")
    for row in rows:
        text = row.get_text(" ", strip=True).lower()
        if "порт" in text or "port" in text:
            val = row.find_next_sibling()
            if val:
                result["current_port"] = val.get_text(strip=True)
        if "назначен" in text or "destination" in text:
            val = row.find_next_sibling()
            if val:
                result["destination"] = val.get_text(strip=True)
        if "линия" in text or "line" in text or "operator" in text:
            val = row.find_next_sibling()
            if val:
                result["line"] = val.get_text(strip=True)

    # Collect port mentions
    all_text = soup.get_text(" ")
    result["ports"] = extract_russian_ports(all_text)

    return result if result["name"] else None


def _deep_find_vessel(obj, imo: str, depth: int = 0) -> Optional[dict]:
    if depth > 8:
        return None
    if isinstance(obj, dict):
        if str(obj.get("imo", "")) == str(imo):
            return obj
        for v in obj.values():
            r = _deep_find_vessel(v, imo, depth + 1)
            if r:
                return r
    elif isinstance(obj, list):
        for item in obj:
            r = _deep_find_vessel(item, imo, depth + 1)
            if r:
                return r
    return None


def _normalize_goradar(v: dict, imo: str) -> dict:
    name = v.get("name") or v.get("vesselName") or v.get("vessel_name") or ""
    line = v.get("operator") or v.get("line") or v.get("company") or v.get("shipowner") or ""
    current_port = (
        v.get("currentPort") or v.get("current_port") or
        v.get("lastPort") or v.get("last_port") or ""
    )
    destination = v.get("destination") or v.get("nextPort") or v.get("next_port") or ""
    last_seen = v.get("lastUpdate") or v.get("updated_at") or v.get("positionReceived") or ""

    # Collect all port strings for basin detection
    ports = []
    for key in ("itinerary", "portCalls", "port_calls", "schedule", "routePorts"):
        pc = v.get(key)
        if isinstance(pc, list):
            for p in pc:
                if isinstance(p, dict):
                    ports.append(p.get("port") or p.get("portName") or p.get("name") or "")
                elif isinstance(p, str):
                    ports.append(p)
    if current_port:
        ports.append(current_port)
    if destination:
        ports.append(destination)

    return {
        "imo": imo,
        "name": str(name).strip(),
        "line": str(line).strip(),
        "current_port": str(current_port).strip(),
        "destination": str(destination).strip(),
        "ports": [p for p in ports if p],
        "route_ports": ports,
        "last_seen": str(last_seen),
    }


# ─── MyShipTracking.com ───────────────────────────────────────────────────────

async def scrape_myshiptracking(imo: str) -> Optional[dict]:
    url = f"https://www.myshiptracking.com/vessels?name={imo}&type=imo"
    async with httpx.AsyncClient(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # Find vessel link
        link = soup.select_one("table a[href*='/vessels/']") or soup.select_one("a[href*='/vessels/']")
        if not link:
            return None

        href = link["href"]
        if href.startswith("/"):
            href = "https://www.myshiptracking.com" + href
        r2 = await client.get(href)
        r2.raise_for_status()
        return _parse_mst_page(r2.text, imo)


def _parse_mst_page(html: str, imo: str) -> Optional[dict]:
    soup = BeautifulSoup(html, "html.parser")
    result = {"imo": imo, "name": "", "line": "", "current_port": "", "destination": "", "ports": [], "route_ports": [], "last_seen": ""}

    h1 = soup.find("h1")
    if h1:
        result["name"] = h1.get_text(strip=True)

    # Key-value pairs in definition lists or tables
    for dt in soup.select("dt, th, .label"):
        label = dt.get_text(strip=True).lower()
        dd = dt.find_next_sibling()
        if not dd:
            continue
        val = dd.get_text(strip=True)
        if "current port" in label or "last port" in label:
            result["current_port"] = val
        elif "destination" in label or "next port" in label:
            result["destination"] = val
        elif "operator" in label or "company" in label:
            result["line"] = val
        elif "last update" in label or "position" in label:
            result["last_seen"] = val

    all_text = soup.get_text(" ")
    result["ports"] = extract_russian_ports(all_text)
    result["route_ports"] = result["ports"]

    return result if result["name"] else None


# ─── VesselTracker.com ────────────────────────────────────────────────────────

async def scrape_vesseltracker(imo: str) -> Optional[dict]:
    url = f"https://www.vesseltracker.com/en/Ships/search.html?query={imo}"
    async with httpx.AsyncClient(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True) as client:
        r = await client.get(url)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        link = soup.select_one("a[href*='/Ships/']")
        if not link:
            return None
        href = link["href"]
        if href.startswith("/"):
            href = "https://www.vesseltracker.com" + href
        r2 = await client.get(href)
        r2.raise_for_status()
        return _parse_vt_page(r2.text, imo)


def _parse_vt_page(html: str, imo: str) -> Optional[dict]:
    soup = BeautifulSoup(html, "html.parser")
    result = {"imo": imo, "name": "", "line": "", "current_port": "", "destination": "", "ports": [], "route_ports": [], "last_seen": ""}

    h1 = soup.find("h1")
    if h1:
        result["name"] = h1.get_text(strip=True)

    for row in soup.select("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True).lower()
            val = cells[1].get_text(strip=True)
            if "port" in label:
                result["current_port"] = val
            elif "destination" in label:
                result["destination"] = val
            elif "operator" in label or "owner" in label:
                result["line"] = val

    all_text = soup.get_text(" ")
    result["ports"] = extract_russian_ports(all_text)
    result["route_ports"] = result["ports"]
    return result if result["name"] else None


# ─── MarineTraffic.com ────────────────────────────────────────────────────────

async def scrape_marinetraffic(imo: str) -> Optional[dict]:
    """Try to get basic info from MarineTraffic vessel page (limited without API)."""
    url = f"https://www.marinetraffic.com/en/ais/details/ships/imo:{imo}"
    async with httpx.AsyncClient(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True) as client:
        r = await client.get(url)
        if r.status_code not in (200, 301, 302):
            return None
        return _parse_mt_page(r.text, imo)


def _parse_mt_page(html: str, imo: str) -> Optional[dict]:
    soup = BeautifulSoup(html, "html.parser")
    result = {"imo": imo, "name": "", "line": "", "current_port": "", "destination": "", "ports": [], "route_ports": [], "last_seen": ""}

    # MarineTraffic embeds JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict) and data.get("@type") in ("Ship", "Vehicle", "Product"):
                result["name"] = data.get("name", "")
                break
        except Exception:
            pass

    h1 = soup.find("h1")
    if h1 and not result["name"]:
        result["name"] = h1.get_text(strip=True)

    # Meta description often contains port info
    meta_desc = soup.find("meta", {"name": "description"})
    if meta_desc:
        content = meta_desc.get("content", "")
        result["ports"] = extract_russian_ports(content)

    all_text = soup.get_text(" ")
    if not result["ports"]:
        result["ports"] = extract_russian_ports(all_text)
    result["route_ports"] = result["ports"]

    return result if result["name"] else None


# ─── Utility ─────────────────────────────────────────────────────────────────

RUSSIAN_PORTS = [
    "Владивосток", "Находка", "Восточный", "Петропавловск-Камчатский",
    "Магадан", "Холмск", "Корсаков", "Ванино", "Советская Гавань",
    "Санкт-Петербург", "Калининград", "Выборг", "Усть-Луга",
    "Новороссийск", "Темрюк", "Ейск", "Тамань", "Туапсе",
    "Ростов-на-Дону", "Азов", "Кавказ", "Керчь",
    "Мурманск", "Архангельск",
]

PORT_ALIASES = {
    "spb": "Санкт-Петербург", "st.petersburg": "Санкт-Петербург",
    "saint petersburg": "Санкт-Петербург", "st petersburg": "Санкт-Петербург",
    "vladivostok": "Владивосток", "nakhodka": "Находка",
    "novorossiysk": "Новороссийск", "novorossisk": "Новороссийск",
    "kaliningrad": "Калининград", "murmansk": "Мурманск",
    "vostochny": "Восточный", "vostochnyy": "Восточный",
    "petropavlovsk": "Петропавловск-Камчатский",
    "vanino": "Ванино", "kholmsk": "Холмск",
    "magadan": "Магадан", "korsakov": "Корсаков",
}


def extract_russian_ports(text: str) -> list:
    """Extract mentions of Russian ports from text."""
    found = []
    text_lower = text.lower()
    for port in RUSSIAN_PORTS:
        if port.lower() in text_lower:
            found.append(port)
    for alias, canon in PORT_ALIASES.items():
        if alias in text_lower and canon not in found:
            found.append(canon)
    return list(set(found))
