SET differential_repository = 'experiment/lifecycle/retention/repository';
SET differential_auto_gc = false;

            ATTACH 'differential:retention' AS keeper (BRANCH 'keeper');
            ATTACH 'differential:retention' AS discard (BRANCH 'discard');
            SELECT
                (SELECT count(*) FROM (
                    SELECT * FROM keeper.transactions
                    EXCEPT
                    SELECT * FROM discard.transactions
                )) AS keeper_only,
                (SELECT count(*) FROM (
                    SELECT * FROM discard.transactions
                    EXCEPT
                    SELECT * FROM keeper.transactions
                )) AS discard_only,
                (SELECT md5(string_agg(transaction_id || '|' || customer_id || '|' || CAST(transaction_date AS VARCHAR) || '|' || account_id || '|' || transaction_type || '|' || currency || '|' || printf('%.2f', transaction_amount), chr(10) ORDER BY transaction_id))
                 FROM keeper.transactions) AS keeper_fingerprint,
                (SELECT md5(string_agg(transaction_id || '|' || customer_id || '|' || CAST(transaction_date AS VARCHAR) || '|' || account_id || '|' || transaction_type || '|' || currency || '|' || printf('%.2f', transaction_amount), chr(10) ORDER BY transaction_id))
                 FROM discard.transactions) AS discard_fingerprint,
                (SELECT md5(string_agg(transaction_id || '|' || customer_id || '|' || CAST(transaction_date AS VARCHAR) || '|' || account_id || '|' || transaction_type || '|' || currency || '|' || printf('%.2f', transaction_amount), chr(10) ORDER BY transaction_id))
                 FROM keeper.transactions AT (VERSION => 1)) AS snapshot_fingerprint;
        