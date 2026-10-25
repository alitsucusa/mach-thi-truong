"""Lấy dữ liệu thị trường công khai, miễn phí, không cần API key, ghi ra site/data/market.json:

- COT (vị thế quỹ lớn) từ báo cáo Legacy của CFTC
- Tồn kho dầu hằng tuần từ EIA
- Lợi suất trái phiếu (danh nghĩa và thực) từ Bộ Tài chính Mỹ, lãi suất EFFR từ Fed New York
- Kịch bản quan sát mang tính giáo dục, suy ra từ các số liệu trên
"""
import csv
import io
import json
import zipfile
from datetime import date, datetime, timedelta, timezone

from common import fetch, previous_json, write_json

# ---------------------------------------------------------------- COT ----
ASSETS = {
    "GC": {"name": "Vàng", "code": "088691"},
    "ES": {"name": "S&P 500 E-mini", "code": "13874A"},
    "NQ": {"name": "Nasdaq 100 E-mini", "code": "209742"},
    "CL": {"name": "Dầu WTI", "code": "067651"},
}
COT_URL = "https://www.cftc.gov/files/dea/history/deacot{year}.zip"


def cot_index(values, weeks):
    """Vị trí của giá trị mới nhất trong biên cao–thấp của N tuần gần nhất (0–100)."""
    window = values[-weeks:]
    lo, hi = min(window), max(window)
    return round(100 * (window[-1] - lo) / (hi - lo)) if hi > lo else 50


def get_cot(prev):
    # Báo cáo chốt số thứ Ba, công bố thứ Sáu. Bản cũ còn mới (chưa tới kỳ công bố sau) thì dùng lại.
    if prev and prev.get("cot"):
        last = date.fromisoformat(prev["cot"]["report_date"])
        if date.today() < last + timedelta(days=10):
            return prev["cot"], "giữ bản cũ (chưa có báo cáo mới)"

    rows = {k: [] for k in ASSETS}
    codes = {a["code"]: k for k, a in ASSETS.items()}
    this_year = date.today().year
    for year in (this_year - 3, this_year - 2, this_year - 1, this_year):
        try:
            z = zipfile.ZipFile(io.BytesIO(fetch(COT_URL.format(year=year), timeout=60)))
        except Exception:
            if year == this_year:
                raise
            continue
        text = z.read(z.namelist()[0]).decode("latin-1")
        for r in csv.DictReader(io.StringIO(text)):
            key = codes.get(r["CFTC Contract Market Code"].strip())
            if key:
                rows[key].append({
                    "d": r["As of Date in Form YYYY-MM-DD"].strip(),
                    "long": int(r["Noncommercial Positions-Long (All)"]),
                    "short": int(r["Noncommercial Positions-Short (All)"]),
                    "oi": int(r["Open Interest (All)"]),
                })

    out = {}
    for key, rs in rows.items():
        rs = sorted({r["d"]: r for r in rs}.values(), key=lambda r: r["d"])  # bỏ trùng, xếp theo ngày
        nets = [r["long"] - r["short"] for r in rs]
        cur, prev_w = rs[-1], rs[-2]
        out[key] = {
            "name": ASSETS[key]["name"],
            "net": nets[-1],
            "change": nets[-1] - nets[-2],
            "long": cur["long"], "short": cur["short"], "oi": cur["oi"],
            "long_change": cur["long"] - prev_w["long"], "short_change": cur["short"] - prev_w["short"],
            "net_pct_oi": round(100 * nets[-1] / cur["oi"], 1),
            "index26": cot_index(nets, 26),
            "index156": cot_index(nets, 156),
            "history": [{"d": r["d"], "net": n} for r, n in zip(rs[-52:], nets[-52:])],
        }
    report = max(a["history"][-1]["d"] for a in out.values())
    return {"report_date": report, "assets": out}, None


# ---------------------------------------------------------------- EIA ----
EIA_URL = "https://ir.eia.gov/wpsr/table1.csv"
EIA_ROWS = [  # (nhãn hiển thị, đầu dòng trong file EIA)
    ("Dầu thô thương mại (không gồm SPR)", "Commercial (Excluding SPR)"),
    ("Kho dự trữ chiến lược (SPR)", "Strategic Petroleum Reserve"),
    ("Xăng", "Total Motor Gasoline"),
    ("Dầu chưng cất (diesel, dầu sưởi)", "Distillate Fuel Oil"),
]


def num(s):
    return float(s.replace(",", "").strip() or 0)


def get_eia():
    text = fetch(EIA_URL).decode("latin-1").replace("\x1a", "")
    rows = list(csv.reader(io.StringIO(text)))
    head = rows[0]  # "STUB_1", tuần này, tuần trước, chênh lệch, %, cùng kỳ năm trước, ...
    week = datetime.strptime(head[1], "%m/%d/%y").date().isoformat()
    out = []
    for label, stub in EIA_ROWS:
        r = next((r for r in rows if r and r[0].strip().startswith(stub)), None)
        if not r:
            continue
        cur, prev = num(r[1]), num(r[2])
        out.append({"name": label, "value": cur, "change": round(cur - prev, 3),
                    "year_ago": num(r[5]), "unit": "triệu thùng"})
    if not out:
        raise ValueError("Không đọc được bảng EIA")
    return {"week": week, "rows": out}


# -------------------------------------------------------------- Vĩ mô ----
TREASURY = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
            "{year}/all?type={kind}&field_tdr_date_value={year}&page&_format=csv")
EFFR_URL = "https://markets.newyorkfed.org/api/rates/unsecured/effr/last/30.json"


def treasury(kind):
    """Trả về danh sách (ngày, {kỳ hạn: lợi suất}) từ mới đến cũ, đủ dài để so với 1 tháng trước."""
    series = []
    for year in (date.today().year, date.today().year - 1):
        text = fetch(TREASURY.format(year=year, kind=kind)).decode("utf-8-sig")
        for r in csv.DictReader(io.StringIO(text)):
            d = datetime.strptime(r.pop("Date"), "%m/%d/%Y").date()
            series.append((d, {k.strip().upper(): float(v) for k, v in r.items() if v}))
        if len(series) > 30:
            break
    return sorted(series, key=lambda x: x[0], reverse=True)


def month_ago(series):
    target = series[0][0] - timedelta(days=30)
    return next((s for s in series if s[0] <= target), series[-1])


# Quan hệ phổ biến khi chỉ số TĂNG: +1 = thường hỗ trợ giá, -1 = thường gây áp lực. Mang tính giáo dục.
IMPACT = {
    "real10": {"GC": -1, "ES": -1, "NQ": -1, "CL": 0},
    "y10":    {"GC": -1, "ES": -1, "NQ": -1, "CL": 0},
    "y2":     {"GC": -1, "ES": -1, "NQ": -1, "CL": 0},
    "be10":   {"GC": 1, "ES": 0, "NQ": 0, "CL": 1},
    "curve":  {"GC": 0, "ES": 0, "NQ": 0, "CL": 0},
    "effr":   {"GC": -1, "ES": -1, "NQ": -1, "CL": 0},
}
FLAT = 0.05  # thay đổi dưới 0,05 điểm % xem như đi ngang


SHORT = {"real10": "lợi suất thực", "y10": "lợi suất 10 năm", "y2": "lợi suất 2 năm",
         "be10": "lạm phát kỳ vọng", "curve": "chênh lệch 10–2 năm", "effr": "lãi suất EFFR"}


def macro_item(key, name, cur, old, unit, note):
    chg = round(cur[1] - old[1], 2)
    direction = 0 if abs(chg) < FLAT else (1 if chg > 0 else -1)
    return {
        "key": key, "name": name, "short": SHORT[key], "value": round(cur[1], 2), "date": cur[0].isoformat(),
        "prev": round(old[1], 2), "prev_date": old[0].isoformat(), "change": chg, "unit": unit,
        "impact": {a: s * direction for a, s in IMPACT[key].items()}, "note": note,
    }


def get_macro():
    nom, real = treasury("daily_treasury_yield_curve"), treasury("daily_treasury_real_yield_curve")
    pick = lambda series, col: [(d, v[col]) for d, v in series if col in v]
    y10, y2, r10 = pick(nom, "10 YR"), pick(nom, "2 YR"), pick(real, "10 YR")
    real_by_date = dict(r10)
    be = [(d, v - real_by_date[d]) for d, v in y10 if d in real_by_date]
    y2_by_date = dict(y2)
    curve = [(d, v - y2_by_date[d]) for d, v in y10 if d in y2_by_date]

    items = [
        macro_item("real10", "Lợi suất thực 10 năm (TIPS)", r10[0], month_ago(r10), "%",
                   "Chi phí cơ hội của việc giữ vàng. Tăng thường gây áp lực lên vàng và cổ phiếu công nghệ."),
        macro_item("y10", "Lợi suất trái phiếu 10 năm", y10[0], month_ago(y10), "%",
                   "Mức chiết khấu cho định giá cổ phiếu. Tăng nhanh thường làm Nasdaq chịu áp lực hơn S&P."),
        macro_item("y2", "Lợi suất 2 năm", y2[0], month_ago(y2), "%",
                   "Phản ánh kỳ vọng lãi suất Fed trong 1–2 năm tới."),
        macro_item("be10", "Lạm phát kỳ vọng 10 năm (breakeven)", be[0], month_ago(be), "%",
                   "= lợi suất danh nghĩa − lợi suất thực. Tăng thường hỗ trợ vàng và dầu."),
        macro_item("curve", "Chênh lệch 10 năm − 2 năm", curve[0], month_ago(curve), "điểm %",
                   "Âm (đường cong đảo ngược) từng đi trước nhiều đợt suy thoái."),
    ]
    try:
        effr = json.loads(fetch(EFFR_URL))["refRates"]
        s = [(date.fromisoformat(r["effectiveDate"]), r["percentRate"]) for r in effr]
        items.append(macro_item("effr", "Lãi suất qua đêm Fed (EFFR)", s[0], s[-1], "%",
                                f"Biên mục tiêu của Fed: {effr[0]['targetRateFrom']}–{effr[0]['targetRateTo']}%."))
    except Exception:
        pass
    return items


# ----------------------------------------------------------- Kịch bản ----
def scenarios(cot, macro, eia):
    """Gợi ý những điều nên quan sát, suy ra theo quy tắc đơn giản. Không phải khuyến nghị."""
    out = {}
    for key in ASSETS:
        notes = []
        c = cot["assets"].get(key) if cot else None
        if c:
            i = c["index156"]
            if i >= 80:
                notes.append(f"Quỹ lớn đang mua ròng gần mức cao nhất 3 năm (COT Index {i}). "
                             "Vị thế đông người dễ bị chốt lời mạnh khi có tin bất lợi.")
            elif i <= 20:
                notes.append(f"Vị thế ròng của quỹ lớn gần mức thấp nhất 3 năm (COT Index {i}). "
                             "Bên bán đã đông, chú ý khả năng đảo chiều khi có tin tốt.")
            else:
                notes.append(f"Vị thế quỹ lớn ở vùng giữa (COT Index {i}), chưa cực đoan.")
            if c["change"]:
                way = "tăng" if c["change"] > 0 else "giảm"
                notes.append(f"Tuần qua vị thế ròng {way} {abs(c['change']):,} hợp đồng.".replace(",", "."))
        moved = lambda sign: [f"{m['short']} {'tăng' if m['change'] > 0 else 'giảm'}"
                              for m in macro if m["impact"].get(key) == sign]
        support, pressure = moved(1), moved(-1)
        score = len(support) - len(pressure)
        if support:
            notes.append("Vĩ mô 1 tháng qua hỗ trợ: " + ", ".join(support) + ".")
        if pressure:
            notes.append("Vĩ mô 1 tháng qua gây áp lực: " + ", ".join(pressure) + ".")
        if not support and not pressure:
            notes.append("Các chỉ số vĩ mô chính gần như đi ngang trong 1 tháng qua.")
        if key == "CL" and eia:
            crude = eia["rows"][0]
            way = "giảm" if crude["change"] < 0 else "tăng"
            notes.append(f"Tồn kho dầu thô thương mại tuần gần nhất {way} {abs(crude['change']):.1f} triệu thùng"
                         + (" (thường được đọc là cầu mạnh)." if crude["change"] < 0 else " (thường được đọc là cầu yếu)."))
        out[key] = {"bias": (score > 0) - (score < 0), "notes": notes}
    return out


def main():
    prev = previous_json("market.json") or {}
    data = {"updated": datetime.now(timezone.utc).isoformat(), "errors": {}}
    for name, fn in (("cot", lambda: get_cot(prev)), ("eia", get_eia), ("macro", get_macro)):
        try:
            res = fn()
            if name == "cot":
                res, info = res
                if info:
                    print(f"COT: {info}")
            data[name] = res
        except Exception as e:
            data["errors"][name] = f"{type(e).__name__}: {e}"
            data[name] = prev.get(name)  # nguồn lỗi thì giữ bản cũ
            print(f"  ! {name}: {data['errors'][name]}")
    data["scenarios"] = scenarios(data.get("cot"), data.get("macro") or [], data.get("eia"))
    write_json("market.json", data)
    cot = data.get("cot") or {}
    print(f"COT {cot.get('report_date')}, EIA {(data.get('eia') or {}).get('week')}, "
          f"vĩ mô {len(data.get('macro') or [])} chỉ số.")


if __name__ == "__main__":
    main()
