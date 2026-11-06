SELECT
    b.classification AS baseline_classification,
    c.classification AS candidate_classification,
    count(*) AS records
FROM baseline.classification b
FULL OUTER JOIN candidate.classification c
    ON b.transaction_id = c.transaction_id
GROUP BY 1, 2
ORDER BY 1, 2;
