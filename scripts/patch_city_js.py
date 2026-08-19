from pathlib import Path

p = Path("app/static/app.js")
text = p.read_text(encoding="utf-8")

start = text.find("function cityLabel")
end = text.find("async function loadHealth")
if start < 0 or end < 0:
    raise SystemExit(f"markers not found start={start} end={end}")

new_block = r'''function cityLabel(codeOrName) {
  const raw = String(codeOrName || "").trim();
  if (!raw) return "输入城市名";
  if (raw.length === 3 && /^[A-Za-z]+$/.test(raw)) {
    const code = raw.toUpperCase();
    return state.cities[code] ? `${state.cities[code]}（${code}）` : `未收录 ${code}`;
  }
  const hit = (state.catalog || []).find(
    (c) => c.name === raw || c.name.includes(raw) || raw.includes(c.name)
  );
  if (hit) return `${hit.name} · ${hit.code}`;
  return raw.length >= 2 ? `将识别「${raw}」` : "输入城市名";
}

function bindCityHints() {
  const origin = document.getElementById("origin");
  const dest = document.getElementById("destination");
  const oh = document.getElementById("originHint");
  const dh = document.getElementById("destHint");
  const paint = (input, hint) => {
    const v = input.value.trim();
    const known =
      (v.length === 3 && /^[A-Za-z]+$/.test(v) && state.cities[v.toUpperCase()]) ||
      (state.catalog || []).some((c) => c.name === v || c.name.includes(v));
    hint.textContent = cityLabel(v);
    hint.classList.toggle("unknown", v.length >= 2 && !known);
  };
  origin.addEventListener("input", () => paint(origin, oh));
  dest.addEventListener("input", () => paint(dest, dh));
}

async function loadCities() {
  state.cities = await api("/api/cities");
  state.catalog = await api("/api/cities/catalog");
  const list = document.getElementById("cityList");
  if (list) {
    list.innerHTML = state.catalog
      .map((c) => `<option value="${c.name}"></option>`)
      .join("");
  }
  bindCityHints();
}

'''

text = text[:start] + new_block + text[end:]
# ensure state has catalog
if "catalog: {}" not in text and "catalog:" not in text.split("const state")[1][:200]:
    text = text.replace(
        "sparkCharts: new Map(),\n};",
        "sparkCharts: new Map(),\n  catalog: [],\n};",
    )
p.write_text(text, encoding="utf-8")
print("patched ok")
