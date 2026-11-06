SET differential_repository = 'experiment/repository';
SET differential_auto_gc = false;
ATTACH 'differential:bank' AS main_raw (BRANCH 'main');
ATTACH 'differential:bank' AS baseline (BRANCH 'baseline');
ATTACH 'differential:bank' AS candidate (BRANCH 'candidate');
CREATE TABLE baseline.classification AS
SELECT
    transaction_id,
    CASE
        WHEN transaction_amount < 1000 THEN 'LOW'
        WHEN transaction_amount >= 1000 AND transaction_amount < 5000 THEN 'MEDIUM'
        WHEN transaction_amount >= 5000 AND transaction_amount < 10000 THEN 'MEDIUM'
        ELSE 'HIGH'
    END AS classification
FROM baseline.transactions;
