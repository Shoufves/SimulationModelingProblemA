# Waste fossil CO2 sensitivity evidence

Research date: 2026-10-20. This directory adds evidence only, not production model inputs.

## One bounded scenario range

Recommended combustion sensitivity: **0.1280571429-0.4005 t fossil CO2/MWh of separately declared waste fuel energy**. An optional central scenario is **0.2271272727**, obtained from arithmetic midpoints 347 kg CO2/t waste and 5.5 MJ/kg LHV. The center is a declared scenario choice, not a national mean.

Derivation:

`EF[t CO2/MWh_fuel] = direct_fossil_CO2[kg/t waste] * 0.0036 / LHV[MJ/kg waste]`.

Use Ma's untreated-gas 249-445 kg/t and Bourtsalas's 4-7 MJ/kg. The minimum combines 249/7; maximum combines 445/4. These are **cross-study rectangular bounds**, not observed pairs or a statistical confidence interval. Fossil carbon fraction of flue gas never enters the energy denominator.

## Original sources and exact locations

1. Ma, He, Lu and Zhang (2024), *Improved method for calculating carbon emissions from waste incineration confirmed by 14C testing of flue gas*, DOI 10.1007/s44246-024-00162-9.
   - Original PDF already retained at `../q2_scope_components/ma_2024_radiocarbon.pdf`; original SI DOCX at `../q2_scope_components/ma_2024_supplement.docx`. Both are referenced and hashed in the new manifest without copying.
   - PDF page 7, section 2.6, equation (7): converts dry gas flow, CO2 concentration and fossil CO2 carbon fraction into kg fossil CO2/t waste.
   - PDF page 11, section 3.3, Figure 5b: Method IV untreated gas **249-445 kg CO2-eq/t waste**; Method V treated gas **233-405**. These denote the paper's fossil-CO2 calculation, not avoided-emissions LCA totals. Formula and full page visually checked.
   - PDF page 14 conclusions repeats 249-445. Abstract says 249-446, a one-unit reporting discrepancy; use body/conclusion 445.
   - SI Table S3 reports waste t/day, dry flue-gas flow and CO2 concentrations; S4 reports fossil-carbon fractions and uncertainty inputs. S1 electricity generation is electrical output, not fuel LHV.
   - No calorific/heating value or paired LHV observations were found in the full main paper/SI. Thus Ma alone cannot establish a fuel-energy EF.
   - Coverage: seven plants, eight conditions, samples November 2022-November 2023; five Shanghai plants, one Jiangsu, one Hebei, including co-incinerated material. Not a national annual 2014-2024 sequence.
2. Bourtsalas, Huang, Zhang and Themelis (2020), *Energy recovery in China from solid wastes by the moving grate and circulating fluidized bed technologies*, DOI 10.1007/s42768-019-00026-8.
   - `bourtsalas_2020_publisher.html`, publisher's original article page; **Abstract, first paragraph**, LHV **4-7 MJ/kg** for Chinese MSW.
   - Comparative research using operating industrial plants and literature. Abstract says moving-grate furnace fuel is as-received MSW, CFB feed is pre-shredded. This is not a nationally weighted annual measured range and is not paired with Ma's waste samples.
   - Published 2020-01-29. The publisher's abstract is publicly accessible; this is an original publisher HTML, not an acquired full-paper PDF.
   - `bourtsalas_2021_correction_publisher.html` preserves the linked correction, titled *Correction to: Missing Conflict of Interest statements in previously published articles*, DOI 10.1007/s42768-021-00078-9. The accessible correction page provides its title and publication metadata; the body is subscription-only.

Source URLs:

- https://link.springer.com/article/10.1007/s44246-024-00162-9
- https://link.springer.com/article/10.1007/s42768-019-00026-8
- https://link.springer.com/article/10.1007/s42768-021-00078-9

## Boundary restrictions

- Apply only to waste fuel, with a separately stated allocation from biomass/Other. Do not apply to all biomass, recovered industrial heat, pumped storage, or a statistical residual.
- No claim that a flue-gas fossil-carbon percentage is an energy or generation percentage.
- Untreated-gas combustion and treated-stack emissions differ. If an explicit cleanup carbon-transfer account is implemented, Ma's treated-gas range gives an alternate 0.1198285714-0.3645 t/MWh_fuel. Do not deduct this difference silently.
- This is direct fossil CO2 only. Biogenic CO2, upstream auxiliaries and avoided grid emissions are outside this EF.
- No use as a historical calibration target or national empirical observation. Cross-study fuel basis and missing paired moisture/LHV data remain material limitations.

## Reproduction and unsuccessful retrieval

Run `tmp/q2-venv/Scripts/python.exe -B data/raw/q2_waste_fossil_ef/research.py` from repository root to rebuild the hashes, extracted publisher text and `sensitivity_range.json`. It runs offline and modifies only this evidence directory.

An official Chongqing 2025 EIA search result mentions measured 2023-2024 wet-basis LHV values 6377, 6584, 5472 and 8736 kJ/kg for a neighbouring project. Its PDF fetch returned HTTP 404 / search-service timeout, so no original was obtained and **none of these numbers is admitted to the recommended range**. Attempted URL: https://sthjj.cq.gov.cn/zwgk_249/zfxxgkzl/fdzdgknr/hjyxpj/pzgcxx/sljsxmhpxxgg/202509/P020250922527036468770.pdf .
