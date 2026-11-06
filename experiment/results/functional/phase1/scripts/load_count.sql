SET differential_repository = 'experiment/repository';
SET differential_auto_gc = false;
ATTACH 'differential:bank' AS main_raw (BRANCH 'main');

        SELECT count(*) AS loaded_rows, count(DISTINCT transaction_id) AS keys
        FROM main_raw.transactions;
    