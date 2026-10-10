#!/usr/bin/env python3
"""Resmî dosyası olmayan meslekler için Claude taslağı meslek bilgi dosyaları üretir.

Aşamalar (her biri sürdürülebilir; var olan çıktı atlanır):
  ref    -> resmî PDF'lerin metnini _claude/ref_txt/<kod>.txt olarak önbelleğe alır
  uret   -> her meslek için `claude -p` ile içerik üretir: _claude/icerik/<kod>.json
  disa_aktar -> tüm içeriği meslek_bilgi.jsonl olarak birleştirir (sistemde kullanım için)
  pdf    -> (isteğe bağlı) içerikten PDF basar: dosyalar/<kod>_<slug>/<Ad> (Claude taslağı).pdf
  durum  -> ilerleme özeti

Örnek:
  python3 _claude/meslek_dosyasi.py ref
  python3 _claude/meslek_dosyasi.py uret --kod 5141.05 7127.09
  python3 _claude/meslek_dosyasi.py uret --paralel 4          # kalan hepsi
  python3 _claude/meslek_dosyasi.py pdf
"""
import argparse, concurrent.futures as cf, datetime, html, json, os, re, subprocess, sys, tempfile, time, unicodedata

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # data/iskur-meslek
CL = os.path.join(KOK, "_claude")
ICERIK = os.path.join(CL, "icerik")
REF = os.path.join(CL, "ref_txt")
LOG = os.path.join(CL, "uretim.log")
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", os.path.expanduser("~/.local/bin/claude"))
def _chrome():
    import glob
    c = sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell")))
    return os.environ.get("CHROME_BIN") or (c[-1] if c else "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


CHROME = _chrome()
MODEL = os.environ.get("MESLEK_MODEL", "sonnet")
TARIH = "Ekim 2026"

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["gorevler", "arac_gerec", "genel_ozellikler", "calisma_ortami", "egitim",
                 "calisma_alanlari", "kazanc", "ilerleme", "benzer_meslekler", "ek_bilgiler"],
    "properties": {
        "gorevler": {"type": "array", "items": {"type": "string"}},
        "arac_gerec": {"type": "array", "items": {"type": "string"}},
        "genel_ozellikler": {"type": "array", "items": {"type": "string"}},
        "calisma_ortami": {"type": "string"},
        "egitim": {"type": "object", "additionalProperties": False,
                   "required": ["verildigi_yerler", "giris_kosullari", "sure_ve_icerik", "belge"],
                   "properties": {"verildigi_yerler": {"type": "string"},
                                  "giris_kosullari": {"type": "array", "items": {"type": "string"}},
                                  "sure_ve_icerik": {"type": "string"},
                                  "belge": {"type": "string"}}},
        "calisma_alanlari": {"type": "string"},
        "kazanc": {"type": "object", "additionalProperties": False,
                   "required": ["egitim_suresince", "egitim_sonrasi"],
                   "properties": {"egitim_suresince": {"type": "string"},
                                  "egitim_sonrasi": {"type": "array", "items": {"type": "string"}}}},
        "ilerleme": {"type": "object", "additionalProperties": False,
                     "required": ["mesleki_egitimde", "is_hayatinda"],
                     "properties": {"mesleki_egitimde": {"type": "string"}, "is_hayatinda": {"type": "string"}}},
        "benzer_meslekler": {"type": "array", "items": {"type": "string"}},
        "ek_bilgiler": {"type": "string"},
    },
}


def log(msg):
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def slug(s, n=60):  # scraper.py ile aynı
    tr = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    s = unicodedata.normalize("NFKD", s.translate(tr)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s[:n].rstrip("-") or "meslek"


def veri():
    with open(os.path.join(KOK, "meslekler.json"), encoding="utf-8") as f:
        return json.load(f)


def hedefler(d, kodlar=None):
    r = [x for x in d if not x["has_dosya"]]
    if kodlar:
        s = set(kodlar)
        r = [x for x in r if x["meslek_kodu"] in s]
    return r


# ---------------------------------------------------------------- ref
def cmd_ref(a):
    os.makedirs(REF, exist_ok=True)
    n = 0
    for x in veri():
        if not x["has_dosya"]:
            continue
        out = os.path.join(REF, x["meslek_kodu"] + ".txt")
        if os.path.exists(out):
            continue
        p = subprocess.run(["pdftotext", "-layout", os.path.join(KOK, x["dosya_path"]), "-"],
                           capture_output=True, text=True)
        t = re.sub(r"^ANKARA .*$", "", p.stdout, flags=re.M)
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r"\n\s*\n+", "\n", t).strip()
        with open(out, "w", encoding="utf-8") as f:
            f.write(t)
        n += 1
    log(f"ref: {n} yeni metin")


def referans(x, resmi):
    """En yakın resmî dosya: aynı birim grubu > meslek grubu > alt ana grup > ana grup."""
    for uz in (4, 3, 2, 1):
        on = x["meslek_kodu"][:uz]
        c = [r for r in resmi if r["meslek_kodu"][:uz] == on]
        if c:
            c.sort(key=lambda r: r["meslek_kodu"])
            r = c[0]
            p = os.path.join(REF, r["meslek_kodu"] + ".txt")
            if os.path.exists(p):
                return r, open(p, encoding="utf-8").read()[:7000]
    return None, ""


def adaylar(x, d):
    k = x["meslek_kodu"]
    a = [y["meslek_adi"] for y in d if y["meslek_kodu"][:4] == k[:4] and y["meslek_kodu"] != k]
    if len(a) < 25:
        a += [y["meslek_adi"] for y in d if y["meslek_kodu"][:3] == k[:3] and y["meslek_kodu"][:4] != k[:4]]
    seen, out = set(), []
    for n in a:
        if n not in seen:
            seen.add(n); out.append(n)
    return out[:60]


def girdi(x, d, resmi):
    r, rt = referans(x, resmi)
    g = [
        "# MESLEK KAYDI (İŞKUR Türk Meslekler Sözlüğü)",
        f"Kod: {x['meslek_kodu']}", f"Ad: {x['meslek_adi']}",
        f"Ana grup: {x['ana_grup']}", f"Alt ana grup: {x['alt_ana_grup']}",
        f"Meslek grubu: {x['meslek_grubu']}", f"Birim grubu: {x['birim_grubu']}",
        f"Gereken minimum eğitim düzeyi: {x['min_egitim_duzeyi']}",
        f"Tanım: {x['meslek_tanimi']}",
        "Görev ve işlem basamakları:", x["gorev_ve_islem_basamaklari"],
        "", "# BENZER MESLEK ADAYLARI", "; ".join(adaylar(x, d)),
    ]
    if r:
        g += ["", f"# REFERANS: başka bir mesleğin resmî İŞKUR dosyası ({r['meslek_kodu']} {r['meslek_adi']}) — yalnız yapı/üslup/bağlam için",
              rt]
    return "\n".join(g)


# ---------------------------------------------------------------- uret
def uret_bir(x, d, resmi, sysprompt):
    kod = x["meslek_kodu"]
    out = os.path.join(ICERIK, kod + ".json")
    if os.path.exists(out):
        return "atlandı"
    cmd = [CLAUDE_BIN, "-p", "--model", MODEL, "--tools", "", "--strict-mcp-config",
           "--setting-sources", "", "--disable-slash-commands", "--no-session-persistence",
           "--system-prompt", sysprompt, "--json-schema", json.dumps(SCHEMA, ensure_ascii=False),
           "--output-format", "json"]
    bekle = 30
    for deneme in range(6):
        try:
            p = subprocess.run(cmd, input=girdi(x, d, resmi), capture_output=True, text=True,
                               timeout=600, cwd=tempfile.gettempdir())
            res = json.loads(p.stdout)
            if res.get("is_error"):
                raise RuntimeError(str(res.get("result"))[:300])
            so = res.get("structured_output")
            if so is None:
                so = json.loads(re.search(r"\{.*\}", res.get("result", ""), re.S).group(0))
            if len(so.get("gorevler", [])) < 2:
                raise RuntimeError("eksik görev listesi")
            so["_meta"] = {"model": MODEL, "uretim": datetime.datetime.now().isoformat(timespec="seconds"),
                           "usage": {k: res.get("usage", {}).get(k) for k in ("input_tokens", "output_tokens")}}
            tmp = out + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(so, f, ensure_ascii=False, indent=1)
            os.replace(tmp, out)
            return "ok"
        except Exception as e:
            msg = str(e) or type(e).__name__
            if "p" in locals() and p.stderr:
                msg += " | " + p.stderr.strip()[-300:]
            log(f"HATA {kod} deneme {deneme + 1}: {msg[:400]}")
            if re.search(r"limit|429|overloaded|quota", msg, re.I):
                bekle = max(bekle, 900)
            time.sleep(bekle)
            bekle = min(bekle * 2, 3600)
    return "başarısız"


def cmd_uret(a):
    os.makedirs(ICERIK, exist_ok=True)
    d = veri()
    resmi = [x for x in d if x["has_dosya"]]
    sysprompt = open(os.path.join(CL, "prompt.md"), encoding="utf-8").read()
    hs = [x for x in hedefler(d, a.kod) if not os.path.exists(os.path.join(ICERIK, x["meslek_kodu"] + ".json"))]
    if a.limit:
        hs = hs[:a.limit]
    log(f"uret: {len(hs)} meslek, paralel={a.paralel}, model={MODEL}")
    ok = 0
    with cf.ThreadPoolExecutor(a.paralel) as ex:
        fs = {ex.submit(uret_bir, x, d, resmi, sysprompt): x for x in hs}
        for f in cf.as_completed(fs):
            x = fs[f]
            s = f.result()
            ok += s == "ok"
            log(f"{s} {x['meslek_kodu']} {x['meslek_adi']} ({ok}/{len(hs)})")
            if s == "ok" and a.pdf:
                try:
                    pdf_bir(x, d)
                except Exception as e:
                    log(f"PDF HATA {x['meslek_kodu']}: {e}")


# ---------------------------------------------------------------- pdf
CSS = """
@page { size: A4; margin: 22mm 18mm 20mm 18mm;
  @bottom-left { content: "Claude taslağı · resmî İŞKUR belgesi değildir"; font: 8pt Arial; color:#a33; }
  @bottom-right { content: "KOD · """ + TARIH + """ · " counter(page) "/" counter(pages); font: 8pt Arial; color:#555; } }
body { font: 10.5pt/1.45 "Times New Roman", Times, serif; color:#111; }
.sayfa { break-before: page; } .sayfa:first-of-type { break-before: auto; }
h1 { font: bold 15pt Arial; text-align:center; letter-spacing:.5px; margin:0 0 2mm; text-transform: uppercase; }
.cizgi { border-top: 1.5px solid #111; margin: 0 0 4mm; }
h2 { font: bold 11pt Arial; margin: 5mm 0 2mm; text-transform: uppercase; }
.blok { display:grid; grid-template-columns: 42mm 1fr; column-gap: 4mm; margin: 2mm 0 3mm; }
.etiket { font: bold 9pt Arial; text-transform: uppercase; padding-top: 1mm; }
.icerik p { margin: 0 0 2mm; text-align: justify; }
ul { margin: 0 0 2mm; padding-left: 5mm; } li { margin: 0 0 .6mm; }
.uyari { border: 1.5px solid #a33; color:#7a1f1f; background:#fdf3f3; padding: 2.5mm 3.5mm; font: 8.5pt/1.4 Arial; margin: 0 0 4mm; }
.uyari b { color:#a33; }
.kunye { font: 8.5pt Arial; color:#444; text-align:center; margin: 0 0 3mm; }
.son { margin-top: 8mm; font-style: italic; font-size: 9.5pt; }
"""

AYRINTI = [
    "İlgili eğitim kurumları,",
    "https://kariyerkapisi.cbiko.gov.tr/",
    "Türkiye İş Kurumu web sayfası https://www.iskur.gov.tr",
    "Mesleğim Hayatım web sitesi https://meslegimhayatim.meb.gov.tr/",
    "Mesleki Yeterlilik Kurumu https://www.myk.gov.tr/",
    "Bünyesinde “Meslek Bilgi Merkezi” bulunan Çalışma ve İş Kurumu İl Müdürlükleri/Hizmet Merkezleri.",
]


def e(s):
    return html.escape(s or "")


def paras(s):
    return "".join(f"<p>{e(p.strip())}</p>" for p in re.split(r"\n\s*\n", s or "") if p.strip())


def ul(items):
    items = [re.sub(r"^[\s\-–•*]+", "", i).strip() for i in items if i and i.strip()]
    return "<ul>" + "".join(f"<li>{e(i)}</li>" for i in items) + "</ul>" if items else "<p>—</p>"


def blok(etiket, govde):
    return f'<div class="blok"><div class="etiket">{etiket}</div><div class="icerik">{govde}</div></div>'


def ozellik_ad(ad):
    return ad  # "X olmak isteyenlerin" kalıbında ad olduğu gibi kullanılır


def html_bir(x, c):
    ad = x["meslek_adi"]
    bas = f'<h1>{e(ad)}</h1><div class="cizgi"></div>'
    s1 = (bas + f'<div class="kunye">Meslek kodu {e(x["meslek_kodu"])} · {e(x["birim_grubu"])} · '
          f'Gereken minimum eğitim: {e(x["min_egitim_duzeyi"])}</div>'
          '<div class="uyari"><b>Bu dosya Claude (Anthropic yapay zekâ modeli) tarafından hazırlanmış bir taslaktır; '
          'resmî bir İŞKUR belgesi değildir.</b> Tanım ve görevler İŞKUR Türk Meslekler Sözlüğü kaydından alınmıştır. '
          'Diğer bölümler genel bilgiye dayanılarak yazılmıştır ve doğrulanmamıştır; eğitim, belge ve ücret konularında '
          'güncel bilgiyi ilgili kurumlardan teyit ediniz.</div>'
          f'<h2>Tanım</h2><div class="icerik">{paras(x["meslek_tanimi"].lstrip("- "))}</div>'
          '<h2>A- Görevler</h2><div class="icerik"><p>İş süreçlerinde, iş sağlığı ve güvenliği kurallarına, çevre koruma '
          'düzenlemelerine, mesleğin verimlilik ve kalite gerekliliklerine uygun olarak;</p>'
          f'{ul(c["gorevler"])}</div>'
          + blok("Kullanılan araç, gereç ve ekipman", ul(c["arac_gerec"])))
    s2 = (bas + "<h2>B- Mesleğin gerektirdiği genel özellikler</h2>"
          f'<div class="icerik"><p>{e(ad)} olmak isteyenlerin;</p>{ul(c["genel_ozellikler"])}<p>kişiler olmaları gerekir.</p></div>'
          f'<h2>C- Çalışma ortamı ve koşulları</h2><div class="icerik">{paras(c["calisma_ortami"])}</div>')
    eg = c["egitim"]
    s3 = (bas + "<h2>D- Meslek eğitimi</h2>"
          + blok("Meslek eğitiminin verildiği yerler", paras(eg["verildigi_yerler"]))
          + blok("Meslek eğitimine giriş koşulları", ul(eg["giris_kosullari"]))
          + blok("Eğitimin süresi ve içeriği", paras(eg["sure_ve_icerik"]))
          + blok("Eğitim sonunda alınan belge-diploma", paras(eg["belge"])))
    kz = c["kazanc"]
    s4 = (bas + f'<h2>E- Çalışma alanları ve iş bulma olanakları</h2><div class="icerik">{paras(c["calisma_alanlari"])}</div>'
          "<h2>F- Eğitim süresince ve eğitim sonrası kazanç</h2>"
          + blok("Eğitim süresince", paras(kz["egitim_suresince"]))
          + blok("Eğitim sonrası", ul(kz["egitim_sonrasi"])))
    il = c["ilerleme"]
    s5 = (bas + "<h2>G- Meslekte ilerleme</h2>"
          + blok("Mesleki eğitimde ilerleme", paras(il["mesleki_egitimde"]))
          + blok("İş hayatında ilerleme", paras(il["is_hayatinda"]))
          + blok("Benzer meslekler", ul(c["benzer_meslekler"])))
    kaynak = [f"Türkiye İş Kurumu, Türk Meslekler Sözlüğü, {x['meslek_kodu']} {ad} meslek kaydı (tanım ve görevler), "
              "https://esube.iskur.gov.tr/meslek/ (erişim: 07.10.2026),",
              "Uluslararası Standart Meslek Sınıflaması – ISCO-08,",
              "Bölüm yapısı: İŞKUR meslek bilgi dosyaları; diğer bölümlerin metni Claude tarafından yazılmıştır."]
    s6 = (bas + f'<h2>H- Ek bilgiler</h2><div class="icerik">{paras(c.get("ek_bilgiler")) or "<p></p>"}</div>'
          f'<h2>I- Kaynakça</h2><div class="icerik">{ul(kaynak)}</div>'
          f'<h2>İ- Ayrıntılı bilgi için</h2><div class="icerik">{ul(AYRINTI)}</div>'
          '<div class="son">Bu dosya; meslek seçme aşamasında olan gençleri bilgilendirme amacıyla, İŞKUR meslek bilgi '
          'dosyalarının yapısı örnek alınarak Claude tarafından taslak olarak hazırlanmıştır. Resmî İŞKUR yayını değildir.</div>')
    sayfalar = "".join(f'<section class="sayfa">{s}</section>' for s in (s1, s2, s3, s4, s5, s6))
    css = CSS.replace("KOD", x["meslek_kodu"])
    return (f'<!doctype html><html lang="tr"><head><meta charset="utf-8"><title>{e(ad)} – Claude taslağı</title>'
            f"<style>{css}</style></head><body>{sayfalar}</body></html>")


def pdf_yolu(x):
    ad = re.sub(r'[/\\:*?"<>|]+', "-", x["meslek_adi"]).strip()
    klasor = os.path.join(KOK, "dosyalar", f"{x['meslek_kodu']}_{slug(x['meslek_adi'])}")
    return klasor, os.path.join(klasor, f"{ad} (Claude taslağı).pdf")


def pdf_bir(x, d=None, zorla=False):
    with open(os.path.join(ICERIK, x["meslek_kodu"] + ".json"), encoding="utf-8") as f:
        c = json.load(f)
    klasor, out = pdf_yolu(x)
    if os.path.exists(out) and not zorla:
        return out
    os.makedirs(klasor, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        h = os.path.join(td, "m.html")
        with open(h, "w", encoding="utf-8") as f:
            f.write(html_bir(x, c))
        tmp = os.path.join(td, "m.pdf")
        subprocess.run([CHROME, "--no-pdf-header-footer",
                        f"--user-data-dir={td}/prof", f"--print-to-pdf={tmp}", "file://" + h],
                       capture_output=True, timeout=120)
        if not os.path.exists(tmp):
            raise RuntimeError("Chrome PDF üretmedi")
        os.replace(tmp, out)
    return out


def cmd_pdf(a):
    d = veri()
    n = 0
    for x in hedefler(d, a.kod):
        if os.path.exists(os.path.join(ICERIK, x["meslek_kodu"] + ".json")):
            pdf_bir(x, d, zorla=a.zorla)
            n += 1
    log(f"pdf: {n} dosya")


ALANLAR = ["meslek_kodu", "meslek_adi", "ana_grup_kodu", "ana_grup", "alt_ana_grup_kodu", "alt_ana_grup",
           "meslek_grubu_kodu", "meslek_grubu", "birim_grubu_kodu", "birim_grubu", "min_egitim_duzeyi",
           "meslek_tanimi", "gorev_ve_islem_basamaklari", "detay_url"]


def cmd_disa_aktar(a):
    """Sözlük kaydı + üretilen bölümler -> meslek_bilgi.jsonl (meslek başına bir satır)."""
    d = veri()
    out = os.path.join(KOK, "meslek_bilgi.jsonl")
    adlar = {y["meslek_adi"] for y in d}
    n = 0
    with open(out + ".tmp", "w", encoding="utf-8") as f:
        for x in hedefler(d):
            p = os.path.join(ICERIK, x["meslek_kodu"] + ".json")
            if not os.path.exists(p):
                continue
            c = json.load(open(p, encoding="utf-8"))
            meta = c.pop("_meta", {})
            rec = {k: x.get(k) for k in ALANLAR}
            c["benzer_meslekler"] = [b for b in c["benzer_meslekler"] if b in adlar]  # sözlükte olmayan adları at
            rec["dosya"] = c
            rec["kaynak"] = {"tur": "claude_taslak", "resmi": False, "model": meta.get("model"),
                             "uretim": meta.get("uretim"),
                             "not": "Tanım ve görevler İŞKUR Türk Meslekler Sözlüğü'nden; diğer bölümler Claude tarafından yazıldı, doğrulanmadı."}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    os.replace(out + ".tmp", out)
    log(f"disa_aktar: {n} kayıt -> {out}")


def cmd_durum(a):
    d = veri()
    hs = hedefler(d)
    ic = sum(os.path.exists(os.path.join(ICERIK, x["meslek_kodu"] + ".json")) for x in hs)
    pd = sum(os.path.exists(pdf_yolu(x)[1]) for x in hs)
    print(f"hedef {len(hs)} · içerik {ic} · pdf {pd}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("ref")
    u = sp.add_parser("uret"); u.add_argument("--kod", nargs="*"); u.add_argument("--paralel", type=int, default=3)
    u.add_argument("--limit", type=int); u.add_argument("--pdf", action="store_true", help="her içerikten hemen PDF bas")
    p = sp.add_parser("pdf"); p.add_argument("--kod", nargs="*"); p.add_argument("--zorla", action="store_true")
    sp.add_parser("durum"); sp.add_parser("disa_aktar")
    a = ap.parse_args()
    {"ref": cmd_ref, "uret": cmd_uret, "pdf": cmd_pdf, "durum": cmd_durum, "disa_aktar": cmd_disa_aktar}[a.cmd](a)
