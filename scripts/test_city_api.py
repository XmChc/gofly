import httpx
import json

# wait for server
r = httpx.post(
    "http://127.0.0.1:8787/api/cities/resolve",
    json={"origin": "厦门", "destination": "乌鲁木齐"},
    timeout=10,
)
print("resolve", r.status_code, r.text)
r2 = httpx.post(
    "http://127.0.0.1:8787/api/cities/resolve",
    json={"origin": "喀什", "destination": "南昌"},
    timeout=10,
)
print("resolve2", r2.status_code, r2.text)
r3 = httpx.get("http://127.0.0.1:8787/api/cities/suggest?q=厦", timeout=10)
print("suggest", r3.status_code, r3.text)
