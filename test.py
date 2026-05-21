"""
Test - debug today Whop
"""

import os
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

WHOP_API_KEY    = os.getenv("WHOP_API_KEY")
WHOP_COMPANY_ID = os.getenv("WHOP_COMPANY_ID")

def test():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — today: {today}")
    print("=" * 50)

    # Test avec différents tris et tailles
    tests = [
        {"per_page": 20, "label": "per_page=20 (actuel)"},
        {"per_page": 100, "label": "per_page=100"},
        {"per_page": 100, "sort_by": "created_at", "order": "desc", "label": "per_page=100 + sort desc"},
    ]

    for t in tests:
        label = t.pop("label")
        resp = requests.get(
            "https://api.whop.com/api/v1/payments",
            headers={"Authorization": f"Bearer {WHOP_API_KEY}"},
            params={"company_id": WHOP_COMPANY_ID, **t},
            timeout=10
        ).json()
        items = resp.get("data", [])
        today_items = []
        for p in items:
            paid_at = p.get("paid_at") or p.get("created_at", 0)
            try:
                if isinstance(paid_at, (int, float)) and paid_at > 0:
                    d = datetime.fromtimestamp(paid_at, tz=timezone.utc).strftime("%Y-%m-%d")
                elif isinstance(paid_at, str):
                    d = paid_at[:10]
                else:
                    d = ""
            except:
                d = ""
            if d == today and p.get("total", 0) > 0:
                today_items.append(p)

        print(f"\n-- {label}")
        print(f"   Total recu: {len(items)} | Aujourd'hui: {len(today_items)}")
        # Afficher les 3 premiers avec leur date
        for p in items[:3]:
            paid_at = p.get("paid_at") or p.get("created_at", 0)
            try:
                if isinstance(paid_at, (int, float)) and paid_at > 0:
                    d = datetime.fromtimestamp(paid_at, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
                else:
                    d = str(paid_at)[:16]
            except:
                d = str(paid_at)
            print(f"   {d} | ${p.get('total')} | {p.get('status')} | {p.get('id')}")

if __name__ == "__main__":
    test()