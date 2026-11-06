SET differential_repository = 'experiment/repository';
SET differential_auto_gc = false;
ATTACH 'differential:bank' AS main_raw (BRANCH 'main');
ATTACH 'differential:bank' AS baseline (BRANCH 'baseline');
ATTACH 'differential:bank' AS candidate (BRANCH 'candidate');

        SELECT 'baseline' AS branch, transaction_id, classification
        FROM baseline.classification
        UNION ALL
        SELECT 'candidate', transaction_id, classification
        FROM candidate.classification
        ORDER BY branch, transaction_id;
    