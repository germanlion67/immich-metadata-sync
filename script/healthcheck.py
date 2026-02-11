import os
import sys
import requests

def main():
    # Load environment variables
    base_url = os.getenv('IMMICH_INSTANCE_URL', '').rstrip('/')
    api_key = os.getenv('IMMICH_API_KEY', '')

    if not base_url or not api_key:
        print("ERROR: Missing IMMICH_INSTANCE_URL or IMMICH_API_KEY", file=sys.stderr)
        sys.exit(1)

    # Use the correct endpoint for server info (deprecated /api/server-info replaced with /server/about)
    url = f"{base_url}/api/server/about"
    headers = {"x-api-key": api_key, "Accept": "application/json"}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Check if we got valid server info (should have version or similar)
        if "version" in data or "build" in data:
            print("OK: Immich API reachable")
            sys.exit(0)
        else:
            print("ERROR: Invalid server response", file=sys.stderr)
            sys.exit(1)

    except requests.exceptions.Timeout:
        print("ERROR: API timeout", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"ERROR: API not reachable: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError:
        print("ERROR: Invalid JSON response", file=sys.stderr)
        sys.exit(1)
