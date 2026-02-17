#!/usr/bin/env python3
"""
Probe endpoints to find the correct API entrypoint and check for 'rating' in assets.
Usage:
  IMMICH_INSTANCE_URL="http://your-immich:2283" IMMICH_API_KEY="key" python3 script/check_api_entrypoints.py
"""
import os
import sys
import json
import time
from urllib import request, error

BASE = os.getenv("IMMICH_INSTANCE_URL")
API_KEY = os.getenv("IMMICH_API_KEY")
if not BASE or not API_KEY:
    print("Set IMMICH_INSTANCE_URL and IMMICH_API_KEY", file=sys.stderr)
    sys.exit(2)

HEADERS = {"x-api-key": API_KEY, "Accept": "application/json", "Content-Type": "application/json"}

def try_get(path, timeout=10):
    url = BASE.rstrip("/") + path
    req = request.Request(url, headers=HEADERS, method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
            return url, json.loads(raw)
    except error.HTTPError as e:
        return url, {"http_error": e.code, "reason": e.reason}
    except Exception as e:
        return url, {"error": str(e)}

def try_post(path, payload, timeout=15):
    url = BASE.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers=HEADERS, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
            return url, json.loads(raw)
    except error.HTTPError as e:
        return url, {"http_error": e.code, "reason": e.reason}
    except Exception as e:
        return url, {"error": str(e)}

def sample_from_list(data):
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        # common paged shapes
        for key in ("items", "assets", "data", "results"):
            val = data.get(key)
            if isinstance(val, list) and val:
                return val[0]
        # try assets.items
        assets = data.get("assets")
        if isinstance(assets, dict):
            items = assets.get("items")
            if isinstance(items, list) and items:
                return items[0]
    return None

# 1) Try search/metadata POST (server likely returns assets there)
print("Trying POST /search/metadata with payload {'withArchived': True, 'size':5}")
url, resp = try_post("/search/metadata", {"withArchived": True, "size": 5})
print(f"-> {url}")
try:
    if isinstance(resp, dict) and ("http_error" in resp or "error" in resp):
        print(json.dumps(resp, indent=2))
    elif isinstance(resp, list):
        print(f"List response ({len(resp)} items).")
    else:
        print("Top-level keys:", list(resp.keys()) if isinstance(resp, dict) else type(resp).__name__)
except Exception:
    print("Response not printable")

sample = sample_from_list(resp)
if sample:
    print("Sample asset from search/metadata:")
    print(json.dumps({
        "id": sample.get("id"),
        "fileName": sample.get("fileName"),
        "rating": sample.get("rating"),
        "isFavorite": sample.get("isFavorite")
    }, ensure_ascii=False, indent=2))
else:
    print("No asset sample found in search/metadata response.")

time.sleep(0.5)

# 2) Try POST /assets/batch with sample ids
print("\nTrying POST /assets/batch with sample ids ['000']")
url, resp = try_post("/assets/batch", {"ids": ["000"]})
print(f"-> {url}")
try:
    if isinstance(resp, dict) and ("http_error" in resp or "error" in resp):
        print(json.dumps(resp, indent=2))
    elif isinstance(resp, list):
        print(f"List response ({len(resp)} items).")
    else:
        print("Top-level keys:", list(resp.keys()) if isinstance(resp, dict) else type(resp).__name__)
except Exception:
    print("Response not printable")

time.sleep(0.5)

# 3) Try common list endpoints GET
for p in ("/assets?limit=5", "/asset?limit=5", "/assets", "/asset"):
    print(f"\nTrying GET {p}")
    url, resp = try_get(p)
    print(f"-> {url}")
    if isinstance(resp, dict) and ('http_error' in resp or 'error' in resp):
        print(json.dumps(resp, indent=2))
        continue
    sample = sample_from_list(resp)
    if sample:
        print("Sample asset:")
        print(json.dumps({
            "id": sample.get("id"),
            "fileName": sample.get("fileName"),
            "rating": sample.get("rating"),
            "isFavorite": sample.get("isFavorite")
        }, ensure_ascii=False, indent=2))
    else:
        if isinstance(resp, dict):
            print("Top-level keys:", list(resp.keys()))
        else:
            print("Response type:", type(resp).__name__)

print("\nDone. If any sample shows a numeric 'rating' (0..5), the API returns star ratings.")
