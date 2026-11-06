SET differential_repository = 'experiment/test/phase1';
SET differential_auto_gc = false;
ATTACH 'differential:bank_b' AS main_raw (BRANCH 'main');
ATTACH 'differential:bank_b' AS baseline (BRANCH 'baseline');
ATTACH 'differential:bank_b' AS candidate (BRANCH 'candidate');

        SELECT
            (SELECT count(*) FROM differential_branches('bank_b')
             WHERE branch_name IN ('baseline', 'candidate')
               AND source_snapshot_id = 1
               AND head_snapshot_id = 1) AS branches_from_snapshot,
            (SELECT head_snapshot_id FROM differential_branches('bank_b')
             WHERE branch_name = 'main') AS main_head,
            (SELECT count(*) FROM main_raw.transactions) AS main_count,
            (SELECT count(*) FROM baseline.transactions) AS baseline_count,
            (SELECT count(*) FROM candidate.transactions) AS candidate_count,
            (SELECT count(*) - count(DISTINCT transaction_id) FROM main_raw.transactions) AS main_duplicate_keys,
            (SELECT count(*) - count(DISTINCT transaction_id) FROM baseline.transactions) AS baseline_duplicate_keys,
            (SELECT count(*) - count(DISTINCT transaction_id) FROM candidate.transactions) AS candidate_duplicate_keys,
            (SELECT count(*) FROM (SELECT * FROM main_raw.transactions EXCEPT SELECT * FROM baseline.transactions)) AS main_not_baseline,
            (SELECT count(*) FROM (SELECT * FROM baseline.transactions EXCEPT SELECT * FROM main_raw.transactions)) AS baseline_not_main,
            (SELECT count(*) FROM (SELECT * FROM baseline.transactions EXCEPT SELECT * FROM candidate.transactions)) AS baseline_not_candidate,
            (SELECT count(*) FROM (SELECT * FROM candidate.transactions EXCEPT SELECT * FROM baseline.transactions)) AS candidate_not_baseline,
            (SELECT md5(string_agg(transaction_id || '|' || customer_id || '|' || CAST(transaction_date AS VARCHAR) || '|' || account_id || '|' || transaction_type || '|' || currency || '|' || printf('%.2f', transaction_amount), chr(10) ORDER BY transaction_id)) FROM main_raw.transactions) AS main_fingerprint,
            (SELECT md5(string_agg(transaction_id || '|' || customer_id || '|' || CAST(transaction_date AS VARCHAR) || '|' || account_id || '|' || transaction_type || '|' || currency || '|' || printf('%.2f', transaction_amount), chr(10) ORDER BY transaction_id)) FROM baseline.transactions) AS baseline_fingerprint,
            (SELECT md5(string_agg(transaction_id || '|' || customer_id || '|' || CAST(transaction_date AS VARCHAR) || '|' || account_id || '|' || transaction_type || '|' || currency || '|' || printf('%.2f', transaction_amount), chr(10) ORDER BY transaction_id)) FROM candidate.transactions) AS candidate_fingerprint;
    