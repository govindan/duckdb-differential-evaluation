SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;

            ATTACH 'differential:lifecycle' AS side (BRANCH 'side');
            SELECT
                (SELECT count(*) FROM side.transactions) AS live_rows,
                (SELECT count(*) FROM side.transactions AT (VERSION => 6)) AS head_rows;
        