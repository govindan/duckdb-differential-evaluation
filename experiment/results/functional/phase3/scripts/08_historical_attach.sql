SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;

            ATTACH 'differential:lifecycle' AS old (SNAPSHOT_VERSION 1);
            ATTACH 'differential:lifecycle' AS revised (SNAPSHOT_VERSION 2);
            SELECT
                (SELECT count(*) FROM old.transactions) AS old_rows,
                (SELECT count(*) FROM revised.transactions) AS revised_rows;
        