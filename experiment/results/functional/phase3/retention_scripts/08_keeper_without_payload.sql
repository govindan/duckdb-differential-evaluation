SET differential_repository = 'experiment/lifecycle/retention/repository';
SET differential_auto_gc = false;

            ATTACH 'differential:retention' AS keeper (BRANCH 'keeper');
            SELECT
                (SELECT count(*) FROM information_schema.tables
                 WHERE table_catalog = 'keeper' AND table_name = 'bulk') AS keeper_bulk_tables,
                (SELECT md5(string_agg(transaction_id || '|' || customer_id || '|' || CAST(transaction_date AS VARCHAR) || '|' || account_id || '|' || transaction_type || '|' || currency || '|' || printf('%.2f', transaction_amount), chr(10) ORDER BY transaction_id))
                 FROM keeper.transactions) AS keeper_fingerprint;
        