#!/usr/bin/env python3
# =========================================================
# HELI FLIGHT QUOTE SYSTEM v1.2.1
# Built by Jetman Global
# Single-file CLI — Helicopter Charter Quotation Tool
# Missions: Pickup or Drop Off | Round Trip | Safari / Campaign
# =========================================================

import os, sys, math, csv, json, re, pathlib, datetime, urllib.parse
from typing import Dict, List, Tuple, Optional

try:
    import requests
except Exception:
    requests = None

VERSION         = "1.2.1"
BASE_AIRPORT    = "wilson"
USD_TO_KES      = 130.0

AIRCRAFT = {
    "as350": {
        "label":     "Airbus AS350 Helicopter (5 seater)",
        "speed":     120.0,
        "rate":      2200.0,
        "overnight": 300.0,
        "idle_day":  2200.0,
    }
}

MIN_CHARGEABLE_HR = 1.0
PAX_ADMIN_FEE_USD = 100.0

DATE_FMT_IN  = "%d/%m/%y"
DATE_FMT_OUT = "%d/%m/%y"

DESKTOP_DIR    = os.path.expanduser("~/Desktop")
QUOTE_FOLDER   = os.path.join(DESKTOP_DIR, "HeliFlightQuotations")
INVOICE_FOLDER = os.path.join(DESKTOP_DIR, "HeliFlightInvoices")

HELI_FLIGHT_LOGO_URL = "https://i.ibb.co/hFfr0RDx/IMG-4294.jpg"

COMPANY_FROM_BLOCK = (
    "TALC CENTRE, GROUND FLOOR\n"
    "WILSON AIRPORT\n"
    "NAIROBI, KENYA\n"
    "INFO@HELIFLIGHTAFRICA.COM\n"
    "+254 721 888 885"
)

BANK_DETAILS_BLOCK = (
    "HELIFLIGHT AIR AFRICA LTD\n"
    "FAMILY BANK  |  BANK CODE: 070  |  SWIFT: FABLKENA\n"
    "USD A/C: 012000070044\n"
    "KES A/C: 012000070043\n"
    "KENYATTA AVENUE BRANCH  |  BRANCH CODE: 012\n"
    "PAYBILL: 222111"
)

TERMS_TEXT = (
    "1. Availability - Subject to aircraft and crew availability at time of booking.\n"
    "2. Rates & Charges - Apply to general passenger flights only.\n"
    "3. Repositioning - All charter quotes include return to base unless otherwise specified.\n"
    "4. Payment Terms - 40% deposit required to confirm; balance payable prior to departure.\n"
    "5. Cancellations - Cancelled bookings attract 20% surcharge; further charges may apply.\n"
    "6. Operational Flexibility - Flights subject to weather, ATC, and operational restrictions.\n"
    "7. Fuel - Fuel costs included in quoted hourly rate."
)

DOC_COUNTERS_FILE = ".hf_doc_counters.json"
DOC_INDEX_FILE    = ".hf_doc_index.json"

def _today_long(): return datetime.date.today().strftime("%b %d, %Y")
def _yyyymmdd():   return datetime.date.today().strftime("%Y%m%d")
def norm(s):       return (s or "").strip().lower()
def ceil_0_1(h):   return math.ceil((h or 0.0) * 10) / 10
def _fmt_usd(x):   return f"USD {float(x):,.2f}"

# =========================================================
# SECTION 2 — AIRPORTS DATABASE
# =========================================================

AIRPORTS: Dict[str, Dict] = {}

USER_AIRPORTS: Dict[str, Dict] = {}
USER_AIRPORTS_FILE = "hf_airports_user.csv"

def _aliases_from_str(s):
    if not s: return []
    return [x.strip().lower() for x in s.split(";") if x.strip()]

def _aliases_to_str(a):
    return ";".join(sorted({x.strip().lower() for x in (a or []) if x.strip()}))

def _read_csv(path):
    p = pathlib.Path(path)
    if not p.exists(): return {}
    out = {}
    with p.open("r", newline="") as f:
        for row in csv.DictReader(f):
            k = norm(row.get("name"))
            if not k: continue
            try:
                out[k] = {"lat": float(row["lat"]), "lon": float(row["lon"]),
                           "aliases": _aliases_from_str(row.get("aliases", ""))}
            except: pass
    return out

def _write_csv(path, data):
    rows = [{"name": k, "lat": v["lat"], "lon": v["lon"],
             "aliases": _aliases_to_str(v.get("aliases", []))}
            for k, v in sorted(data.items())]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["name", "lat", "lon", "aliases"])
        w.writeheader(); w.writerows(rows)

def load_airports():
    global USER_AIRPORTS
    USER_AIRPORTS = _read_csv(USER_AIRPORTS_FILE)

def save_user_airports():
    _write_csv(USER_AIRPORTS_FILE, USER_AIRPORTS)

def _resolve_key(q):
    q = norm(q)
    if not q: return None
    for src in (USER_AIRPORTS, AIRPORTS):
        if q in src: return q
        for k, v in src.items():
            if q in (v.get("aliases") or []): return k
    toks = [t for t in q.split() if t]
    for src in (USER_AIRPORTS, AIRPORTS):
        for k in src:
            if all(t in k for t in toks): return k
        for k in src:
            if q in k: return k
    return None

def lookup_coords(name):
    k = _resolve_key(name)
    if not k: raise ValueError(f"Location '{name}' not found.")
    rec = USER_AIRPORTS.get(k) or AIRPORTS.get(k)
    return float(rec["lat"]), float(rec["lon"])

def get_airport_record(name):
    k = _resolve_key(name)
    return (USER_AIRPORTS.get(k) or AIRPORTS.get(k)) if k else None

def add_airport(name, lat, lon, aliases=None):
    k = norm(name)
    USER_AIRPORTS[k] = {"lat": float(lat), "lon": float(lon),
                        "aliases": [a.strip().lower() for a in (aliases or []) if a.strip()]}
    save_user_airports()

def edit_airport(name_or_alias, new_name=None, lat=None, lon=None,
                 add_aliases=None, remove_aliases=None, set_aliases=None):
    k = _resolve_key(name_or_alias)
    if not k: raise ValueError("Location not found.")
    rec = (USER_AIRPORTS.get(k) or AIRPORTS.get(k)).copy()
    rec["aliases"] = [a.lower() for a in rec.get("aliases", [])]
    if lat is not None: rec["lat"] = float(lat)
    if lon is not None: rec["lon"] = float(lon)
    if set_aliases is not None:
        rec["aliases"] = [a.strip().lower() for a in set_aliases if a.strip()]
    else:
        if add_aliases:
            for a in add_aliases:
                a = a.strip().lower()
                if a and a not in rec["aliases"]: rec["aliases"].append(a)
        if remove_aliases:
            rem = {a.strip().lower() for a in remove_aliases if a.strip()}
            rec["aliases"] = [a for a in rec["aliases"] if a not in rem]
    newk = norm(new_name) if new_name else k
    USER_AIRPORTS[newk] = rec
    if k in USER_AIRPORTS and newk != k: del USER_AIRPORTS[k]
    save_user_airports()

def delete_airport(name_or_alias):
    k = _resolve_key(name_or_alias)
    if not k or k not in USER_AIRPORTS:
        raise ValueError("Only user-added locations can be deleted.")
    del USER_AIRPORTS[k]; save_user_airports()

# =========================================================
# SECTION 3 — GEOMETRY & MAP PIN PARSING
# =========================================================

R_NM = 3440.065

def haversine_nm(a_lat, a_lon, b_lat, b_lon):
    p1 = math.radians(a_lat); p2 = math.radians(b_lat)
    dphi = math.radians(b_lat - a_lat); dl = math.radians(b_lon - a_lon)
    x = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R_NM * 2 * math.atan2(math.sqrt(x), math.sqrt(1 - x))

def parse_map_pin(s):
    s = (s or "").strip()
    # Strip + signs Google adds between coordinates
    s = s.replace(",+", ",").replace("%2C+", ",")

    # Format 1: raw lat,lon
    m = re.match(r'^\s*([-+]?\d+(\.\d+)?)\s*,\s*([-+]?\d+(\.\d+)?)\s*$', s)
    if m: return float(m.group(1)), float(m.group(3))

    try:
        u = urllib.parse.urlparse(s)
        q = urllib.parse.parse_qs(u.query)

        # Format 2: ?q=lat,lon
        if "q" in q:
            m = re.match(r'^\s*([-+]?\d+(\.\d+)?)\s*,\s*([-+]?\d+(\.\d+)?)\s*$', q["q"][0])
            if m: return float(m.group(1)), float(m.group(3))

        # Format 3: /@lat,lon,zoom
        m2 = re.search(r'@([-+]?\d+(\.\d+)?),([-+]?\d+(\.\d+)?),', u.path)
        if m2: return float(m2.group(1)), float(m2.group(3))

        # Format 4: !3d!4d encoding
        m4 = re.search(r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', s)
        if m4: return float(m4.group(1)), float(m4.group(2))

        # Format 5: /maps/search/lat,lon
        m5 = re.search(r'/maps/search/([-+]?\d+\.\d+),([-+]?\d+\.\d+)', s)
        if m5: return float(m5.group(1)), float(m5.group(2))

        # Format 6: /maps/place/.../@lat,lon
        m6 = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', s)
        if m6: return float(m6.group(1)), float(m6.group(2))

    except: pass
    raise ValueError("Enter 'lat,lon' or a Google Maps URL with coordinates.")

def _extract_place_name(url: str) -> Optional[str]:
    try:
        u = urllib.parse.urlparse(url)
        q = urllib.parse.parse_qs(u.query)
        if "q" in q and q["q"][0]:
            return q["q"][0].strip()
    except: pass
    return None

def _resolve_short_url(url: str) -> str:
    if requests and ("goo.gl" in url or "maps.app" in url):
        try:
            r = requests.get(url, allow_redirects=True, timeout=5,
                           headers={"User-Agent": "Mozilla/5.0"})
            resolved = r.url
            # Strip + signs
            resolved = resolved.replace(",+", ",").replace("%2C+", ",")
            return resolved
        except: pass
    return url

def _to_coord(s):
    try:
        lat, lon = parse_map_pin(s)
        return (f"{lat:.5f},{lon:.5f} (GPS)", lat, lon, True)
    except:
        lat, lon = lookup_coords(s)
        return (s.strip().title(), lat, lon, False)

# =========================================================
# SECTION 4 — MISSION CALCULATIONS
# =========================================================

def _compute_leg(o_lat, o_lon, d_lat, d_lon, speed):
    nm = haversine_nm(o_lat, o_lon, d_lat, d_lon)
    hrs = round(max(nm / speed, 0.0), 4)
    return round(nm, 1), hrs

def _flight_cost(hrs, rate):
    return round(hrs * rate, 2)

def compute_one_way(pickup, dropoff, ac_key="as350"):
    prof = AIRCRAFT[ac_key]
    speed, rate = prof["speed"], prof["rate"]
    src = _to_coord(pickup)
    dst = _to_coord(dropoff)

    if abs(src[1] - dst[1]) < 1e-4 and abs(src[2] - dst[2]) < 1e-4:
        raise ValueError(f"Pickup and drop-off are the same location ({src[0]}). Please enter two different locations.")

    base_lat, base_lon = lookup_coords(BASE_AIRPORT)
    segments = []

    if not (abs(src[1] - base_lat) < 1e-4 and abs(src[2] - base_lon) < 1e-4):
        nm_p, hrs_p = _compute_leg(base_lat, base_lon, src[1], src[2], speed)
        segments.append({"type": "positioning", "origin": "Wilson Airport",
                         "destination": src[0], "nm": nm_p, "hours": hrs_p,
                         "cost": _flight_cost(hrs_p, rate), "date": None})

    nm_r, hrs_r = _compute_leg(src[1], src[2], dst[1], dst[2], speed)
    segments.append({"type": "revenue", "origin": src[0], "destination": dst[0],
                     "nm": nm_r, "hours": hrs_r,
                     "cost": _flight_cost(hrs_r, rate), "date": None})

    if not (abs(dst[1] - base_lat) < 1e-4 and abs(dst[2] - base_lon) < 1e-4):
        nm_d, hrs_d = _compute_leg(dst[1], dst[2], base_lat, base_lon, speed)
        segments.append({"type": "depositioning", "origin": dst[0],
                         "destination": "Wilson Airport",
                         "nm": nm_d, "hours": hrs_d,
                         "cost": _flight_cost(hrs_d, rate), "date": None})

    total_hrs = sum(s["hours"] for s in segments)
    billed = ceil_0_1(max(total_hrs, MIN_CHARGEABLE_HR))
    flight_cost = _flight_cost(billed, rate)
    total = round(flight_cost + PAX_ADMIN_FEE_USD, 2)

    return {"mission": "one_way", "aircraft": prof["label"], "ac_key": ac_key,
            "segments": segments, "billed_hours": billed, "flight_cost": flight_cost,
            "pax_fees": PAX_ADMIN_FEE_USD, "waiting_usd": 0.0,
            "overnight_usd": 0.0, "total_usd": total}

def compute_return(pickup, dropoff, depart_str, return_str, ac_key="as350"):
    prof = AIRCRAFT[ac_key]
    speed, rate = prof["speed"], prof["rate"]
    ov_rate = prof["overnight"]
    idle_rate = prof["idle_day"]

    try:
        d0 = datetime.datetime.strptime(depart_str, DATE_FMT_IN).date()
        d1 = datetime.datetime.strptime(return_str, DATE_FMT_IN).date()
    except:
        raise ValueError("Dates must be DD/MM/YY")

    wait_days = max((d1 - d0).days, 0)

    if wait_days >= 3:
        drop = compute_one_way(pickup, dropoff, ac_key)
        for s in drop["segments"]:
            if s["type"] == "revenue": s["date"] = d0.strftime(DATE_FMT_OUT)
        pick = compute_one_way(dropoff, pickup, ac_key)
        for s in pick["segments"]:
            if s["type"] == "revenue": s["date"] = d1.strftime(DATE_FMT_OUT)
        return {"mission": "pick_and_drop", "drop": drop, "pick": pick,
                "warning": "Stay exceeds 2 nights - converted to Pick & Drop.",
                "total_usd": round(drop["total_usd"] + pick["total_usd"], 2)}

    src = _to_coord(pickup)
    dst = _to_coord(dropoff)
    base_lat, base_lon = lookup_coords(BASE_AIRPORT)
    segments = []

    if not (abs(src[1] - base_lat) < 1e-4 and abs(src[2] - base_lon) < 1e-4):
        nm_p, hrs_p = _compute_leg(base_lat, base_lon, src[1], src[2], speed)
        segments.append({"type": "positioning", "origin": "Wilson Airport",
                         "destination": src[0], "nm": nm_p, "hours": hrs_p,
                         "cost": _flight_cost(hrs_p, rate), "date": None})

    nm1, h1 = _compute_leg(src[1], src[2], dst[1], dst[2], speed)
    segments.append({"type": "revenue", "origin": src[0], "destination": dst[0],
                     "nm": nm1, "hours": h1, "cost": _flight_cost(h1, rate),
                     "date": d0.strftime(DATE_FMT_OUT)})

    waiting = 0.0
    overnight = 0.0

    if wait_days == 1:
        overnight += ov_rate
        segments.append({"note": f"Overnight crew per diem - night of {d0.strftime(DATE_FMT_OUT)}",
                          "cost": round(ov_rate, 2)})
    elif wait_days == 2:
        overnight += ov_rate * 2
        waiting += idle_rate
        segments.append({"note": f"Overnights - {d0.strftime(DATE_FMT_OUT)} and {(d0 + datetime.timedelta(days=1)).strftime(DATE_FMT_OUT)}",
                          "cost": round(ov_rate * 2, 2)})
        segments.append({"note": f"Full idle day - {(d0 + datetime.timedelta(days=1)).strftime(DATE_FMT_OUT)}",
                          "cost": round(idle_rate, 2)})

    nm2, h2 = _compute_leg(dst[1], dst[2], src[1], src[2], speed)
    segments.append({"type": "revenue", "origin": dst[0], "destination": src[0],
                     "nm": nm2, "hours": h2, "cost": _flight_cost(h2, rate),
                     "date": d1.strftime(DATE_FMT_OUT)})

    if not (abs(src[1] - base_lat) < 1e-4 and abs(src[2] - base_lon) < 1e-4):
        nm_d, hrs_d = _compute_leg(src[1], src[2], base_lat, base_lon, speed)
        segments.append({"type": "depositioning", "origin": src[0],
                         "destination": "Wilson Airport",
                         "nm": nm_d, "hours": hrs_d,
                         "cost": _flight_cost(hrs_d, rate), "date": None})

    total_hrs = sum(s["hours"] for s in segments if s.get("type") in
                    ("positioning", "revenue", "depositioning"))
    billed = ceil_0_1(max(total_hrs, MIN_CHARGEABLE_HR))
    flight_cost = _flight_cost(billed, rate)
    total = round(flight_cost + PAX_ADMIN_FEE_USD + waiting + overnight, 2)

    return {"mission": "return", "aircraft": prof["label"], "ac_key": ac_key,
            "segments": segments, "billed_hours": billed, "flight_cost": flight_cost,
            "pax_fees": PAX_ADMIN_FEE_USD, "waiting_usd": round(waiting, 2),
            "overnight_usd": round(overnight, 2), "total_usd": total}

def compute_safari(legs, ac_key="as350"):
    prof = AIRCRAFT[ac_key]
    speed, rate = prof["speed"], prof["rate"]
    ov_rate = prof["overnight"]
    idle_rate = prof["idle_day"]

    if not legs:
        raise ValueError("Safari requires at least one leg.")

    parsed = []
    for L in legs:
        try:
            d = datetime.datetime.strptime(L["date"], DATE_FMT_IN).date()
        except:
            raise ValueError(f"Invalid date '{L.get('date')}'. Use DD/MM/YY.")
        parsed.append({"origin": L["origin"].strip(),
                       "destination": L["destination"].strip(), "date": d})

    span = (parsed[-1]["date"] - parsed[0]["date"]).days + 1
    if span > 7:
        return {"error": f"Safari span is {span} days - exceeds 7-day maximum."}

    segments = []
    waiting = 0.0

    first_src = _to_coord(parsed[0]["origin"])
    base_lat, base_lon = lookup_coords(BASE_AIRPORT)

    if not (abs(first_src[1] - base_lat) < 1e-4 and abs(first_src[2] - base_lon) < 1e-4):
        nm_p, hrs_p = _compute_leg(base_lat, base_lon, first_src[1], first_src[2], speed)
        segments.append({"type": "positioning", "origin": "Wilson Airport",
                         "destination": first_src[0], "nm": nm_p, "hours": hrs_p,
                         "cost": _flight_cost(hrs_p, rate), "date": None})

    for i, leg in enumerate(parsed):
        src = _to_coord(leg["origin"])
        dst = _to_coord(leg["destination"])
        nm, hrs = _compute_leg(src[1], src[2], dst[1], dst[2], speed)
        segments.append({"type": "revenue", "origin": src[0], "destination": dst[0],
                         "nm": nm, "hours": hrs, "cost": _flight_cost(hrs, rate),
                         "date": leg["date"].strftime(DATE_FMT_OUT)})

        if i < len(parsed) - 1:
            nxt = parsed[i + 1]
            idle = (nxt["date"] - leg["date"]).days - 1
            if idle > 2:
                return {"error": f"Idle gap of {idle} days between legs - maximum is 2."}
            if idle > 0:
                idle_cost = idle_rate * idle
                waiting += idle_cost
                label = "day" if idle == 1 else "days"
                segments.append({"note": f"{idle} idle {label} - {leg['date'].strftime(DATE_FMT_OUT)} to {nxt['date'].strftime(DATE_FMT_OUT)}",
                                  "cost": round(idle_cost, 2)})
            nxt_src = _to_coord(nxt["origin"])
            if norm(leg["destination"]) != norm(nxt["origin"]):
                nm_r, hrs_r = _compute_leg(dst[1], dst[2], nxt_src[1], nxt_src[2], speed)
                segments.append({"type": "repositioning", "origin": dst[0],
                                 "destination": nxt_src[0], "nm": nm_r, "hours": hrs_r,
                                 "cost": _flight_cost(hrs_r, rate),
                                 "date": nxt["date"].strftime(DATE_FMT_OUT)})

    last_dst = _to_coord(parsed[-1]["destination"])
    if not (abs(last_dst[1] - base_lat) < 1e-4 and abs(last_dst[2] - base_lon) < 1e-4):
        nm_d, hrs_d = _compute_leg(last_dst[1], last_dst[2], base_lat, base_lon, speed)
        segments.append({"type": "depositioning", "origin": last_dst[0],
                         "destination": "Wilson Airport",
                         "nm": nm_d, "hours": hrs_d,
                         "cost": _flight_cost(hrs_d, rate), "date": None})

    nights = max((parsed[-1]["date"] - parsed[0]["date"]).days, 0)
    overnight_usd = round(nights * ov_rate, 2)
    total_hrs = sum(s["hours"] for s in segments if s.get("type") in
                    ("positioning", "revenue", "repositioning", "depositioning"))
    billed = ceil_0_1(max(total_hrs, MIN_CHARGEABLE_HR))
    flight_cost = _flight_cost(billed, rate)
    total = round(flight_cost + PAX_ADMIN_FEE_USD + waiting + overnight_usd, 2)

    return {"mission": "safari", "aircraft": prof["label"], "ac_key": ac_key,
            "segments": segments, "billed_hours": billed, "flight_cost": flight_cost,
            "pax_fees": PAX_ADMIN_FEE_USD, "waiting_usd": round(waiting, 2),
            "overnight_usd": overnight_usd, "total_usd": total}

# =========================================================
# SECTION 5 — CLI PRINTING
# =========================================================

def _leg_tag(t):
    return {"positioning": " [Positioning]", "repositioning": " [Repositioning]",
            "depositioning": " [Depositioning]"}.get((t or "").lower(), "")

def _print_segments(segments):
    for s in segments or []:
        if "note" in s:
            cost_str = f"  ->  {_fmt_usd(s['cost'])}" if s.get("cost") else ""
            print(f"    NOTE: {s['note']}{cost_str}")
            continue
        tag = _leg_tag(s.get("type"))
        date = f"  [{s['date']}]" if s.get("date") else ""
        print(f"    {s.get('origin','')}  ->  {s.get('destination','')}{tag}"
              f"  |  {float(s.get('hours',0)):.1f} hrs  |  {float(s.get('nm',0)):.1f} NM{date}")

def _sum_flight(segments):
    nm = sum(float(s.get("nm", 0) or 0) for s in segments if s.get("type"))
    hrs = sum(float(s.get("hours", 0) or 0) for s in segments if s.get("type"))
    return round(nm, 1), round(hrs, 1)

def _print_billing(result):
    print("\n  -- BILLING --")
    ac_key = result.get("ac_key", "as350")
    rate = AIRCRAFT.get(ac_key, {}).get("rate", 2200.0)
    billed = float(result.get("billed_hours", 0))
    print(f"  Aircraft Rental:    {billed:.1f} hrs @ USD {rate:,.0f}/hr = {_fmt_usd(result.get('flight_cost', 0))}")
    if result.get("pax_fees"):
        print(f"  Pax / Admin Fees:   {_fmt_usd(result['pax_fees'])}")
    if float(result.get("waiting_usd", 0) or 0) > 0:
        print(f"  Idle Day Charges:   {_fmt_usd(result['waiting_usd'])}")
    if float(result.get("overnight_usd", 0) or 0) > 0:
        print(f"  Overnight Per Diem: {_fmt_usd(result['overnight_usd'])}")
    print(f"  {'--'*21}")
    print(f"  TOTAL:              {_fmt_usd(result['total_usd'])}")

def print_summary(result):
    print("\n" + "="*55)
    print("  HELI FLIGHT - CHARTER QUOTE")
    print("="*55)

    if "error" in result:
        print(f"\n  ERROR: {result['error']}\n"); return

    mission = result.get("mission", "")

    if mission == "pick_and_drop":
        drop = result["drop"]; pick = result["pick"]
        print(f"\n  Aircraft:  {drop.get('aircraft', '')}")
        if result.get("warning"): print(f"\n  WARNING: {result['warning']}")
        print("\n  -- DROP LEG --")
        _print_segments(drop["segments"])
        nm_d, hrs_d = _sum_flight(drop["segments"])
        print(f"\n  Subtotal:  {nm_d:.1f} NM  |  {hrs_d:.1f} hrs  |  {_fmt_usd(drop['total_usd'])}")
        print("\n  -- PICK LEG --")
        _print_segments(pick["segments"])
        nm_p, hrs_p = _sum_flight(pick["segments"])
        print(f"\n  Subtotal:  {nm_p:.1f} NM  |  {hrs_p:.1f} hrs  |  {_fmt_usd(pick['total_usd'])}")
        print(f"\n  COMBINED TOTAL: {_fmt_usd(result['total_usd'])}")
    else:
        print(f"\n  Aircraft:  {result.get('aircraft', '')}")
        print(f"  Mission:   {mission.replace('_', ' ').title()}\n")
        _print_segments(result.get("segments", []))
        nm, hrs = _sum_flight(result.get("segments", []))
        print(f"\n  Distance: {nm:.1f} NM  |  Flight Time: {hrs:.1f} hrs")
        _print_billing(result)

    print("\n  -- NOTES --")
    print("  * Quote valid 48 hours from issue.")
    print("  * 40% deposit required to confirm booking.")
    print("  * Subject to weather, ATC & crew availability.")
    print("="*55)

# =========================================================
# SECTION 6 — PDF GENERATION
# =========================================================

def _read_json(path, default):
    try: return json.loads(pathlib.Path(path).read_text())
    except: return default

def _write_json(path, data):
    pathlib.Path(path).write_text(json.dumps(data, indent=2))

def _next_doc_number(prefix):
    for folder in (QUOTE_FOLDER, INVOICE_FOLDER):
        pathlib.Path(folder).mkdir(parents=True, exist_ok=True)
    counters = _read_json(DOC_COUNTERS_FILE, {})
    today = _yyyymmdd()
    key = f"{prefix}_{today}"
    seq = int(counters.get(key, 0)) + 1
    counters[key] = seq
    _write_json(DOC_COUNTERS_FILE, counters)
    return f"{prefix}-{today}-{seq:04d}"

def _routing_lines(segments):
    lines = []
    for s in segments or []:
        if "note" in s: continue
        tag = _leg_tag(s.get("type")).strip(" []")
        date = s.get("date", "")
        hrs = float(s.get("hours", 0) or 0)
        nm = float(s.get("nm", 0) or 0)
        line = f"{s.get('origin','')} -> {s.get('destination','')}  {hrs:.1f} hrs | {nm:.1f} NM"
        if tag: line += f" ({tag})"
        if date: line = f"{date}  {line}"
        lines.append(line)
    return lines

def _build_description(result):
    mission = result.get("mission", "")
    aircraft = (result.get("aircraft") or
                (result.get("drop") or {}).get("aircraft") or "")
    lines = [f"Equipment: {aircraft}", "Routing:"]
    if mission == "pick_and_drop":
        drop = result.get("drop") or {}
        pick = result.get("pick") or {}
        d_segs = drop.get("segments") or []
        p_segs = pick.get("segments") or []
        d_date = next((s["date"] for s in d_segs if s.get("type") == "revenue" and s.get("date")), "")
        p_date = next((s["date"] for s in p_segs if s.get("type") == "revenue" and s.get("date")), "")
        lines.append(f"Drop {d_date}".strip())
        lines += _routing_lines(d_segs)
        lines.append(f"Pick {p_date}".strip())
        lines += _routing_lines(p_segs)
    else:
        lines += _routing_lines(result.get("segments") or [])
    return "\n".join(lines)

def load_invoice_api_key():
    env = os.environ.get("INVGEN_API_KEY")
    if env: return env.strip()
    f = pathlib.Path(".invoice_api_key")
    if f.exists(): return f.read_text().strip()
    return None

def build_pdf_payload(doc_type, client_name, client_email, client_phone,
                       user_note, discount_usd, result, extras=None):
    header = "INVOICE" if doc_type == "I" else "QUOTATION"
    number = _next_doc_number("HF-INV" if doc_type == "I" else "HF-QUO")
    mission = (result or {}).get("mission", "")

    if mission == "pick_and_drop":
        drop = result.get("drop") or {}
        pick = result.get("pick") or {}
        billed = float(drop.get("billed_hours", 0)) + float(pick.get("billed_hours", 0))
        pax = float(drop.get("pax_fees", 0)) + float(pick.get("pax_fees", 0))
        waiting = 0.0; overnight = 0.0
        aircraft = drop.get("aircraft", "") or pick.get("aircraft", "")
        ac_key = drop.get("ac_key", "as350")
    else:
        billed = float(result.get("billed_hours", 0))
        pax = float(result.get("pax_fees", 0))
        waiting = float(result.get("waiting_usd", 0) or 0)
        overnight = float(result.get("overnight_usd", 0) or 0)
        ac_key = result.get("ac_key", "as350")

    rate = float(AIRCRAFT.get(ac_key, {}).get("rate", 2200.0))
    ov_rate = float(AIRCRAFT.get(ac_key, {}).get("overnight", 300.0))
    idle_rate = float(AIRCRAFT.get(ac_key, {}).get("idle_day", 2200.0))

    desc = _build_description(result)
    if user_note: desc += f"\n\nNote: {user_note}"

    items = [{"name": "Aircraft Charter - Airbus AS350",
              "description": desc, "quantity": billed, "unit_cost": rate}]
    if pax:
        items.append({"name": "Passenger Taxes & Admin Fees", "quantity": 1, "unit_cost": pax})
    idle_qty = round(waiting / idle_rate) if idle_rate > 0 and waiting else 0
    if idle_qty > 0:
        items.append({"name": "Full Day Waiting / Idle Charges", "quantity": idle_qty, "unit_cost": idle_rate})
    nights_qty = round(overnight / ov_rate) if ov_rate > 0 and overnight else 0
    if nights_qty > 0:
        items.append({"name": "Overnight Crew Per Diem", "quantity": nights_qty, "unit_cost": ov_rate})
    if extras: items.extend(extras)

    to = client_name
    if client_phone: to += f"\nTel: {client_phone}"
    if client_email: to += f"\nEmail: {client_email}"

    discount_amount = 0.0
    try:
        val = float((discount_usd or "0").strip())
        if val > 0: discount_amount = val
    except: pass

    payload = {
        "logo": HELI_FLIGHT_LOGO_URL, "from": COMPANY_FROM_BLOCK, "to": to,
        "number": number, "date": _today_long(), "header": header, "currency": "USD",
        "items": items, "discounts": discount_amount,
        "notes_title": "BANK DETAILS", "notes": BANK_DETAILS_BLOCK,
        "terms_title": "TERMS & CONDITIONS", "terms": TERMS_TEXT,
        "fields": {"tax": False, "discounts": True, "shipping": False}
    }

    folder = INVOICE_FOLDER if doc_type == "I" else QUOTE_FOLDER
    out_path = f"{folder}/{number}.pdf"
    return payload, out_path, number

def generate_pdf(payload, out_path):
    if not requests:
        raise RuntimeError("Install requests: pip3 install requests")
    api_key = load_invoice_api_key()
    if not api_key:
        raise RuntimeError("No API key. Set INVGEN_API_KEY or create .invoice_api_key file.")
    pathlib.Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    resp = requests.post("https://invoice-generator.com", json=payload,
                         headers={"Authorization": f"Bearer {api_key}"})
    if resp.status_code != 200:
        raise RuntimeError(f"API error ({resp.status_code}): {resp.text}")
    pathlib.Path(out_path).write_bytes(resp.content)
# SECTION 7 — PDF PROMPT
# =========================================================

def ask_pdf_export(result):
    if isinstance(result, dict) and result.get("error"): return
    ans = input("\nGenerate PDF? (Y/N): ").strip().lower()
    if ans != "y": return
    doc = input("I = Invoice  |  Q = Quotation: ").strip().upper()
    if doc not in ("I", "Q"): print("Cancelled."); return
    name = input("Client Name: ").strip()
    if not name: print("Name required."); return
    email = input("Client Email (optional): ").strip()
    phone = input("Client Phone (optional): ").strip()
    note = input("Special Notes (optional): ").strip()
    disc = input("Discount USD (optional): ").strip()
    extras = []
    more = input("Additional charges? (Y/N): ").strip().lower()
    while more == "y":
        nm = input("  Charge name: ").strip() or "Additional Charge"
        try:
            qty = float(input("  Quantity: ").strip() or "1")
            rate = float(input("  Rate USD: ").strip() or "0")
            extras.append({"name": nm, "quantity": qty, "unit_cost": rate})
        except: print("  Invalid - skipping.")
        more = input("  Add another? (Y/N): ").strip().lower()
    try:
        payload, out_path, number = build_pdf_payload(doc, name, email, phone, note, disc or "0", result, extras)
        generate_pdf(payload, out_path)
        print(f"\n  PDF saved: {out_path}")
        idx = _read_json(DOC_INDEX_FILE, [])
        idx.append({"number": number, "path": out_path,
                    "type": "INVOICE" if doc == "I" else "QUOTATION",
                    "client": name, "created_at": datetime.datetime.now().isoformat()})
        _write_json(DOC_INDEX_FILE, idx)
    except Exception as e:
        print(f"\n  PDF failed: {e}")

# =========================================================
# SECTION 8 — CLI MENU
# =========================================================

def cli_get_location(prompt_msg):
    while True:
        name = input(prompt_msg).strip()
        low = name.lower()
        if low in ("back", "home", "exit"): return low
        if not name: print("  Cannot be empty."); continue

        if "goo.gl" in name or "maps.app" in name:
            name = _resolve_short_url(name)

        try:
            lat, lon = parse_map_pin(name)
            print(f"  GPS accepted: ({lat:.5f}, {lon:.5f})")
            print(f"  WARNING: Verify coordinates against certified source (Foreflight / Garmin).")
            return name
        except:
            if "http" in name.lower():
                place = _extract_place_name(name)
                if place:
                    print(f"  URL contains place name: '{place}' - looking up in database...")
                    name = place

        try:
            lat, lon = lookup_coords(name)
            print(f"  Found '{name}': ({lat:.4f}, {lon:.4f})")
            return name
        except ValueError:
            print(f"  '{name}' not found.")
            ans = input("  Add as new airport / heliport? (Y/N): ").strip().lower()
            if ans in ("y", "yes"):
                try:
                    lat = float(input("    Latitude (certified source): ").strip())
                    lon = float(input("    Longitude (certified source): ").strip())
                    als = input("    Aliases (comma-separated, optional): ").strip()
                    add_airport(name, lat, lon,
                                [a.strip() for a in als.split(",") if a.strip()] if als else [])
                    print(f"    '{name}' added to database.")
                    return name
                except:
                    print("    Invalid coordinates - please try again.")
            else:
                print("  Enter GPS coordinates directly or type 'back'.")

def cli_menu():
    print("\n" + "="*55)
    print("  HELI FLIGHT  -  CHARTER QUOTE SYSTEM  v1.2.1")
    print("  Wilson Airport, Nairobi")
    print("="*55)
    print("  1.  Pickup or Drop Off      ( Same Day )")
    print("  2.  Round Trip              ( Same or different day return )")
    print("  3.  Safari / Campaign       ( Multiple stops / days )")
    print("  4.  Exit")
    print("-"*55)
    while True:
        c = input("  Select (1-4): ").strip()
        if c in ("1", "2", "3", "4"): return c
        print("  Invalid - enter 1 to 4.")

def run():
    load_airports()
    print("\n  Tip: type 'back' at any prompt to return to menu.")
    while True:
        choice = cli_menu()
        try:
            if choice == "1":
                pickup = cli_get_location("  Pickup (name / GPS / Maps URL): ")
                if pickup in ("back", "home", "exit"):
                    if pickup == "exit": break
                    continue
                dropoff = cli_get_location("  Drop-off (name / GPS / Maps URL): ")
                if dropoff in ("back", "home", "exit"):
                    if dropoff == "exit": break
                    continue
                result = compute_one_way(pickup, dropoff)
                print_summary(result); ask_pdf_export(result)

            elif choice == "2":
                pickup = cli_get_location("  Pickup: ")
                if pickup in ("back", "home", "exit"):
                    if pickup == "exit": break
                    continue
                dropoff = cli_get_location("  Drop-off: ")
                if dropoff in ("back", "home", "exit"):
                    if dropoff == "exit": break
                    continue
                d0 = input("  Departure date (DD/MM/YY): ").strip()
                d1 = input("  Return date (DD/MM/YY): ").strip()
                result = compute_return(pickup, dropoff, d0, d1)
                print_summary(result); ask_pdf_export(result)

            elif choice == "3":
                try: n = int(input("  Number of legs (2-8): ").strip())
                except: print("  Invalid."); continue
                if n < 1: print("  Minimum 1 leg."); continue
                legs = []; cancel = False
                for i in range(n):
                    print(f"\n  Leg {i+1} of {n}")
                    o = cli_get_location("    Origin: ")
                    if o in ("back", "home", "exit"):
                        if o == "exit": return
                        cancel = True; break
                    d = cli_get_location("    Destination: ")
                    if d in ("back", "home", "exit"):
                        if d == "exit": return
                        cancel = True; break
                    dt = input("    Date (DD/MM/YY): ").strip()
                    legs.append({"origin": o, "destination": d, "date": dt})
                if cancel or not legs: continue
                result = compute_safari(legs)
                print_summary(result); ask_pdf_export(result)

            elif choice == "4":
                print("\n  Heli Flight Quote System - session ended.\n"); break

        except Exception as e:
            print(f"\n  Error: {e}")
            if os.environ.get("HF_DEBUG"):
                import traceback; traceback.print_exc()

        cont = input("\n  New quote? (Y/N): ").strip().lower()
        if cont not in ("y", "yes"):
            print("\n  Heli Flight Quote System - session ended.\n"); break

if __name__ == "__main__":
    run()

def _build_pdf_html(payload):
    from html import escape as esc
    doc_type = str(payload.get("header", "Invoice"))
    logo = payload.get("logo", "")
    from_block = payload.get("from", "")
    to_block = payload.get("to", "")
    number = payload.get("number", "")
    date = payload.get("date", "")
    due_date = payload.get("due_date", "")
    items = payload.get("items", [])
    discount = float(payload.get("discounts", 0) or 0)
    bank_block = payload.get("notes", "")
    terms = payload.get("terms", "")
    currency = payload.get("currency", "USD")
    from_lines = [l for l in from_block.split("\n") if l.strip()]
    company_name = from_lines[0] if from_lines else ""
    company_rest = "<br>".join(esc(l) for l in from_lines[1:]) if len(from_lines) > 1 else ""
    to_lines = [l for l in to_block.split("\n") if l.strip()]
    client_name = to_lines[0] if to_lines else ""
    client_rest = "<br>".join(esc(l) for l in to_lines[1:]) if len(to_lines) > 1 else ""
    subtotal = 0.0
    rows_html = ""
    for item in items:
        raw_name = str(item.get("name", ""))
        qty = float(item.get("quantity", 1))
        unit = float(item.get("unit_cost", 0))
        amount = round(qty * unit, 2)
        subtotal += amount
        parts = raw_name.split("\n")
        title = esc(parts[0])
        detail = "<br>".join(esc(p) for p in parts[1:] if p.strip()) if len(parts) > 1 else ""
        detail_html = f'<span class="item-detail">{detail}</span>' if detail else ""
        qty_display = int(qty) if qty == int(qty) else qty
        rows_html += f'<tr><td><span class="item-title">{title}</span>{detail_html}</td><td>{qty_display}</td><td>{currency} {unit:,.2f}</td><td>{currency} {amount:,.2f}</td></tr>'
    total = round(subtotal - discount, 2)
    discount_row = f'<div class="total-row discount"><span>Discount</span><span>&minus; {currency} {discount:,.2f}</span></div>' if discount > 0 else ""
    doc_upper = doc_type.upper()
    if doc_upper == "RECEIPT":
        total_label, date_label2, date_val2 = "Amount Received", "Payment Date", date
        show_bank, show_terms, bill_label = False, False, "Received From"
        footer_right = "Thank you for your payment."
    elif doc_upper == "INVOICE":
        total_label, date_label2, date_val2 = "Total Due", "Due", due_date
        show_bank, show_terms, bill_label = bool(bank_block), bool(terms), "Bill To"
        footer_right = ""
    else:
        total_label, date_label2, date_val2 = "Total Estimate", "Valid Until", due_date
        show_bank, show_terms, bill_label = False, bool(terms), "Prepared For"
        footer_right = "Quote valid for 48 hours from date of issue."
    bank_html = ""
    if show_bank and bank_block:
        bank_lines = "<br>".join(esc(l) for l in bank_block.split("\n") if l.strip())
        bank_html = f'<div class="bank-section"><div class="section-title">Bank Details</div><div class="bank-detail">{bank_lines}</div></div>'
    terms_html = ""
    if show_terms and terms:
        terms_lines = "<br>".join(esc(l) for l in terms.split("\n") if l.strip())
        terms_html = f'<div class="terms-section"><div class="section-title">Terms &amp; Conditions</div><div class="terms-text">{terms_lines}</div></div>'
    bottom_html = f'<div class="bottom-grid">{bank_html}{terms_html}</div>' if (bank_html or terms_html) else ""
    css = "*{box-sizing:border-box;margin:0;padding:0}@page{size:A4;margin:0}html,body{width:210mm;min-height:297mm;font-family:Arial,sans-serif;background:#fff}.accent-bar{height:2.5pt;background:#000}.page{width:210mm;min-height:297mm;background:#fff;padding:16mm 16mm 24mm;position:relative}.header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10mm;padding-bottom:8mm;border-bottom:0.5pt solid #000}.logo{height:54pt;object-fit:contain;display:block;margin-bottom:6pt}.company-block{font-size:9pt;color:#333;line-height:1.85}.company-name{font-weight:bold;color:#000;font-size:10pt;display:block;margin-bottom:1pt}.doc-type{font-size:28pt;letter-spacing:4pt;text-transform:uppercase;color:#000;line-height:1;text-align:right}.doc-number{font-size:7pt;color:#999;margin-top:6pt;letter-spacing:1pt;text-transform:uppercase;text-align:right}.meta-row{display:flex;gap:8mm;margin-bottom:8mm;align-items:flex-start}.bill-to{flex:1}.party-label{font-size:6.5pt;font-weight:bold;letter-spacing:2pt;text-transform:uppercase;color:#aaa;margin-bottom:6pt}.party-name{font-size:13pt;color:#000;margin-bottom:4pt}.party-detail{font-size:8pt;color:#666;line-height:1.9}.dates-box{flex:1.4;border:0.5pt solid #e0e0e0;display:flex}.date-item{flex:1;padding:8pt 12pt;border-right:0.5pt solid #e0e0e0}.date-item:last-child{border-right:none}.date-label{font-size:6.5pt;font-weight:bold;letter-spacing:1.5pt;text-transform:uppercase;color:#aaa;margin-bottom:4pt}.date-value{font-size:11pt;color:#000}table{width:100%;border-collapse:collapse;margin-bottom:6mm}thead tr{border-top:0.5pt solid #000;border-bottom:0.5pt solid #000}thead th{padding:6pt 9pt;font-size:6.5pt;font-weight:bold;letter-spacing:1.5pt;text-transform:uppercase;color:#000;text-align:left}thead th:nth-child(2),thead th:nth-child(3){text-align:center}thead th:last-child{text-align:right}tbody tr{border-bottom:0.5pt solid #f0f0f0}tbody td{padding:9pt 9pt;font-size:9pt;color:#111;vertical-align:top;line-height:1.6}tbody td:nth-child(2),tbody td:nth-child(3){text-align:center;color:#555}tbody td:last-child{text-align:right;font-weight:bold;white-space:nowrap}.item-title{font-weight:bold;color:#000;font-size:8.5pt;display:block;margin-bottom:3pt}.item-detail{font-size:7pt;color:#999;line-height:1.75;display:block}.totals-wrap{display:flex;justify-content:flex-end;margin-bottom:8mm}.totals{width:60mm}.total-row{display:flex;justify-content:space-between;padding:4pt 0;font-size:8pt;color:#888;border-bottom:0.5pt solid #f5f5f5}.total-row.discount{color:#c00}.total-final{display:flex;justify-content:space-between;align-items:baseline;padding:9pt 0 0;margin-top:4pt;border-top:0.5pt solid #000}.total-final-label{font-size:10pt;font-weight:bold;letter-spacing:1pt;text-transform:uppercase}.total-final-amount{font-size:14pt;font-weight:bold}.bottom-grid{display:flex;gap:8mm;margin-bottom:8mm}.bank-section{flex:1}.terms-section{flex:1.4}.section-title{font-size:6.5pt;font-weight:bold;letter-spacing:2pt;text-transform:uppercase;color:#aaa;margin-bottom:7pt;padding-bottom:5pt;border-bottom:0.5pt solid #eee}.bank-detail{font-size:7.5pt;color:#555;line-height:2}.terms-text{font-size:7pt;color:#888;line-height:1.85}.footer{position:absolute;bottom:10mm;left:16mm;right:16mm;border-top:0.5pt solid #ebebeb;padding-top:6pt;display:flex;justify-content:space-between}.footer-brand{font-size:6.5pt;color:#ccc;letter-spacing:1.5pt;text-transform:uppercase}.footer-right{font-size:6.5pt;color:#bbb;font-style:italic}"
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><style>{css}</style></head><body><div class="accent-bar"></div><div class="page"><div class="header"><div><img class="logo" src="{esc(logo)}" alt="Logo"><div class="company-block"><span class="company-name">{esc(company_name)}</span>{company_rest}</div></div><div><div class="doc-type">{esc(doc_type)}</div><div class="doc-number">Ref &mdash; {esc(number)}</div></div></div><div class="meta-row"><div class="bill-to"><div class="party-label">{esc(bill_label)}</div><div class="party-name">{esc(client_name)}</div><div class="party-detail">{client_rest}</div></div><div class="dates-box"><div class="date-item"><div class="date-label">Date</div><div class="date-value">{esc(date)}</div></div><div class="date-item"><div class="date-label">{esc(date_label2)}</div><div class="date-value">{esc(date_val2)}</div></div><div class="date-item"><div class="date-label">Currency</div><div class="date-value">{esc(currency)}</div></div></div></div><table><thead><tr><th style="width:52%">Description</th><th>Qty</th><th>Unit Rate</th><th>Amount</th></tr></thead><tbody>{rows_html}</tbody></table><div class="totals-wrap"><div class="totals"><div class="total-row"><span>Subtotal</span><span>{currency} {subtotal:,.2f}</span></div>{discount_row}<div class="total-final"><span class="total-final-label">{esc(total_label)}</span><span class="total-final-amount">{currency} {total:,.2f}</span></div></div></div>{bottom_html}<div class="footer"><div class="footer-brand">Powered by Quotecloud JG</div><div class="footer-right">{esc(footer_right)}</div></div></div></body></html>"""


def generate_pdf_weasy(payload, out_path):
    from weasyprint import HTML as WeasyprintHTML
    import pathlib
    pathlib.Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    html_string = _build_pdf_html(payload)
    WeasyprintHTML(string=html_string, base_url=None).write_pdf(out_path)
