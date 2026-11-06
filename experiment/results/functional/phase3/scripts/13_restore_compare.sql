SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;

            ATTACH 'differential:lifecycle' AS work (BRANCH 'work');
            ATTACH 'differential:lifecycle' AS raw (SNAPSHOT_VERSION 1);
            SELECT
                (SELECT count(*) FROM work.transactions) AS restored_rows,
                (SELECT count(*) FROM (
                    SELECT * FROM work.transactions
                    EXCEPT
                    SELECT * FROM raw.transactions
                )) AS restored_not_snapshot,
                (SELECT count(*) FROM (
                    SELECT * FROM raw.transactions
                    EXCEPT
                    SELECT * FROM work.transactions
                )) AS snapshot_not_restored;
        