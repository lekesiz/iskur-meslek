// Gerçek sonuç doğrulaması için SQL üretir. Sorgu prod'da salt-okunur çalışır ve YALNIZ
// toplu metrik döndürür: kişi verisi veritabanından çıkmaz.
//
// Soru: aynı kariyer verisiyle, hangi FORMÜL kullanıcıların favori / öncelik listesine aldığı
// kariyerleri daha üst sıraya koyuyor? Kariyer profilleri olarak katalogdaki kayıtlı profiller
// (careers.riasec_*, bigfive_profile, values_profile) kullanılır; böylece fark yalnız formülden gelir.
//   a_prod  bugünkü formül (server/career-matching-engine.ts; YZ yeniden sıralaması hariç)
//   c_*     çift standartlaştırma (kullanıcı: KULLANICI_NORM, kariyer: katalog dağılımı),
//           farklı blok ağırlıklarıyla
//
//   node gercek_sonuc_sql.mjs > sorgu.sql   (2026-10-10 sonucu: data/iskur-profiles/eslestirme/gercek_sonuc_raporu.json)
import { RIASEC, VALUES, BIGFIVE, KULLANICI_NORM } from "./eslestirme.mjs";

const arr = (xs) => `array[${xs.join(",")}]`;
const userZ = (col, keys, nrm) => `(select array_agg(z - m order by i) from (select i, z, avg(z) over () m from (
      select i, ((${col}->>k)::float8 - mu)/sd z
      from unnest(${arr(keys.map((k) => `'${k}'`))}::text[], ${arr(keys.map((k) => nrm[k][0]))}::float8[], ${arr(keys.map((k) => nrm[k][1]))}::float8[])
        with ordinality t(k, mu, sd, i)) s0) s)`;
const carZ = (col, n) => `(select array_agg(z - m order by i) from (select i, z, avg(z) over () m from (
      select i, (x - mu)/nullif(sd,0) z from unnest(k.${col}, cs.${n}_mu, cs.${n}_sd) with ordinality t(x, mu, sd, i)) s0) s)`;
const stat = (n, D) => `${arr([...Array(D)].map((_, i) => `avg(${n}[${i + 1}])`))} ${n}_mu, ` +
  `${arr([...Array(D)].map((_, i) => `stddev_pop(${n}[${i + 1}])`))} ${n}_sd`;
const unitArr = (e) => `(select array_agg(x/nullif(n,0) order by i) from (select i, x, sqrt(sum(x*x) over ()) n from unnest(${e}) with ordinality t(x,i)) q)`;
const centUnit = (e) => unitArr(`(select array_agg(x - m order by i) from (select i, x, avg(x) over () m from unnest(${e}) with ordinality t(x,i)) q)`);
const dotN = (a, b, D) => [...Array(D)].map((_, i) => `coalesce(${a}[${i + 1}]*${b}[${i + 1}],0)`).join("+");
const euc = (a, b, D) => `sqrt(${[...Array(D)].map((_, i) => `power(${a}[${i + 1}]-${b}[${i + 1}],2)`).join("+")})`;
const mad = (a, b, D) => `(${[...Array(D)].map((_, i) => `abs(${a}[${i + 1}]-${b}[${i + 1}])`).join("+")})/${D}`;

const W = { c_bugunku_agirlik: [0.45, 0.30, 0.25], c_esit: [1 / 3, 1 / 3, 1 / 3], c_riasec_agir: [0.6, 0.2, 0.2],
  c_sadece_riasec: [1, 0, 0], c_kisilik_agir: [0.3, 0.45, 0.25], c_deger_agir: [0.3, 0.25, 0.45] };
const cScore = ([a, b, c]) => `(${a}*(50+50*coalesce(cr,0)) + case when has_b then ${b}*(50+50*coalesce(cb,0)) else 0 end + case when has_v then ${c}*(50+50*coalesce(cv,0)) else 0 end)
    / nullif(${a} + case when has_b then ${b} else 0 end + case when has_v then ${c} else 0 end, 0)`;
const methods = ["a_prod", ...Object.keys(W)];

const sql = `set statement_timeout = '120s';
with kraw as (
  select id,
    ${arr(["r", "i", "a", "s", "e", "c"].map((x) => `riasec_${x}::float8`))} r,
    ${arr(BIGFIVE.map((x) => `(bigfive_profile->>'${x}')::float8`))} b,
    ${arr(VALUES.map((x) => `(values_profile->>'${x}')::float8`))} v
  from public.careers where riasec_r is not null and bigfive_profile is not null and values_profile is not null),
cs as (select ${stat("r", 6)}, ${stat("b", 5)}, ${stat("v", 6)} from kraw),
car as materialized (
  select k.id, ${unitArr(carZ("r", "r"))} zr, ${unitArr(carZ("b", "b"))} zb, ${unitArr(carZ("v", "v"))} zv,
    array(select x/20.0 from unnest(k.r) x) cr_raw, k.b cb_raw, k.v cv_raw,
    ${centUnit("k.r")} pr, ${centUnit("k.b")} pb, ${centUnit("k.v")} pv
  from kraw k cross join cs),
real_users as (select id from public.users where deleted_at is null and coalesce(email,'') not ilike '%@test.reflektif.net'),
outc as materialized (
  select user_id, career_id, 'favori' tur from public.career_favorites
  union select user_id, career_id, 'oncelik' from public.career_priorities
  union select user_id, career_id, 'oncelik_ilgili' from public.career_priorities where status in ('interested','applied','accepted')),
lat as (
  select distinct on (t.user_id, t.test_code) t.user_id, t.test_code, t.raw_scores
  from public.test_results t join real_users ru on ru.id = t.user_id
  where t.completed_at is not null and t.test_code in ('riasec','bigfive','values') and t.user_id in (select user_id from outc)
  order by t.user_id, t.test_code, t.completed_at desc),
u as (
  select user_id,
    (array_agg(raw_scores) filter (where test_code='riasec'))[1] riasec,
    (array_agg(raw_scores) filter (where test_code='bigfive'))[1] bigfive,
    (array_agg(raw_scores) filter (where test_code='values'))[1] vals
  from lat group by user_id),
ua as (
  select user_id, bigfive is not null has_b, vals is not null has_v,
    ${unitArr(userZ("riasec", RIASEC, KULLANICI_NORM.riasec))} zr,
    case when bigfive is not null then ${unitArr(userZ("bigfive", BIGFIVE, KULLANICI_NORM.bigfive))} end zb,
    case when vals is not null then ${unitArr(userZ("vals", VALUES, KULLANICI_NORM.values))} end zv,
    ${arr(RIASEC.map((k) => `least(5,(riasec->>'${k}')::float8/20)`))} ur,
    ${arr(BIGFIVE.map((k) => `(bigfive->>'${k}')::float8`))} ub,
    ${arr(VALUES.map((k) => `(vals->>'${k}')::float8`))} uv
  from u where riasec is not null),
ub as materialized (select ua.*, ${centUnit("ur")} pr, ${centUnit("ub")} pb, ${centUnit("uv")} pv from ua),
pair as (
  select ub.user_id, car.id career_id, has_b, has_v,
    ${dotN("ub.zr", "car.zr", 6)} cr, ${dotN("ub.zb", "car.zb", 5)} cb, ${dotN("ub.zv", "car.zv", 6)} cv,
    round(((${dotN("ub.pr", "car.pr", 6)}+1)/2*0.55 + greatest(0,1-${euc("ub.ur", "car.cr_raw", 6)}/sqrt(150))*0.45)*100) sr,
    round((${dotN("ub.pb", "car.pb", 5)}+1)/2*100*0.5 + greatest(0,100-${mad("ub.ub", "car.cb_raw", 5)}*2)*0.5) sb,
    round((${dotN("ub.pv", "car.pv", 6)}+1)/2*100*0.5 + greatest(0,100-${mad("ub.uv", "car.cv_raw", 6)}*2)*0.5) sv
  from ub cross join car),
sc as (
  select user_id, career_id,
    case when has_b and has_v then round(sr*0.45+sb*0.30+sv*0.25) when has_b then round(sr*0.55+sb*0.45)
         when has_v then round(sr*0.55+sv*0.45) else sr end a_prod,
    ${Object.entries(W).map(([n, w]) => `${cScore(w)} ${n}`).join(",\n    ")}
  from pair),
rk as (
  select user_id, career_id, count(*) over (partition by user_id) n_car,
    ${methods.map((m) => `rank() over (partition by user_id order by ${m} desc) ${m}`).join(",\n    ")}
  from sc),
hit as (select o.tur, r.* from outc o join rk r on r.user_id = o.user_id and r.career_id = o.career_id),
per_user as (
  select tur, user_id, count(*) n_item, max(n_car) n_car,
    ${methods.map((m) => `avg((${m}-1)::float8/(n_car-1)) ${m}_p, avg((${m}<=30)::int) ${m}_t`).join(",\n    ")}
  from hit group by tur, user_id)
select tur, count(*) kullanici, sum(n_item) kariyer, max(n_car) havuz,
  ${methods.map((m) => `round(avg(${m}_p)::numeric,3) ${m}_yuzdelik, round(avg(${m}_t)::numeric,3) ${m}_ilk30`).join(",\n  ")}
from per_user group by tur order by tur;`;
process.stdout.write(sql);
console.error(`sorgu ${(sql.length / 1024).toFixed(1)} KB`);
