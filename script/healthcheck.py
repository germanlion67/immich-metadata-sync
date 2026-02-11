import os
import requests
import sys

# Lade Umgebungsvariablen
base_url = os.getenv('IMMICH_INSTANCE_URL', '').rstrip('/')
api_key = os.getenv('IMMICH_API_KEY')

if not base_url or not api_key:
    print("ERROR: IMMICH_INSTANCE_URL or IMMICH_API_KEY missing", file=sys.stderr)
    sys.exit(1)

headers = {
    'x-api-key': api_key,
    'Accept': 'application/json',
}

# Teste API-Konnektivität mit einem einfachen Endpoint (z.B. Server-Info)
try:
    response = requests.get(f"{base_url}/api/server-info", headers=headers, timeout=10)
    response.raise_for_status()
    data = response.json()
    if 'version' in data:
        print("Healthcheck passed: API reachable")
        sys.exit(0)
    else:
        print("ERROR: Unexpected API response", file=sys.stderr)
        sys.exit(1)
except requests.exceptions.RequestException as e:
    print(f"ERROR: API not reachable: {e}", file=sys.stderr)
    sys.exit(1)
