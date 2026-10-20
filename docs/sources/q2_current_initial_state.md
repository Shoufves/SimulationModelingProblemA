# Independent observed end-2024 initial state

This version is a new initial condition for projections from 2025. It does not
alter the 2014 historical experiment, erase its capacity error, or claim that a
matching opening stock validates historical investment behavior.

`scripts/q2_current_factory.py` uses the same reviewed EI generation vintage and
national observation table. Exact 2024 broad capacity totals are preserved:
hydro includes 58,690 MW of pumped storage, while the primary hydro generator
excludes that storage power. Nuclear, wind and solar match the observed stock.
Coal 1,190,000 MW and gas 140,000 MW are rounded CEC report anchors, not exact
subtechnology census values. Biomass uses CEC 45,970 MW; oil holds the explicitly
uncertain 2014 5,116 MW anchor. The remaining thermal stock plus statistical Other
stock is declared inactive, not silently productive coal.

The original pre-2015 capacity reconstruction is retained. For 2015–2024 broad
stocks use contemporaneous national observations; thermal subtype shares and
pumped stock interpolate between disclosed 2014 and 2024 endpoints. These are
age-reconstruction inputs, not observed subtype histories. The core reconstructs
2009 residual ages, positive annual increments and retirement, then normalizes
survivors to the 2024 snapshot. Unknown gross retirements and actual plant ages
remain limitations. An explicit age multiplier supplies sensitivity.

Other generation is not silently added to coal. Pumped output is a declared
utilisation sensitivity whose base matches the archived 65.7 TWh 2024 observation
(HydroChina report PDF page 26, independently viewed). Its CF is
65.7e6/(58,690*8,760). Assigning this output to the EI Other residual remains a
conditional classification bridge, not an observed identity. Infeasible bridge
settings are rejected. Pumping input uses an assumed 0.8 round-trip efficiency;
it is not observed annual pumping. Remaining Other is a statistical adjustment.
Recovered industrial heat is zero in this opening.
Pumped physical energy, power and initial SOC are accounted separately.

Opening construction is independently inferred from 2021–2024 mean net capacity
growth and the technology lead time. Each initial queue entry has opening work
in progress, a paid fraction and a restricted escrow balance. A queue multiplier
includes a zero-queue sensitivity. This is not a measured project register.
2024 capacity and recent additions seed future construction capability. The
construction proxy is then rebased to CEC 2024 gross commissioned MW: coal
33,100, gas 18,300, conventional hydro 6,260 (13,790 less pumped 7,530), nuclear
3,930, wind 81,370, and solar approximately 280,000. This is a scale proxy, not
an observation of maximum attainable construction capability. It avoids
multiplying the old solar response 2.5 into the much larger 2024 stock and
creating an unsupported opening ceiling around 776 GW/year. The original GDP
response and prospective decaying solar expansion rule remain conditional
behavioral assumptions; the 2014 historical manufacturing expansion is not
compounded again through 2024. Biomass and oil retain their original explicit
construction assumptions where no comparable gross commissioning row is used.

All productive plant book values, work in progress, restricted escrow,
unrestricted cash, subsidy receivables, lender debt and residual shareholder
equity appear in `model.opening_balance_sheet`. Base debt is 50% of plant book
value plus committed construction and escrow. Cash is 10% of gross current
replacement cost. These are financial priors, not measured national accounts.
Loans begin scheduled service in 2025; no opening asset is a 2025 windfall
income. They are owned opening balance-sheet stocks. The explicit debt, cash and
queue options allow alternative financial openings with identical observed
physical capacity. Consumer, grid and supplemental asset opening finance retain
the model's declared reconstruction rules; the generator sheet is not an
all-sector consolidated national balance sheet.

Subsidy opening meters are reconstructed through 2024 by allocating observed
annual wind, solar and biomass generation across reconstructed cohorts alive in
each year, with midyear online exposure and station export fractions. Production
before available data is explicitly approximated using the opening reference
capacity factor. Lifetime meters include pre-2015 production and are never reset
at 2024. Lower-zone lifetime caps apply from the opening. Cohorts commissioned
from 2021 receive no new wind/solar eligibility. This is a grandfathering proxy:
actual approval dates and qualifying project directories are unavailable.

A separate finite fund replays 2015–2024 published annual receipts and expenditure
limits against these reconstructed claims. Its closing cash and unpaid claims
form the opening fund and receivables; they are neither observed national arrears
nor spendable sponsor cash. An arrears multiplier is disclosed separately.
Municipal opening arrears are assumed zero. Existing biomass composition and
finite waste delivery assumptions restart from observed 2024 biomass output;
post-2024 delivery remains a bounded scenario, not a future observation.

All training parameters remain frozen. No 2030 target, future realised outcome,
or 2025–2060 policy ranking selects this opening. Forecast conclusions must be
reported conditional on financial, age, queue, eligibility and Other-boundary
priors, alongside the historical model's separate fit diagnosis.
