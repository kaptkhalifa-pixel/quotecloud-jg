# =========================================================
# QUOTECLOUD BY JETMAN GLOBAL
# app.py v2.0.0
# White-label charter quote platform
# Baseline: heliflight app.py v1.7.3
# =========================================================
import sys, os, json, re, urllib.parse, pathlib
sys.path.insert(0, os.path.dirname(__file__))
from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for
from functools import wraps
import quotecloud_engine as hq

app = Flask(__name__)

# ------------------------------------------------------------------
# Load operator config
# ------------------------------------------------------------------
OPERATOR_CONFIG_FILE = "operator_config.json"

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

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "AIzaSyByT9tWG6pHLXslzp5aJFElULC9oJwXu5o")
INVGEN_API_KEY = os.environ.get("INVGEN_API_KEY", "sk_elcdkPBJLZnAMEghIVyDc6llmS0iOraY")
ADMIN_USER = os.environ.get("ADMIN_USER", OPERATOR.get("env", {}).get("admin_user", "admin"))
ADMIN_PASS = os.environ.get("ADMIN_PASS", OPERATOR.get("env", {}).get("admin_pass", "changeme"))
AIRCRAFT_CONFIG_FILE = "hf_aircraft.json"

hq.load_airports()

# ------------------------------------------------------------------
# Auth
# ------------------------------------------------------------------
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
        if (request.form.get("username") == ADMIN_USER and
                request.form.get("password") == ADMIN_PASS):
            session["logged_in"] = True
            return redirect(url_for("index"))
        error = "Invalid credentials. Please try again."
    return render_template("login.html", operator=OPERATOR, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ------------------------------------------------------------------
# Aircraft
# ------------------------------------------------------------------
DEFAULT_AIRCRAFT = {
    "as350": {
        "label": "Airbus AS350",
        "seater": 5,
        "speed": 120.0,
        "rate": 2200.0,
        "pax_fee": 100.0,
        "active": True
    }
}

def load_aircraft():
    p = pathlib.Path(AIRCRAFT_CONFIG_FILE)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return DEFAULT_AIRCRAFT.copy()

def save_aircraft(data):
    pathlib.Path(AIRCRAFT_CONFIG_FILE).write_text(json.dumps(data, indent=2))

# ------------------------------------------------------------------
# Geocoding
# ------------------------------------------------------------------
def reverse_geocode(lat, lon):
    try:
        import requests as req
        r = req.get("https://maps.googleapis.com/maps/api/geocode/json",
                    params={"latlng": f"{lat},{lon}", "key": GOOGLE_API_KEY, "region": "ke"},
                    timeout=5)
        data = r.json()
        if data.get("status") == "OK":
            components = data["results"][0]["address_components"]
            locality = next((c["long_name"] for c in components
                             if "locality" in c["types"]), None)
            admin = next((c["long_name"] for c in components
                          if "administrative_area_level_1" in c["types"]), None)
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
            r = req.get(s, allow_redirects=True, timeout=5,
                        headers={"User-Agent": "Mozilla/5.0"})
            s = r.url
        except Exception:
            pass
    s = s.replace(",+", ",").replace("%2C+", ",")
    try:
        lat, lon = hq.parse_map_pin(s)
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
        query = clean if "kenya" in clean.lower() else clean + " Kenya"
        r = req.get("https://maps.googleapis.com/maps/api/geocode/json",
                    params={"address": query, "key": GOOGLE_API_KEY, "region": "ke"},
                    timeout=5)
        data = r.json()
        if data.get("status") == "OK":
            loc = data["results"][0]["geometry"]["location"]
            lat, lon = float(loc["lat"]), float(loc["lng"])
            if -5.0 <= lat <= 5.0 and 33.5 <= lon <= 42.0:
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

# ------------------------------------------------------------------
# Quote engine
# ------------------------------------------------------------------
def compute_for_aircraft(mission, ac_key, ac_cfg, pickup_coord, dropoff_coord,
                          depart=None, ret=None, legs=None, display_map=None):
    orig = hq.AIRCRAFT.copy()
    orig_pax = hq.PAX_ADMIN_FEE_USD
    hq.AIRCRAFT[ac_key] = {
        "label": f"{ac_cfg['label']} ({ac_cfg['seater']} seater)",
        "speed": float(ac_cfg["speed"]),
        "rate": float(ac_cfg["rate"]),
        "overnight": 300.0,
        "idle_day": float(ac_cfg["rate"]),
    }
    hq.PAX_ADMIN_FEE_USD = float(ac_cfg["pax_fee"])
    try:
        if mission == "one_way":
            result = hq.compute_one_way(pickup_coord, dropoff_coord, ac_key)
        elif mission == "return":
            import datetime as dt
            d0 = dt.datetime.strptime(depart, "%d/%m/%y").date()
            d1 = dt.datetime.strptime(ret, "%d/%m/%y").date()
            wait_days = max((d1 - d0).days, 0)
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
            result = {
                "mission": "return_both",
                "option_a": option_a,
                "option_b": option_b,
                "wait_days": wait_days
            }
        elif mission == "safari":
            result = hq.compute_safari(legs, ac_key)
        else:
            result = {"error": "Unknown mission"}
        if display_map:
            apply_display_names(result, display_map)
        result["ac_label"] = f"{ac_cfg['label']} ({ac_cfg['seater']} seater)"
        result["ac_key"] = ac_key
    except Exception as e:
        result = {
            "error": str(e),
            "ac_label": f"{ac_cfg['label']} ({ac_cfg['seater']} seater)",
            "ac_key": ac_key
        }
    finally:
        hq.AIRCRAFT = orig
        hq.PAX_ADMIN_FEE_USD = orig_pax
    return result

def run_quote_engine(data):
    mission = data.get("mission")
    aircraft_cfg = load_aircraft()
    active = {k: v for k, v in aircraft_cfg.items() if v.get("active")}
    if not active:
        return {"error": "No aircraft available."}, 400
    display_map = {}
    try:
        if mission == "one_way":
            raw_p = data.get("pickup", "")
            raw_d = data.get("dropoff", "")
            p_disp, p_coord = resolve_location(raw_p, user_label=raw_p)
            d_disp, d_coord = resolve_location(raw_d, user_label=raw_d)
            if p_disp is None:
                return {"error": f"Not recognised: {repr(raw_p)}. Use location name, Maps link or coordinates.", "not_found": raw_p}, 400
            if d_disp is None:
                return {"error": f"Not recognised: {repr(raw_d)}. Use location name, Maps link or coordinates.", "not_found": raw_d}, 400
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
                return {"error": f"Not recognised: {repr(raw_p)}.", "not_found": raw_p}, 400
            if d_disp is None:
                return {"error": f"Not recognised: {repr(raw_d)}.", "not_found": raw_d}, 400
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
                    return {"error": f"Not recognised: {repr(raw_o)}.", "not_found": raw_o}, 400
                if d_disp2 is None:
                    return {"error": f"Not recognised: {repr(raw_d2)}.", "not_found": raw_d2}, 400
                display_map[o_coord] = o_disp
                display_map[d_coord2] = d_disp2
                legs.append({"origin": o_coord, "destination": d_coord2, "date": L.get("date", "")})
            results = [compute_for_aircraft("safari", k, v, None, None,
                                            legs=legs, display_map=display_map) for k, v in active.items()]
        else:
            return {"error": "Unknown mission type"}, 400
        return {"multi": True, "results": results}, 200
    except Exception as e:
        return {"error": str(e)}, 400

# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------
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

@app.route("/pdf", methods=["POST"])
@login_required
def pdf():
    data = request.get_json()
    try:
        result = data["result"]
        doc_type = data.get("doc_type", "Q")
        name = data.get("client_name", "Client")
        email = data.get("client_email", "")
        phone = data.get("client_phone", "")
        note = data.get("note", "")
        discount = data.get("discount", "0")
        extras = data.get("extras", [])
        payload, out_path, number = hq.build_pdf_payload(
            doc_type, name, email, phone, note, discount, result, extras)
        hq.generate_pdf(payload, out_path)
        return send_file(out_path, as_attachment=True,
                         download_name=f"{number}.pdf",
                         mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 400

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

# ------------------------------------------------------------------
# Operator config routes
# ------------------------------------------------------------------
@app.route("/operator/config", methods=["GET"])
@login_required
def get_operator_config():
    return jsonify(OPERATOR)

@app.route("/operator/config/save", methods=["POST"])
@login_required
def save_operator_config():
    data = request.get_json()
    try:
        pathlib.Path(OPERATOR_CONFIG_FILE).write_text(json.dumps(data, indent=2))
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ------------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True, port=5000)
