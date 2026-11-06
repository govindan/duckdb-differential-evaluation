CREATE TABLE candidate.classification AS
SELECT
    transaction_id,
    CASE
        WHEN transaction_amount < 1000 THEN 'LOW'
        WHEN transaction_amount >= 1000 AND transaction_amount < 5000 THEN 'MEDIUM'
        ELSE 'HIGH'
    END AS classification
FROM candidate.transactions;
