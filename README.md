# İŞKUR Türk Meslekler Sözlüğü — ham veri

Kaynak: <https://esube.iskur.gov.tr/meslek/meslek.aspx> (Türkiye İş Kurumu, e-Şube "Meslek Ara").
Çekim tarihi: 2026-10-07. Betik: `scraper.py` (yalnız Python standart kütüphanesi).

## Dosyalar

| Yol | İçerik |
|---|---|
| `meslekler.csv` | Meslek başına bir satır, UTF-8 **BOM'lu** (Excel Türkçe karakterleri doğru açar) |
| `meslekler.json` | Aynı veri, JSON dizi |
| `dosyalar/<kod>_<slug>/` | Meslek dosyası (PDF), sitedeki özgün dosya adıyla |
| `detay/<kod>.html` | Meslek detay popup sayfası (script ve viewstate temizlenmiş) |
| `_state/` | Ara durum: `liste.json`, `tum_meslekler.xlsx` (resmi tam liste raporu), `dosya_linkleri.json`, `indirilenler.json`, `detay_hatalar.json`, `run.log` |

## Alanlar (`meslekler.csv` / `.json`)

- `meslek_kodu` — ISCO-08 tabanlı kod, ör. `3258.02`
- `meslek_adi`
- `ana_grup_kodu` / `ana_grup` — kodun 1. hanesi / adı (detay sayfasından)
- `alt_ana_grup_kodu` / `alt_ana_grup` — ilk 2 hane
- `meslek_grubu_kodu` / `meslek_grubu` — ilk 3 hane
- `birim_grubu_kodu` / `birim_grubu` — ilk 4 hane
- `min_egitim_duzeyi` — "Gereken Minimum Eğitim Düzeyi"
- `guncel_meslek` — EVET/HAYIR
- `meslek_tanimi`, `gorev_ve_islem_basamaklari` — detay sayfasındaki metinler
- `has_dosya` — sitede meslek bilgi dosyası var mı
- `dosya_path` — indirilen dosyanın bu klasöre göre yolu (yoksa boş)
- `dosya_url` — dosyanın kaynak URL'si
- `detay_path`, `detay_url` — detay sayfasının yerel kopyası ve kaynağı

Grup kodları koddan türetilir; grup adları detay sayfasından gelir (detayı çekilemeyen satırda boş kalır).

## Sitedeki URL kalıpları

- Arama: `meslek.aspx` — ASP.NET WebForms postback (`__VIEWSTATE`/`__EVENTVALIDATION` korunur).
  - Ara: `__EVENTTARGET=ctl05$ctlPageCommand$CommandItem_Search`; "yalnız dosyası olanlar": `ctl05$ctlMeslekDosyasi=on`
  - Sayfalama (15 satır/sayfa): `__EVENTTARGET=ctl05$ctlDataPager$btnNext`
  - "Tüm meslek listesi" düğmesi (`ctl05$Button1`) → `ViewReport.ashx?ReportNumber=…&ReportFormat=7` (xlsx; kod + ad)
- Detay: `ViewMeslekDetayPopUp.aspx?uiID=<meslek_kodu>` (doğrudan GET, oturum gerekmez)
- Meslek dosyası: `Handler/MeslekDosyaFileDownloadHandler.ashx?id=<şifreli id>&name=<meslek adı>` (PDF; `id` yalnız arama sonucundan alınabilir)

## Yeniden çalıştırma

```bash
cd data/iskur-meslek
python3 scraper.py              # tüm aşamalar: list files download detail build
python3 scraper.py detail build # yalnız eksik detayları tamamla ve çıktıyı yeniden üret
python3 scraper.py --delay 2 download
```

Her aşama sürdürülebilir: mevcut detay/dosya atlanır. Listeyi veya dosya linklerini
tazelemek için `_state/liste.json` ya da `_state/dosya_linkleri.json` silinip yeniden çalıştırılır.
İstekler tek tek, aralarında ≥1 sn, hata halinde üstel geri çekilmeyle (2,4,8,16,32 sn) yapılır.

## Claude taslağı meslek bilgi dosyaları (resmî değil)

Sitede resmî meslek bilgi dosyası (PDF) bulunan 1123 meslek dışında kalan **6642 meslek** için,
İŞKUR meslek bilgi dosyalarının bölüm yapısı (Tanım, A Görevler … İ Ayrıntılı bilgi için) izlenerek
Claude (Sonnet) ile her meslek ayrı ayrı değerlendirilerek taslak içerik üretildi (Ekim 2026).

> **Uyarı:** Bu içerik resmî bir İŞKUR yayını değildir. Tanım ve görevler İŞKUR Türk Meslekler
> Sözlüğü kaydından alınmıştır; diğer bölümler (eğitim, çalışma ortamı, kazanç, ilerleme vb.) genel
> bilgiye dayanılarak yazılmıştır ve doğrulanmamıştır. Kullanıcıya gösterilirken bu not korunmalıdır.

| Yol | İçerik |
|---|---|
| `meslek_bilgi.jsonl` | 6642 satır; her satır bir meslek: sözlük alanları + `dosya` (bölümler) + `kaynak` (`tur: "claude_taslak"`, `resmi: false`) |
| `_claude/icerik/<kod>.json` | Meslek başına ham içerik (üretim meta verisiyle) |
| `_claude/meslek_dosyasi.py` | Üretim hattı: `ref`, `uret`, `disa_aktar`, `pdf`, `durum` |
| `_claude/prompt.md` | Üretimde kullanılan talimat |
| `_claude/ref_txt/<kod>.txt` | Resmî PDF'lerin metni (en yakın gruptaki resmî dosya referans olarak verildi) |

`dosya` alanları: `gorevler[]`, `arac_gerec[]`, `genel_ozellikler[]`, `calisma_ortami`,
`egitim{verildigi_yerler, giris_kosullari[], sure_ve_icerik, belge}`, `calisma_alanlari`,
`kazanc{egitim_suresince, egitim_sonrasi[]}`, `ilerleme{mesleki_egitimde, is_hayatinda}`,
`benzer_meslekler[]` (yalnız sözlükteki adlar), `ek_bilgiler`.

```bash
python3 _claude/meslek_dosyasi.py durum                 # ilerleme
python3 _claude/meslek_dosyasi.py uret --paralel 3      # eksikleri üret (sürdürülebilir)
python3 _claude/meslek_dosyasi.py disa_aktar            # meslek_bilgi.jsonl'yi yeniden yaz
python3 _claude/meslek_dosyasi.py pdf --kod 5141.05     # isteğe bağlı PDF (yerel, token harcamaz)
```

Örnek olarak 13 meslek için PDF basıldı: `dosyalar/<kod>_<slug>/<Ad> (Claude taslağı).pdf`.

## 17 boyutlu profil (`profil/`)

`profil/iskur_17boyut_profil.{csv,json}`: 7765 meslek için O*NET tabanlı RIASEC, iş değerleri ve
Big Five boyutları (çok dilli embedding ile eşleştirme). Düşük güvenli eşleşmeler
`inceleme_listesi_dusuk_guven.csv` içinde; özet `ozet.json`'da. Embedding önbelleği (`.emb_cache`) repoya konmadı.

> Buradaki profil ilk sürümdür (v1). LLM ile yeniden sıralanmış, daha doğru v2 eşleştirmesi
> reflektif/reflektif PR #2726'dadır; sisteme alınırken v2 esas alınmalıdır.
