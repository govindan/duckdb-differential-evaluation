SET differential_repository = 'experiment/test/phase1';
SET differential_auto_gc = false;
ATTACH 'differential:bank_a' AS main_raw (BRANCH 'main');
ATTACH 'differential:bank_a' AS baseline (BRANCH 'baseline');
ATTACH 'differential:bank_a' AS candidate (BRANCH 'candidate');

        SELECT classification, count(*) AS n
        FROM candidate.classification
        GROUP BY classification
        ORDER BY classification;
    