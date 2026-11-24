# FX and commodity research controls
1. State base/quote convention and currency of portfolio NAV. Convert prices and returns consistently; for CAD per USD, CAD value of a USD asset equals USD value times CAD per USD. Combine asset and FX returns multiplicatively, not by simple addition when precision matters.
2. Identify spot versus futures, contract maturity, quotation unit and settlement calendar. A continuous futures series needs a documented roll rule; a price-only index is not necessarily an investable total return.
3. Distinguish carry, roll yield, spot moves and financing. Do not compare commodity returns with currency returns without aligned horizons, timestamps and costs.
4. Stress asset price and FX jointly and separately. Missing derivatives specifications or basis data require abstention from precise valuation.
5. Log source timestamp, conversion equation, expected sign, exposure, scenario and caveats.
Learning: save validated sign/roll errors and source changes, not price guesses.
Official reference: Bank of Canada Valet https://www.bankofcanada.ca/valet/docs/ ; FRED API https://fred.stlouisfed.org/docs/api/fred/ .
