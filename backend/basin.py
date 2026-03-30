"""
Basin (бассейн) determination logic.

Rules:
  ДВ          — calls at Владивосток, Находка, Восточный (+ foreign ports)
  ДВ каботаж  — only RU Far East ports (Vladivostok, Nakhodka, Vostochny, Kholmsk,
                  Korsakov, Magadan, Petropavlovsk, Vanino, Sovetskaya) — no foreign ports
  ДВ без РФ   — Far East route but NO Russian ports at all
  Балтийский  — calls at Санкт-Петербург, Калининград, Выборг, Усть-Луга (+ foreign)
  Балтика каботаж — only between St.Petersburg ↔ Kaliningrad (ring), no foreign
  Новороссийск — calls at Новороссийск, Туапсе, Тамань, Темрюк, Кавказ, Ростов, Азов, Керчь
  Транзит     — foreign route without RU ports
  Неизвестно  — fallback
"""

from typing import List

# Port sets
FAR_EAST_RU = {
    "Владивосток", "Находка", "Восточный", "Петропавловск-Камчатский",
    "Магадан", "Холмск", "Корсаков", "Ванино", "Советская Гавань",
}

FAR_EAST_FOREIGN = {
    # Japanese ports in FE shipping lanes
    "Tokyo", "Yokohama", "Osaka", "Kobe", "Nagoya", "Hakata",
    "Busan", "Incheon", "Qingdao", "Shanghai", "Tianjin", "Dalian",
    "Ningbo", "Guangzhou", "Shenzhen", "Xiamen", "Hong Kong",
    "Singapore", "Port Klang", "Laem Chabang",
    # Also include transliterations
    "токио", "иокогама", "осака", "кобэ", "нагоя",
    "пусан", "циндао", "шанхай", "тяньцзинь", "далянь",
    "нингбо", "гуанчжоу", "шэньчжэнь", "сямэнь",
    "сингапур",
}

FAR_EAST_KEYWORDS = {
    "japan", "korea", "china", "singapore", "vietnam", "taiwan",
    "япония", "корея", "китай", "сингапур", "вьетнам",
    "pacific", "asia", "азия", "pacific",
}

BALTIC_RU = {
    "Санкт-Петербург", "Калининград", "Выборг", "Усть-Луга",
}

BLACK_SEA_RU = {
    "Новороссийск", "Темрюк", "Ейск", "Тамань", "Туапсе",
    "Ростов-на-Дону", "Азов", "Кавказ", "Керчь",
}

ALL_RU_PORTS = FAR_EAST_RU | BALTIC_RU | BLACK_SEA_RU | {"Мурманск", "Архангельск"}

CABOTAGE_FE_RING = {"Владивосток", "Находка", "Восточный", "Холмск", "Корсаков",
                    "Петропавловск-Камчатский", "Магадан", "Ванино"}
CABOTAGE_BALTIC_RING = {"Санкт-Петербург", "Калининград"}


def _normalize(ports: List[str]) -> set:
    """Lowercase + strip normalization for matching."""
    return {p.strip().lower() for p in ports if p}


def determine_basin(ports: List[str], route_ports: List[str]) -> str:
    """
    Determine basin from lists of port mentions.
    `ports` — extracted Russian port names (canonical)
    `route_ports` — all ports from schedule/itinerary (mixed languages)
    """
    all_ports_combined = list(set(ports + route_ports))

    # Normalize everything to lowercase for detection
    norm = _normalize(all_ports_combined)
    ports_canonical = {p for p in ports if p}  # keep original case RU ports

    fe_ru_found = FAR_EAST_RU & ports_canonical
    baltic_ru_found = BALTIC_RU & ports_canonical
    black_sea_found = BLACK_SEA_RU & ports_canonical
    all_ru_found = ALL_RU_PORTS & ports_canonical

    # Check for any foreign port in combined text
    has_foreign = _has_foreign_port(norm, all_ports_combined)

    # ── Far East ────────────────────────────────────────────────────────────
    if fe_ru_found:
        # Check if ONLY FE ports (cabotage = no foreign, no other RU basins)
        non_fe_ru = all_ru_found - FAR_EAST_RU
        if not has_foreign and not non_fe_ru:
            # Pure FE cabotage
            return "ДВ каботаж"
        return "ДВ"

    # Far East without RU ports (foreign FE route)
    if _is_far_east_route(norm, all_ports_combined):
        return "ДВ без РФ"

    # ── Baltic ──────────────────────────────────────────────────────────────
    if baltic_ru_found:
        non_baltic_ru = all_ru_found - BALTIC_RU
        if not has_foreign and not non_baltic_ru:
            # Only Baltic RU ports — cabotage (SPB ↔ KGD ring)
            return "Балтика каботаж"
        return "Балтийский"

    # ── Black Sea / Novorossiysk ─────────────────────────────────────────────
    if black_sea_found:
        return "Новороссийск"

    # ── Other RU (Murmansk, etc.) ────────────────────────────────────────────
    if all_ru_found:
        return "ДВ"  # Default RU to ДВ if unmatched

    # No RU ports at all — transit
    if all_ports_combined:
        return "Транзит"

    return "Неизвестно"


def _has_foreign_port(norm_set: set, all_ports: list) -> bool:
    """Check if there are any clearly foreign (non-RU) ports."""
    foreign_city_hints = {
        "hamburg", "rotterdam", "antwerp", "felixstowe", "bremerhaven",
        "le havre", "algeciras", "valencia", "barcelona", "genoa",
        "piraeus", "istanbul", "mersin", "beirut", "jeddah",
        "dubai", "abu dhabi", "mundra", "nhava sheva",
        "colombo", "port klang", "laem chabang",
        "busan", "qingdao", "shanghai", "tianjin",
        "tokyo", "yokohama", "osaka",
        "new york", "los angeles", "long beach",
        "montreal", "vancouver",
        "hamburg", "котка", "хельсинки", "таллин", "рига", "клайпеда",
    }
    for hint in foreign_city_hints:
        if hint in norm_set:
            return True
    # Check for text hints in full port strings
    for p in all_ports:
        pl = p.lower()
        for hint in foreign_city_hints:
            if hint in pl:
                return True
    return False


def _is_far_east_route(norm_set: set, all_ports: list) -> bool:
    """Check if this looks like a Far East route even without RU ports."""
    for kw in FAR_EAST_KEYWORDS:
        if kw in norm_set:
            return True
    for fe in FAR_EAST_FOREIGN:
        if fe.lower() in norm_set:
            return True
    # Check port strings
    for p in all_ports:
        pl = p.lower()
        for fe in FAR_EAST_FOREIGN:
            if fe.lower() in pl:
                return True
        for kw in FAR_EAST_KEYWORDS:
            if kw in pl:
                return True
    return False
