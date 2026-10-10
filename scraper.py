#!/usr/bin/env python3
"""İŞKUR Türk Meslekler Sözlüğü kazıyıcı (yalnız standart kütüphane).

Aşamalar (her biri sürdürülebilir; tekrar çalıştırınca kaldığı yerden devam eder):
  list     -> "Tüm meslek listesi" Excel raporu (kod + ad, tüm meslekler)
  files    -> "Meslek dosyası olanlar" aramasını sayfa sayfa gezip dosya linklerini toplar
  download -> meslek dosyalarını (PDF) dosyalar/<kod>_<slug>/ altına indirir
  detail   -> her meslek için ViewMeslekDetayPopUp.aspx sayfasını detay/<kod>.html olarak önbelleğe alır
  build    -> meslekler.csv (UTF-8 BOM) ve meslekler.json üretir

Kullanım:  python3 scraper.py [all|list|files|download|detail|build] [--delay 1.0]
"""
import csv, html, http.cookiejar, json, os, re, sys, time, unicodedata, urllib.error
import urllib.parse, urllib.request, zipfile, io

BASE = "https://esube.iskur.gov.tr/meslek/"
SEARCH = BASE + "meslek.aspx"
DETAIL = BASE + "ViewMeslekDetayPopUp.aspx?uiID={}"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "_state")
DETAY_DIR = os.path.join(HERE, "detay")
DOSYA_DIR = os.path.join(HERE, "dosyalar")
DELAY = 1.0

_cj = http.cookiejar.CookieJar()
_op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cj))
_last = [0.0]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def fetch(url, data=None, referer=SEARCH, tries=5):
    """Tek istek; istekler arası DELAY, hata durumunda üstel geri çekilme."""
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    for i in range(tries):
        wait = _last[0] + DELAY - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        req = urllib.request.Request(url, data=body, headers={"User-Agent": UA, "Referer": referer})
        try:
            with _op.open(req, timeout=120) as f:
                return f.read(), dict(f.headers.items())
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            code = getattr(e, "code", None)
            if code == 404:
                raise
            backoff = 2 ** (i + 1)
            log(f"  hata ({e}); {backoff}s sonra tekrar [{i + 1}/{tries}]")
            time.sleep(backoff)
    raise RuntimeError(f"istek başarısız: {url}")


def text(b):
    return b.decode("utf-8", "replace")


def hidden_fields(h):
    d = {}
    for m in re.finditer(r"<input[^>]*type=\"hidden\"[^>]*>", h):
        n = re.search(r'name="([^"]+)"', m.group())
        v = re.search(r'value="([^"]*)"', m.group())
        if n:
            d[n.group(1)] = html.unescape(v.group(1)) if v else ""
    return d


def form(h, **extra):
    d = hidden_fields(h)
    for k in ("ctl05$ctlAppCode", "ctl05$ctlAppName", "ctl05$ctlAppType", "ctl05$ctlEgtDuzey"):
        d.setdefault(k, "")
    d.update(extra)
    return d


def clean(s):
    s = html.unescape(re.sub(r"<[^>]+>", "", s or ""))
    return re.sub(r"[ \t]+", " ", s).strip()


def slug(s, n=60):
    tr = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    s = unicodedata.normalize("NFKD", s.translate(tr)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s[:n].rstrip("-") or "meslek"


def jload(p, default):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def jsave(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


# ---------------------------------------------------------------- list
def stage_list():
    out = os.path.join(STATE, "liste.json")
    if os.path.exists(out):
        log("liste zaten var:", out)
        return
    h = text(fetch(SEARCH)[0])
    h2 = text(fetch(SEARCH, form(h, **{"ctl05$Button1": "Tüm meslek listesini görmek için tıklayınız."}))[0])
    m = re.search(r'href="(ViewReport\.ashx\?[^"]+)"', h2)
    if not m:
        raise RuntimeError("Excel rapor linki bulunamadı")
    url = urllib.parse.urljoin(SEARCH, html.unescape(m.group(1)))
    b, _ = fetch(url)
    with open(os.path.join(STATE, "tum_meslekler.xlsx"), "wb") as f:
        f.write(b)
    z = zipfile.ZipFile(io.BytesIO(b))
    sh = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        shared = [clean(x) for x in re.findall(r"<si>(.*?)</si>", z.read("xl/sharedStrings.xml").decode(), re.S)]
    rows = []
    for r in re.findall(r"<row[^>]*>(.*?)</row>", sh, re.S):
        cells = []
        for attrs, inner in re.findall(r"<c([^>]*)>(.*?)</c>", r, re.S):
            v = clean(inner)
            if 't="s"' in attrs and v.isdigit():
                v = shared[int(v)]
            cells.append(v)
        if len(cells) >= 2 and re.match(r"^\d{4}\.\d{2}$", cells[0]):
            rows.append({"meslek_kodu": cells[0], "meslek_adi": cells[1]})
    jsave(out, rows)
    log(f"liste: {len(rows)} meslek")


# ---------------------------------------------------------------- files
ROW_RE = re.compile(
    r"MeslekDetayPopUp\('([^']+)'\).*?</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>", re.S)


def parse_grid(h):
    rows = []
    for kod, ad, cell in ROW_RE.findall(h):
        link = re.search(r'<div style="">\s*<a href="(Handler/MeslekDosyaFileDownloadHandler\.ashx\?[^"]+)"', cell)
        rows.append({"meslek_kodu": kod.strip(), "meslek_adi": clean(ad),
                     "dosya_url": urllib.parse.urljoin(SEARCH, html.unescape(link.group(1))) if link else ""})
    pg = re.search(r"/ (\d+) <a[^>]*btnChangeCurrentPage.*?Toplam Kayıt: (\d+)", h, re.S)
    return rows, (int(pg.group(1)), int(pg.group(2))) if pg else (1, len(rows))


def stage_files():
    out = os.path.join(STATE, "dosya_linkleri.json")
    st = jload(out, {"done": False, "pages": {}})
    if st["done"]:
        log("dosya linkleri zaten toplandı")
        return
    h = text(fetch(SEARCH)[0])
    h = text(fetch(SEARCH, form(h, **{"__EVENTTARGET": "ctl05$ctlPageCommand$CommandItem_Search",
                                       "ctl05$ctlMeslekDosyasi": "on"}))[0])
    page = 1
    while True:
        rows, (npages, total) = parse_grid(h)
        cur = re.search(r'txtCurrentPage" type="text" value="(\d+)"', h)
        page = int(cur.group(1)) if cur else page
        st["pages"][str(page)] = rows
        st["npages"], st["total"] = npages, total
        jsave(out, st)
        log(f"dosya sayfası {page}/{npages} ({len(rows)} satır, toplam {total})")
        if page >= npages or "ctl05$ctlDataPager$btnNext" not in h:
            break
        h = text(fetch(SEARCH, form(h, **{"__EVENTTARGET": "ctl05$ctlDataPager$btnNext",
                                           "ctl05$ctlMeslekDosyasi": "on"}))[0])
    got = sum(len(v) for v in st["pages"].values())
    st["done"] = got >= st["total"]
    jsave(out, st)
    log(f"dosya linkleri: {got}/{st['total']}")


def file_links():
    st = jload(os.path.join(STATE, "dosya_linkleri.json"), {"pages": {}})
    d = {}
    for rows in st["pages"].values():
        for r in rows:
            if r["dosya_url"]:
                d[r["meslek_kodu"]] = r
    return d


# ---------------------------------------------------------------- download
def fname_from(headers, fallback):
    cd = {k.lower(): v for k, v in headers.items()}.get("content-disposition", "")
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd, re.I)
    if m:
        return urllib.parse.unquote(m.group(1))
    m = re.search(r'filename="?([^";]+)"?', cd, re.I)
    if m:
        raw = m.group(1)
        try:
            raw = raw.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        return urllib.parse.unquote(raw)
    return fallback


def stage_download():
    idx_p = os.path.join(STATE, "indirilenler.json")
    idx = jload(idx_p, {})
    links = file_links()
    log(f"indirilecek: {len(links)} (önceden: {len(idx)})")
    for i, (kod, r) in enumerate(sorted(links.items()), 1):
        if kod in idx and os.path.exists(os.path.join(HERE, idx[kod]["dosya_path"])):
            continue
        folder = f"dosyalar/{kod}_{slug(r['meslek_adi'])}"
        # URL'deki name parametresi Türkçe karakter/boşluk içerir; düzgün kodla
        u = urllib.parse.urlsplit(r["dosya_url"])
        q = urllib.parse.urlencode(urllib.parse.parse_qsl(u.query, keep_blank_values=True))
        url = urllib.parse.urlunsplit(u._replace(query=q))
        try:
            b, hd = fetch(url)
        except Exception as e:  # noqa: BLE001
            log(f"  [{i}] {kod} İNDİRİLEMEDİ: {e}")
            idx[kod] = {"hata": str(e), "dosya_path": ""}
            jsave(idx_p, idx)
            continue
        ctype = {k.lower(): v for k, v in hd.items()}.get("content-type", "")
        name = fname_from(hd, f"{kod}.pdf" if b[:4] == b"%PDF" else f"{kod}.bin")
        name = os.path.basename(name).strip() or f"{kod}.pdf"
        os.makedirs(os.path.join(HERE, folder), exist_ok=True)
        with open(os.path.join(HERE, folder, name), "wb") as f:
            f.write(b)
        idx[kod] = {"dosya_path": f"{folder}/{name}", "boyut": len(b), "content_type": ctype,
                    "pdf": b[:4] == b"%PDF"}
        jsave(idx_p, idx)
        log(f"  [{i}/{len(links)}] {kod} -> {name} ({len(b)} B)")


# ---------------------------------------------------------------- detail
def strip_detail(h):
    h = re.sub(r"<script.*?</script>", "", h, flags=re.S)
    h = re.sub(r'<input type="hidden"[^>]*>', "", h)
    return h


def stage_detail():
    os.makedirs(DETAY_DIR, exist_ok=True)
    codes = [r["meslek_kodu"] for r in jload(os.path.join(STATE, "liste.json"), [])]
    codes += [k for k in file_links() if k not in set(codes)]
    todo = [c for c in codes if not os.path.exists(os.path.join(DETAY_DIR, f"{c}.html"))]
    log(f"detay: {len(codes) - len(todo)} hazır, {len(todo)} kaldı")
    fails = jload(os.path.join(STATE, "detay_hatalar.json"), {})
    for i, kod in enumerate(todo, 1):
        try:
            b, _ = fetch(DETAIL.format(urllib.parse.quote(kod)))
        except Exception as e:  # noqa: BLE001
            fails[kod] = str(e)
            jsave(os.path.join(STATE, "detay_hatalar.json"), fails)
            log(f"  {kod} detay hatası: {e}")
            continue
        h = text(b)
        if "ctl03_ctlLblMeslekKod" not in h:
            fails[kod] = "beklenmeyen sayfa"
            jsave(os.path.join(STATE, "detay_hatalar.json"), fails)
            log(f"  {kod} beklenmeyen içerik ({len(h)} B)")
            continue
        fails.pop(kod, None)
        with open(os.path.join(DETAY_DIR, f"{kod}.html"), "w", encoding="utf-8") as f:
            f.write(strip_detail(h))
        if i % 100 == 0:
            jsave(os.path.join(STATE, "detay_hatalar.json"), fails)
            log(f"  detay {i}/{len(todo)}")
    jsave(os.path.join(STATE, "detay_hatalar.json"), fails)


DETAIL_FIELDS = {
    "ana_grup": "ctl03_ctlLblAnaGrup", "alt_ana_grup": "ctl03_ctlLblAltGrubu",
    "meslek_grubu": "ctl03_ctlLblKategori", "birim_grubu": "ctl03_ctlLblBirimGrubu",
    "min_egitim_duzeyi": "ctl03_ctlLblMinEgitimDuzeyi", "meslek_tanimi": "ctl03_ctlMeslekTanimi",
    "guncel_meslek": "ctl03_ctlLblGuncelMeslek",
}


def parse_detail(kod):
    p = os.path.join(DETAY_DIR, f"{kod}.html")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        h = f.read()
    d = {}
    for k, i in DETAIL_FIELDS.items():
        m = re.search(rf'id="{i}"[^>]*>(.*?)</span>', h, re.S)
        d[k] = clean(m.group(1)) if m else ""
    m = re.search(r'id="ctl03_ctlIslemBasamaklari"[^>]*>(.*?)</textarea>', h, re.S)
    d["gorev_ve_islem_basamaklari"] = html.unescape(m.group(1)).strip() if m else ""
    return d


# ---------------------------------------------------------------- build
def stage_build():
    liste = jload(os.path.join(STATE, "liste.json"), [])
    links = file_links()
    idx = jload(os.path.join(STATE, "indirilenler.json"), {})
    rows, seen = [], set()
    for r in liste + [{"meslek_kodu": k, "meslek_adi": v["meslek_adi"]} for k, v in links.items()]:
        kod = r["meslek_kodu"]
        if kod in seen:
            continue
        seen.add(kod)
        d = parse_detail(kod)
        p = kod.split(".")[0]
        row = {
            "meslek_kodu": kod,
            "meslek_adi": r["meslek_adi"],
            "ana_grup_kodu": p[:1], "ana_grup": d.get("ana_grup", ""),
            "alt_ana_grup_kodu": p[:2], "alt_ana_grup": d.get("alt_ana_grup", ""),
            "meslek_grubu_kodu": p[:3], "meslek_grubu": d.get("meslek_grubu", ""),
            "birim_grubu_kodu": p[:4], "birim_grubu": d.get("birim_grubu", ""),
            "min_egitim_duzeyi": d.get("min_egitim_duzeyi", ""),
            "guncel_meslek": d.get("guncel_meslek", ""),
            "meslek_tanimi": d.get("meslek_tanimi", ""),
            "gorev_ve_islem_basamaklari": d.get("gorev_ve_islem_basamaklari", ""),
            "has_dosya": kod in links,
            "dosya_path": idx.get(kod, {}).get("dosya_path", ""),
            "dosya_url": links[kod]["dosya_url"] if kod in links else "",
            "detay_path": f"detay/{kod}.html" if d else "",
            "detay_url": DETAIL.format(kod),
        }
        rows.append(row)
    rows.sort(key=lambda x: x["meslek_kodu"])
    jsave(os.path.join(HERE, "meslekler.json"), rows)
    with open(os.path.join(HERE, "meslekler.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    log(f"build: {len(rows)} meslek, {sum(r['has_dosya'] for r in rows)} dosyalı, "
        f"{sum(bool(r['dosya_path']) for r in rows)} indirilmiş, {sum(bool(r['detay_path']) for r in rows)} detaylı")


STAGES = {"list": stage_list, "files": stage_files, "download": stage_download,
          "detail": stage_detail, "build": stage_build}

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--delay" in args:
        i = args.index("--delay")
        DELAY = float(args[i + 1])
        del args[i:i + 2]
    os.makedirs(STATE, exist_ok=True)
    which = args or ["all"]
    for s in (list(STAGES) if which == ["all"] else which):
        log(f"== {s}")
        STAGES[s]()
