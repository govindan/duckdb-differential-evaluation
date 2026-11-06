SET differential_repository = 'experiment/test/phase1';
SET differential_auto_gc = false;
ATTACH 'differential:bank_b' AS main_raw (BRANCH 'main');
ATTACH 'differential:bank_b' AS baseline (BRANCH 'baseline');
ATTACH 'differential:bank_b' AS candidate (BRANCH 'candidate');

        SELECT branch, transaction_id, customer_id, transaction_date, account_id,
               transaction_type, currency, transaction_amount
        FROM (
            SELECT 'main' AS branch, transaction_id, customer_id,
                   CAST(transaction_date AS VARCHAR) AS transaction_date,
                   account_id, transaction_type, currency,
                   printf('%.2f', transaction_amount) AS transaction_amount
            FROM main_raw.transactions
            UNION ALL
            SELECT 'baseline', transaction_id, customer_id,
                   CAST(transaction_date AS VARCHAR),
                   account_id, transaction_type, currency,
                   printf('%.2f', transaction_amount)
            FROM baseline.transactions
            UNION ALL
            SELECT 'candidate', transaction_id, customer_id,
                   CAST(transaction_date AS VARCHAR),
                   account_id, transaction_type, currency,
                   printf('%.2f', transaction_amount)
            FROM candidate.transactions
        )
        ORDER BY branch, transaction_id;
    