SET differential_repository = 'experiment/repository';
SET differential_auto_gc = false;
ATTACH 'differential:bank' AS main_raw (BRANCH 'main');
ATTACH 'differential:bank' AS baseline (BRANCH 'baseline');
ATTACH 'differential:bank' AS candidate (BRANCH 'candidate');
WITH compared AS (
    SELECT
        b.transaction_id AS baseline_id,
        c.transaction_id AS candidate_id,
        b.classification AS baseline_classification,
        c.classification AS candidate_classification,
        bt.transaction_amount AS baseline_amount,
        ct.transaction_amount AS candidate_amount
    FROM baseline.classification b
    FULL OUTER JOIN candidate.classification c
        ON b.transaction_id = c.transaction_id
    LEFT JOIN baseline.transactions bt
        ON bt.transaction_id = b.transaction_id
    LEFT JOIN candidate.transactions ct
        ON ct.transaction_id = c.transaction_id
)
SELECT
    count(*) AS joined_rows,
    count(*) FILTER (WHERE baseline_id IS NOT NULL) AS baseline_rows,
    count(*) FILTER (WHERE candidate_id IS NOT NULL) AS candidate_rows,
    count(*) FILTER (WHERE baseline_id IS NULL AND candidate_id IS NOT NULL) AS added_records,
    count(*) FILTER (WHERE baseline_id IS NOT NULL AND candidate_id IS NULL) AS missing_records,
    count(*) FILTER (
        WHERE baseline_id IS NOT NULL
          AND candidate_id IS NOT NULL
          AND baseline_classification IS DISTINCT FROM candidate_classification
    ) AS changed_records,
    count(*) FILTER (
        WHERE baseline_id IS NOT NULL
          AND candidate_id IS NOT NULL
          AND baseline_classification IS NOT DISTINCT FROM candidate_classification
    ) AS unchanged_records,
    (SELECT count(*) - count(DISTINCT transaction_id) FROM baseline.classification) AS baseline_duplicate_keys,
    (SELECT count(*) - count(DISTINCT transaction_id) FROM candidate.classification) AS candidate_duplicate_keys,
    count(*) FILTER (
        WHERE baseline_id IS NOT NULL
          AND candidate_id IS NOT NULL
          AND baseline_amount IS DISTINCT FROM candidate_amount
    ) AS amount_mismatches,
    count(*) FILTER (
        WHERE baseline_id IS NOT NULL
          AND candidate_id IS NOT NULL
          AND baseline_amount >= 5000
          AND baseline_amount < 10000
    ) AS rows_in_changed_band,
    count(*) FILTER (
        WHERE baseline_id IS NOT NULL
          AND candidate_id IS NOT NULL
          AND baseline_classification IS DISTINCT FROM candidate_classification
          AND baseline_amount >= 5000
          AND baseline_amount < 10000
          AND baseline_classification = 'MEDIUM'
          AND candidate_classification = 'HIGH'
    ) AS medium_to_high_in_band,
    count(*) FILTER (
        WHERE baseline_id IS NOT NULL
          AND candidate_id IS NOT NULL
          AND baseline_classification IS DISTINCT FROM candidate_classification
          AND NOT (baseline_amount >= 5000 AND baseline_amount < 10000)
    ) AS changed_outside_band,
    count(*) FILTER (
        WHERE baseline_id IS NOT NULL
          AND candidate_id IS NOT NULL
          AND baseline_classification IS DISTINCT FROM candidate_classification
          AND NOT (baseline_classification = 'MEDIUM' AND candidate_classification = 'HIGH')
    ) AS changed_other_transition
FROM compared;
