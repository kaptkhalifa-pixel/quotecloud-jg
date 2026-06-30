"""
Quotecloud JG Live Smoke Test
Run after every deploy to verify all PDF-generating routes work end-to-end
against the LIVE Render deployment.
Usage: python3 smoke_test.py
"""
import sys
import requests
import datetime
import getpass

BASE_URL = "https://quotecloud-jg.onrender.com"

results = []
session = requests.Session()
created_tokens = []
created_record_numbers = []

def test(name, fn):
    try:
        fn()
        results.append((name, True, ""))
        print(f"PASS {name}")
    except Exception as e:
        results.append((name, False, str(e)))
        print(f"FAIL {name} -- Error: {e}")

def login():
    username = input("Admin username: ").strip()
    password = getpass.getpass("Admin password: ").strip()
    resp = session.post(f"{BASE_URL}/login", data={"username": username, "password": password}, allow_redirects=False)
    if resp.status_code != 302 or "login" in resp.headers.get("Location", ""):
        raise Exception("Login failed -- check credentials")
    print("Logged in successfully.\n")

def admin_one_way():
    body = {
        "doc_type": "Quotation",
        "client_name": "Smoke Test Client",
        "client_email": "test@test.com",
        "client_phone": "254700000000",
        "discount": "0",
        "note": "",
        "extras": [],
        "currency": "USD",
        "kes_rate": 0,
        "result": {
            "mission": "one_way",
            "ac_label": "Test Aircraft",
            "ac_key": "test_ac",
            "total_usd": 1500,
            "rate_usd": 1500,
            "segments": [{"type": "revenue", "origin": "Wilson", "destination": "Nanyuki", "nm": 100, "hours": 1.0, "cost": 1500, "date": None}]
        }
    }
    resp = session.post(f"{BASE_URL}/pdf", json=body)
    if resp.status_code != 200:
        raise Exception(f"Status {resp.status_code}: {resp.text[:200]}")
    if len(resp.content) < 1000:
        raise Exception(f"PDF suspiciously small ({len(resp.content)} bytes)")
    doc_number = resp.headers.get("X-DOC-NUMBER", "")
    if doc_number:
        created_record_numbers.append(doc_number)
        created_tokens.append(doc_number)

def client_booking_pdf():
    token = f"SMOKE-TEST-{datetime.datetime.now().strftime('%H%M%S')}"
    body = {
        "client_name": "Smoke Test Client",
        "client_email": "test@test.com",
        "client_phone": "254700000000",
        "token": token,
        "result": {
            "mission": "one_way",
            "ac_label": "Test Aircraft",
            "ac_key": "test_ac",
            "total_usd": 1500,
            "rate_usd": 1500,
            "segments": [{"type": "revenue", "origin": "Wilson", "destination": "Nanyuki", "nm": 100, "hours": 1.0, "cost": 1500, "date": None}]
        }
    }
    resp = requests.post(f"{BASE_URL}/booking/pdf", json=body)
    if resp.status_code != 200:
        raise Exception(f"Status {resp.status_code}: {resp.text[:200]}")
    if len(resp.content) < 1000:
        raise Exception(f"PDF suspiciously small ({len(resp.content)} bytes)")
    created_tokens.append(token)
    created_record_numbers.append(token)

def manual_invoice_test():
    body = {
        "client_name": "Smoke Test Client",
        "client_email": "test@test.com",
        "client_phone": "254700000000",
        "discount": "0",
        "note": "",
        "doc_type": "Invoice",
        "line_items": [{"description": "Test Charter", "quantity": 1, "unit_cost": 1500}]
    }
    resp = session.post(f"{BASE_URL}/manual_invoice", json=body)
    if resp.status_code != 200:
        raise Exception(f"Status {resp.status_code}: {resp.text[:200]}")
    if len(resp.content) < 1000:
        raise Exception(f"PDF suspiciously small ({len(resp.content)} bytes)")
    doc_number = resp.headers.get("X-DOC-NUMBER", "")
    if doc_number:
        created_record_numbers.append(doc_number)
        created_tokens.append(doc_number)

def receipt_test():
    inv_body = {
        "client_name": "Smoke Test Client",
        "client_email": "test@test.com",
        "client_phone": "254700000000",
        "discount": "0",
        "note": "",
        "doc_type": "Invoice",
        "line_items": [{"description": "Test Charter for Receipt", "quantity": 1, "unit_cost": 1500}]
    }
    inv_resp = session.post(f"{BASE_URL}/manual_invoice", json=inv_body)
    if inv_resp.status_code != 200:
        raise Exception(f"Could not create test invoice for receipt test: {inv_resp.status_code}")
    doc_number = inv_resp.headers.get("X-DOC-NUMBER", "")
    if not doc_number:
        raise Exception("No doc number returned from invoice creation")
    created_record_numbers.append(doc_number)
    created_tokens.append(doc_number)

    receipt_body = {
        "number": doc_number,
        "paid_amount": 1500,
        "paid_date": datetime.date.today().strftime("%d/%m/%Y"),
        "payment_mode": "M-Pesa",
        "payment_ref": "SMOKE-TEST-REF"
    }
    resp = session.post(f"{BASE_URL}/records/generate_receipt", json=receipt_body)
    if resp.status_code != 200:
        raise Exception(f"Status {resp.status_code}: {resp.text[:200]}")
    if len(resp.content) < 1000:
        raise Exception(f"PDF suspiciously small ({len(resp.content)} bytes)")
    receipt_number = resp.headers.get("X-DOC-NUMBER", "")
    if receipt_number:
        created_record_numbers.append(receipt_number)

print("=" * 50)
print("QUOTECLOUD JG LIVE SMOKE TEST")
print(f"Target: {BASE_URL}")
print("=" * 50)
print()

try:
    login()
except Exception as e:
    print(f"FATAL: Could not log in -- {e}")
    sys.exit(1)

test("Admin one-way quote PDF", admin_one_way)
test("Client-facing booking PDF", client_booking_pdf)
test("Manual/CRM invoice PDF", manual_invoice_test)
test("Receipt generation PDF", receipt_test)

print()
print("Cleaning up test data...")
try:
    admin_pass = getpass.getpass("Re-enter admin password to confirm cleanup: ").strip()
    unique_tokens = list(set(created_tokens))
    if unique_tokens:
        del_resp = session.post(f"{BASE_URL}/bookings/delete", json={"tokens": unique_tokens, "password": admin_pass})
        if del_resp.status_code == 200:
            print(f"Deleted {del_resp.json().get('deleted', 0)} test booking(s).")
        else:
            print(f"Booking cleanup warning: {del_resp.status_code} {del_resp.text[:150]}")
    for num in set(created_record_numbers):
        del_resp = session.post(f"{BASE_URL}/records/delete", json={"number": num, "password": admin_pass})
        if del_resp.status_code != 200:
            print(f"Record cleanup warning for {num}: {del_resp.status_code}")
    print("Cleanup complete.")
except Exception as e:
    print(f"Cleanup warning (non-fatal, you may need to manually delete test records): {e}")

print()
print("=" * 50)
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"RESULT: {passed}/{total} passed")
print("=" * 50)

if passed < total:
    sys.exit(1)

