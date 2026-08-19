import httpx
import json

base = "http://127.0.0.1:8787"
h = httpx.get(f"{base}/api/health", timeout=10).json()
print("health platforms", h["platforms"], "scanning", h["scanning"], "next", h.get("next_run_at"))
routes = httpx.get(f"{base}/api/routes", timeout=10).json()
print("routes", len(routes), "spark", routes[0].get("sparkline") if routes else None)
if routes:
    rid = routes[0]["id"]
    t = httpx.get(f"{base}/api/routes/{rid}/trend?days=7", timeout=10).json()
    print("trend stats", t["stats"])
    print("platforms", list(t["series"].keys()), "best pts", len(t["best_series"]))
