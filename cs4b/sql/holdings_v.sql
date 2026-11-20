DROP VIEW IF EXISTS holdings_v;

-- holdings_v: the one view the model reads (Lab 32B).
-- One row per CURRENT-period holding. The BDC name comes from filings, joined on adsh
-- (the accession number), so each holding is matched to exactly one filing.
-- price   = 100 * fair_value / principal for debt (principal > 0), NULL otherwise.
-- is_debt = 1 where principal > 0, else 0 (never NULL).
CREATE VIEW holdings_v AS
SELECT
    h.adsh                                   AS adsh,
    f.name                                   AS bdc,
    f.form                                   AS form,
    f.period                                 AS period,
    h.identifier                             AS identifier,
    h.investment_type                        AS investment_type,
    h.industry                               AS industry,
    h.fair_value                             AS fair_value,
    h.cost                                   AS cost,
    h.principal                              AS principal,
    CASE WHEN h.principal > 0
         THEN ROUND(100.0 * h.fair_value / h.principal, 4)
         ELSE NULL END                       AS price,
    h.pik_rate                               AS pik_rate,
    h.interest_rate                          AS interest_rate,
    h.spread                                 AS spread,
    h.maturity                               AS maturity,
    CASE WHEN h.principal > 0 THEN 1 ELSE 0 END AS is_debt
FROM holdings AS h
JOIN filings  AS f ON f.adsh = h.adsh
WHERE h.period_role = 'current';
