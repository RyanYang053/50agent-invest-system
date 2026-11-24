# Rates and credit analysis
1. Fix currency, observation date, maturity and quotation convention. Separate policy rate, sovereign nominal yield, real yield and corporate credit spread. Never merge yields with different duration or instrument definitions without documenting the mismatch.
2. Build a curve table, compute slope in basis points and decompose a rate move into nominal yield and observed inflation-compensation proxy where comparable. Inflation compensation is not a pure inflation forecast.
3. Estimate first-order bond sensitivity using modified duration; for material changes request convexity and instrument cash flows. For credit, report spread duration separately and consider default/recovery risk.
4. Provide alternative explanations for steepening and flattening; policy expectations, term premium and liquidity need not move together. Preserve an unknown category when decomposition is not identifiable.
5. For replay require actual release availability and a vintage query. Compare results with a later revision only as a separate sensitivity.
Acceptance: unit and tenor match, signed basis-point changes, date alignment, missing inputs block precision. Learning: record independent forecast errors by horizon and yield tenor.
Official reference: ALFRED https://fred.stlouisfed.org/docs/api/fred/alfred.html ; Bank of Canada Valet https://www.bankofcanada.ca/valet/docs/ .
