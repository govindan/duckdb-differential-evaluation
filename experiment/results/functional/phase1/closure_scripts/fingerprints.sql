SET differential_repository = 'experiment/repository';
SET differential_auto_gc = false;
ATTACH 'differential:bank' AS main_raw (BRANCH 'main');
ATTACH 'differential:bank' AS baseline (BRANCH 'baseline');
ATTACH 'differential:bank' AS candidate (BRANCH 'candidate');

        SELECT
            (SELECT md5(string_agg(transaction_id || '|' || classification, chr(10) ORDER BY transaction_id))
             FROM baseline.classification) AS baseline_output_after,
            (SELECT count(*) FROM baseline.classification) AS baseline_output_rows,
            (SELECT md5(string_agg(transaction_id || '|' || customer_id || '|' || CAST(transaction_date AS VARCHAR) || '|' || account_id || '|' || transaction_type || '|' || currency || '|' || printf('%.2f', transaction_amount), chr(10) ORDER BY transaction_id))
             FROM main_raw.transactions) AS main_raw_after,
            (SELECT md5(string_agg(transaction_id || '|' || customer_id || '|' || CAST(transaction_date AS VARCHAR) || '|' || account_id || '|' || transaction_type || '|' || currency || '|' || printf('%.2f', transaction_amount), chr(10) ORDER BY transaction_id))
             FROM baseline.transactions) AS baseline_raw_after,
            (SELECT md5(string_agg(transaction_id || '|' || customer_id || '|' || CAST(transaction_date AS VARCHAR) || '|' || account_id || '|' || transaction_type || '|' || currency || '|' || printf('%.2f', transaction_amount), chr(10) ORDER BY transaction_id))
             FROM candidate.transactions) AS candidate_raw_after,
            (SELECT md5(string_agg(transaction_id || '|' || customer_id || '|' || CAST(transaction_date AS VARCHAR) || '|' || account_id || '|' || transaction_type || '|' || currency || '|' || printf('%.2f', transaction_amount), chr(10) ORDER BY transaction_id))
             FROM main_raw.transactions AT (VERSION => 1)) AS snapshot_raw_after;
    