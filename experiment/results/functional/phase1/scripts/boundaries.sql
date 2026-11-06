SET differential_repository = 'experiment/repository';
SET differential_auto_gc = false;
ATTACH 'differential:bank' AS main_raw (BRANCH 'main');
ATTACH 'differential:bank' AS baseline (BRANCH 'baseline');
ATTACH 'differential:bank' AS candidate (BRANCH 'candidate');

        SELECT transaction_id, printf('%.2f', transaction_amount) AS transaction_amount,
               classification, 'baseline' AS branch
        FROM baseline.classification
        JOIN baseline.transactions USING (transaction_id)
        WHERE transaction_id IN ('BND-999.99', 'BND-1000.00', 'BND-4999.99', 'BND-5000.00', 'BND-9999.99', 'BND-10000.00')
        UNION ALL
        SELECT transaction_id, printf('%.2f', transaction_amount) AS transaction_amount,
               classification, 'candidate' AS branch
        FROM candidate.classification
        JOIN candidate.transactions USING (transaction_id)
        WHERE transaction_id IN ('BND-999.99', 'BND-1000.00', 'BND-4999.99', 'BND-5000.00', 'BND-9999.99', 'BND-10000.00')
        ORDER BY branch, transaction_id;
    