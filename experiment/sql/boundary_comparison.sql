SELECT
    t.transaction_id,
    printf('%.2f', t.transaction_amount) AS transaction_amount,
    b.classification AS baseline_classification,
    c.classification AS candidate_classification,
    CASE
        WHEN b.classification IS DISTINCT FROM c.classification THEN 'changed'
        ELSE 'unchanged'
    END AS comparison
FROM baseline.transactions t
JOIN baseline.classification b USING (transaction_id)
JOIN candidate.classification c USING (transaction_id)
WHERE t.transaction_id IN (
    'BND-999.99',
    'BND-1000.00',
    'BND-4999.99',
    'BND-5000.00',
    'BND-9999.99',
    'BND-10000.00'
)
ORDER BY t.transaction_amount;
