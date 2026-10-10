// Eşleştirme değerlerinin doğrulaması: sentetik kullanıcılarla geri-bulma testi,
// bugünkü formülle karşılaştırma, tipik profillerle yüz geçerliliği, yapısal kontroller.
//   node dogrulama.mjs <v2.csv> <rapor.json>
import fs from "node:fs";
import {
  parseCsv, buildOccupations, userVectors, userVectorsV1, scoreNew, scoreCurrent,
  RIASEC, VALUES, BIGFIVE, KULLANICI_NORM, mean,
} from "./eslestirme.mjs";

const [csvPath, outPath] = process.argv.slice(2);
const rows = parseCsv(fs.readFileSync(csvPath, "utf8"));
const { occ } = buildOccupations(rows);
const N = occ.length;

// tekrarlanabilir rastgelelik
let seed = 20261010;
const rnd = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296);
const gauss = () => { const u = 1 - rnd(), v = rnd(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };
const clamp = (x) => Math.max(20, Math.min(100, Math.round(x)));

// meslek popülasyonu istatistikleri (ham)
const colStats = (key, D) => {
  const mu = [...Array(D)].map((_, d) => mean(occ.map((o) => o._raw[key][d])));
  const sd = [...Array(D)].map((_, d) => Math.sqrt(mean(occ.map((o) => (o._raw[key][d] - mu[d]) ** 2))));
  return { mu, sd };
};
const S = { R: colStats("R", 6), V: colStats("V", 6), B: colStats("B", 5) };
const toObj = (keys, arr) => Object.fromEntries(keys.map((k, i) => [k, arr[i]]));
const NR = RIASEC.map((k) => KULLANICI_NORM.riasec[k]);
const NV = VALUES.map((k) => KULLANICI_NORM.values[k]);
const NB = BIGFIVE.map((k) => KULLANICI_NORM.bigfive[k]);
const ELEV = 8, ERR = 6; // kişi geneli seviye (yanıt eğilimi) ve ölçme hatası, puan cinsinden

/**
 * G1 "gerçek dağılım": kullanıcının özelliği mesleğin z profiline ρ kadar benzer; puanlar
 * gerçek Reflektif kullanıcı dağılımında üretilir (boyut ortalaması/sapması = prod normu).
 * Sapmanın bir kısmı kişiye özgü seviye (ELEV) ve ölçme hatasıdır (ERR); kalan kısım özelliktir.
 */
function userG1(o, rho) {
  const e = ELEV * gauss(), mix = (z) => rho * z + Math.sqrt(1 - rho * rho) * gauss();
  const gen = (raw, st, nrm) => raw.map((x, d) => {
    const [mu, sd] = nrm[d]; const trait = Math.sqrt(Math.max(1, sd * sd - ELEV * ELEV - ERR * ERR));
    return clamp(mu + trait * mix((x - st.mu[d]) / st.sd[d]) + e + ERR * gauss());
  });
  return {
    riasec: toObj(RIASEC, gen(o._raw.R, S.R, NR)),
    values: toObj(VALUES, gen(o._raw.V, S.V, NV)),
    bigfive: toObj(BIGFIVE, gen(o._raw.B, S.B, NB)),
  };
}
/**
 * G2 "O*NET şekli" (stres testi): kullanıcının profil ŞEKLİ mesleğin ham O*NET profiliyle aynı
 * (ör. işçide R ve C çok yüksek, A çok düşük), yalnız genel seviyesi kullanıcı ortalamasına
 * kaydırılmış. Prod verisi bu dünyayla çelişiyor (kullanıcıların ortalama RIASEC şekli düz,
 * O*NET'in ortalama şekli R/C ağırlıklı), ama bugünkü formülün lehine olduğu için tutuldu.
 */
function userG2(o, rho) {
  const k = occ[Math.floor(rnd() * N)];
  const m = (a, b, nrm) => { const lvl = mean(nrm.map((x) => x[0]));
    return a.map((x, d) => clamp(lvl + 0.8 * (rho * x + (1 - rho) * b[d] - 50) + ELEV * 0 + ERR * gauss())); };
  return {
    riasec: toObj(RIASEC, m(o._raw.R, k._raw.R, NR)),
    values: toObj(VALUES, m(o._raw.V, k._raw.V, NV)),
    bigfive: toObj(BIGFIVE, m(o._raw.B, k._raw.B, NB)),
  };
}
/** Prod normundan bağımsız boyutlarla rastgele gerçekçi kullanıcı (tekil/hub analizi için). */
function userRandom() {
  const e = ELEV * gauss();
  const g = (nrm) => nrm.map(([mu, sd]) => clamp(mu + Math.sqrt(sd * sd - ELEV * ELEV) * gauss() + e));
  return { riasec: toObj(RIASEC, g(NR)), values: toObj(VALUES, g(NV)), bigfive: toObj(BIGFIVE, g(NB)) };
}

const METHODS = {
  bugunku: (u, uv, o) => scoreCurrent(u, o),
  v1: (u, uv, o) => scoreNew(uv.v1, o, { v1: true, ayirtAgirlik: true }),
  v2: (u, uv, o) => scoreNew(uv.v2, o),
  v2_ayirt: (u, uv, o) => scoreNew(uv.v2, o, { ayirtAgirlik: true }),
};
const vecs = (u) => ({ v1: userVectorsV1(u), v2: userVectors(u) });

function evaluate(gen, sample, label) {
  const res = {};
  for (const m of Object.keys(METHODS)) res[m] = { ranks: [], isco4_top20: 0, ana_grup_top10: 0, egitim_top10_fark: [] };
  for (const j of sample) {
    const o = occ[j]; const u = gen(o); const uv = vecs(u);
    for (const [m, f] of Object.entries(METHODS)) {
      const sc = new Float64Array(N);
      for (let i = 0; i < N; i++) sc[i] = f(u, uv, occ[i]);
      const own = sc[j];
      let higher = 0; for (let i = 0; i < N; i++) if (sc[i] > own + 1e-9) higher++;
      res[m].ranks.push(higher + 1);
      const top = [...sc.keys()].sort((a, b) => sc[b] - sc[a]).slice(0, 20);
      if (top.some((i) => occ[i].isco4 === o.isco4)) res[m].isco4_top20++;
      res[m].ana_grup_top10 += top.slice(0, 10).filter((i) => occ[i].isco4[0] === o.isco4[0]).length / 10;
    }
  }
  const n = sample.length, out = { senaryo: label, n };
  for (const [m, r] of Object.entries(res)) {
    const s = [...r.ranks].sort((a, b) => a - b);
    out[m] = {
      medyan_sira: s[Math.floor(n / 2)],
      ilk10_oran: +(r.ranks.filter((x) => x <= 10).length / n).toFixed(3),
      ilk50_oran: +(r.ranks.filter((x) => x <= 50).length / n).toFixed(3),
      ilk_yuzde5_oran: +(r.ranks.filter((x) => x <= N * 0.05).length / n).toFixed(3),
      isco4_ilk20: +(r.isco4_top20 / n).toFixed(3),
      ana_grup_ilk10: +(r.ana_grup_top10 / n).toFixed(3),
    };
  }
  console.log(JSON.stringify(out));
  return out;
}

// her ISCO ana grubundan eşit örnek
const byMajor = {};
occ.forEach((o, i) => (byMajor[o.isco4[0]] ??= []).push(i));
const sample = [];
for (const g of Object.keys(byMajor).sort()) {
  const idx = [...byMajor[g]];
  for (let k = 0; k < 40 && idx.length; k++) sample.push(idx.splice(Math.floor(rnd() * idx.length), 1)[0]);
}

const rapor = { ornek_meslek: sample.length, kullanici_normu: KULLANICI_NORM.surum, senaryolar: [] };
const SKIP = process.env.SADECE_ARKETIP === "1";
if (!SKIP) for (const rho of [0.8, 0.6]) rapor.senaryolar.push(evaluate((o) => userG1(o, rho), sample, `G1 gerçek dağılım ρ=${rho}`));
if (!SKIP) rapor.senaryolar.push(evaluate((o) => userG2(o, 0.8), sample, "G2 O*NET şekli (stres testi) ρ=0.8"));

// ---------------------------------------------------------------- çeşitlilik / "hub" analizi
// Gerçek dağılımdan 1000 rastgele kullanıcı: ilk 10'larda kaç farklı meslek çıkıyor, en sık
// çıkan meslek kullanıcıların yüzde kaçının ilk 10'unda, ilk 10'ların ISCO ana grup dağılımı.
rapor.cesitlilik = {};
const randUsers = [...Array(1000)].map(userRandom);
for (const [m, f] of Object.entries(SKIP ? {} : METHODS)) {
  const cnt = new Map(), major = {};
  for (const u of randUsers) {
    const uv = vecs(u);
    const top = occ.map((o, i) => [f(u, uv, o), i]).sort((a, b) => b[0] - a[0]).slice(0, 10);
    for (const [, i] of top) { cnt.set(i, (cnt.get(i) ?? 0) + 1); major[occ[i].isco4[0]] = (major[occ[i].isco4[0]] ?? 0) + 1; }
  }
  const sorted = [...cnt.entries()].sort((a, b) => b[1] - a[1]);
  rapor.cesitlilik[m] = {
    ilk10da_gorulen_farkli_meslek: cnt.size,
    en_sik_meslek: `${occ[sorted[0][0]].meslek_adi} (kullanıcıların %${(sorted[0][1] / 10).toFixed(1)}'i)`,
    en_sik_10_meslegin_payi: +(sorted.slice(0, 10).reduce((s, x) => s + x[1], 0) / 10000).toFixed(3),
    isco_ana_grup_dagilimi: Object.fromEntries(Object.entries(major).sort().map(([g, c]) => [g, +(c / 10000).toFixed(3)])),
  };
  console.log(m, JSON.stringify(rapor.cesitlilik[m]));
}
// Ortalama kullanıcı (her boyut prod ortalamasında) kime eşleşiyor?
const avgUser = { riasec: toObj(RIASEC, NR.map((x) => x[0])), values: toObj(VALUES, NV.map((x) => x[0])), bigfive: toObj(BIGFIVE, NB.map((x) => x[0])) };
rapor.ortalama_kullanici = Object.fromEntries(Object.entries(METHODS).map(([m, f]) => {
  const uv = vecs(avgUser);
  return [m, occ.map((o, i) => [f(avgUser, uv, o), i]).sort((a, b) => b[0] - a[0]).slice(0, 5).map(([s, i]) => `${occ[i].meslek_adi} (${Math.round(s)})`)];
}));

// ---------------------------------------------------------------- tipik profiller
// Tipik profiller kullanıcı normuna göre z olarak tanımlanır (0 = ortalama Reflektif kullanıcısı)
// ve gerçek puan ölçeğine çevrilir; böylece her yönteme gerçekçi ham puan verilir.
const ARKETIP_Z = {
  "Araştırmacı-bilimsel (I, O yüksek)": { riasec: { I: 2, R: 0.5, A: 0.3 }, bigfive: { O: 1.5 }, values: { CRE: 1, AUT: 1 } },
  "Sosyal-yardım (S, A yüksek)": { riasec: { S: 2, A: 0.5, I: 0.3 }, bigfive: { A: 1.5, E: 0.5 }, values: { ALT: 1.5, REL: 0.8 } },
  "Girişimci-lider (E yüksek)": { riasec: { E: 2, S: 0.5, C: 0.3 }, bigfive: { E: 1.5, C: 0.5 }, values: { REU: 1.2, AUT: 0.8 } },
  "El becerisi-teknik (R yüksek)": { riasec: { R: 2, I: 0.5, C: 0.3 }, bigfive: { C: 0.5 }, values: { SEC: 1, AUT: 0.5 } },
  "Sanatsal (A, O yüksek)": { riasec: { A: 2, I: 0.3, S: 0.3 }, bigfive: { O: 1.5, N: 0.5 }, values: { CRE: 1.5, AUT: 1 } },
  "Düzenli-büro (C yüksek)": { riasec: { C: 2, E: 0.5 }, bigfive: { C: 1.5 }, values: { SEC: 1.2, REL: 0.5 } },
};
const zToRaw = (z, keys, nrm) => toObj(keys, keys.map((k, d) => clamp(nrm[d][0] + (z[k] ?? -0.3) * nrm[d][1])));
const ARKETIP = Object.fromEntries(Object.entries(ARKETIP_Z).map(([ad, z]) => [ad, {
  riasec: zToRaw(z.riasec, RIASEC, NR), bigfive: zToRaw(z.bigfive, BIGFIVE, NB), values: zToRaw(z.values, VALUES, NV),
}]));
rapor.arketipler = {};
for (const [ad, u] of Object.entries(ARKETIP)) {
  const uv = vecs(u);
  const top = (f) => occ.map((o, i) => [f(u, uv, o), i]).sort((a, b) => b[0] - a[0]).slice(0, 10)
    .map(([s, i]) => `${occ[i].meslek_adi} (${occ[i].holland_kodu}, ${Math.round(s)})`);
  rapor.arketipler[ad] = { puanlar: u, v2: top(METHODS.v2), bugunku: top(METHODS.bugunku) };
}

// ---------------------------------------------------------------- yapısal kontroller
// Holland altıgeni: komşu tiplerin meslekler arası korelasyonu karşıt tiplerden yüksek olmalı.
const corr = (a, b) => { const ma = mean(a), mb = mean(b); let s = 0, sa = 0, sb = 0;
  for (let i = 0; i < a.length; i++) { s += (a[i] - ma) * (b[i] - mb); sa += (a[i] - ma) ** 2; sb += (b[i] - mb) ** 2; }
  return s / Math.sqrt(sa * sb); };
const col = (d) => occ.map((o) => o._raw.R[d]);
const komsu = [], karsi = [];
for (let d = 0; d < 6; d++) { komsu.push(corr(col(d), col((d + 1) % 6))); karsi.push(corr(col(d), col((d + 3) % 6))); }
rapor.holland_altigen = { komsu_ort_r: +mean(komsu).toFixed(3), karsi_ort_r: +mean(karsi).toFixed(3) };
// ayırt edicilik dağılımı ve eşsiz vektör sayısı
const q = (arr, p) => { const s = [...arr].sort((a, b) => a - b); return s[Math.floor(p * (s.length - 1))]; };
for (const k of ["riasec_ayirt", "deger_ayirt", "bigfive_ayirt"]) {
  const a = occ.map((o) => o[k]); rapor[k] = { p10: q(a, 0.1), medyan: q(a, 0.5), p90: q(a, 0.9) };
}
rapor.essiz_profil = new Set(occ.map((o) => [...o.riasec_v, ...o.deger_v, ...o.bigfive_v].join())).size;

fs.writeFileSync(outPath, JSON.stringify(rapor, null, 1));
console.log(JSON.stringify({ holland: rapor.holland_altigen, essiz: rapor.essiz_profil }));
