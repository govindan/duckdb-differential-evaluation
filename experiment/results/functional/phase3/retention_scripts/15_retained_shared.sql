SET differential_repository = 'experiment/lifecycle/retention/repository';
SET differential_auto_gc = false;

            ATTACH 'differential:retention' AS keeper (BRANCH 'keeper');
            SELECT
                (SELECT count(*) FROM keeper.transactions) AS keeper_rows,
                (SELECT count(*) FROM (
                    SELECT * FROM keeper.transactions
                    EXCEPT
                    SELECT * FROM keeper.transactions AT (VERSION => 1)
                )) AS keeper_not_snapshot,
                (SELECT count(*) FROM (
                    SELECT * FROM keeper.transactions AT (VERSION => 1)
                    EXCEPT
                    SELECT * FROM keeper.transactions
                )) AS snapshot_not_keeper,
                (SELECT md5(string_agg(transaction_id || '|' || customer_id || '|' || CAST(transaction_date AS VARCHAR) || '|' || account_id || '|' || transaction_type || '|' || currency || '|' || printf('%.2f', transaction_amount), chr(10) ORDER BY transaction_id))
                 FROM keeper.transactions) AS keeper_fingerprint,
                (SELECT md5(string_agg(transaction_id || '|' || customer_id || '|' || CAST(transaction_date AS VARCHAR) || '|' || account_id || '|' || transaction_type || '|' || currency || '|' || printf('%.2f', transaction_amount), chr(10) ORDER BY transaction_id))
                 FROM keeper.transactions AT (VERSION => 1)) AS snapshot_fingerprint,
                (SELECT count(*) FROM information_schema.tables
                 WHERE table_catalog = 'keeper' AND table_name = 'bulk') AS keeper_bulk_tables;
        