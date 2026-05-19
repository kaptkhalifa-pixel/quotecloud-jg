# =========================================================
# QUOTECLOUD BY JETMAN GLOBAL
# app.py v2.4.9
# v2.4.9 changes:
#   - Added /expand_maps_url route for client-side Maps resolution
#   - Fixed missing @app.route decorator on /fx/rates
# =========================================================
import sys, os, json, re, pathlib, datetime
sys.path.insert(0, os.path.dirname(__file__))
from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for
from functools import wraps
import quotecloud_engine as hq

app = Flask(__name__)

OPERATOR_CONFIG_FILE = "operator_config.json"
AIRCRAFT_CONFIG_FILE = "hf_aircraft.json"
RECORDS_FILE = "qc_records.json"

def load_operator_config():
    p = pathlib.Path(OPERATOR_CONFIG_FILE)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception as e:
            print(f"ERROR loading operator config: {e}")
    return {}

OPERATOR = load_operator_config()

app.secret_key = os.environ.get("SECRET_KEY", OPERATOR.get("env", {}).get("secret_key", "qc-secret-2026"))
app.config["PERMANENT_SESSION_LIFETIME"] = datetime.timedelta(days=7)

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "AIzaSyByT9tWG6pHLXslzp5aJFElULC9oJwXu5o")
INVGEN_API_KEY = os.environ.get("INVGEN_API_KEY", "sk_elcdkPBJLZnAMEghIVyDc6llmS0iOraY")

def get_admin_user():
    return os.environ.get("ADMIN_USER", OPERATOR.get("env", {}).get("admin_user", "admin"))

def get_admin_pass():
    return os.environ.get("ADMIN_PASS", OPERATOR.get("env", {}).get("admin_pass", "changeme"))

def get_quoting_rules():
    return OPERATOR.get("quoting_rules", {
        "min_flight_hours": 1.0,
        "max_nights_before_pickup_drop": 3,
        "max_flight_hours_per_day": 10.0,
        "max_idle_days_between_legs": 1,
        "show_distance_to_client": False,
        "ground_time_buffer_enabled": False,
        "ground_time_buffer_minutes": 0,
        "currency": "USD",
        "currency_symbol": "$",
        "quote_validity_hours": 48
    })

def get_geo_lock():
    return OPERATOR.get("geo_lock", {
        "enabled": True,
        "region_name": "Kenya",
        "preset": "kenya",
        "lat_min": -5.0,
        "lat_max": 5.0,
        "lon_min": 33.5,
        "lon_max": 42.0
    })

def get_whatsapp():
    return OPERATOR.get("contact", {}).get("whatsapp", "")

def get_aircraft_mode():
    return OPERATOR.get("aircraft_mode", "helicopter")

def get_region_name():
    return OPERATOR.get("geo_lock", {}).get("region_name", "Kenya")

def get_company_from_block():
    c = OPERATOR.get("contact", {})
    lines = [
        OPERATOR.get("company_name", ""),
        c.get("address", ""),
        c.get("email", ""),
        c.get("phone", "")
    ]
    return "\n".join([l for l in lines if l])

def get_bank_details_block():
    bank = OPERATOR.get("bank", {})
    lines = []
    if bank.get("account_name"):
        lines.append(bank["account_name"].upper())
    if bank.get("bank_name") and bank.get("branch"):
        lines.append(f"{bank['bank_name'].upper()} | BANK CODE: {bank.get('branch','').split(',')[-1].strip()} | SWIFT: {bank.get('swift','')}")
    elif bank.get("bank_name"):
        lines.append(bank["bank_name"].upper())
    if bank.get("usd_account"):
        lines.append(f"USD A/C: {bank['usd_account']}")
    if bank.get("kes_account"):
        lines.append(f"KES A/C: {bank['kes_account']}")
    if bank.get("branch"):
        lines.append(f"{bank['branch'].upper()}")
    if bank.get("paybill"):
        lines.append(f"PAYBILL: {bank['paybill']}")
    return "\n".join(lines)

hq.load_airports()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if (request.form.get("username") == get_admin_user() and
                request.form.get("password") == get_admin_pass()):
            remember = request.form.get("remember") == "on"
            session.permanent = remember
            session["logged_in"] = True
            return redirect(url_for("index"))
        error = "Invalid credentials. Please try again."
    return render_template("login.html", operator=OPERATOR, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

def load_aircraft():
    p = pathlib.Path(AIRCRAFT_CONFIG_FILE)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    default = {
        "as350": {
            "label": "Airbus AS350",
            "seater": 5,
            "speed": 120.0,
            "rate": 2200.0,
            "pax_fee": 100.0,
            "overnight_rate": 300.0,
            "idle_day_rate": 2200.0,
            "active": True,
            "type": "helicopter",
            "home_airstrip": "Wilson Airport, Nairobi",
            "routing_mode": "standard"
        }
    }
    pathlib.Path(AIRCRAFT_CONFIG_FILE).write_text(json.dumps(default, indent=2))
    return default

def save_aircraft(data):
    pathlib.Path(AIRCRAFT_CONFIG_FILE).write_text(json.dumps(data, indent=2))

def load_records():
    p = pathlib.Path(RECORDS_FILE)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return []

def save_records(records):
    pathlib.Path(RECORDS_FILE).write_text(json.dumps(records, indent=2))

def next_record_number(doc_type="Quotation"):
    records = load_records()
    prefix = OPERATOR.get("invoice", {}).get("prefix", "QC")
    year = datetime.date.today().year
    if doc_type in ("Quotation", "Quote"):
        type_code = "Q"
    elif doc_type == "Invoice":
        type_code = "I"
    elif doc_type == "Receipt":
        type_code = "R"
    else:
        type_code = "Q"
    seq = len([r for r in records
               if str(year) in r.get("number", "") and
               f"-{type_code}-" in r.get("number", "")]) + 1
    return f"{prefix}-{type_code}-{year}-{seq:03d}"

def save_record(record_type, client_name, client_email, amount, doc_number, result=None, extra=None):
    records = load_records()
    rec = {
        "number": doc_number,
        "type": record_type,
        "client_name": client_name,
        "client_email": client_email,
        "amount": round(float(amount), 2),
        "date": datetime.date.today().strftime("%d/%m/%Y"),
        "timestamp": datetime.datetime.now().isoformat(),
        "result_summary": result or {},
        "paid": False,
        "paid_amount": 0,
        "paid_date": "",
        "payment_mode": "",
        "payment_ref": "",
        "receipt_number": "",
        "payment_log": []
    }
    if extra:
        rec.update(extra)
    records.append(rec)
    save_records(records)

def check_geo_lock(lat, lon):
    geo = get_geo_lock()
    if not geo.get("enabled", True):
        return True
    return (float(geo.get("lat_min", -5.0)) <= lat <= float(geo.get("lat_max", 5.0)) and
            float(geo.get("lon_min", 33.5)) <= lon <= float(geo.get("lon_max", 42.0)))

def geo_lock_error(location_name):
    wa = get_whatsapp()
    region = get_region_name()
    wa_msg = f" Please WhatsApp us: +{wa} if you believe this is an error or to discuss a custom charter." if wa else ""
    return (f"We're sorry - '{location_name}' appears to be outside our operating region. "
            f"Our services are currently available within {region}.{wa_msg}")

def reverse_geocode(lat, lon):
    try:
        import requests as req
        r = req.get("https://maps.googleapis.com/maps/api/geocode/json",
                    params={"latlng": f"{lat},{lon}", "key": GOOGLE_API_KEY, "region": "ke"},
                    timeout=5)
        data = r.json()
        if data.get("status") == "OK":
            components = data["results"][0]["address_components"]
            locality = next((c["long_name"] for c in components if "locality" in c["types"]), None)
            admin = next((c["long_name"] for c in components if "administrative_area_level_1" in c["types"]), None)
            if locality and admin and "+" not in locality:
                return f"Pin, {locality}, {admin}"
            if locality and "+" not in locality:
                return f"Pin, {locality}"
            addr = data["results"][0].get("formatted_address", "")
            if addr and "+" not in addr:
                return f"Pin, {addr}"
    except Exception:
        pass
    return None

def is_maps_url(s):
    return any(x in s for x in ["google.com/maps", "goo.gl", "maps.app", "maps.google"])

def resolve_location(s, user_label=None):
    s = (s or "").strip()
    if not s:
        return None, s
    original_input = user_label or s
    if "goo.gl" in s or "maps.app" in s:
        try:
            import requests as req
            r = req.get(s, allow_redirects=True, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
            s = r.url
        except Exception:
            pass
    s = s.replace(",+", ",").replace("%2C+", ",")
    try:
        lat, lon = hq.parse_map_pin(s)
        if not check_geo_lock(lat, lon):
            return None, s
        display = reverse_geocode(lat, lon) or f"Pin, {lat:.5f}, {lon:.5f}"
        return display, f"{lat},{lon}"
    except Exception:
        pass
    if is_maps_url(s):
        return None, s
    place = hq._extract_place_name(s)
    if place:
        s = place
    try:
        lat, lon = hq.lookup_coords(s)
        if not check_geo_lock(lat, lon):
            return None, s
        return s.title(), s
    except Exception:
        pass
    clean = s.strip()
    if len(clean) < 3:
        return None, s
    if not re.match(r"^[a-zA-Z0-9\s\-'\,\.]+$", clean):
        return None, s
    if re.match(r"^[0-9\s]+$", clean):
        return None, s
    try:
        import requests as req
        region = OPERATOR.get("geo_lock", {}).get("region_name", "Kenya")
        query = clean if region.lower() in clean.lower() else clean + f" {region}"
        r = req.get("https://maps.googleapis.com/maps/api/geocode/json",
                    params={"address": query, "key": GOOGLE_API_KEY, "region": "ke"}, timeout=5)
        data = r.json()
        if data.get("status") == "OK":
            loc = data["results"][0]["geometry"]["location"]
            lat, lon = float(loc["lat"]), float(loc["lng"])
            if check_geo_lock(lat, lon):
                return original_input.strip().title(), f"{lat},{lon}"
    except Exception:
        pass
    return None, s

def _coords_match(a, b):
    try:
        ap = a.replace(" (GPS)", "").split(",")
        bp = b.replace(" (GPS)", "").split(",")
        if len(ap) == 2 and len(bp) == 2:
            return (abs(float(ap[0]) - float(bp[0])) < 0.001 and
                    abs(float(ap[1]) - float(bp[1])) < 0.001)
    except Exception:
        pass
    return False

def _replace_with_display(val, display_map):
    if not val:
        return val
    if val in display_map:
        return display_map[val]
    for k, v in display_map.items():
        if _coords_match(val, k):
            return v
    return val

def apply_display_names(result, display_map):
    if not result or not display_map:
        return result
    for s in (result.get("segments") or []):
        for field in ("origin", "destination"):
            s[field] = _replace_with_display(s.get(field, ""), display_map)
    for key in ("drop", "pick", "option_a", "option_b"):
        if result.get(key):
            apply_display_names(result[key], display_map)
    return result

def enrich_segments(segments):
    for s in (segments or []):
        if s.get("nm") and not s.get("dist_nm"):
            s["dist_nm"] = s["nm"]
    return segments

def enrich_result(result):
    if not result:
        return result
    enrich_segments(result.get("segments", []))
    for key in ("drop", "pick", "option_a", "option_b"):
        if result.get(key):
            enrich_result(result[key])
    return result

def apply_ground_time_buffer(result, buffer_hours):
    if not result or buffer_hours <= 0:
        return result
    for s in (result.get("segments") or []):
        if s.get("type") == "revenue":
            s["hours"] = round(float(s.get("hours", 0)) + buffer_hours, 2)
    for key in ("drop", "pick", "option_a", "option_b"):
        if result.get(key):
            apply_ground_time_buffer(result[key], buffer_hours)
    return result

def validate_safari_legs(legs, rules):
    wa = get_whatsapp()
    max_idle = int(rules.get("max_idle_days_between_legs", 1))
    wa_msg = f" For assistance, WhatsApp us: +{wa}" if wa else ""
    dates = []
    for L in legs:
        if L.get("date"):
            try:
                dates.append(datetime.datetime.strptime(L["date"], "%d/%m/%y").date())
            except Exception:
                pass
    if dates:
        span = (max(dates) - min(dates)).days
        if span > 7:
            return f"This safari itinerary spans {span} days which exceeds the maximum of 7 days.{wa_msg}"
        sorted_dates = sorted(dates)
        prev_date = None
        for d in sorted_dates:
            if prev_date:
                gap = (d - prev_date).days
                idle = gap - 1
                if idle > max_idle:
                    return f"This itinerary has {idle} idle day(s) between legs which exceeds the maximum of {max_idle} day(s).{wa_msg}"
            prev_date = d
    return None

def compute_for_aircraft(mission, ac_key, ac_cfg, pickup_coord, dropoff_coord,
                          depart=None, ret=None, legs=None, display_map=None):
    rules = get_quoting_rules()
    overnight_rate = float(ac_cfg.get("overnight_rate", 300.0))
    idle_day_rate = float(ac_cfg.get("idle_day_rate", ac_cfg.get("rate", 1500.0)))
    max_nights = int(rules.get("max_nights_before_pickup_drop", 3))
    speed = float(ac_cfg["speed"])
    rate = float(ac_cfg["rate"])
    routing_mode = ac_cfg.get("routing_mode", "standard")
    wa = get_whatsapp()
    buffer_enabled = rules.get("ground_time_buffer_enabled", False)
    buffer_mins = float(rules.get("ground_time_buffer_minutes", 0))
    buffer_hours = (buffer_mins / 60.0) if buffer_enabled and buffer_mins > 0 else 0

    orig = hq.AIRCRAFT.copy()
    orig_pax = hq.PAX_ADMIN_FEE_USD
    hq.AIRCRAFT[ac_key] = {
        "label": f"{ac_cfg['label']} ({ac_cfg['seater']} seater)",
        "speed": speed,
        "rate": rate,
        "overnight": overnight_rate,
        "idle_day": idle_day_rate,
    }
    hq.PAX_ADMIN_FEE_USD = float(ac_cfg["pax_fee"])

    try:
        if mission == "one_way":
            result = hq.compute_one_way(pickup_coord, dropoff_coord, ac_key)
        elif mission == "return":
            d0 = datetime.datetime.strptime(depart, "%d/%m/%y").date()
            d1 = datetime.datetime.strptime(ret, "%d/%m/%y").date()
            wait_days = max((d1 - d0).days, 0)
            wa_msg = f" For questions, WhatsApp us: +{wa}" if wa else ""
            option_a = hq.compute_return(pickup_coord, dropoff_coord, depart, ret, ac_key)
            drop = hq.compute_one_way(pickup_coord, dropoff_coord, ac_key)
            for sg in drop["segments"]:
                if sg.get("type") == "revenue":
                    sg["date"] = d0.strftime("%d/%m/%y")
            pick = hq.compute_one_way(dropoff_coord, pickup_coord, ac_key)
            for sg in pick["segments"]:
                if sg.get("type") == "revenue":
                    sg["date"] = d1.strftime("%d/%m/%y")
            option_b = {
                "mission": "pick_and_drop",
                "drop": drop,
                "pick": pick,
                "warning": "",
                "total_usd": round(drop["total_usd"] + pick["total_usd"], 2)
            }
            pickup_drop_msg = (
                f"This return trip exceeds {max_nights} night(s). Based on our aircraft "
                f"utilization schedule and operational commitments, only the Pick & Drop "
                f"option is available for stays of this duration. Our team will coordinate "
                f"both flights to ensure a seamless experience.{wa_msg}"
            )
            result = {
                "mission": "return_both",
                "option_a": option_a,
                "option_b": option_b,
                "wait_days": wait_days,
                "max_nights": max_nights,
                "pickup_drop_msg": pickup_drop_msg
            }
        elif mission == "safari":
            result = hq.compute_safari(legs, ac_key)
        else:
            result = {"error": "Unknown mission"}

        if display_map:
            apply_display_names(result, display_map)
        enrich_result(result)
        if buffer_hours > 0:
            apply_ground_time_buffer(result, buffer_hours)

        result["ac_label"] = f"{ac_cfg['label']} ({ac_cfg['seater']} seater)"
        result["ac_key"] = ac_key
        result["ac_type"] = ac_cfg.get("type", "helicopter")
        result["home_airstrip"] = ac_cfg.get("home_airstrip", "")
        result["rate_usd"] = rate
        result["overnight_rate_usd"] = overnight_rate
        result["idle_day_rate_usd"] = idle_day_rate
        result["pax_fee_usd_display"] = float(ac_cfg["pax_fee"])
        result["routing_mode"] = routing_mode

    except Exception as e:
        result = {
            "error": str(e),
            "ac_label": f"{ac_cfg['label']} ({ac_cfg['seater']} seater)",
            "ac_key": ac_key,
            "ac_type": ac_cfg.get("type", "helicopter"),
            "home_airstrip": ac_cfg.get("home_airstrip", "")
        }
    finally:
        hq.AIRCRAFT = orig
        hq.PAX_ADMIN_FEE_USD = orig_pax

    return result

def get_active_aircraft(ac_type_filter="all"):
    aircraft_cfg = load_aircraft()
    mode = get_aircraft_mode()
    if mode == "helicopter":
        type_filter = "helicopter"
    elif mode == "fixed_wing":
        type_filter = "fixed_wing"
    else:
        type_filter = ac_type_filter
    return {k: v for k, v in aircraft_cfg.items()
            if v.get("active") and
            (type_filter == "all" or v.get("type", "helicopter") == type_filter)}

def run_quote_engine(data):
    mission = data.get("mission")
    rules = get_quoting_rules()
    ac_type_filter = data.get("ac_type_filter", "all")
    active = get_active_aircraft(ac_type_filter)
    if not active:
        return {"error": "No aircraft available for the selected type."}, 400

    display_map = {}
    try:
        if mission == "one_way":
            raw_p = data.get("pickup", "")
            raw_d = data.get("dropoff", "")
            p_disp, p_coord = resolve_location(raw_p, user_label=raw_p)
            d_disp, d_coord = resolve_location(raw_d, user_label=raw_d)
            if p_disp is None:
                return {"error": geo_lock_error(raw_p), "not_found": raw_p}, 400
            if d_disp is None:
                return {"error": geo_lock_error(raw_d), "not_found": raw_d}, 400
            display_map[p_coord] = p_disp
            display_map[d_coord] = d_disp
            results = [compute_for_aircraft("one_way", k, v, p_coord, d_coord,
                                            display_map=display_map) for k, v in active.items()]
        elif mission == "return":
            raw_p = data.get("pickup", "")
            raw_d = data.get("dropoff", "")
            p_disp, p_coord = resolve_location(raw_p, user_label=raw_p)
            d_disp, d_coord = resolve_location(raw_d, user_label=raw_d)
            if p_disp is None:
                return {"error": geo_lock_error(raw_p), "not_found": raw_p}, 400
            if d_disp is None:
                return {"error": geo_lock_error(raw_d), "not_found": raw_d}, 400
            display_map[p_coord] = p_disp
            display_map[d_coord] = d_disp
            results = [compute_for_aircraft("return", k, v, p_coord, d_coord,
                                            depart=data.get("depart", ""),
                                            ret=data.get("return_date", ""),
                                            display_map=display_map) for k, v in active.items()]
        elif mission == "safari":
            legs = []
            for L in (data.get("legs") or []):
                raw_o = L.get("origin", "")
                raw_d2 = L.get("destination", "")
                o_disp, o_coord = resolve_location(raw_o, user_label=raw_o)
                d_disp2, d_coord2 = resolve_location(raw_d2, user_label=raw_d2)
                if o_disp is None:
                    return {"error": geo_lock_error(raw_o), "not_found": raw_o}, 400
                if d_disp2 is None:
                    return {"error": geo_lock_error(raw_d2), "not_found": raw_d2}, 400
                display_map[o_coord] = o_disp
                display_map[d_coord2] = d_disp2
                legs.append({"origin": o_coord, "destination": d_coord2, "date": L.get("date", "")})
            safari_error = validate_safari_legs(legs, rules)
            if safari_error:
                return {"error": safari_error}, 400
            results = [compute_for_aircraft("safari", k, v, None, None,
                                            legs=legs, display_map=display_map) for k, v in active.items()]
        else:
            return {"error": "Unknown mission type"}, 400

        return {"multi": True, "results": results}, 200

    except Exception as e:
        return {"error": str(e)}, 400

def calc_pdf_total(result, extra_items, discount):
    base = float(result.get("total_usd", 0))
    extras_total = sum(
        float(ei.get("quantity", 1)) * float(ei.get("unit_cost", 0))
        for ei in (extra_items or [])
    )
    disc = float(discount) if discount else 0
    return round(base + extras_total - disc, 2)

def get_flight_segments(result):
    segs = result.get("segments", [])
    return [s for s in segs if s.get("type") and s.get("origin")]

def get_note_segments(result):
    segs = result.get("segments", [])
    return [s for s in segs if s.get("note") and not s.get("type")]

def build_routing_lines(segments):
    lines = []
    for s in segments:
        if not s.get("type") or not s.get("origin"):
            continue
        nm = s.get("nm") or s.get("dist_nm") or 0
        hrs = s.get("hours", 0)
        seg_type = s.get("type", "").title()
        origin = s.get("origin", "")
        dest = s.get("destination", "")
        date = s.get("date", "")
        date_str = f"{date} " if date else ""
        lines.append(
            f"{date_str}{origin} -> {dest} {float(hrs):.1f} hrs | {float(nm):.1f} NM ({seg_type})"
        )
    return lines

def build_pdf_payload_from_result(doc_type, result, client_name, client_email,
                                   client_phone, note, discount, extra_items):
    items = []
    ac_label = result.get("ac_label", "Aircraft")
    rate = result.get("rate_usd", 0)
    overnight_rate = result.get("overnight_rate_usd", 0)
    idle_day_rate = result.get("idle_day_rate_usd", 0)

    mission = result.get("mission", "")
    if mission == "pick_and_drop":
        drop_segs = result.get("drop", {}).get("segments", [])
        pick_segs = result.get("pick", {}).get("segments", [])
        all_segments = drop_segs + pick_segs
        flight_total_usd = (result.get("drop", {}).get("total_usd", 0) +
                           result.get("pick", {}).get("total_usd", 0))
    else:
        all_segments = result.get("segments", [])
        flight_total_usd = result.get("total_usd", 0)

    flying_segs = [s for s in all_segments if s.get("type") and s.get("origin")]
    total_hrs = sum(float(s.get("hours", 0)) for s in flying_segs)

    routing_lines = build_routing_lines(flying_segs)
    routing_text = "Routing:\n" + "\n".join(routing_lines) if routing_lines else ""
    note_line = f"Note: {note}" if note else ""

    if total_hrs > 0 and rate > 0:
        item_parts = [f"Equipment: {ac_label}"]
        if routing_text:
            item_parts.append(routing_text)
        if note_line:
            item_parts.append(note_line)
        items.append({
            "name": "Aircraft Charter\n" + "\n".join(item_parts),
            "quantity": str(round(total_hrs, 2)),
            "unit_cost": str(rate)
        })

    pax_fee = result.get("pax_fee_usd") or result.get("pax_fee_usd_display") or 0
    if pax_fee > 0:
        items.append({
            "name": "Passenger Taxes & Admin Fees",
            "quantity": "1",
            "unit_cost": str(pax_fee)
        })

    overnight_usd = result.get("overnight_usd") or result.get("overnight_cost_usd") or 0
    if overnight_usd > 0 and overnight_rate > 0:
        nights = round(float(overnight_usd) / float(overnight_rate))
        if nights > 0:
            items.append({
                "name": f"Overnight Per Diem\n{nights} night{'s' if nights != 1 else ''} away from base",
                "quantity": str(nights),
                "unit_cost": str(overnight_rate)
            })

    waiting_usd = result.get("waiting_usd") or result.get("idle_cost_usd") or 0
    if waiting_usd > 0 and idle_day_rate > 0:
        idle_days = round(float(waiting_usd) / float(idle_day_rate))
        if idle_days > 0:
            items.append({
                "name": f"Idle Day Charge\nAircraft on ground, not utilised",
                "quantity": str(idle_days),
                "unit_cost": str(idle_day_rate)
            })

    for ei in (extra_items or []):
        items.append({
            "name": ei.get("name", "Additional Charge"),
            "quantity": str(ei.get("quantity", "1")),
            "unit_cost": str(ei.get("unit_cost", "0"))
        })

    to_block = "\n".join(filter(None, [client_name, client_email, client_phone]))
    bank_block = get_bank_details_block()
    terms = OPERATOR.get("invoice", {}).get("terms", "")
    doc_number = next_record_number(doc_type)
    disc = float(discount) if discount else 0

    payload = {
        "logo": OPERATOR.get("logo_url", ""),
        "from": get_company_from_block(),
        "to": to_block,
        "number": doc_number,
        "date": datetime.date.today().strftime("%d %b %Y"),
        "due_date": (datetime.date.today() + datetime.timedelta(days=7)).strftime("%d %b %Y"),
        "items": items,
        "discounts": disc,
        "fields": {"tax": False, "discounts": True, "shipping": False},
        "notes": bank_block,
        "notes_title": "BANK DETAILS",
        "terms": terms,
        "terms_title": "TERMS & CONDITIONS",
        "currency": "USD",
        "header": doc_type
    }

    return payload, doc_number

@app.route("/")
@login_required
def index():
    return render_template("index.html", operator=OPERATOR)

@app.route("/admin/quote", methods=["POST"])
@login_required
def admin_quote():
    data = request.get_json()
    result, status = run_quote_engine(data)
    return jsonify(result), status

@app.route("/quote", methods=["GET"])
def quote_page():
    return render_template("quote.html", operator=OPERATOR)

@app.route("/quote/calculate", methods=["POST"])
def quote_calculate():
    data = request.get_json()
    result, status = run_quote_engine(data)
    return jsonify(result), status

@app.route("/pdf", methods=["POST"])
@login_required
def pdf():
    data = request.get_json()
    try:
        result = data["result"]
        doc_type = data.get("doc_type", "Quotation")
        client_name = data.get("client_name", "Client")
        client_email = data.get("client_email", "")
        client_phone = data.get("client_phone", "")
        note = data.get("note", "")
        discount = data.get("discount", "0")
        extra_items = data.get("extras", [])

        payload, doc_number = build_pdf_payload_from_result(
            doc_type, result, client_name, client_email,
            client_phone, note, discount, extra_items)

        out_path = f"/tmp/{doc_number}.pdf"
        hq.generate_pdf(payload, out_path)

        total = calc_pdf_total(result, extra_items, discount)
        save_record(doc_type, client_name, client_email, total, doc_number, {
            "ac_label": result.get("ac_label", ""),
            "mission": result.get("mission", "")
        })

        return send_file(out_path, as_attachment=True,
                         download_name=f"{doc_number}.pdf",
                         mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/pdf_all", methods=["POST"])
@login_required
def pdf_all():
    data = request.get_json()
    try:
        results = data.get("results", [])
        doc_type = data.get("doc_type", "Quotation")
        client_name = data.get("client_name", "Client")
        client_email = data.get("client_email", "")
        client_phone = data.get("client_phone", "")
        note = data.get("note", "")
        discount = data.get("discount", "0")
        extra_items = data.get("extras", [])

        generated = []
        for res in results:
            if res.get("error"):
                continue
            if res.get("mission") == "return_both":
                wd = res.get("wait_days", 0)
                max_n = res.get("max_nights", 3)
                if wd >= max_n:
                    actual = res["option_b"]
                    actual["mission"] = "pick_and_drop"
                else:
                    actual = res["option_a"]
            else:
                actual = res

            actual["rate_usd"] = res.get("rate_usd", actual.get("rate_usd", 0))
            actual["overnight_rate_usd"] = res.get("overnight_rate_usd", 0)
            actual["idle_day_rate_usd"] = res.get("idle_day_rate_usd", 0)
            actual["pax_fee_usd_display"] = res.get("pax_fee_usd_display", 0)
            actual["ac_label"] = res.get("ac_label", "")
            actual["ac_key"] = res.get("ac_key", "")

            payload, doc_number = build_pdf_payload_from_result(
                doc_type, actual, client_name, client_email,
                client_phone, note, discount, extra_items)

            out_path = f"/tmp/{doc_number}.pdf"
            hq.generate_pdf(payload, out_path)

            total = calc_pdf_total(actual, extra_items, discount)
            save_record(doc_type, client_name, client_email, total, doc_number, {
                "ac_label": res.get("ac_label", ""),
                "mission": actual.get("mission", "")
            })
            generated.append({
                "number": doc_number,
                "path": out_path,
                "ac_label": res.get("ac_label", "")
            })

        return jsonify({"success": True, "files": generated})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/pdf_download_temp", methods=["GET"])
@login_required
def pdf_download_temp():
    path = request.args.get("path", "")
    name = request.args.get("name", "document.pdf")
    if not path.startswith("/tmp/") or ".." in path:
        return jsonify({"error": "Invalid path"}), 400
    return send_file(path, as_attachment=True,
                     download_name=name, mimetype="application/pdf")

@app.route("/manual_invoice", methods=["POST"])
@login_required
def manual_invoice():
    data = request.get_json()
    try:
        client_name = data.get("client_name", "Client")
        client_email = data.get("client_email", "")
        client_phone = data.get("client_phone", "")
        note = data.get("note", "")
        discount = data.get("discount", "0")
        terms_override = data.get("terms", "")
        bank_override = data.get("bank_block", "")
        line_items = data.get("line_items", [])
        doc_type = data.get("doc_type", "Invoice")
        doc_number = next_record_number(doc_type)

        items = []
        total = 0.0
        for item in line_items:
            qty = float(item.get("quantity", 1))
            unit = float(item.get("unit_cost", 0))
            items.append({
                "name": item.get("description", ""),
                "quantity": str(qty),
                "unit_cost": str(unit)
            })
            total += qty * unit

        disc = float(discount) if discount else 0
        total = round(total - disc, 2)

        to_block = "\n".join(filter(None, [client_name, client_email, client_phone]))
        bank_block = bank_override if bank_override else get_bank_details_block()
        terms = terms_override if terms_override else OPERATOR.get("invoice", {}).get("terms", "")

        payload = {
            "logo": OPERATOR.get("logo_url", ""),
            "from": get_company_from_block(),
            "to": to_block,
            "number": doc_number,
            "date": datetime.date.today().strftime("%d %b %Y"),
            "due_date": (datetime.date.today() + datetime.timedelta(days=7)).strftime("%d %b %Y"),
            "items": items,
            "discounts": disc,
            "fields": {"tax": False, "discounts": True, "shipping": False},
            "notes": bank_block,
            "notes_title": "BANK DETAILS",
            "terms": terms,
            "terms_title": "TERMS & CONDITIONS",
            "currency": "USD",
            "header": doc_type
        }

        out_path = f"/tmp/{doc_number}.pdf"
        hq.generate_pdf(payload, out_path)
        save_record(doc_type, client_name, client_email, total, doc_number)

        return send_file(out_path, as_attachment=True,
                         download_name=f"{doc_number}.pdf",
                         mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/records", methods=["GET"])
@login_required
def get_records():
    return jsonify(load_records())

@app.route("/records/get_one", methods=["POST"])
@login_required
def get_one_record():
    data = request.get_json()
    number = data.get("number", "")
    records = load_records()
    rec = next((r for r in records if r.get("number") == number), None)
    if not rec:
        return jsonify({"error": "Record not found"}), 404
    return jsonify(rec)

@app.route("/records/delete", methods=["POST"])
@login_required
def delete_record_route():
    data = request.get_json()
    number = data.get("number", "")
    password = data.get("password", "")
    records = load_records()
    rec = next((r for r in records if r.get("number") == number), None)
    if rec and (rec.get("paid") or float(rec.get("paid_amount", 0)) > 0):
        if password != get_admin_pass():
            return jsonify({"error": "Password required to delete a paid record."}), 403
    records = [r for r in records if r.get("number") != number]
    save_records(records)
    return jsonify({"success": True})

@app.route("/records/mark_paid", methods=["POST"])
@login_required
def mark_paid():
    data = request.get_json()
    number = data.get("number", "")
    paid_amount = float(data.get("paid_amount", 0))
    paid_date = data.get("paid_date", datetime.date.today().strftime("%d/%m/%Y"))
    payment_mode = data.get("payment_mode", "")
    payment_ref = data.get("payment_ref", "")

    records = load_records()
    rec = next((r for r in records if r.get("number") == number), None)
    if not rec:
        return jsonify({"error": "Record not found"}), 404

    total = float(rec.get("amount", 0))
    prev_paid = float(rec.get("paid_amount", 0))
    remaining = round(total - prev_paid, 2)
    if paid_amount > remaining:
        return jsonify({"error": f"Amount exceeds remaining balance of USD ${remaining:,.2f}"}), 400

    new_total_paid = round(prev_paid + paid_amount, 2)
    rec["paid"] = new_total_paid >= total
    rec["paid_amount"] = new_total_paid
    rec["paid_date"] = paid_date
    rec["payment_mode"] = payment_mode
    rec["payment_ref"] = payment_ref

    if "payment_log" not in rec:
        rec["payment_log"] = []
    rec["payment_log"].append({
        "date": paid_date,
        "amount": round(paid_amount, 2),
        "mode": payment_mode,
        "ref": payment_ref,
        "recorded_at": datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    })

    save_records(records)
    return jsonify({"success": True, "balance": round(total - new_total_paid, 2),
                    "fully_paid": new_total_paid >= total})

@app.route("/records/generate_receipt", methods=["POST"])
@login_required
def generate_receipt():
    data = request.get_json()
    number = data.get("number", "")
    paid_amount = float(data.get("paid_amount", 0))
    paid_date = data.get("paid_date", datetime.date.today().strftime("%d/%m/%Y"))
    payment_mode = data.get("payment_mode", "")
    payment_ref = data.get("payment_ref", "")

    records = load_records()
    rec = next((r for r in records if r.get("number") == number), None)
    if not rec:
        return jsonify({"error": "Record not found"}), 404

    total = float(rec.get("amount", 0))
    receipt_number = next_record_number("Receipt")

    to_block = "\n".join(filter(None, [
        rec.get("client_name", ""),
        rec.get("client_email", ""),
    ]))

    payment_desc_lines = ["Amount Invoiced"]
    if payment_mode:
        payment_desc_lines.append(f"Mode: {payment_mode}")
    if payment_ref:
        payment_desc_lines.append(f"Reference: {payment_ref}")
    payment_desc_lines.append(f"Date: {paid_date}")
    payment_desc_lines.append(f"Invoice Ref: {number}")

    items = [{
        "name": "\n".join(payment_desc_lines),
        "quantity": "1",
        "unit_cost": str(total)
    }]

    bank_block = get_bank_details_block()
    terms = OPERATOR.get("invoice", {}).get("terms", "")

    payload = {
        "logo": OPERATOR.get("logo_url", ""),
        "from": get_company_from_block(),
        "to": to_block,
        "number": receipt_number,
        "date": datetime.date.today().strftime("%d %b %Y"),
        "items": items,
        "amount_paid": paid_amount,
        "notes": bank_block,
        "notes_title": "BANK DETAILS",
        "terms": terms,
        "terms_title": "TERMS & CONDITIONS",
        "currency": "USD",
        "header": "Receipt"
    }

    out_path = f"/tmp/{receipt_number}.pdf"
    hq.generate_pdf(payload, out_path)

    rec["paid"] = paid_amount >= total
    rec["paid_amount"] = round(paid_amount, 2)
    rec["paid_date"] = paid_date
    rec["payment_mode"] = payment_mode
    rec["payment_ref"] = payment_ref
    rec["receipt_number"] = receipt_number

    if "payment_log" not in rec:
        rec["payment_log"] = []
    rec["payment_log"].append({
        "date": paid_date,
        "amount": round(paid_amount, 2),
        "mode": payment_mode,
        "ref": payment_ref,
        "recorded_at": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
        "receipt": receipt_number
    })

    save_records(records)
    save_record("Receipt", rec.get("client_name", ""), rec.get("client_email", ""),
                paid_amount, receipt_number)

    return send_file(out_path, as_attachment=True,
                     download_name=f"{receipt_number}.pdf",
                     mimetype="application/pdf")

@app.route("/records/edit", methods=["POST"])
@login_required
def edit_record():
    data = request.get_json()
    number = data.get("number", "")
    password = data.get("password", "")

    records = load_records()
    rec = next((r for r in records if r.get("number") == number), None)
    if not rec:
        return jsonify({"error": "Record not found"}), 404

    if rec.get("paid") or float(rec.get("paid_amount", 0)) > 0:
        if password != get_admin_pass():
            return jsonify({"error": "Password required to edit a paid record."}), 403

    if data.get("client_name"):
        rec["client_name"] = data["client_name"]
    if data.get("client_email") is not None:
        rec["client_email"] = data["client_email"]
    if data.get("amount") is not None:
        rec["amount"] = round(float(data["amount"]), 2)
    if data.get("date"):
        rec["date"] = data["date"]

    save_records(records)
    return jsonify({"success": True})

@app.route("/airports", methods=["GET"])
@login_required
def airports():
    all_airports = {}
    for k, v in hq.AIRPORTS.items():
        all_airports[k] = {**v, "source": "system"}
    for k, v in hq.USER_AIRPORTS.items():
        all_airports[k] = {**v, "source": "user"}
    return jsonify(all_airports)

@app.route("/add_airport", methods=["POST"])
@login_required
def add_airport():
    data = request.get_json()
    try:
        name = data.get("name", "").strip()
        lat = float(data.get("lat", 0))
        lon = float(data.get("lon", 0))
        aliases = data.get("aliases", [])
        if not name:
            return jsonify({"error": "Name required"}), 400
        hq.add_airport(name, lat, lon, aliases)
        return jsonify({"success": True, "name": name})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/edit_airport", methods=["POST"])
@login_required
def edit_airport():
    data = request.get_json()
    try:
        name = data.get("name", "").strip()
        if not name:
            return jsonify({"error": "Name required"}), 400
        kwargs = {}
        if data.get("new_name"):
            kwargs["new_name"] = data["new_name"]
        if data.get("lat") is not None:
            kwargs["lat"] = float(data["lat"])
        if data.get("lon") is not None:
            kwargs["lon"] = float(data["lon"])
        if data.get("set_aliases") is not None:
            kwargs["set_aliases"] = data["set_aliases"]
        hq.edit_airport(name, **kwargs)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/delete_airport", methods=["POST"])
@login_required
def delete_airport():
    data = request.get_json()
    try:
        name = data.get("name", "").strip()
        hq.delete_airport(name)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/aircraft", methods=["GET"])
@login_required
def get_aircraft():
    return jsonify(load_aircraft())

@app.route("/aircraft/save", methods=["POST"])
@login_required
def save_aircraft_route():
    data = request.get_json()
    try:
        save_aircraft(data)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/settings/config", methods=["GET"])
@login_required
def get_config():
    return jsonify(OPERATOR)

@app.route("/settings/config/public", methods=["GET"])
def get_config_public():
    safe = {
        "company_name": OPERATOR.get("company_name", ""),
        "tagline": OPERATOR.get("tagline", ""),
        "logo_url": OPERATOR.get("logo_url", ""),
        "contact": OPERATOR.get("contact", {}),
        "branding": OPERATOR.get("branding", {}),
        "trust_bar": OPERATOR.get("trust_bar", []),
        "footer_tagline": OPERATOR.get("footer_tagline", ""),
        "aircraft_mode": OPERATOR.get("aircraft_mode", "helicopter"),
        "landing_field_disclaimer": OPERATOR.get("landing_field_disclaimer", ""),
        "geo_lock": {"region_name": get_region_name()},
        "quoting_rules": {
            "show_distance_to_client": OPERATOR.get("quoting_rules", {}).get("show_distance_to_client", False),
            "quote_validity_hours": OPERATOR.get("quoting_rules", {}).get("quote_validity_hours", 48)
        }
    }
    return jsonify(safe)

@app.route("/settings/save", methods=["POST"])
@login_required
def save_settings():
    global OPERATOR
    data = request.get_json()
    try:
        pathlib.Path(OPERATOR_CONFIG_FILE).write_text(json.dumps(data, indent=2))
        OPERATOR = data
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/settings/change_password", methods=["POST"])
@login_required
def change_password():
    global OPERATOR
    data = request.get_json()
    current = data.get("current_password", "")
    new_pass = data.get("new_password", "")
    confirm = data.get("confirm_password", "")
    if current != get_admin_pass():
        return jsonify({"error": "Current password is incorrect."}), 400
    if not new_pass or len(new_pass) < 6:
        return jsonify({"error": "New password must be at least 6 characters."}), 400
    if new_pass != confirm:
        return jsonify({"error": "Passwords do not match."}), 400
    try:
        OPERATOR["env"]["admin_pass"] = new_pass
        pathlib.Path(OPERATOR_CONFIG_FILE).write_text(json.dumps(OPERATOR, indent=2))
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/get_maps_key", methods=["GET"])
def get_maps_key():
    return jsonify({"key": GOOGLE_API_KEY})

@app.route("/expand_maps_url", methods=["POST"])
def expand_maps_url():
    data = request.get_json()
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "URL required"}), 400
    try:
        import requests as req
        r = req.get(url, allow_redirects=True, timeout=8,
                    headers={"User-Agent": "Mozilla/5.0"})
        return jsonify({"final_url": r.url, "success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/fx/rates", methods=["GET"])
def fx_rates():
    try:
        import requests as req
        r = req.get("https://open.er-api.com/v6/latest/USD", timeout=5)
        data = r.json()
        if data.get("result") == "success":
            rates = data.get("rates", {})
            return jsonify({
                "success": True,
                "rates": {
                    "KES": rates.get("KES", 0),
                    "EUR": rates.get("EUR", 0),
                    "GBP": rates.get("GBP", 0),
                    "TZS": rates.get("TZS", 0),
                    "UGX": rates.get("UGX", 0)
                },
                "updated": data.get("time_last_update_utc", "")
            })
    except Exception:
        pass
    return jsonify({"success": False, "rates": {}})

@app.route("/search_location", methods=["POST"])
@login_required
def search_location():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    disp, coord = resolve_location(name, user_label=name)
    if not disp:
        return jsonify({"found": False})
    parts = coord.split(",")
    return jsonify({"found": True, "lat": float(parts[0]), "lon": float(parts[1]), "display": disp})

@app.route("/resolve_pin", methods=["POST"])
@login_required
def resolve_pin():
    data = request.get_json()
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "URL required"}), 400
    disp, coord = resolve_location(url)
    if disp is None:
        return jsonify({"found": False})
    parts = coord.split(",")
    return jsonify({"found": True, "lat": float(parts[0]), "lon": float(parts[1]), "display": disp})

if __name__ == "__main__":
    app.run(debug=True, port=5000)
