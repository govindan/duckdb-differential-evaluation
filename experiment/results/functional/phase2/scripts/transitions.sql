SET differential_repository = 'experiment/repository';
SET differential_auto_gc = false;
ATTACH 'differential:bank' AS main_raw (BRANCH 'main');
ATTACH 'differential:bank' AS baseline (BRANCH 'baseline');
ATTACH 'differential:bank' AS candidate (BRANCH 'candidate');
SELECT
    b.classification AS baseline_classification,
    c.classification AS candidate_classification,
    count(*) AS records
FROM baseline.classification b
FULL OUTER JOIN candidate.classification c
    ON b.transaction_id = c.transaction_id
GROUP BY 1, 2
ORDER BY 1, 2;
