# Decision: consume the dated CEX reference companion

HT-005 extends the accepted direct reader with a separately pinned contract-history JSON
produced by CMB's existing reference layer (ADR-0041). Bind it to the exact market release
and require explicit retrospective knowledge time. No CMB Python imports or SQLite access.

Raw observations remain readable for every product and symbol. A history-aware projection
uses separate canonical instruments for relaunches and reused tickers; rejects unknown,
restricted, closed or boundary-crossing hourly bars; and preserves funding rates without
claiming they are payable cashflows. These checks express reviewed-notice assumptions,
not complete contract specifications or historical source availability. Unqualified HT-004
transport stays explicitly event-time-only when no companion is supplied.
