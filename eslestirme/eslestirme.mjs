// İŞKUR meslekleri × Reflektif kullanıcı profili: eşleştirme değerleri üretimi.
// Girdi: v2 17 boyutlu meslek profili CSV'si (PR #2726). Çıktı: meslek başına
// kullanıcı puanlarıyla doğrudan nokta çarpımı yapılabilen, önceden normalize
// edilmiş vektörler + ayırt edicilik + eğitim sırası.
//
//   node eslestirme.mjs <v2.csv> <cikti_klasoru>
import fs from "node:fs";
import path from "node:path";

export const RIASEC = ["R", "I", "A", "S", "E", "C"];
export const VALUES = ["CRE", "ALT", "SEC", "AUT", "REL", "REU"];
export const BIGFIVE = ["O", "C", "E", "A", "N"];
const CSV_COLS = {
  riasec: ["riasec_r", "riasec_i", "riasec_a", "riasec_s", "riasec_e", "riasec_c"],
  values: ["deger_cre", "deger_alt", "deger_sec", "deger_aut", "deger_rel", "deger_reu"],
  bigfive: ["bigfive_o", "bigfive_c", "bigfive_e", "bigfive_a", "bigfive_n"],
};
export const EGITIM_SIRA = {
  "Okur Yazar Olmayan": 0, "Okur Yazar": 1, "İlkokul": 2, "İlköğretim": 3,
  "Ortaöğretim (Lise ve Dengi)": 4, "Önlisans": 5, "Lisans": 6, "Yüksek Lisans": 7, "Doktora": 8,
};

// ---------------------------------------------------------------- yardımcılar
export const mean = (v) => v.reduce((a, b) => a + b, 0) / v.length;
export const center = (v) => { const m = mean(v); return v.map((x) => x - m); };
export const norm = (v) => Math.sqrt(v.reduce((a, b) => a + b * b, 0));
export const unit = (v) => { const n = norm(v); return n > 1e-9 ? v.map((x) => x / n) : v.map(() => 0); };
export const dot = (a, b) => a.reduce((s, x, i) => s + x * b[i], 0);
const r3 = (x) => Math.round(x * 1000) / 1000;
const r1 = (x) => Math.round(x * 10) / 10;

export function parseCsv(text) {
  text = text.replace(/^﻿/, "");
  const rows = []; let row = [], f = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"') { if (text[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += c; }
    else if (c === '"') q = true;
    else if (c === ",") { row.push(f); f = ""; }
    else if (c === "\n") { row.push(f); rows.push(row); row = []; f = ""; }
    else if (c !== "\r") f += c;
  }
  if (f || row.length) { row.push(f); rows.push(row); }
  const h = rows.shift();
  return rows.filter((r) => r.length === h.length).map((r) => Object.fromEntries(h.map((k, i) => [k, r[i]])));
}

function stats(mat) {
  const D = mat[0].length;
  const mu = [...Array(D)].map((_, d) => mean(mat.map((r) => r[d])));
  const sd = [...Array(D)].map((_, d) => Math.sqrt(mean(mat.map((r) => (r[d] - mu[d]) ** 2))));
  return { mu, sd };
}

// ---------------------------------------------------------------- meslek tarafı
/**
 * Reflektif kullanıcı normu (prod, 2026-10-10): her kullanıcının her testteki son tamamlanmış
 * sonucu; silinmiş ve @test.reflektif.net hesaplar hariç. Yalnız boyut başına toplu istatistik.
 * RIASEC n=1040, Big Five n=573, Değerler n=483. [ortalama, sapma]
 */
export const KULLANICI_NORM = {
  surum: "kullanici-norm-2026-10",
  riasec: { R: [66.9, 13.3], I: [71.7, 13.6], A: [74.7, 13.6], S: [76.6, 13.7], E: [75.4, 14.9], C: [75.9, 13.2] },
  bigfive: { O: [80.2, 10.8], C: [77.7, 12.1], E: [74.4, 14.6], A: [78.0, 10.7], N: [64.6, 16.8] },
  values: { CRE: [83.3, 13.9], ALT: [75.8, 16.9], SEC: [80.9, 12.2], AUT: [81.0, 12.9], REL: [78.9, 13.6], REU: [84.8, 13.7] },
};

/**
 * Çift standartlaştırma. İki taraf farklı ölçeklerde olduğu için her taraf KENDİ
 * popülasyonuna göre z'ye çevrilir, sonra boyutlar arası merkezlenir (kişinin/mesleğin genel
 * seviyesi, yani "her şeyi yüksek işaretleme" eğilimi atılır) ve birim vektöre indirilir.
 * Eşleşme = iki birim vektörün nokta çarpımı = z profilleri arası Pearson r.
 *
 * Meslek başına:
 *  - riasec_v / bigfive_v / deger_v: meslek popülasyonuna göre z → merkezle → birim vektör.
 *  - *_ayirt: merkezlenmiş z vektörünün boyu / √D — meslek o testte ne kadar belirgin bir
 *    profil taşıyor (≈1 tipik; küçükse o blok bu meslek için az bilgi taşır).
 *  - riasec_sekil_v: ham RIASEC'in merkezlenmiş birim vektörü (klasik Holland şekli; açıklama
 *    ve duyarlılık testi için).
 */
export function buildOccupations(rows) {
  const R = rows.map((r) => CSV_COLS.riasec.map((c) => +r[c]));
  const V = rows.map((r) => CSV_COLS.values.map((c) => +r[c]));
  const B = rows.map((r) => CSV_COLS.bigfive.map((c) => +r[c]));
  const rs = stats(R), vs = stats(V), bs = stats(B);
  const Vips = V.map(center), vis = stats(Vips);
  const zc = (x, st) => center(x.map((v, d) => (v - st.mu[d]) / st.sd[d]));
  const out = rows.map((r, i) => {
    const rz = zc(R[i], rs), vz = zc(V[i], vs), bz = zc(B[i], bs);
    const v1vz = Vips[i].map((x, d) => (x - vis.mu[d]) / vis.sd[d]);
    return {
      meslek_kodu: r.meslek_kodu, meslek_adi: r.meslek_adi, isco4: r.isco4,
      min_egitim_duzeyi: r.min_egitim_duzeyi, egitim_sira: EGITIM_SIRA[r.min_egitim_duzeyi] ?? null,
      guven: r.guven, holland_kodu: r.holland_kodu,
      // kullanıcı ölçeğinde seviye (O*NET 1–7 → Likert 1–5 → %maks): gösterim/açıklama için
      riasec_seviye: R[i].map((x) => r1(20 + 0.8 * x)),
      riasec_v: unit(rz).map(r3), deger_v: unit(vz).map(r3), bigfive_v: unit(bz).map(r3),
      riasec_z: rz.map(r3), deger_z: vz.map(r3), bigfive_z: bz.map(r3),
      riasec_ayirt: r3(norm(rz) / Math.sqrt(6)),
      deger_ayirt: r3(norm(vz) / Math.sqrt(6)),
      bigfive_ayirt: r3(norm(bz) / Math.sqrt(5)),
      riasec_sekil_v: unit(center(R[i])).map(r3),
      _raw: { R: R[i], V: V[i], B: B[i] },
      // ilk tur (eslestirme-v1) vektörleri, karşılaştırma için
      _v1: {
        riasec_v: unit(center(R[i])), deger_v: unit(v1vz),
        bigfive_v: unit(B[i].map((x, d) => (x - bs.mu[d]) / bs.sd[d])),
        deger_ayirt: norm(v1vz) / Math.sqrt(6),
        bigfive_ayirt: norm(B[i].map((x, d) => (x - bs.mu[d]) / bs.sd[d])) / Math.sqrt(5),
      },
    };
  });
  const meta = Object.fromEntries([["riasec", RIASEC, rs], ["deger", VALUES, vs], ["bigfive", BIGFIVE, bs]]
    .map(([ad, keys, st]) => [ad, Object.fromEntries(keys.map((k, d) => [k, [r3(st.mu[d]), r3(st.sd[d])]]))]));
  return { occ: out, meta };
}

// ---------------------------------------------------------------- kullanıcı tarafı
/** Kullanıcı puanlarını (test_results.raw_scores, 0–100) eşleştirme vektörlerine çevirir. */
export function userVectors(u, norms = KULLANICI_NORM) {
  const vec = (scores, keys, n) => unit(center(keys.map((k) => {
    const [mu, sd] = n[k]; return ((scores[k] ?? mu) - mu) / sd;
  })));
  const res = {};
  if (u.riasec) res.riasec = vec(u.riasec, RIASEC, norms.riasec);
  if (u.values) res.values = vec(u.values, VALUES, norms.values);
  if (u.bigfive) res.bigfive = vec(u.bigfive, BIGFIVE, norms.bigfive);
  return res;
}

export const WEIGHTS = {
  all: { riasec: 0.45, bigfive: 0.30, values: 0.25 },
  rb: { riasec: 0.55, bigfive: 0.45, values: 0 },
  rv: { riasec: 0.55, bigfive: 0, values: 0.45 },
  r: { riasec: 1, bigfive: 0, values: 0 },
};
/**
 * Önerilen eşleştirme: blok başına `50 + 50·(kullanıcı_v · meslek_v)` (0–100), bugünkü motorun
 * blok ağırlıklarıyla toplanır. `ayirtAgirlik` (varsayılan kapalı; doğrulamada fark getirmedi) açıkken Big Five/Değer ağırlığı mesleğin o bloktaki
 * belirginliğiyle (min(1, *_ayirt)) ölçeklenir.
 */
export function scoreNew(uv, o, { ayirtAgirlik = false, v1 = false } = {}) {
  const has = { b: !!uv.bigfive, v: !!uv.values };
  const W = has.b && has.v ? WEIGHTS.all : has.b ? WEIGHTS.rb : has.v ? WEIGHTS.rv : WEIGHTS.r;
  const src = v1 ? o._v1 : o;
  let wB = W.bigfive, wV = W.values;
  if (ayirtAgirlik) { wB *= Math.min(1, src.bigfive_ayirt); wV *= Math.min(1, src.deger_ayirt); }
  const sR = 50 + 50 * dot(uv.riasec, src.riasec_v);
  const sB = has.b ? 50 + 50 * dot(uv.bigfive, src.bigfive_v) : 0;
  const sV = has.v ? 50 + 50 * dot(uv.values, src.deger_v) : 0;
  return (W.riasec * sR + wB * sB + wV * sV) / (W.riasec + wB + wV);
}

/** İlk tur (v1) kullanıcı vektörleri: RIASEC/Değer kişi içi merkezleme, Big Five norm-v1 P25/P75. */
export const BIGFIVE_NORM_V1 = { A: [72, 84], C: [70, 86], E: [66, 84], N: [54, 76], O: [74, 88] };
export function userVectorsV1(u) {
  return {
    riasec: unit(center(RIASEC.map((k) => u.riasec[k]))),
    values: u.values && unit(center(VALUES.map((k) => u.values[k]))),
    bigfive: u.bigfive && unit(BIGFIVE.map((k) => {
      const [a, b] = BIGFIVE_NORM_V1[k]; return (u.bigfive[k] - (a + b) / 2) / ((b - a) / 1.349);
    })),
  };
}

// ---------------------------------------------------------------- bugünkü formül (karşılaştırma)
function pearson(a, b) {
  const x = center(a), y = center(b); const n = norm(x) * norm(y);
  return n > 0 ? dot(x, y) / n : 0;
}
export function scoreCurrent(u, o) {
  // server/career-matching-engine.ts computeRiasecScore / computeBigFiveScore / computeValuesScore
  const ur = RIASEC.map((k) => Math.min(5, (u.riasec[k] ?? 50) / 20));
  const or = o._raw.R.map((x) => x / 20);
  const eu = Math.sqrt(ur.reduce((s, x, i) => s + (x - or[i]) ** 2, 0));
  const sR = Math.round((((pearson(ur, or) + 1) / 2) * 0.55 + Math.max(0, 1 - eu / Math.sqrt(150)) * 0.45) * 100);
  const blk = (uu, oo) => {
    const avg = mean(uu.map((x, i) => Math.abs(x - oo[i])));
    return Math.round(((pearson(uu, oo) + 1) / 2) * 100 * 0.5 + Math.max(0, 100 - avg * 2) * 0.5);
  };
  const has = { b: !!u.bigfive, v: !!u.values };
  const W = has.b && has.v ? WEIGHTS.all : has.b ? WEIGHTS.rb : has.v ? WEIGHTS.rv : WEIGHTS.r;
  const sB = has.b ? blk(BIGFIVE.map((k) => u.bigfive[k]), o._raw.B) : 0;
  const sV = has.v ? blk(VALUES.map((k) => u.values[k]), o._raw.V) : 0;
  return Math.round(sR * W.riasec + sB * W.bigfive + sV * W.values);
}

// ---------------------------------------------------------------- ana
if (import.meta.url === `file://${process.argv[1]}`) {
  const [csvPath, outDir] = process.argv.slice(2);
  const rows = parseCsv(fs.readFileSync(csvPath, "utf8"));
  const { occ, meta } = buildOccupations(rows);
  fs.mkdirSync(outDir, { recursive: true });
  const clean = occ.map(({ _raw, _v1, ...o }) => o);
  fs.writeFileSync(path.join(outDir, "meslek_eslestirme.json"),
    JSON.stringify({ surum: "eslestirme-v2", kullanici_normu: KULLANICI_NORM, kaynak: "iskur_17boyut_profil.csv (v2, PR #2726)",
      boyutlar: { riasec: RIASEC, deger: VALUES, bigfive: BIGFIVE }, meslek_istatistikleri: meta,
      meslekler: clean }));
  const H = ["meslek_kodu", "meslek_adi", "isco4", "min_egitim_duzeyi", "egitim_sira", "guven", "holland_kodu",
    ...RIASEC.map((k) => `riasec_seviye_${k}`), ...RIASEC.map((k) => `riasec_v_${k}`),
    ...VALUES.map((k) => `deger_v_${k}`), ...BIGFIVE.map((k) => `bigfive_v_${k}`),
    ...RIASEC.map((k) => `riasec_z_${k}`), ...VALUES.map((k) => `deger_z_${k}`), ...BIGFIVE.map((k) => `bigfive_z_${k}`),
    "riasec_ayirt", "deger_ayirt", "bigfive_ayirt"];
  const esc = (s) => (/[",\n]/.test(String(s)) ? `"${String(s).replace(/"/g, '""')}"` : String(s));
  const lines = [H.join(",")].concat(clean.map((o) => [o.meslek_kodu, o.meslek_adi, o.isco4, o.min_egitim_duzeyi,
    o.egitim_sira, o.guven, o.holland_kodu, ...o.riasec_seviye, ...o.riasec_v, ...o.deger_v, ...o.bigfive_v,
    ...o.riasec_z, ...o.deger_z, ...o.bigfive_z, o.riasec_ayirt, o.deger_ayirt, o.bigfive_ayirt].map(esc).join(",")));
  fs.writeFileSync(path.join(outDir, "meslek_eslestirme.csv"), "﻿" + lines.join("\n") + "\n");
  console.log(`${clean.length} meslek yazıldı →`, outDir);
  console.log(JSON.stringify(meta));
}
