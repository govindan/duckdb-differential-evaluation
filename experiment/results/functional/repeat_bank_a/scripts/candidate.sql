SET differential_repository = 'experiment/test/phase1';
SET differential_auto_gc = false;
ATTACH 'differential:bank_a' AS main_raw (BRANCH 'main');
ATTACH 'differential:bank_a' AS baseline (BRANCH 'baseline');
ATTACH 'differential:bank_a' AS candidate (BRANCH 'candidate');
CREATE TABLE candidate.classification AS
SELECT
    transaction_id,
    CASE
        WHEN transaction_amount < 1000 THEN 'LOW'
        WHEN transaction_amount >= 1000 AND transaction_amount < 5000 THEN 'MEDIUM'
        ELSE 'HIGH'
    END AS classification
FROM candidate.transactions;
