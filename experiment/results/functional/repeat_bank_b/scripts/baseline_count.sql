SET differential_repository = 'experiment/test/phase1';
SET differential_auto_gc = false;
ATTACH 'differential:bank_b' AS main_raw (BRANCH 'main');
ATTACH 'differential:bank_b' AS baseline (BRANCH 'baseline');
ATTACH 'differential:bank_b' AS candidate (BRANCH 'candidate');

        SELECT count(*) AS classified_rows,
               count(*) - count(DISTINCT transaction_id) AS duplicate_keys,
               count(*) - count(classification) AS null_classifications,
               md5(string_agg(transaction_id || '|' || classification, chr(10) ORDER BY transaction_id)) AS fingerprint
        FROM baseline.classification;
    