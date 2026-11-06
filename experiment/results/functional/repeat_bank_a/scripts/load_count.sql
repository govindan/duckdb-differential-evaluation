SET differential_repository = 'experiment/test/phase1';
SET differential_auto_gc = false;
ATTACH 'differential:bank_a' AS main_raw (BRANCH 'main');

        SELECT count(*) AS loaded_rows, count(DISTINCT transaction_id) AS keys
        FROM main_raw.transactions;
    