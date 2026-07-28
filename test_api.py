import urllib.request
import json
import sys

def test_api(payload):
    req = urllib.request.Request(
        "http://localhost:8001/api/intake", 
        method="POST", 
        headers={"Content-Type": "application/json"}, 
        data=json.dumps(payload).encode('utf-8')
    )
    try:
        res = urllib.request.urlopen(req)
        print(f"Status: {res.getcode()}")
        print(f"Response: {res.read().decode('utf-8')}")
    except urllib.error.HTTPError as e:
        print(f"HTTP Error Status: {e.code}")
        print(f"Response: {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"Error: {str(e)}")
    print("-" * 40)

print("--- High Confidence Complaint ---")
test_api({
    "raw_text": "I cannot log into the AFMS portal, my password is locked",
    "complainant_service_no": "12345",
    "complainant_name": "Test User",
    "complainant_unit": "HQ",
    "complainant_rank": "Sgt",
    "operator_id": "test"
})

print("--- Ambiguous Complaint ---")
test_api({
    "raw_text": "the system isn't working",
    "complainant_service_no": "99999",
    "complainant_name": "Test User 2",
    "complainant_unit": "Admin",
    "complainant_rank": "Cpl",
    "operator_id": "test"
})
