# =========================================================
# QUOTECLOUD BY JETMAN GLOBAL
# app.py v2.5.0
# v2.4.9 changes:
#   - Added /expand_maps_url route for client-side Maps resolution
#   - Fixed missing @app.route decorator on /fx/rates
# =========================================================
import sys, os, json, re, pathlib, datetime
sys.path.insert(0, os.path.dirname(__file__))
from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for
from functools import wraps
import quotecloud_engine as hq

import firebase_admin
from firebase_admin import credentials, firestore

FIREBASE_STORAGE_BUCKET = "quotecloud-264db.firebasestorage.app"

def init_firestore():
    if firebase_admin._apps:
        return firestore.client()
    cred_json = os.environ.get("FIREBASE_CREDENTIALS_JSON")
    if cred_json:
        cred_dict = json.loads(cred_json.strip())
        cred = credentials.Certificate(cred_dict)
    else:
        key_path = pathlib.Path(__file__).parent / "firebase-key.json"
        if not key_path.exists():
            raise RuntimeError("No Firebase credentials found (env var or local file).")
        cred = credentials.Certificate(str(key_path))
    firebase_admin.initialize_app(cred, {"storageBucket": FIREBASE_STORAGE_BUCKET})
    return firestore.client()

db = init_firestore()

def upload_pdf_to_firebase(pdf_path, doc_number):
    try:
        from firebase_admin import storage as fb_storage
        bucket = fb_storage.bucket()
        blob_path = f"tenants/{TENANT_ID}/pdfs/{doc_number}.pdf"
        blob = bucket.blob(blob_path)
        blob.upload_from_filename(pdf_path, content_type="application/pdf")
        blob.make_public()
        return blob.public_url
    except Exception as e:
        print(f"Firebase Storage upload error: {e}")
        return None

TENANT_ID = os.environ.get("TENANT_ID", "jetman-global")

def tenant_doc():
    return db.collection("tenants").document(TENANT_ID)

def tenant_collection(name):
    return tenant_doc().collection(name)

def load_operator_config():
    try:
        snap = tenant_doc().get()
        if snap.exists:
            data = snap.to_dict()
            if data:
                return data
    except Exception as e:
        print(f"Firestore load_operator_config error: {e}")
    file_config = load_operator_config_from_file()
    if file_config:
        save_operator_config(file_config)
    return file_config

def save_operator_config(config):
    try:
        tenant_doc().set(config, merge=True)
    except Exception as e:
        print(f"Firestore save_operator_config error: {e}")

app = Flask(__name__)

OPERATOR_CONFIG_FILE = "operator_config.json"
AIRCRAFT_CONFIG_FILE = "hf_aircraft.json"
RECORDS_FILE = "qc_records.json"
BOOKINGS_FILE = "qc_bookings.json"

def load_operator_config_from_file():
    p = pathlib.Path(OPERATOR_CONFIG_FILE)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception as e:
            print(f"ERROR loading operator config file: {e}")
    return {}

OPERATOR = load_operator_config()

if not OPERATOR.get("branding"):
    OPERATOR["branding"] = {"primary_color": "#1a56db", "accent_color": "#f59e0b", "button_color": "#f59e0b", "button_text": "#ffffff"}
if not OPERATOR.get("company_name"):
    OPERATOR["company_name"] = "Quotecloud"
if not OPERATOR.get("logo_url"):
    OPERATOR["logo_url"] = ""
if not OPERATOR.get("footer"):
    OPERATOR["footer"] = {"powered_by": "Quotecloud — Jetman Global", "powered_url": "https://jetmanglobal.com"}

app.secret_key = os.environ.get("SECRET_KEY", OPERATOR.get("env", {}).get("secret_key", "qc-secret-2026"))
app.config["PERMANENT_SESSION_LIFETIME"] = datetime.timedelta(days=7)
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

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
def parse_smart_date(s):
    if not s or not str(s).strip():
        return s
    import re as _re
    s = str(s).strip()
    s = _re.sub(r'(\d+)(st|nd|rd|th)', r'\1', s, flags=_re.IGNORECASE)
    fmts = [
        ("%d/%m/%y", _re.compile(r'^\d{1,2}/\d{1,2}/\d{2}$')),
        ("%d/%m/%Y", _re.compile(r'^\d{1,2}/\d{1,2}/\d{4}$')),
        ("%d-%m-%y", _re.compile(r'^\d{1,2}-\d{1,2}-\d{2}$')),
        ("%d-%m-%Y", _re.compile(r'^\d{1,2}-\d{1,2}-\d{4}$')),
        ("%d.%m.%Y", _re.compile(r'^\d{1,2}\.\d{1,2}\.\d{4}$')),
        ("%d %b %Y", _re.compile(r'^\d{1,2}\s+[A-Za-z]+\s+\d{4}$')),
        ("%d %B %Y", _re.compile(r'^\d{1,2}\s+[A-Za-z]+\s+\d{4}$')),
        ("%B %d %Y", _re.compile(r'^[A-Za-z]+\s+\d{1,2}\s+\d{4}$')),
        ("%b %d %Y", _re.compile(r'^[A-Za-z]+\s+\d{1,2}\s+\d{4}$')),
    ]
    for fmt, pattern in fmts:
        if pattern.match(s):
            try:
                d = datetime.datetime.strptime(s, fmt)
                return d.strftime("%d/%m/%y")
            except Exception:
                continue
    return s

def get_geo_lock():
    if OPERATOR.get("geo_lock"):
        return OPERATOR["geo_lock"]
    return OPERATOR.get("geo_lock", {

        "enabled": True,
        "region_name": "Kenya",
        "mode": "radius",
        "center_lat": -0.023,
        "center_lon": 37.906,
        "radius_km": 500
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
    if bank.get("bank_name"):
        bank_line = bank["bank_name"].upper()
        if bank.get("swift"):
            bank_line += f" | SWIFT: {bank['swift']}"
        if bank.get("branch"):
            bank_line += f" | {bank['branch'].upper()}"
        lines.append(bank_line)
    if bank.get("kes_account"):
        kes_cur = bank.get("kes_currency", "KES")
        lines.append(f"{kes_cur} A/C: {bank['kes_account']}")
    if bank.get("usd_account"):
        usd_cur = bank.get("usd_currency", "USD")
        lines.append(f"{usd_cur} A/C: {bank['usd_account']}")
    if bank.get("paybill"):
        lines.append(f"MOBILE: {bank['paybill']}")
    return "\n".join(lines)

hq.set_firestore_collection_fn(tenant_collection)
hq.load_airports()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

# Brute force protection
_login_attempts = {}

@app.route("/login", methods=["GET", "POST"])
def login():
    import time
    error = None
    ip = request.remote_addr or "unknown"
    now = time.time()
    # Clean old entries
    _login_attempts[ip] = [t for t in _login_attempts.get(ip, []) if now - t < 900]
    if len(_login_attempts.get(ip, [])) >= 5:
        mins = int((900 - (now - _login_attempts[ip][0])) / 60) + 1
        return render_template("login.html", operator=OPERATOR, error=f"Too many attempts. Try again in {mins} minutes.")
    if request.method == "POST":
        if (request.form.get("username") == get_admin_user() and
                request.form.get("password") == get_admin_pass()):
            _login_attempts.pop(ip, None)
            session.permanent = True
            session["logged_in"] = True
            return redirect(url_for("index"))
        _login_attempts.setdefault(ip, []).append(now)
        remaining = 5 - len(_login_attempts[ip])
        error = f"Invalid credentials. {remaining} attempt{'s' if remaining != 1 else ''} remaining."
    return render_template("login.html", operator=OPERATOR, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

def load_aircraft():
    try:
        docs = tenant_collection("aircraft").stream()
        result = {doc.id: doc.to_dict() for doc in docs}
        if result:
            return result
    except Exception as e:
        print(f"Firestore load_aircraft error: {e}")
    default = {
        "as350": {
            "label": "Airbus AS350",
            "seater": 5,
            "speed": 120.0,
            "rate": 2200.0,
            "pax_fee": 100.0,
            "overnight_rate": 300.0,
            "idle_day_rate": 2200.0,
            "active": False,
            "type": "helicopter",
            "home_airstrip": "Wilson Airport, Nairobi",
            "routing_mode": "standard"
        }
    }
    return default

def save_aircraft(data):
    try:
        col = tenant_collection("aircraft")
        batch = db.batch()
        existing = col.stream()
        for doc in existing:
            batch.delete(doc.reference)
        batch.commit()
        batch = db.batch()
        for key, ac in data.items():
            doc_ref = col.document(key)
            batch.set(doc_ref, ac)
        batch.commit()
    except Exception as e:
        print(f"Firestore save_aircraft error: {e}")

def load_bookings():
    try:
        docs = tenant_collection("bookings").stream()
        return {doc.id: doc.to_dict() for doc in docs}
    except Exception as e:
        print(f"Firestore load_bookings error: {e}")
        return {}

def save_bookings(bookings):
    try:
        col = tenant_collection("bookings")
        batch = db.batch()
        existing = col.stream()
        for doc in existing:
            batch.delete(doc.reference)
        batch.commit()
        batch = db.batch()
        for token, b in bookings.items():
            doc_ref = col.document(token)
            batch.set(doc_ref, b)
        batch.commit()
    except Exception as e:
        print(f"Firestore save_bookings error: {e}")
def write_audit_log(action, details={}):
    try:
        tenant_collection("audit").add({
            "action": action,
            "details": details,
            "timestamp": datetime.datetime.now().isoformat(),
            "date": datetime.date.today().isoformat()
        })
    except Exception as e:
        print(f"Audit log error: {e}")
def generate_token(doc_type="Q"):
    import random, string
    prefix = OPERATOR.get("invoice", {}).get("prefix", "JG")
    today = datetime.date.today()
    date_str = today.strftime("%d%m%y")
    chars = string.ascii_uppercase + string.digits
    rand = ''.join(random.choices(chars, k=6))
    return f"{prefix}-{doc_type}-{date_str}-{rand}"

def generate_booking_token():
    return generate_token("Q")

def inherit_token(token, new_type):
    parts = token.split("-")
    if len(parts) == 4:
        parts[1] = new_type
        return "-".join(parts)
    return generate_token(new_type)

def load_records(include_deleted=False):
    try:
        docs = tenant_collection("records").order_by("timestamp").stream()
        records = [doc.to_dict() for doc in docs]
        if not include_deleted:
            records = [r for r in records if not r.get("deleted")]
        return records
    except Exception as e:
        print(f"Firestore load_records error: {e}")
        return []

def save_records(records):
    try:
        col = tenant_collection("records")
        batch = db.batch()
        existing = col.stream()
        for doc in existing:
            batch.delete(doc.reference)
        batch.commit()
        batch = db.batch()
        for rec in records:
            doc_ref = col.document(rec["number"])
            batch.set(doc_ref, rec)
        batch.commit()
    except Exception as e:
        print(f"Firestore save_records error: {e}")

def next_record_number(doc_type="Quotation", token_override=None):
    if token_override:
        return token_override
    if doc_type in ("Quotation", "Quote"):
        type_code = "Q"
    elif doc_type == "Invoice":
        type_code = "I"
    elif doc_type == "Receipt":
        type_code = "R"
    else:
        type_code = "Q"
    return generate_token(type_code)

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
    center_lat = float(geo.get("center_lat", -0.023))
    center_lon = float(geo.get("center_lon", 37.906))
    radius_km = float(geo.get("radius_km", 500))
    radius_nm = radius_km / 1.852
    return _nm_distance(lat, lon, center_lat, center_lon) <= radius_nm

BASE_SNAP_NM = 4.0

def _nm_distance(lat1, lon1, lat2, lon2):
    import math
    R = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def get_base_key_for_aircraft(ac_cfg):
    home = ac_cfg.get("home_airstrip", "wilson")
    base_name = home.split(",")[0].strip().lower()
    try:
        hq.lookup_coords(base_name)
        return base_name
    except Exception:
        words = base_name.split()
        for w in words:
            try:
                hq.lookup_coords(w)
                return w
            except Exception:
                pass
    return base_name

def snap_to_base_coords(lat, lon, base_lat, base_lon, snap_nm=None):
    radius = float(snap_nm) if snap_nm else BASE_SNAP_NM
    return _nm_distance(lat, lon, base_lat, base_lon) <= radius

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
    if s.startswith("ChIJ"):
        try:
            import requests as req
            gr = req.get("https://maps.googleapis.com/maps/api/geocode/json",
                        params={"place_id": s, "key": GOOGLE_API_KEY},
                        timeout=5)
            gdata = gr.json()
            if gdata.get("status") == "OK":
                loc = gdata["results"][0]["geometry"]["location"]
                lat, lon = float(loc["lat"]), float(loc["lng"])
                if check_geo_lock(lat, lon):
                    display = original_input.strip().title() if original_input != s else (reverse_geocode(lat, lon) or f"Pin, {lat:.5f}, {lon:.5f}")
                    return display, f"{lat},{lon}"
        except Exception:
            pass
    if "goo.gl" in s or "maps.app" in s:
        try:
            import requests as req
            r = req.get(s, allow_redirects=True, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
            expanded = r.url
            # Try coords directly from expanded URL
            try:
                lat, lon = hq.parse_map_pin(expanded)
                if check_geo_lock(lat, lon):
                    display = reverse_geocode(lat, lon) or f"Pin, {lat:.5f}, {lon:.5f}"
                    return display, f"{lat},{lon}"
            except Exception:
                pass
            # Try ftid Place ID
            import re as re2
            ftid_match = re2.search(r'ftid=([^&]+)', expanded)
            if ftid_match:
                try:
                    gr = req.get("https://maps.googleapis.com/maps/api/geocode/json",
                                params={"place_id": ftid_match.group(1), "key": GOOGLE_API_KEY},
                                timeout=5)
                    gdata = gr.json()
                    if gdata.get("status") == "OK":
                        loc = gdata["results"][0]["geometry"]["location"]
                        lat, lon = float(loc["lat"]), float(loc["lng"])
                        if check_geo_lock(lat, lon):
                            display = reverse_geocode(lat, lon) or f"Pin, {lat:.5f}, {lon:.5f}"
                            return display, f"{lat},{lon}"
                except Exception:
                    pass
            # Try q parameter
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(expanded)
            params = parse_qs(parsed.query)
            q = (params.get('q') or params.get('query') or [''])[0]
            if q:
                region = OPERATOR.get("geo_lock", {}).get("region_name", "Kenya")
                query = q if region.lower() in q.lower() else f"{q} {region}"
                try:
                    gr = req.get("https://maps.googleapis.com/maps/api/geocode/json",
                                params={"address": query, "key": GOOGLE_API_KEY, "region": "ke"},
                                timeout=5)
                    gdata = gr.json()
                    if gdata.get("status") == "OK":
                        loc = gdata["results"][0]["geometry"]["location"]
                        lat, lon = float(loc["lat"]), float(loc["lng"])
                        if check_geo_lock(lat, lon):
                            display = reverse_geocode(lat, lon) or f"Pin, {lat:.5f}, {lon:.5f}"
                            return display, f"{lat},{lon}"
                except Exception:
                    pass
            s = expanded
        except Exception:
            pass

    q_coord = re.search(r'[?&]q=(-?\d+\.?\d*),(-?\d+\.?\d*)', s)
    if q_coord:
        try:
            lat, lon = float(q_coord.group(1)), float(q_coord.group(2))
            if check_geo_lock(lat, lon):
                display = reverse_geocode(lat, lon) or f"Pin, {lat:.5f}, {lon:.5f}"
                return display, f"{lat},{lon}"
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
    if not re.match(r"^[a-zA-Z0-9\s\-'\,\.\(\)\/]+$", clean):
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
                # Never return a URL as display name - reverse geocode instead
                if "http" in original_input.lower() or "goo.gl" in original_input.lower() or "maps.app" in original_input.lower():
                    display = reverse_geocode(lat, lon) or f"Pin, {lat:.5f}, {lon:.5f}"
                    return display, f"{lat},{lon}"
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
        if s.get("type") in ("revenue", "positioning", "depositioning"):
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
    # Convert all aircraft costs to primary currency if rate_currency differs
    rate_currency = ac_cfg.get("rate_currency", "USD")
    _cf = 1.0
    fx_cfg = OPERATOR.get("fx", {})
    pri_cur = fx_cfg.get("primary_currency") or OPERATOR.get("quoting_rules", {}).get("currency") or "USD"
    if rate_currency != pri_cur and rate > 0:
        try:
            if fx_cfg.get("mode") == "manual":
                fx_rates = fx_cfg.get("rates", {})
                rate_to_usd = 1.0 / fx_rates[rate_currency] if fx_rates.get(rate_currency) else 1.0
                usd_to_pri = fx_rates.get(pri_cur, 1.0)
                _cf = rate_to_usd * usd_to_pri
            else:
                import requests as req
                r = req.get(f"https://open.er-api.com/v6/latest/{rate_currency}", timeout=5)
                rdata = r.json()
                if rdata.get("result") == "success":
                    _cf = float(rdata.get("rates", {}).get(pri_cur, 1.0))
            rate = rate * _cf
            overnight_rate = overnight_rate * _cf
            idle_day_rate = idle_day_rate * _cf
        except Exception:
            _cf = 1.0
    routing_mode = ac_cfg.get("routing_mode", "standard")
    wa = get_whatsapp()
    buffer_enabled = rules.get("ground_time_buffer_enabled", False)
    buffer_mins = float(rules.get("ground_time_buffer_minutes", 0))
    buffer_hours = (buffer_mins / 60.0) if buffer_enabled and buffer_mins > 0 else 0

    base_lat_cfg = ac_cfg.get("base_lat")
    base_lon_cfg = ac_cfg.get("base_lon")
    base_key = get_base_key_for_aircraft(ac_cfg)
    allow_urban_hops = (ac_cfg.get("type", "helicopter") == "helicopter" and
                        ac_cfg.get("allow_urban_hops", False))
    def maybe_snap(coord):
        if not coord or allow_urban_hops:
            return coord
        try:
            parts = coord.split(",")
            if len(parts) == 2:
                lat, lon = float(parts[0]), float(parts[1])
                if base_lat_cfg and base_lon_cfg:
                    if snap_to_base_coords(lat, lon, float(base_lat_cfg), float(base_lon_cfg), snap_nm=ac_cfg.get("snap_radius_nm")):
                        return base_key
        except Exception:
            pass
        return coord
    if pickup_coord:
        pickup_coord = maybe_snap(pickup_coord)
    if dropoff_coord:
        dropoff_coord = maybe_snap(dropoff_coord)
    if legs:
        for leg in legs:
            leg["origin"] = maybe_snap(leg["origin"])
            leg["destination"] = maybe_snap(leg["destination"])

    orig = hq.AIRCRAFT.copy()
    orig_pax = hq.PAX_ADMIN_FEE_USD
    hq.AIRCRAFT[ac_key] = {
        "label": f"{ac_cfg['label']} ({ac_cfg['seater']} seater)",
        "speed": speed,
        "rate": rate,
        "overnight": overnight_rate,
        "idle_day": idle_day_rate,
        "base_key": base_key,
        "base_label": ac_cfg.get("home_airstrip", "Wilson Airport, Nairobi"),
    }
    pax_enabled = ac_cfg.get("pax_fee_enabled", True)
    hq.PAX_ADMIN_FEE_USD = float(ac_cfg["pax_fee"]) * _cf if pax_enabled else 0.0
    hq.MIN_CHARGEABLE_HR = float(rules.get("min_flight_hours", 1.0))

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
        overnight_enabled = ac_cfg.get("overnight_enabled", True)
        result["overnight_rate_usd"] = overnight_rate if overnight_enabled else 0.0
        result["idle_day_rate_usd"] = idle_day_rate
        result["pax_fee_usd_display"] = float(ac_cfg["pax_fee"]) * _cf if pax_enabled else 0.0
        result["pax_label"] = ac_cfg.get("pax_label", "Mission Fixed Costs")
        result["overnight_label"] = ac_cfg.get("overnight_label", "Crew Overnight")
        result["pax_fee_enabled"] = pax_enabled
        result["overnight_enabled"] = overnight_enabled
        result["routing_mode"] = routing_mode
        min_hrs = float(rules.get("min_flight_hours", 1.0))
        result["min_chargeable_hrs"] = min_hrs
        result["min_applied"] = result.get("billed_hours", 0) > sum(
            float(s.get("hours", 0)) for s in (result.get("segments") or []) if s.get("type"))
        result["images"] = ac_cfg.get("images", [])

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
    force_ac = data.pop("_force_aircraft", None)
    if force_ac:
        active = force_ac
    else:
        active = get_active_aircraft(ac_type_filter)
    if not active:
        return {"error": "No aircraft available for the selected type."}, 400

    display_map = {}
    try:
        if mission == "one_way":
            raw_p = data.get("pickup", "")
            raw_d = data.get("dropoff", "")
            pid_p = data.get("pickup_place_id", "")
            pid_d = data.get("dropoff_place_id", "")
            p_disp, p_coord = resolve_location(pid_p or raw_p, user_label=raw_p)
            d_disp, d_coord = resolve_location(pid_d or raw_d, user_label=raw_d)
            if p_disp is None:
                return {"error": geo_lock_error(raw_p), "not_found": raw_p}, 400
            if d_disp is None:
                return {"error": geo_lock_error(raw_d), "not_found": raw_d}, 400
            display_map[p_coord] = p_disp
            display_map[d_coord] = d_disp
            ow_date = data.get("depart", "")
            results = [compute_for_aircraft("one_way", k, v, p_coord, d_coord,
                                            display_map=display_map) for k, v in active.items()]
            if ow_date:
                for res in results:
                    for s in (res.get("segments") or []):
                        if s.get("type") == "revenue":
                            s["date"] = ow_date
        elif mission == "return":
            raw_p = data.get("pickup", "")
            raw_d = data.get("dropoff", "")
            pid_p = data.get("pickup_place_id", "")
            pid_d = data.get("dropoff_place_id", "")
            p_disp, p_coord = resolve_location(pid_p or raw_p, user_label=raw_p)
            d_disp, d_coord = resolve_location(pid_d or raw_d, user_label=raw_d)
            if p_disp is None:
                return {"error": geo_lock_error(raw_p), "not_found": raw_p}, 400
            if d_disp is None:
                return {"error": geo_lock_error(raw_d), "not_found": raw_d}, 400
            display_map[p_coord] = p_disp
            display_map[d_coord] = d_disp
            results = [compute_for_aircraft("return", k, v, p_coord, d_coord,
                                            depart=parse_smart_date(data.get("depart", "")),
                                            ret=parse_smart_date(data.get("return_date", "")),
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
def get_pdf_timestamp():
    try:
        import pytz
        eat = pytz.timezone("Africa/Nairobi")
        now = datetime.datetime.now(eat)
        return now.strftime("Generated: %d %b %Y, %H:%M EAT")
    except Exception:
        now = datetime.datetime.utcnow()
        return now.strftime("Generated: %d %b %Y, %H:%M UTC")

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
                                   client_phone, note, discount, extra_items,
                                   currency="USD", kes_rate=0, ghost_mode=False):

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
    min_hrs = float(result.get("min_chargeable_hrs", 0))
    if min_hrs > 0 and total_hrs < min_hrs:
        total_hrs = min_hrs

    routing_lines = build_routing_lines(flying_segs)
    routing_text = "Routing:\n" + "\n".join(routing_lines) if routing_lines else ""
    note_line = f"Note: {note}" if note else ""

    if ghost_mode:
        total_bundled = float(result.get("total_usd", 0))
        item_parts = [f"Equipment: {ac_label}"]
        if routing_text:
            item_parts.append(routing_text)
        if note_line:
            item_parts.append(note_line)
        item_parts.append("Charter price — all inclusive.")
        items.append({
            "name": "Charter Package\n" + "\n".join(item_parts),
            "quantity": "1",
            "unit_cost": str(round(total_bundled, 2))
        })
    elif total_hrs > 0 and rate > 0:
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
    pax_label = result.get("_adj_pax_label") or result.get("pax_label") or "Mission Costs"
    overnight_label = result.get("overnight_label") or "Crew Overnight"
    was_adjusted_check = result.get("_was_adjusted", False)
    if not ghost_mode:
        if pax_fee > 0 and not was_adjusted_check:
            items.append({
                "name": pax_label,
                "quantity": "1",
                "unit_cost": str(pax_fee)
            })
        elif pax_fee > 0 and was_adjusted_check:
            adj_pax = float(result.get("pax_fee_usd_display") or 0)
            if adj_pax > 0:
                items.append({
                    "name": pax_label,
                    "quantity": "1",
                    "unit_cost": str(round(adj_pax, 2))
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

    to_block = "\n".join(filter(None, [client_name, client_phone, client_email]))
    bank_block = get_bank_details_block()
    terms = OPERATOR.get("invoice", {}).get("terms", "")
    token_override = extra_items.pop("_token_override", None) if isinstance(extra_items, dict) else None
    doc_number = next_record_number(doc_type, token_override)
    disc = float(discount) if discount else 0

    # Determine primary currency from operator config
    fx_cfg = OPERATOR.get("fx", {})
    pdf_currency = fx_cfg.get("primary_currency") or OPERATOR.get("quoting_rules", {}).get("currency") or "USD"

    # Fetch secondary currency reference rate
    sec_currency = ""
    sec_rate = 0.0
    show_secondary = fx_cfg.get("show_kes", True)
    sec_currency = fx_cfg.get("secondary_currency") or OPERATOR.get("secondary_currency") or ""
    if show_secondary and sec_currency:
        try:
            if fx_cfg.get("mode") == "manual":
                sec_rate = float(fx_cfg.get("rates", {}).get(sec_currency, 0))
            else:
                import requests as req
                r = req.get(f"https://open.er-api.com/v6/latest/{pdf_currency}", timeout=5)
                rdata = r.json()
                if rdata.get("result") == "success":
                    sec_rate = float(rdata.get("rates", {}).get(sec_currency, 0))
        except Exception:
            sec_rate = 0.0

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
        "notes": bank_block + (f"\n\nNote: {note}" if note else ""),
        "notes_title": "BANK DETAILS",
        "terms": terms,
        "terms_title": "TERMS & CONDITIONS",
        "currency": pdf_currency,
        "header": doc_type
    }

    # Add secondary currency reference line
    if sec_currency and sec_rate > 0:
        import datetime as _dt
        today_str = _dt.date.today().strftime("%d %b %Y")
        total_usd = float(result.get("total_usd", 0))
        sec_total = round(total_usd * sec_rate)
        payload["kes_note"] = f"≈ {sec_currency} {sec_total:,}  (1 {pdf_currency} = {sec_rate:.2f} {sec_currency})"

    return payload, doc_number

@app.route("/")
def root():
    return redirect(url_for("quote_page"))

@app.route("/admin")
@login_required
def index():
    templates = OPERATOR.get("message_templates", {})
    msg_templates = {
        "quote": templates.get("quote", DEFAULT_MSG_TEMPLATES["quote"]),
        "invoice": templates.get("invoice", DEFAULT_MSG_TEMPLATES["invoice"]),
        "receipt": templates.get("receipt", DEFAULT_MSG_TEMPLATES["receipt"])
    }
    return render_template("index.html", operator=OPERATOR, msg_templates=msg_templates)

@app.route("/admin/quote", methods=["POST"])
@login_required
def admin_quote():
    data = request.get_json()
    result, status = run_quote_engine(data)
    return jsonify(result), status

@app.route("/quote", methods=["GET"])
def quote_page():
    return render_template("quote.html", operator=OPERATOR)


@app.route("/quote/brand-pdf", methods=["POST"])
def quote_brand_pdf():
    import io, os, datetime, uuid
    data = request.get_json()
    result = data.get("result")
    if not result:
        return jsonify({"error": "No result provided"}), 400
    company_name = data.get("company_name", "My Company")
    address = data.get("address", "")
    phone = data.get("phone", "")
    client_name = data.get("client_name", "Valued Client")
    logo_url = data.get("logo_url", "")
    try:
        from_block = company_name
        if address: from_block += f"\n{address}"
        if phone: from_block += f"\n{phone}"
        payload, doc_number = build_pdf_payload_from_result(
            "Quotation", result, client_name, "", phone, "", "0", [],
            currency="USD", kes_rate=0, ghost_mode=False)
        payload["from"] = from_block
        payload["logo"] = logo_url
        payload["powered_by"] = "Powered by QC Aero · qcaero.app"
        out_path = f"/tmp/{doc_number}.pdf"
        hq.generate_pdf_weasy(payload, out_path)
        with open(out_path, "rb") as f:
            pdf_bytes = f.read()
        # Upload to Firebase with 5min auto-delete flag
        try:
            from firebase_admin import storage as fb_storage
            bucket = fb_storage.bucket()
            blob_path = f"demo/brand-pdfs/{doc_number}.pdf"
            blob = bucket.blob(blob_path)
            blob.upload_from_filename(out_path, content_type="application/pdf")
            blob.make_public()
            pdf_url = blob.public_url
            # Schedule delete after 5 mins via metadata
            blob.metadata = {"delete_after": (datetime.datetime.utcnow() + datetime.timedelta(minutes=5)).isoformat()}
            blob.patch()
        except Exception:
            pdf_url = ""
        try:
            os.remove(out_path)
        except Exception:
            pass
        response = __import__('flask').send_file(
            io.BytesIO(pdf_bytes), as_attachment=True,
            download_name=f"{company_name.replace(' ','-')}-Quote.pdf",
            mimetype="application/pdf")
        response.headers["X-PDF-URL"] = pdf_url
        response.headers["X-DOC-NUMBER"] = doc_number
        return response
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/quote/calculate", methods=["POST"])
def quote_calculate():
    data = request.get_json()
    # Handle custom aircraft injection
    custom_ac = data.pop("custom_aircraft", None)
    if custom_ac:
        ac_key = "custom_aircraft"
        custom_ac["active"] = True
        # Temporarily inject into engine
        orig = hq.AIRCRAFT.copy()
        hq.AIRCRAFT[ac_key] = {
            "label": f"{custom_ac.get('label','Custom')} ({custom_ac.get('seater',1)} seater)",
            "speed": float(custom_ac.get("speed", 150)),
            "rate": float(custom_ac.get("rate", 0)),
            "overnight": float(custom_ac.get("overnight_rate", 0)),
            "idle_day": float(custom_ac.get("idle_day_rate", custom_ac.get("rate", 0))),
            "base_key": "custom_base",
            "base_label": custom_ac.get("home_airstrip", ""),
        }
        if custom_ac.get("base_lat") and custom_ac.get("base_lon"):
            hq.USER_AIRPORTS["custom_base"] = {
                "lat": float(custom_ac["base_lat"]),
                "lon": float(custom_ac["base_lon"]),
                "aliases": [],
                "name": custom_ac.get("home_airstrip", "Base")
            }
        hq.PAX_ADMIN_FEE_USD = float(custom_ac.get("pax_fee", 0)) if custom_ac.get("pax_fee_enabled") else 0.0
        # Force only custom aircraft
        data["_force_aircraft"] = {ac_key: custom_ac}
        result, status = run_quote_engine(data)
        hq.AIRCRAFT = orig
    else:
        result, status = run_quote_engine(data)
    return jsonify(result), status

@app.route("/pdf", methods=["POST"])
@login_required
def pdf():
    data = request.get_json()
    try:
        result = data["result"]
        doc_type = data.get("doc_type", "Quotation")
        if doc_type in ("Invoice", "Receipt"):
            return jsonify({"error": "Invoices and receipts must be generated from the CRM. Go to Enquiries to invoice this client."}), 400
        client_name = data.get("client_name", "Client")
        client_email = data.get("client_email", "")
        client_phone = data.get("client_phone", "")
        note = data.get("note", "")
        discount = data.get("discount", "0")
        extra_items = data.get("extras", [])

        currency = data.get("currency", "USD")
        kes_rate = float(data.get("kes_rate", 0))
        ghost_mode = data.get("ghost_mode", False)
        payload, doc_number = build_pdf_payload_from_result(
            doc_type, result, client_name, client_email,
            client_phone, note, discount, extra_items,
            currency=currency, kes_rate=kes_rate, ghost_mode=ghost_mode)
        payload["powered_by"] = "Quotecloud JG"

        out_path = f"/tmp/{doc_number}.pdf"
        hq.generate_pdf_weasy(payload, out_path)
        import os
        pdf_size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
        print(f"PDF generated: {out_path} size={pdf_size} bytes")
        pdf_url = upload_pdf_to_firebase(out_path, doc_number)
        print(f"Firebase Storage result: {pdf_url}")
        # Read PDF into memory before any other operations
        with open(out_path, "rb") as f:
            pdf_bytes = f.read()

        total = calc_pdf_total(result, extra_items, discount)
        save_record(doc_type, client_name, client_email, total, doc_number, extra={
            "ac_label": result.get("ac_label", ""),
            "mission": result.get("mission", ""),
            "pdf_url": pdf_url or "",
            "client_phone": client_phone,
            "client_whatsapp": client_phone
        })
        if True:
            bookings = load_bookings()
            route_summary = ""
            segs = result.get("segments") or []
            if result.get("mission") == "pick_and_drop":
                segs = list(result.get("drop", {}).get("segments", [])) + list(result.get("pick", {}).get("segments", []))
            elif result.get("mission") == "return_both":
                segs = list((result.get("option_a") or {}).get("segments", [])) + list((result.get("option_b") or {}).get("segments", []))
            rev = [s for s in segs if s.get("type") == "revenue"]
            all_flight = [s for s in segs if s.get("type") in ("revenue", "positioning", "depositioning")]
            if rev:
                route_summary = ", ".join(f"{s.get('origin','')} to {s.get('destination','')}" + (f" on {s['date']}" if s.get('date') else "") for s in rev)
            total_hrs_val = round(sum(float(s.get("hours", 0)) for s in all_flight), 2)
            total_nm_val = round(sum(float(s.get("distance_nm", 0)) for s in all_flight))
            bookings[doc_number] = {
                "token": doc_number,
                "status": "PENDING",
                "client_name": client_name,
                "client_email": client_email,
                "client_whatsapp": client_phone,
                "ac_label": result.get("ac_label", ""),
                "ac_key": result.get("ac_key", ""),
                "total_usd": total,
                "mission": result.get("mission", ""),
                "route_summary": route_summary,
                "total_hrs": total_hrs_val,
                "total_nm": total_nm_val,
                "quote_snapshot": result,
                "quote_extras": extra_items or [],
                "pdf_url": pdf_url or "",
                "invoice_number": "",
                "invoice_url": "",
                "created_at": datetime.datetime.now().isoformat(),
                "updated_at": datetime.datetime.now().isoformat(),
                "payment_method": "",
                "payment_ref": "",
                "notes": note or "",
                "source": "admin"
            }
            save_bookings(bookings)

        import io
        response = send_file(io.BytesIO(pdf_bytes), as_attachment=False,
                             download_name=f"{doc_number}.pdf",
                             mimetype="application/pdf")
        response.headers["X-PDF-URL"] = pdf_url or ""
        response.headers["X-DOC-NUMBER"] = doc_number
        return response

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
            hq.generate_pdf_weasy(payload, out_path)

            total = calc_pdf_total(actual, extra_items, discount)
            save_record(doc_type, client_name, client_email, total, doc_number, {
                "ac_label": res.get("ac_label", ""),
                "mission": actual.get("mission", "")
            })

            bookings = load_bookings()
            route_summary = ""
            segs = actual.get("segments") or []
            if actual.get("mission") == "pick_and_drop":
                segs = list(actual.get("drop", {}).get("segments", [])) + list(actual.get("pick", {}).get("segments", []))
            rev = [s for s in segs if s.get("type") == "revenue"]
            if rev:
                route_summary = ", ".join(f"{s.get('origin','')} to {s.get('destination','')}" + (f" on {s['date']}" if s.get('date') else "") for s in rev)
            bookings[doc_number] = {
                "token": doc_number,
                "status": "PENDING",
                "client_name": client_name,
                "client_email": client_email,
                "client_whatsapp": client_phone,
                "ac_label": res.get("ac_label", ""),
                "ac_key": res.get("ac_key", ""),
                "total_usd": total,
                "mission": actual.get("mission", ""),
                "route_summary": route_summary,
                "quote_snapshot": actual,
                "pdf_url": "",
                "invoice_number": "",
                "invoice_url": "",
                "created_at": datetime.datetime.now().isoformat(),
                "updated_at": datetime.datetime.now().isoformat(),
                "payment_method": "",
                "payment_ref": "",
                "notes": note or "",
                "source": "admin"
            }
            save_bookings(bookings)

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

@app.route("/booking/invoice", methods=["POST"])
@login_required
def booking_invoice():
    data = request.get_json()
    try:
        source_token = data.get("source_token", "")
        client_name = data.get("client_name", "Client")
        client_email = data.get("client_email", "")
        client_phone = data.get("client_phone", "")
        note = data.get("note", "")
        discount = data.get("discount", "0")
        uplift_items = data.get("uplift_items", [])

        bookings = load_bookings()
        booking = bookings.get(source_token)
        if not booking:
            return jsonify({"error": "Booking not found"}), 404

        snap = booking.get("quote_snapshot", {})
        if not snap:
            return jsonify({"error": "No quote data found for this booking"}), 400

        payload, doc_number = build_pdf_payload_from_result(
            "Invoice", snap, client_name, client_email, client_phone, note, "0", uplift_items)

        payload["number"] = inherit_token(source_token, "I")
        doc_number = payload["number"]

        disc = float(discount) if discount else 0
        base_total = float(snap.get("total_usd", 0))
        if snap.get("mission") == "return_both":
            base_total = float((snap.get("option_a") or {}).get("total_usd", 0))
        uplift_total = sum(float(it.get("quantity", 1)) * float(it.get("unit_cost", 0)) for it in uplift_items)
        final_total = round(base_total + uplift_total - disc, 2)
        payload["discounts"] = disc

        out_path = f"/tmp/{doc_number}.pdf"
        hq.generate_pdf_weasy(payload, out_path)
        pdf_url = upload_pdf_to_firebase(out_path, doc_number)

        save_record("Invoice", client_name, client_email, final_total, doc_number,
                    extra={"pdf_url": pdf_url or ""})

        bookings[source_token]["invoice_number"] = doc_number
        bookings[source_token]["invoice_url"] = pdf_url or ""
        bookings[source_token]["status"] = "INVOICED"
        bookings[source_token]["updated_at"] = datetime.datetime.now().isoformat()
        save_bookings(bookings)

        with open(out_path, "rb") as f:
            pdf_bytes = f.read()
        import io
        response = send_file(io.BytesIO(pdf_bytes), as_attachment=False,
                             download_name=f"{doc_number}.pdf",
                             mimetype="application/pdf")
        response.headers["X-PDF-URL"] = pdf_url or ""
        response.headers["X-DOC-NUMBER"] = doc_number
        return response
    except Exception as e:
        return jsonify({"error": str(e)}), 400

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
        source_token = data.get("source_token", "")
        if doc_type in ("Quotation", "Quote"):
            type_code = "Q"
        elif doc_type == "Invoice":
            type_code = "I"
        elif doc_type == "Receipt":
            type_code = "R"
        else:
            type_code = "Q"
        doc_number = inherit_token(source_token, type_code) if source_token else generate_token(type_code)

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

        to_block = "\n".join(filter(None, [client_name, client_phone, client_email]))
        bank_block = bank_override if bank_override else get_bank_details_block()
        terms = terms_override if terms_override else OPERATOR.get("invoice", {}).get("terms", "")

        kes_note = ""
        fx_config = OPERATOR.get("fx", {})
        sec_currency = fx_config.get("secondary_currency") or OPERATOR.get("secondary_currency") or ""
        pri_cur = fx_config.get("primary_currency") or OPERATOR.get("quoting_rules", {}).get("currency") or "USD"
        if fx_config.get("show_kes", True) and sec_currency:
            kes_rate_inv = 0
            try:
                if fx_config.get("mode") == "manual":
                    kes_rate_inv = float(fx_config.get("rates", {}).get(sec_currency, 0))
                else:
                    import requests as req
                    r = req.get(f"https://open.er-api.com/v6/latest/{pri_cur}", timeout=5)
                    rdata = r.json()
                    if rdata.get("result") == "success":
                        kes_rate_inv = float(rdata.get("rates", {}).get(sec_currency, 0))
            except Exception:
                kes_rate_inv = 0
            if kes_rate_inv > 0:
                kes_total = round(total * kes_rate_inv)
                today_str = datetime.date.today().strftime("%d %b %Y")
                kes_note = f"≈ {sec_currency} {kes_total:,}  (1 {pri_cur} = {kes_rate_inv:.2f} {sec_currency})"

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
            "notes": bank_block + (f"\n\nNote: {note}" if note else ""),
            "notes_title": "BANK DETAILS",
            "terms": terms,
            "terms_title": "TERMS & CONDITIONS",
            "currency": "USD",
            "kes_note": kes_note,
            "header": doc_type
        }

        out_path = f"/tmp/{doc_number}.pdf"
        hq.generate_pdf_weasy(payload, out_path)
        pdf_url = upload_pdf_to_firebase(out_path, doc_number)
        save_record(doc_type, client_name, client_email, total, doc_number,
                    extra={"pdf_url": pdf_url or ""})

        bookings = load_bookings()
        if source_token and source_token in bookings:
            bookings[source_token]["invoice_number"] = doc_number
            bookings[source_token]["invoice_url"] = pdf_url or ""
            bookings[source_token]["status"] = "INVOICED"
            bookings[source_token]["updated_at"] = datetime.datetime.now().isoformat()
            save_bookings(bookings)
        elif not source_token:
            bookings[doc_number] = {
                "token": doc_number,
                "status": "INVOICED" if doc_type == "Invoice" else "PENDING",
                "client_name": client_name,
                "client_email": client_email,
                "client_whatsapp": client_phone,
                "ac_label": "",
                "ac_key": "",
                "total_usd": total,
                "mission": "manual",
                "route_summary": ", ".join(it.get("name","") for it in items)[:120],
                "quote_snapshot": {},
                "pdf_url": pdf_url or "",
                "invoice_number": doc_number if doc_type == "Invoice" else "",
                "invoice_url": pdf_url or "" if doc_type == "Invoice" else "",
                "created_at": datetime.datetime.now().isoformat(),
                "updated_at": datetime.datetime.now().isoformat(),
                "payment_method": "",
                "payment_ref": "",
                "notes": note or "",
                "source": "admin_manual"
            }
            save_bookings(bookings)

        response = send_file(out_path, as_attachment=False,
                             download_name=f"{doc_number}.pdf",
                             mimetype="application/pdf")
        response.headers["X-PDF-URL"] = pdf_url or ""
        response.headers["X-DOC-NUMBER"] = doc_number
        return response
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
    for r in records:
        if r.get("number") == number:
            r["deleted"] = True
            r["deleted_at"] = datetime.datetime.now().isoformat()
            write_audit_log("record_deleted", {
                "number": number,
                "doc_type": r.get("doc_type", ""),
                "client_name": r.get("client_name", ""),
                "total_usd": r.get("total_usd", 0)
            })
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
    receipt_number = inherit_token(number, "R")

    to_block = "\n".join(filter(None, [
        rec.get("client_name", ""),
        rec.get("client_phone", ""),
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
        "due_date": datetime.date.today().strftime("%d %b %Y"),
        "items": items,
        "discounts": 0,
        "fields": {"tax": False, "discounts": False, "shipping": False},
        "notes": bank_block,
        "notes_title": "BANK DETAILS",
        "terms": terms,
        "terms_title": "TERMS & CONDITIONS",
        "currency": "USD",
        "header": "Receipt"
    }

    out_path = f"/tmp/{receipt_number}.pdf"
    hq.generate_pdf_weasy(payload, out_path)
    receipt_pdf_url = upload_pdf_to_firebase(out_path, receipt_number)

    rec["paid"] = paid_amount >= total
    rec["paid_amount"] = round(paid_amount, 2)
    rec["paid_date"] = paid_date
    rec["payment_mode"] = payment_mode
    rec["payment_ref"] = payment_ref
    rec["receipt_number"] = receipt_number
    rec["receipt_url"] = receipt_pdf_url or ""

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
                paid_amount, receipt_number,
                extra={"pdf_url": receipt_pdf_url or "",
                       "client_whatsapp": rec.get("client_whatsapp", "")})

    if rec.get("paid"):
        bookings = load_bookings()
        matching_token = None
        for tok, b in bookings.items():
            if b.get("invoice_number") == number:
                matching_token = tok
                break
        if matching_token:
            bookings[matching_token]["status"] = "PAID"
            bookings[matching_token]["payment_method"] = payment_mode
            bookings[matching_token]["payment_ref"] = payment_ref
            bookings[matching_token]["updated_at"] = datetime.datetime.now().isoformat()
            save_bookings(bookings)

    response = send_file(out_path, as_attachment=False,
                         download_name=f"{receipt_number}.pdf",
                         mimetype="application/pdf")
    response.headers["X-PDF-URL"] = receipt_pdf_url or ""
    response.headers["X-DOC-NUMBER"] = receipt_number
    return response

@app.route("/records/update_whatsapp", methods=["POST"])
@login_required
def update_record_whatsapp():
    data = request.get_json()
    number = data.get("number", "")
    whatsapp = data.get("client_whatsapp", "").strip()
    records = load_records()
    rec = next((r for r in records if r.get("number") == number), None)
    if not rec:
        return jsonify({"error": "Record not found"}), 404
    rec["client_whatsapp"] = whatsapp
    save_records(records)
    return jsonify({"success": True})

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
@app.route("/aircraft/resolve_base", methods=["POST"])
@login_required
def resolve_base():
    data = request.get_json()
    location = (data.get("location") or "").strip()
    if not location:
        return jsonify({"error": "Location required"}), 400
    disp, coord = resolve_location(location, user_label=location)
    if not disp:
        return jsonify({"found": False, "error": "Could not resolve location"})
    parts = coord.split(",")
    if len(parts) == 2:
        return jsonify({"found": True, "lat": float(parts[0]), "lon": float(parts[1]), "display": disp})
    return jsonify({"found": False})

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
            "quote_validity_hours": OPERATOR.get("quoting_rules", {}).get("quote_validity_hours", 48),
            "show_rate_breakdown": OPERATOR.get("quoting_rules", {}).get("show_rate_breakdown", True)
        }
    }
    return jsonify(safe)

@app.route("/settings/save", methods=["POST"])
@login_required
def save_settings():
    global OPERATOR
    data = request.get_json()
    try:
        save_operator_config(data)
        OPERATOR = data
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── PER-SECTION SETTINGS SAVES ───

@app.route("/settings/save/branding", methods=["POST"])
@login_required
def save_branding():
    global OPERATOR
    data = request.get_json()
    try:
        fields = ["company_name", "tagline", "logo_url", "footer_tagline", "branding", "trust_bar", "social", "contact"]
        update = {k: data[k] for k in fields if k in data}
        OPERATOR.update(update)
        save_operator_config(OPERATOR)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/settings/save/aircraft_mode", methods=["POST"])
@login_required
def save_aircraft_mode():
    global OPERATOR
    data = request.get_json()
    try:
        if "aircraft_mode" in data: OPERATOR["aircraft_mode"] = data["aircraft_mode"]
        if "landing_field_disclaimer" in data: OPERATOR["landing_field_disclaimer"] = data["landing_field_disclaimer"]
        if "airport_suitability_message" in data: OPERATOR["airport_suitability_message"] = data["airport_suitability_message"]
        save_operator_config(OPERATOR)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/settings/save/geo_lock", methods=["POST"])
@login_required
def save_geo_lock():
    global OPERATOR
    data = request.get_json()
    try:
        OPERATOR["geo_lock"] = data.get("geo_lock", {})
        save_operator_config(OPERATOR)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/settings/save/quoting_rules", methods=["POST"])
@login_required
def save_quoting_rules():
    global OPERATOR
    data = request.get_json()
    try:
        OPERATOR["quoting_rules"] = data.get("quoting_rules", {})
        save_operator_config(OPERATOR)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/settings/save/extra_time", methods=["POST"])
@login_required
def save_extra_time():
    global OPERATOR
    data = request.get_json()
    try:
        if "quoting_rules" not in OPERATOR:
            OPERATOR["quoting_rules"] = {}
        OPERATOR["quoting_rules"]["ground_time_buffer_enabled"] = data.get("enabled", False)
        OPERATOR["quoting_rules"]["ground_time_buffer_minutes"] = data.get("minutes", 0)
        save_operator_config(OPERATOR)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/settings/save/client_display", methods=["POST"])
@login_required
def save_client_display():
    global OPERATOR
    data = request.get_json()
    try:
        if "quoting_rules" not in OPERATOR:
            OPERATOR["quoting_rules"] = {}
        OPERATOR["quoting_rules"]["show_distance_to_client"] = data.get("show_distance_to_client", False)
        OPERATOR["quoting_rules"]["quote_validity_hours"] = data.get("quote_validity_hours", 48)
        save_operator_config(OPERATOR)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/settings/save/bank", methods=["POST"])
@login_required
def save_bank():
    global OPERATOR
    data = request.get_json()
    try:
        OPERATOR["bank"] = data.get("bank", {})
        if "invoice" not in OPERATOR: OPERATOR["invoice"] = {}
        if "terms" in data: OPERATOR["invoice"]["terms"] = data["terms"]
        if "prefix" in data: OPERATOR["invoice"]["prefix"] = data["prefix"]
        save_operator_config(OPERATOR)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/settings/save/currency", methods=["POST"])
@login_required
def save_currency():
    global OPERATOR
    data = request.get_json()
    try:
        if "quoting_rules" not in OPERATOR: OPERATOR["quoting_rules"] = {}
        OPERATOR["quoting_rules"]["currency"] = data.get("currency", "USD")
        OPERATOR["quoting_rules"]["currency_symbol"] = data.get("currency_symbol", "$")
        OPERATOR["secondary_currency"] = data.get("secondary_currency", "")
        if "fx" not in OPERATOR: OPERATOR["fx"] = {}
        OPERATOR["fx"]["secondary_currency"] = data.get("secondary_currency", "")
        OPERATOR["fx"]["primary_currency"] = data.get("currency", "USD")
        save_operator_config(OPERATOR)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/settings/save/change_email", methods=["POST"])
@login_required
def save_change_email():
    global OPERATOR
    data = request.get_json()
    password = data.get("password", "")
    new_email = data.get("new_email", "").strip().lower()
    if not new_email:
        return jsonify({"error": "Email required"}), 400
    if password != get_admin_pass():
        return jsonify({"error": "Incorrect password"}), 400
    try:
        if "contact" not in OPERATOR: OPERATOR["contact"] = {}
        OPERATOR["contact"]["email"] = new_email
        save_operator_config(OPERATOR)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# PASSWORD RESET FLOW — Powered by Resend
# ============================================================

def get_resend_api_key():
    return os.environ.get("RESEND_API_KEY", "")

def get_admin_email():
    return os.environ.get("ADMIN_EMAIL", OPERATOR.get("contact", {}).get("email", ""))

def send_reset_email(to_email, reset_link, company_name):
    try:
        import resend
        resend.api_key = get_resend_api_key()
        params = {
            "from": "Quotecloud <noreply@jetman.co.ke>",
            "to": [to_email],
            "subject": f"Password Reset — {company_name}",
            "html": f"""
            <div style="font-family:Inter,sans-serif;max-width:480px;margin:0 auto;padding:40px 24px;background:#fff">
              <div style="font-size:11px;letter-spacing:3px;text-transform:uppercase;color:#999;margin-bottom:32px">Quotecloud · Password Reset</div>
              <h1 style="font-size:22px;font-weight:600;color:#000;margin-bottom:12px">Reset your password</h1>
              <p style="font-size:14px;color:#555;line-height:1.7;margin-bottom:32px">
                A password reset was requested for your <strong>{company_name}</strong> admin account. 
                Click the button below to set a new password. This link expires in <strong>1 hour</strong>.
              </p>
              <a href="{reset_link}" style="display:inline-block;background:#000;color:#fff;padding:14px 28px;text-decoration:none;font-size:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;border-radius:2px">Reset Password →</a>
              <p style="font-size:12px;color:#999;margin-top:32px;line-height:1.6">
                If you didn't request this, ignore this email — your password won't change.<br>
                Link: {reset_link}
              </p>
            </div>
            """
        }
        resend.Emails.send(params)
        return True
    except Exception as e:
        print(f"Resend error: {e}")
        return False

def save_reset_token(token, email):
    try:
        if db:
            expiry = (datetime.datetime.now() + datetime.timedelta(hours=1)).isoformat()
            tenant_collection("password_resets").document(token).set({
                "token": token,
                "email": email,
                "expiry": expiry,
                "used": False,
                "created_at": datetime.datetime.now().isoformat()
            })
            return True
    except Exception as e:
        print(f"Save reset token error: {e}")
    return False

def get_reset_token(token):
    try:
        if db:
            doc = tenant_collection("password_resets").document(token).get()
            if doc.exists:
                return doc.to_dict()
    except Exception as e:
        print(f"Get reset token error: {e}")
    return None

def invalidate_reset_token(token):
    try:
        if db:
            tenant_collection("password_resets").document(token).update({"used": True})
    except Exception as e:
        print(f"Invalidate token error: {e}")

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "GET":
        return render_template("forgot_password.html")
    data = request.get_json()
    email = (data.get("email") or "").strip().lower()
    admin_email = get_admin_email().strip().lower()
    if not email:
        return jsonify({"error": "Email required"}), 400
    if email != admin_email:
        return jsonify({"success": True, "message": "If that email matches our records, a reset link has been sent."})
    token = generate_token("PR")
    base_url = request.host_url.rstrip("/")
    reset_link = f"{base_url}/reset-password/{token}"
    save_reset_token(token, email)
    company_name = OPERATOR.get("company_name", "Quotecloud")
    sent = send_reset_email(email, reset_link, company_name)
    if sent:
        return jsonify({"success": True, "message": "Reset link sent. Check your email."})
    return jsonify({"error": "Failed to send email. Please contact support."}), 500

@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if request.method == "GET":
        record = get_reset_token(token)
        if not record:
            return render_template("reset_password.html", error="Invalid or expired reset link.", token=token, valid=False)
        if record.get("used"):
            return render_template("reset_password.html", error="This reset link has already been used.", token=token, valid=False)
        expiry = datetime.datetime.fromisoformat(record.get("expiry", ""))
        if datetime.datetime.now() > expiry:
            return render_template("reset_password.html", error="This reset link has expired. Please request a new one.", token=token, valid=False)
        return render_template("reset_password.html", token=token, valid=True, error=None)

    data = request.get_json()
    new_pass = data.get("new_password", "")
    confirm = data.get("confirm_password", "")
    if not new_pass or len(new_pass) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400
    if new_pass != confirm:
        return jsonify({"error": "Passwords do not match."}), 400
    record = get_reset_token(token)
    if not record or record.get("used"):
        return jsonify({"error": "Invalid or already used reset link."}), 400
    expiry = datetime.datetime.fromisoformat(record.get("expiry", ""))
    if datetime.datetime.now() > expiry:
        return jsonify({"error": "Reset link has expired."}), 400
    try:
        global OPERATOR
        if "env" not in OPERATOR or OPERATOR["env"] is None:
            OPERATOR["env"] = {}
        OPERATOR["env"]["admin_pass"] = new_pass
        save_operator_config(OPERATOR)
        invalidate_reset_token(token)
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
        save_operator_config(OPERATOR)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/get_maps_key", methods=["GET"])
def get_maps_key():
    return jsonify({"key": ""})  # Key no longer exposed to frontend

@app.route("/maps/geocode", methods=["GET"])
def maps_geocode():
    import requests as req
    params = dict(request.args)
    params["key"] = GOOGLE_API_KEY
    r = req.get("https://maps.googleapis.com/maps/api/geocode/json", params=params, timeout=5)
    return jsonify(r.json())

@app.route("/maps/place", methods=["GET"])
def maps_place():
    import requests as req
    params = dict(request.args)
    params["key"] = GOOGLE_API_KEY
    r = req.get("https://maps.googleapis.com/maps/api/geocode/json", params=params, timeout=5)
    return jsonify(r.json())

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
    fx_config = OPERATOR.get("fx", {})
    show_kes = fx_config.get("show_kes", True)
    pri_cur = fx_config.get("primary_currency") or OPERATOR.get("quoting_rules", {}).get("currency") or "USD"
    sec_cur = fx_config.get("secondary_currency") or OPERATOR.get("secondary_currency") or ""
    if fx_config.get("mode") == "manual":
        manual_rates = fx_config.get("rates", {})
        rates_out = {}
        if sec_cur:
            rates_out[sec_cur] = float(manual_rates.get(sec_cur, 0))
        return jsonify({
            "success": True,
            "show_kes": show_kes,
            "primary_currency": pri_cur,
            "secondary_currency": sec_cur,
            "rates": rates_out,
            "updated": "Manual rate set by operator",
            "mode": "manual"
        })
    try:
        import requests as req
        r = req.get(f"https://open.er-api.com/v6/latest/{pri_cur}", timeout=5)
        data = r.json()
        if data.get("result") == "success":
            rates = data.get("rates", {})
            rates_out = {}
            if sec_cur:
                rates_out[sec_cur] = rates.get(sec_cur, 0)
            return jsonify({
                "success": True,
                "show_kes": show_kes,
                "primary_currency": pri_cur,
                "secondary_currency": sec_cur,
                "rates": rates_out,
                "updated": data.get("time_last_update_utc", ""),
                "mode": "auto"
            })
    except Exception:
        pass
    return jsonify({"success": False, "rates": {}, "mode": "auto"})

@app.route("/fx/save", methods=["POST"])
@login_required
def fx_save():
    global OPERATOR
    data = request.get_json()
    try:
        existing_fx = OPERATOR.get("fx", {})
        pri_cur = existing_fx.get("primary_currency") or OPERATOR.get("quoting_rules", {}).get("currency") or "USD"
        sec_cur = existing_fx.get("secondary_currency") or OPERATOR.get("secondary_currency") or ""
        rates = {}
        if sec_cur and data.get(sec_cur):
            rates[sec_cur] = float(data.get(sec_cur, 0))
        OPERATOR["fx"] = {
            "mode": data.get("mode", "auto"),
            "show_kes": data.get("show_kes", True),
            "primary_currency": pri_cur,
            "secondary_currency": sec_cur,
            "rates": rates
        }
        save_operator_config(OPERATOR)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
@app.route("/autocomplete", methods=["POST"])
def autocomplete():
    data = request.get_json()
    query = (data.get("query") or "").strip()
    if not query or len(query) < 3:
        return jsonify({"predictions": []})

    local_matches = []
    q_lower = query.lower()
    for key, rec in hq.USER_AIRPORTS.items():
        name = rec.get("name", key)
        aliases = rec.get("aliases", [])
        if q_lower in key.lower() or q_lower in name.lower() or any(q_lower in a.lower() for a in aliases):
            local_matches.append({
                "description": name.title(),
                "main": name.title(),
                "secondary": "Verified Location",
                "place_id": "",
                "local_key": key
            })

    try:
        import requests as req
        geo = get_geo_lock()
        geo_enabled = geo.get("enabled", False)
        params = {"input": query, "key": GOOGLE_API_KEY, "language": "en"}
        if geo_enabled and geo.get("center_lat") and geo.get("center_lon"):
            center_lat = geo.get("center_lat")
            center_lon = geo.get("center_lon")
            radius_km = geo.get("radius_km", 500)
            radius_m = int(float(radius_km) * 1000)
            params["location"] = f"{center_lat},{center_lon}"
            params["radius"] = radius_m
            params["strictbounds"] = False
        r = req.get(
            "https://maps.googleapis.com/maps/api/place/autocomplete/json",
            params=params,
            timeout=5
        )
        gdata = r.json()
        google_predictions = [{"description": p["description"], "main": p.get("structured_formatting", {}).get("main_text", ""), "secondary": p.get("structured_formatting", {}).get("secondary_text", ""), "place_id": p.get("place_id", "")} for p in gdata.get("predictions", [])]
    except Exception:
        google_predictions = []

    predictions = local_matches + google_predictions
    return jsonify({"predictions": predictions})

@app.route("/resolve_place", methods=["POST"])
def resolve_place():
    data = request.get_json()
    place_id = (data.get("place_id") or "").strip()
    label = (data.get("label") or "").strip()
    if not place_id:
        return jsonify({"found": False}), 400
    try:
        import requests as req
        r = req.get("https://maps.googleapis.com/maps/api/geocode/json",
                    params={"place_id": place_id, "key": GOOGLE_API_KEY},
                    timeout=5)
        gdata = r.json()
        if gdata.get("status") == "OK":
            loc = gdata["results"][0]["geometry"]["location"]
            lat, lon = float(loc["lat"]), float(loc["lng"])
            if check_geo_lock(lat, lon):
                display = label or reverse_geocode(lat, lon) or f"Pin, {lat:.5f}, {lon:.5f}"
                return jsonify({"found": True, "lat": lat, "lon": lon, "display": display, "coord": f"{lat},{lon}"})
            else:
                return jsonify({"found": False, "geo_error": True, "display": label})
    except Exception as e:
        pass
    return jsonify({"found": False})

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

@app.route("/backup/configs", methods=["GET"])
def backup_configs():
    key = request.args.get("key", "")
    if key != app.secret_key:
        return jsonify({"error": "Unauthorized"}), 401
    configs = {}
    for fname in [OPERATOR_CONFIG_FILE, AIRCRAFT_CONFIG_FILE, RECORDS_FILE, BOOKINGS_FILE]:
        p = pathlib.Path(fname)
        if p.exists():
            try:
                configs[fname] = json.loads(p.read_text())
            except Exception:
                configs[fname] = {}
        else:
            configs[fname] = {}
    return jsonify(configs)
@app.route("/upload_image", methods=["POST"])
@login_required
def upload_image():
    try:
        from firebase_admin import storage as fb_storage
        import uuid
        file = request.files.get("image")
        if not file:
            return jsonify({"error": "No image provided"}), 400
        ext = pathlib.Path(file.filename or "image.jpg").suffix or ".jpg"
        unique_name = f"{uuid.uuid4().hex}{ext}"
        bucket = fb_storage.bucket()
        blob_path = f"tenants/{TENANT_ID}/images/{unique_name}"
        blob = bucket.blob(blob_path)
        blob.upload_from_file(file, content_type=file.mimetype or "image/jpeg")
        blob.make_public()
        return jsonify({"success": True, "url": blob.public_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 400
@app.route("/booking/request", methods=["POST"])
def booking_request():
    data = request.get_json()
    try:
        client_name = data.get("client_name", "").strip()
        print(f"DEBUG booking_request: selected_total={data.get('selected_total')} snap_total={data.get('quote_snapshot',{}).get('total_usd')} option_a_total={data.get('quote_snapshot',{}).get('option_a',{}).get('total_usd') if data.get('quote_snapshot',{}).get('option_a') else None}")
        client_email = data.get("client_email", "").strip()
        quote_snapshot = data.get("quote_snapshot", {})
        if not client_name:
            return jsonify({"error": "Name required"}), 400
        token = data.get("token_override", "").strip() or generate_booking_token()
        bookings = load_bookings()
        route_summary = data.get("route_summary", "")
        client_whatsapp = data.get("client_whatsapp", "").strip()
        bookings[token] = {
            "token": token,
            "status": "PENDING",
            "client_name": client_name,
            "client_email": client_email,
            "client_whatsapp": client_whatsapp,
            "ac_label": quote_snapshot.get("ac_label", ""),
            "ac_key": quote_snapshot.get("ac_key", ""),
            "total_usd": data.get("selected_total") or quote_snapshot.get("total_usd") or float((quote_snapshot.get("option_a") or {}).get("total_usd", 0)),
            "mission": quote_snapshot.get("mission", ""),
            "route_summary": route_summary,
            "total_hrs": round(sum(float(s.get("hours", 0)) for s in [seg for segs in [
                quote_snapshot.get("segments") or [],
                (quote_snapshot.get("drop") or {}).get("segments", []),
                (quote_snapshot.get("pick") or {}).get("segments", []),
                (quote_snapshot.get("option_a") or {}).get("segments", []),
                (quote_snapshot.get("option_b") or {}).get("segments", []),
            ] for seg in segs if seg.get("type") in ("revenue", "positioning", "depositioning")]), 2),
            "total_nm": round(sum(float(s.get("distance_nm", 0)) for s in [seg for segs in [
                quote_snapshot.get("segments") or [],
                (quote_snapshot.get("drop") or {}).get("segments", []),
                (quote_snapshot.get("pick") or {}).get("segments", []),
                (quote_snapshot.get("option_a") or {}).get("segments", []),
                (quote_snapshot.get("option_b") or {}).get("segments", []),
            ] for seg in segs if seg.get("type") in ("revenue", "positioning", "depositioning")])),
            "quote_snapshot": quote_snapshot,
            "created_at": datetime.datetime.now().isoformat(),
            "updated_at": datetime.datetime.now().isoformat(),
            "payment_method": "",
            "payment_ref": "",
            "notes": ""
        }
        save_bookings(bookings)
        wa = get_whatsapp()
        notify_lines = [
            "NEW CHARTER REQUEST",
            f"Ref: {token}",
            f"Client: {client_name}",
            f"Email: {client_email}",
            f"Aircraft: {quote_snapshot.get('ac_label','')}",
            f"Route: {route_summary}",
            f"Total: USD ${float(quote_snapshot.get('total_usd',0)):,.2f}",
            "Review in your admin panel."
        ]
        notify_msg = "\n".join(notify_lines)
        encoded_msg = notify_msg.replace(' ', '%20').replace('\n', '%0A')
        notify_wa = f"https://wa.me/{wa}?text={encoded_msg}" if wa else ""
        return jsonify({
            "success": True,
            "token": token,
            "notify_wa": notify_wa
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400
@app.route("/booking/pdf/<token>", methods=["GET"])
def booking_pdf_get(token):
    try:
        out_path = f"/tmp/{token}.pdf"
        if not pathlib.Path(out_path).exists():
            return jsonify({"error": "PDF not found"}), 404
        return send_file(out_path, as_attachment=False,
                         download_name=f"{token}.pdf",
                         mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 400
@app.route("/booking/pdf", methods=["POST"])
def booking_pdf():
    data = request.get_json()
    try:
        client_name = data.get("client_name", "Client")
        client_email = data.get("client_email", "")
        client_phone = data.get("client_phone", "")
        token = data.get("token", "")
        result = data.get("result", {})

        pdf_currency_mode = "USD"
        kes_rate_for_pdf = 0

        payload, _ = build_pdf_payload_from_result(
            "Quotation", result, client_name, client_email, client_phone, "", "0", [],
            currency=pdf_currency_mode, kes_rate=kes_rate_for_pdf)
        if kes_rate_for_pdf > 0:
            total_for_kes = float(result.get("total_usd", 0))
            if result.get("mission") == "return_both":
                total_for_kes = float((result.get("option_a") or {}).get("total_usd", 0))
            kes_total_val = round(total_for_kes * kes_rate_for_pdf)
            today_str = datetime.date.today().strftime("%-d/%-m/%y")
            payload["kes_note"] = f"KES {kes_total_val:,} (rate 1 USD = KES {kes_rate_for_pdf:.2f}, date {today_str})"
        payload["number"] = token
        payload["notes"] = ""
        payload["notes_title"] = ""
        out_path = f"/tmp/{token}.pdf"
        hq.generate_pdf_weasy(payload, out_path)
        pdf_url = upload_pdf_to_firebase(out_path, token)
        total = float(result.get("total_usd", 0))
        if result.get("mission") == "return_both":
            total = float((result.get("option_a") or {}).get("total_usd", 0))
        save_record("Quotation", client_name, client_email, total, token, extra={
            "pdf_url": pdf_url or "",
            "client_phone": client_phone,
            "client_whatsapp": client_phone,
            "ac_label": result.get("ac_label", ""),
            "mission": result.get("mission", ""),
            "source": "client"
        })
        bookings = load_bookings()
        if token in bookings:
            bookings[token]["pdf_url"] = pdf_url or ""
            bookings[token]["updated_at"] = datetime.datetime.now().isoformat()
            save_bookings(bookings)
        response = send_file(out_path, as_attachment=False,
                             download_name=f"{token}.pdf",
                             mimetype="application/pdf")
        response.headers["X-PDF-URL"] = pdf_url or ""
        response.headers["X-DOC-NUMBER"] = token
        return response
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/booking/status/<token>", methods=["GET"])
def booking_status(token):
    bookings = load_bookings()
    b = bookings.get(token)
    if not b:
        return jsonify({"error": "Booking not found"}), 404
    return jsonify({
        "token": b["token"],
        "status": b["status"],
        "ac_label": b["ac_label"],
        "total_usd": b["total_usd"],
        "client_name": b["client_name"],
        "created_at": b["created_at"]
    })

@app.route("/booking/update", methods=["POST"])
@login_required
def booking_update():
    data = request.get_json()
    token = data.get("token", "")
    status = data.get("status", "")
    bookings = load_bookings()
    if token not in bookings:
        return jsonify({"error": "Booking not found"}), 404
    bookings[token]["status"] = status
    bookings[token]["updated_at"] = datetime.datetime.now().isoformat()
    if status == "INVOICED":
        bookings[token]["invoice_requested"] = False
        bookings[token]["invoice_requested_at"] = ""
    if data.get("notes"):
        bookings[token]["notes"] = data["notes"]
    if data.get("payment_ref"):
        bookings[token]["payment_ref"] = data["payment_ref"]
    if data.get("payment_method"):
        bookings[token]["payment_method"] = data["payment_method"]
    save_bookings(bookings)
    return jsonify({"success": True})

@app.route("/bookings", methods=["GET"])
@login_required
def get_bookings():
    bookings = load_bookings()
    visible = [b for b in bookings.values() if not b.get("deleted")]
    return jsonify(visible)

@app.route("/booking/get", methods=["POST"])
@login_required
def booking_get():
    data = request.get_json()
    token = data.get("token", "")
    bookings = load_bookings()
    if token not in bookings:
        return jsonify({"error": "Booking not found"}), 404
    return jsonify(bookings[token])
@app.route("/booking/invoice_request", methods=["POST"])
def booking_invoice_request():
    data = request.get_json()
    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"error": "Token required"}), 400
    bookings = load_bookings()
    if token not in bookings:
        return jsonify({"error": "Booking not found"}), 404
    bookings[token]["invoice_requested"] = True
    bookings[token]["invoice_requested_at"] = datetime.datetime.now().isoformat()
    bookings[token]["updated_at"] = datetime.datetime.now().isoformat()
    save_bookings(bookings)
    return jsonify({"success": True, "token": token})
@app.route("/bookings/delete", methods=["POST"])
@login_required
def delete_bookings():
    data = request.get_json()
    password = data.get("password", "")
    tokens = data.get("tokens", [])
    if password != get_admin_pass():
        return jsonify({"error": "Invalid password."}), 403
    if not tokens:
        return jsonify({"error": "No tokens provided."}), 400
    bookings = load_bookings()
    deleted = 0
    for token in tokens:
        if token in bookings:
            bookings[token]["deleted"] = True
            bookings[token]["deleted_at"] = datetime.datetime.now().isoformat()
            deleted += 1
            write_audit_log("booking_deleted", {
                "token": token,
                "client_name": bookings[token].get("client_name", ""),
                "total_usd": bookings[token].get("total_usd", 0)
            })
    save_bookings(bookings)
    return jsonify({"success": True, "deleted": deleted})
@app.route("/debug/pdf_test", methods=["GET"])
@login_required
def debug_pdf_test():
    try:
        hq.generate_pdf_weasy({"header":"Invoice","logo":"","from":"Test Co","to":"Client","number":"TEST-001","date":"28 May 2026","due_date":"04 Jun 2026","items":[{"name":"Test Item","quantity":1,"unit_cost":100}],"discounts":0,"notes":"","terms":"","currency":"USD"}, "/tmp/test_weasy.pdf")
        return jsonify({"success": True, "message": "WeasyPrint OK"})
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()})

@app.route("/admin/wipe_data", methods=["POST"])
@login_required
def wipe_data():
    data = request.get_json()
    if data.get("password") != get_admin_pass():
        return jsonify({"error": "Invalid password"}), 403
    pathlib.Path(RECORDS_FILE).write_text("[]")
    pathlib.Path(BOOKINGS_FILE).write_text("{}")
    return jsonify({"success": True, "message": "Wiped."})
DEFAULT_MSG_TEMPLATES = {
    "quote": "Hello {client_name},\n\nPlease find herein your quotation from {company}.\n\n📄 View Quote: {pdf_url}\n\nRef: {ref}\nAmount: USD ${amount}\n\nTO CONFIRM YOUR BOOKING:\n• This quote is valid for 48 hours.\n• To proceed, please confirm and we will issue a formal invoice.\n• Kindly have passenger IDs and passports ready upon booking.\n\nFor any queries, reach us anytime:\n📞 {phone}\n\nThank you for choosing {company}.\n\nWarm regards,\n{company} Reservations Team",
    "invoice": "Hello {client_name},\n\nPlease find herein your invoice from {company}.\n\n📄 View Invoice: {pdf_url}\n\nRef: {ref}\nAmount: USD ${amount}\n\nPAYMENT TERMS:\n• A deposit of 40% is required to secure your booking.\n• Full balance must be cleared prior to departure.\n• Kindly share copies of all passenger IDs and passports upon confirmation.\n\nFor any queries, reach us anytime:\n📞 {phone}\n\nThank you for choosing {company}.\n\nWarm regards,\n{company} Reservations Team",
    "receipt": "Dear {client_name},\n\nThank you for your payment. Please find attached your receipt from {company}.\n\n📄 View Receipt: {pdf_url}\n\nRef: {ref}\nAmount Received: USD ${amount}\n\nYOUR FLIGHT IS CONFIRMED:\n• Our airport team will be in touch ahead of departure.\n• Please have your ID/Passport ready for check-in.\n• Arrive at least 30 minutes before scheduled departure.\n• Luggage allowance will be confirmed by our team.\n\nFor assistance anytime:\n📞 {phone}\n\nWe look forward to flying with you.\n\nWarm regards,\n{company} Reservations Team"
}

@app.route("/settings/message_templates", methods=["GET"])
@login_required
def get_message_templates():
    templates = OPERATOR.get("message_templates", {})
    result = {}
    for key in ("quote", "invoice", "receipt"):
        result[key] = templates.get(key, DEFAULT_MSG_TEMPLATES[key])
    return jsonify(result)

@app.route("/settings/message_templates/save", methods=["POST"])
@login_required
def save_message_templates():
    global OPERATOR
    data = request.get_json()
    try:
        if "message_templates" not in OPERATOR:
            OPERATOR["message_templates"] = {}
        for key in ("quote", "invoice", "receipt"):
            if data.get(key):
                OPERATOR["message_templates"][key] = data[key]
        save_operator_config(OPERATOR)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/share/email", methods=["POST"])
@login_required
def share_email():
    data = request.get_json()
    try:
        import resend
        resend.api_key = os.environ.get("RESEND_API_KEY", "")
        to_email = data.get("to_email", "")
        client_name = data.get("client_name", "Valued Client")
        doc_type = data.get("doc_type", "Document")
        doc_number = data.get("doc_number", "")
        pdf_url = data.get("pdf_url", "")
        amount = float(data.get("amount", 0))
        ac_label = data.get("ac_label", "")
        route = data.get("route", "")
        company_name = OPERATOR.get("company_name", "Jetman Global")
        contact_phone = OPERATOR.get("contact", {}).get("phone", "+254 701 007 777")
        is_invoice = doc_type == "Invoice"
        pdf_btn = f'<a href="{pdf_url}" style="display:inline-block;background:#000;color:#fff;padding:14px 28px;text-decoration:none;font-size:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;border-radius:2px;margin:20px 0">View {doc_type} →</a>' if pdf_url else ""
        payment_section = """
        <div style="background:#f8f8f8;border-left:3px solid #000;padding:16px 20px;margin:20px 0;border-radius:0 4px 4px 0">
          <p style="font-weight:700;font-size:13px;letter-spacing:1px;text-transform:uppercase;margin:0 0 10px">Payment Terms</p>
          <p style="margin:4px 0;font-size:13px;color:#333">• A deposit of 40% is required to secure your booking.</p>
          <p style="margin:4px 0;font-size:13px;color:#333">• Full balance must be cleared prior to departure.</p>
          <p style="margin:4px 0;font-size:13px;color:#333">• Kindly share copies of all passenger IDs and passports upon confirmation.</p>
        </div>""" if is_invoice else """
        <div style="background:#f8f8f8;border-left:3px solid #000;padding:16px 20px;margin:20px 0;border-radius:0 4px 4px 0">
          <p style="font-weight:700;font-size:13px;letter-spacing:1px;text-transform:uppercase;margin:0 0 10px">To Confirm Your Booking</p>
          <p style="margin:4px 0;font-size:13px;color:#333">• This quote is valid for 48 hours.</p>
          <p style="margin:4px 0;font-size:13px;color:#333">• To proceed, confirm and we will issue a formal invoice.</p>
          <p style="margin:4px 0;font-size:13px;color:#333">• Kindly have passenger IDs and passports ready upon booking.</p>
        </div>"""
        html = f"""
        <div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;padding:40px 24px;background:#fff">
          <div style="font-size:10px;letter-spacing:3px;text-transform:uppercase;color:#999;margin-bottom:32px">{company_name} · Charter Aviation</div>
          <h1 style="font-size:22px;font-weight:700;color:#000;margin-bottom:6px">{doc_type}</h1>
          <p style="font-size:13px;color:#999;margin-bottom:32px">Ref — {doc_number}</p>
          <p style="font-size:15px;color:#333;line-height:1.7;margin-bottom:8px">Dear {client_name},</p>
          <p style="font-size:14px;color:#555;line-height:1.7;margin-bottom:4px">Please find herein your {doc_type.lower()} from {company_name}.</p>
          {f'<p style="font-size:13px;color:#555;margin-bottom:4px">Aircraft: <strong>{ac_label}</strong></p>' if ac_label else ''}
          {f'<p style="font-size:13px;color:#555;margin-bottom:4px">Route: <strong>{route}</strong></p>' if route else ''}
          <p style="font-size:16px;font-weight:700;color:#000;margin:16px 0">Total: USD ${amount:,.2f}</p>
          {pdf_btn}
          {payment_section}
          <p style="font-size:13px;color:#555;line-height:1.7">For any queries, reach us anytime:<br>
          <strong>📞 {contact_phone}</strong></p>
          <div style="margin-top:40px;padding-top:20px;border-top:1px solid #eee">
            <p style="font-size:12px;color:#999;margin:0">Thank you for choosing {company_name}.</p>
            <p style="font-size:12px;color:#999;margin:4px 0">Warm regards, {company_name} Reservations Team</p>
          </div>
        </div>"""
        params = {
            "from": f"{company_name} <noreply@jetman.co.ke>",
            "to": [to_email],
            "subject": f"{doc_type} — Ref {doc_number} — {company_name}",
            "html": html
        }
        resend.Emails.send(params)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
if __name__ == "__main__":
    app.run(debug=True, port=5000)

