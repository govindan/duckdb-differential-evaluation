SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;

            ATTACH 'differential:lifecycle' AS main_raw (BRANCH 'main');
            ATTACH 'differential:lifecycle_clone' AS cloned;
            SELECT
                (SELECT count(*) FROM main_raw.transactions) AS main_rows,
                (SELECT count(*) FROM main_raw.transactions AT (VERSION => 1)) AS snapshot_rows,
                (SELECT count(*) FROM cloned.marker) AS clone_marker;
        