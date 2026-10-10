# İŞKUR meslekleri × Reflektif kullanıcı profili: algoritmik eşleştirme değerleri

Bu klasördeki betikler, 7765 İŞKUR mesleğinin her biri için Reflektif test çıktılarıyla
(RIASEC, Big Five, Değerler) **yapay zekâ çağrısı olmadan**, yalnız nokta çarpımıyla
eşleştirilebilen değerleri üretir ve doğrular. Girdi, PR #2726'daki v2 17 boyutlu profildir
(`data/iskur-profiles/iskur_17boyut_profil.csv`).

**Uygulamaya bağlı değil.** Şema, server ve client değişmez; bu PR yalnız veri, betik ve
doğrulama raporu ekler.

## Neden ham 17 boyut yetmiyor

İki taraf aynı boyut adlarını taşıyor ama aynı ölçekte değil. Kullanıcı normu prod'dan
okundu (2026-10-10; her kullanıcının her testteki son sonucu; silinmiş ve test hesapları
hariç; yalnız boyut başına toplu istatistik):

| | Kullanıcı ortalaması (sapma) | Meslek ortalaması (sapma) |
| --- | --- | --- |
| RIASEC R / I / A / S / E / C | 67 / 72 / 75 / 77 / 75 / 76 (≈13–15) | 70 / 30 / 17 / 24 / 27 / 56 (15–30) |
| Big Five O / C / E / A / N | 80 / 78 / 74 / 78 / 65 (11–17) | 49 / 73 / 49 / 46 / 44 (7–18) |
| Değerler | 76–85 (12–17) | 34–54 (12–21) |

- Kullanıcılar genel olarak yüksek işaretliyor (ters maddeli soru yok). Bu yüzden bugünkü
  formüldeki mutlak fark terimi (`100 − 2·ortalama|fark|`) çoğu farkı uyumsuzluk sayıyor.
- Kullanıcıların ortalama RIASEC şekli neredeyse düz. Mesleklerin ortalama şekli ise R ve C
  ağırlıklı, çünkü O*NET işgücünü yansıtıyor. Ham şekil benzerliği bu ortak şekle takılıyor.

## Yöntem: çift standartlaştırma

Her taraf **kendi popülasyonuna göre** z puanına çevrilir. Sonra boyutlar arasında
merkezlenir; böylece kişinin veya mesleğin genel seviyesi, yani "her şeyi yüksek işaretleme"
eğilimi atılır. En son birim vektöre indirilir. Eşleşme iki birim vektörün nokta çarpımıdır;
bu da iki z profili arasındaki Pearson r'ye eşittir.

- Meslek tarafı önceden hesaplanır (`buildOccupations`).
- Kullanıcı tarafı her istekte hesaplanır (`userVectors`); normlar `KULLANICI_NORM` içinde.
- Skor (`scoreNew`): her test bloğu için `50 + 50·r` (0–100). Bloklar bugünkü motorun
  ağırlıklarıyla toplanır: üç test varsa 0,45 / 0,30 / 0,25, iki test varsa 0,55 / 0,45.
- Tek kullanıcı × 7765 meslek, sıralama dahil **~1,3 ms** (Node, Apple silicon).

### Meslek başına üretilen değerler

`data/iskur-profiles/eslestirme/meslek_eslestirme.{json,csv}`, 7765 satır:

| Alan | Anlamı |
| --- | --- |
| `riasec_v[6]`, `bigfive_v[5]`, `deger_v[6]` | Eşleştirme vektörleri (z → merkezle → birim) |
| `riasec_z`, `bigfive_z`, `deger_z` | Aynı profilin merkezlenmiş z hâli (açıklama için: "bu meslekte S belirgin yüksek") |
| `riasec_ayirt`, `bigfive_ayirt`, `deger_ayirt` | ‖z‖/√D: meslek o testte ne kadar belirgin bir profil taşıyor (≈1 tipik) |
| `riasec_seviye[6]` | Kullanıcı ölçeğinde RIASEC seviyesi, yalnız gösterim için (20 + 0,8 × O*NET 0–100) |
| `holland_kodu`, `egitim_sira`, `guven` | Filtre ve etiketler. `egitim_sira`: 0 okur-yazar değil … 8 doktora |

`riasec_sekil_v` (ham RIASEC'in klasik Holland şekli) yalnız JSON'da yer alır; açıklama ve
karşılaştırma içindir.

## Doğrulama

Komut: `node dogrulama.mjs <v2.csv> <rapor.json>`. Sonuçlar
`data/iskur-profiles/eslestirme/dogrulama_raporu.json` dosyasında. Kullanıcı ↔ meslek için
gerçek bir doğru cevap (ör. kişinin seçtiği kariyer) yok; testler, gerçek kullanıcı
dağılımına oturtulmuş sentetik kullanıcılarla yapıldı.

Karşılaştırılan yöntemler:
- **bugünkü:** `server/career-matching-engine.ts` formülünün birebir kopyası.
- **v1:** bu PR'ın ilk turu (norm yokken).
- **v2:** önerilen yöntem.

### 1. Geri bulma

Her ISCO ana grubundan 40, toplam 400 meslek seçildi. Her biri için o mesleğe uyan bir
kullanıcı üretildi ve 7765 meslek arasında sıralandı.

| Senaryo | Yöntem | Medyan sıra | İlk 50 | İlk %5 | Aynı ISCO-4 ilk 20'de |
| --- | --- | --- | --- | --- | --- |
| G1, ρ=0,8 | bugünkü | 1398 | %4,3 | %24,5 | %10,5 |
| | v1 | 491 | %15,0 | %43,8 | %19,0 |
| | **v2** | **211** | **%25,3** | **%61,5** | **%28,0** |
| G1, ρ=0,6 | bugünkü | 1716 | %4,8 | %17,5 | %6,8 |
| | v1 | 757 | %8,5 | %34,3 | %11,0 |
| | **v2** | **515** | **%14,0** | **%43,0** | **%19,5** |
| G2 (stres testi) | bugünkü | 204 | %27,5 | %60,8 | %26,8 |
| | v1 | **139** | **%28,0** | **%71,3** | **%34,0** |
| | v2 | 469 | %8,5 | %44,0 | %20,3 |

Senaryolar:
- **G1, gerçek dağılım.** Kullanıcının özelliği mesleğin profiline ρ kadar benziyor. Puanlar
  prod normunun ortalama ve sapmasıyla üretildi; kişiye özgü seviye (sapma 8) ve ölçme hatası
  (sapma 6) eklendi.
- **G2, O*NET şekli.** Kullanıcının profil şekli mesleğin ham O*NET profiliyle aynı, yalnız
  seviyesi kaydırılmış. Bu dünya prod verisiyle çelişiyor: öyle olsaydı kullanıcıların ortalama
  RIASEC şekli R ve C ağırlıklı çıkardı, oysa düz. Bugünkü formülün lehine olduğu için stres
  testi olarak tutuldu.

7765 mesleğin yalnız 3504'ünün profili eşsiz, çünkü birçok meslek aynı O*NET seçimlerini
paylaşıyor. Bu yüzden "tam meslek" sırası doğası gereği sınırlı; ISCO-4 isabeti daha anlamlı
bir ölçüt.

### 2. Çeşitlilik ve sürekli öne çıkan meslekler

Prod normundan 1000 rastgele kullanıcı üretildi ve her birinin ilk 10'u incelendi.

| | İlk 10'larda görülen farklı meslek | En sık çıkan meslek | İlk 10'ların ISCO 1+2 (yönetici + profesyonel) payı |
| --- | --- | --- | --- |
| bugünkü | 1363 | Amerikan Kültürü ve Edebiyatı Öğretim Üyesi (kullanıcıların %8,1'i) | %89,5 |
| v1 | 2567 | Spiker (%5,0) | %54,5 |
| **v2** | **3596** | Görüntü ve Ses Sistemleri Elemanı (%2,4) | %25,1 |

Bugünkü formül, kullanıcıların profilinden bağımsız olarak çoğunu birkaç akademik ve
yönetici mesleğine yığıyor; bu, ölçek farkından doğan bir yan etki. v2'de ilk 10'lar
kullanıcıya göre değişiyor. v2'nin dağılımının "doğru" oran olup olmadığı ise ancak gerçek
sonuç verisiyle (seçilen kariyerler) söylenebilir.

### 3. Tipik profiller (yüz geçerliliği)

Profiller kullanıcı normuna göre z ile tanımlandı (ör. "C yüksek" = C +2 sapma, diğerleri
ortalamanın biraz altında) ve gerçek puan ölçeğine çevrildi.

| Profil | v2 ilk sıralar | bugünkü ilk sıralar |
| --- | --- | --- |
| Büro (C yüksek) | tesis başkontrolörü, büro memuru, hazine operasyon uzmanı | yönetici, başhekim, tıbbi direktör |
| El becerisi (R yüksek) | elektrik şebeke teknisyeni, katener işçisi, klima teknisyeni | inşaat mühendisi çeşitleri |
| Sanatsal (A yüksek) | animasyon, grafik animasyoncu, görsel tasarımcı | orkestra şefliği öğretim üyesi, oyun tasarımcısı, şair |
| Araştırmacı (I yüksek) | jeofizik, jeoloji, ziraat mühendisi | antropolog, arkeolog |
| Sosyal (S yüksek) | usta öğretici, meslek dersi öğretmenleri, engelli bakım teknikeri | sınıf öğretmeni, çocuk gelişimci |
| Girişimci (E yüksek) | koordinatör, yönetici, spor hakemi | STK başkanı, cumhurbaşkanı, bakan |

- Büro, el becerisi ve sanatsal profillerde v2 daha isabetli.
- Sosyal profilde bugünkü formül daha iyi. v2'de #2726'nın öğretmen profili karışımı
  (öğretilen alanla %35 harmanlama) meslek dersi öğretmenlerini öne çıkarıyor.
- Girişimci profilinde iki yöntem de zayıf.
- Eğitim düzeyi skora girmediği için düşük eğitimli işler de çıkabiliyor. Bu yüzden
  `egitim_sira` filtre olarak kullanılmalı.

### 4. Yapısal kontrol

Holland altıgeni: komşu tipler arası ortalama r = 0,10, karşıt tipler arası −0,44. Bu,
kuramın öngördüğü sırayla uyumlu.

### 5. Gerçek seçimlerle karşılaştırma (ve neden karar veremediği)

`gercek_sonuc_sql.mjs` prod'da salt-okunur çalışan, yalnız toplu sonuç döndüren bir sorgu
üretir; kişi verisi veritabanından çıkmaz. Her iki formül **aynı veriyle**, yani katalogdaki
932 kariyerin kayıtlı profilleriyle çalıştırıldı. Böylece fark yalnız formülden geliyor.
Sonuçlar `data/iskur-profiles/eslestirme/gercek_sonuc_raporu.json` dosyasında.

Ölçüt: kullanıcının favorilediği kariyerin, o kullanıcı için 932 kariyer arasındaki ortalama
yüzdelik sırası (0 = en üst, 0,5 = rastgele).

| Favori (222 kullanıcı, 1189 seçim) | Ortalama yüzdelik | İlk 30'da |
| --- | --- | --- |
| Bugünkü formül | 0,034 | %79,8 |
| Kişiselleştirmesiz popülerlik sırası | 0,085 | %42,8 |
| v2, ağırlıklar 0,6 / 0,2 / 0,2 | 0,230 | %19,1 |
| v2, bugünkü ağırlıklar 0,45 / 0,30 / 0,25 | 0,237 | %18,8 |
| v2, eşit ağırlık | 0,255 | %16,8 |
| v2, kişilik veya değer ağır | 0,268 | %16,2–16,9 |

Öncelik listesinde (207 kullanıcı, 698 seçim) aynı sıra çıkıyor.

**Bu tablo yöntemleri tarafsız karşılaştırmıyor.** Seçimlerin tamamı, kullanıcı bugünkü
formülün (ve YZ'nin) ürettiği listeyi gördükten sonra yapılmış. Testten önce yapılmış seçim
yalnız 4 favori, 1 kullanıcı. 932 kariyerden yalnız 301'i en az bir kez favorilenmiş.
Hiç kişiselleştirme içermeyen popülerlik sırası bile favorileri %8,5 yüzdeliğe koyuyor.
Yani bu veri, kullanıcıların neyi seçtiğinden çok onlara neyin gösterildiğini ölçüyor.

Yine de iki bilgi veriyor:
- v2, kullanıcılara hiç gösterilmediği hâlde onların seçtiği kariyerleri ortalama ilk
  çeyreğe koyuyor (rastgele 0,5).
- v2 ağırlıkları arasında RIASEC'e ağırlık veren varyantlar biraz önde. Kişilik ve değer
  ağırlıklı varyantlar geride; katalogdaki Big Five ve Değer profilleri büyük ölçüde YZ ile
  üretilmiş olduğu için bu beklenen bir sonuç. Farklar küçük, ağırlık değişikliği için tek
  başına yeterli kanıt değil.

**Doğru test:** Bundan sonrası için tarafsız ölçüm, iki sıralamanın kullanıcıya karışık
gösterildiği bir deneyle yapılabilir. Örneğin "team-draft interleaving": iki listeden sırayla
seçilen öneriler tek liste olarak gösterilir ve tıklanan/favorilenen önerinin hangi yöntemden
geldiği kaydedilir. Bu, uygulamada değişiklik gerektiriyor; bu PR'ın kapsamı dışında.

### Blok ağırlığını belirginliğe göre ölçeklemek

Big Five ve Değer bloğunun ağırlığını `min(1, *_ayirt)` ile ölçeklemek (`ayirtAgirlik`)
denendi. Kazancı ölçme hatası düzeyinde kaldı ve çeşitliliği düşürdü, bu yüzden varsayılan
olarak kapalı.

## Sınırlar ve sonraki adımlar

1. **Gerçek sonuçla kalibrasyon.** Mevcut seçim verisi gösterilen listeye bağlı olduğu için
   (bölüm 5) tarafsız kalibrasyon ancak bir karışık sıralama (interleaving) deneyiyle
   yapılabilir. Blok ağırlıkları da hâlâ keyfi
   (`docs/PSIKOMETRIK_IYILESTIRME_ONERILERI_2026-09-06.md` A8).
2. **Normun sürümü.** `KULLANICI_NORM` bir anlık kesit. `shared/bigfive-norm.ts`'teki gibi
   dondurulmalı ve `docs/NORM_V2_CHANGE_PROTOCOL.md` ile yönetilmeli. Big Five için oradaki
   P25/P75 bu kesitle tutarlı (ör. A 72/84).
3. **Eğitim.** `egitim_sira`, kullanıcının hedef veya mevcut eğitim düzeyiyle filtre ya da
   yumuşak ceza olarak uygulanmalı.
4. **Kaynak profilin sınırları** (#2726 README): silahlı kuvvetler satırları zayıf; Big Five
   ve Değer eşleme tablosu psikometrik olarak doğrulanmamış; O*NET seçimlerini bir LLM yaptı;
   öğretmen harmanlaması sosyal profilleri etkiliyor.
