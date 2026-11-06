SET differential_repository = 'experiment/test/phase1';
SET differential_auto_gc = false;
ATTACH 'differential:bank_a' AS main_raw (BRANCH 'main');
ATTACH 'differential:bank_a' AS baseline (BRANCH 'baseline');
ATTACH 'differential:bank_a' AS candidate (BRANCH 'candidate');

        SELECT
            (SELECT count(*) FROM information_schema.tables
             WHERE table_catalog = 'main_raw' AND table_name = 'classification') AS main_classification_tables,
            (SELECT count(*) FROM information_schema.tables
             WHERE table_catalog = 'baseline' AND table_name = 'classification') AS baseline_classification_tables,
            (SELECT count(*) FROM information_schema.tables
             WHERE table_catalog = 'candidate' AND table_name = 'classification') AS candidate_classification_tables,
            (SELECT count(*) FROM information_schema.columns
             WHERE table_catalog = 'main_raw' AND table_name = 'transactions'
               AND column_name = 'classification') AS main_classification_columns,
            (SELECT count(*) FROM baseline.classification) AS baseline_classified_rows,
            (SELECT count(*) FROM candidate.classification) AS candidate_classified_rows,
            (SELECT md5(string_agg(transaction_id || '|' || classification, chr(10) ORDER BY transaction_id))
             FROM baseline.classification) AS baseline_fingerprint,
            (SELECT md5(string_agg(transaction_id || '|' || classification, chr(10) ORDER BY transaction_id))
             FROM candidate.classification) AS candidate_fingerprint,
            (SELECT md5(string_agg(transaction_id || '|' || customer_id || '|' || CAST(transaction_date AS VARCHAR) || '|' || account_id || '|' || transaction_type || '|' || currency || '|' || printf('%.2f', transaction_amount), chr(10) ORDER BY transaction_id))
             FROM main_raw.transactions) AS main_raw_fingerprint,
            (SELECT md5(string_agg(transaction_id || '|' || customer_id || '|' || CAST(transaction_date AS VARCHAR) || '|' || account_id || '|' || transaction_type || '|' || currency || '|' || printf('%.2f', transaction_amount), chr(10) ORDER BY transaction_id))
             FROM baseline.transactions) AS baseline_raw_fingerprint,
            (SELECT md5(string_agg(transaction_id || '|' || customer_id || '|' || CAST(transaction_date AS VARCHAR) || '|' || account_id || '|' || transaction_type || '|' || currency || '|' || printf('%.2f', transaction_amount), chr(10) ORDER BY transaction_id))
             FROM candidate.transactions) AS candidate_raw_fingerprint,
            (SELECT count(*) FROM (SELECT * FROM main_raw.transactions EXCEPT SELECT * FROM baseline.transactions)) AS main_not_baseline,
            (SELECT count(*) FROM (SELECT * FROM baseline.transactions EXCEPT SELECT * FROM candidate.transactions)) AS baseline_not_candidate;
    