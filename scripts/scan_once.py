import httpx

print("scan...")
resp = httpx.post("http://127.0.0.1:8787/api/routes/1/scan", timeout=360.0)
data = resp.json()
for x in data.get("results", []):
    err = (x.get("error") or "").replace("\n", " ")[:120]
    print(
        f"{x['platform']}: price={x.get('min_price')} "
        f"offers={x.get('offer_count')} err={err}"
    )
