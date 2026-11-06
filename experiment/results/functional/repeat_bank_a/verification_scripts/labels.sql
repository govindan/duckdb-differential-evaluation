SET differential_repository = 'experiment/test/phase1';
SET differential_auto_gc = false;
ATTACH 'differential:bank_a' AS main_raw (BRANCH 'main');
ATTACH 'differential:bank_a' AS baseline (BRANCH 'baseline');
ATTACH 'differential:bank_a' AS candidate (BRANCH 'candidate');

        SELECT 'baseline' AS branch, transaction_id, classification
        FROM baseline.classification
        UNION ALL
        SELECT 'candidate', transaction_id, classification
        FROM candidate.classification
        ORDER BY branch, transaction_id;
    