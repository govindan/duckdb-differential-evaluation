SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;

            ATTACH 'differential:lifecycle' AS main_raw (BRANCH 'main');
            ATTACH 'differential:lifecycle_clone' AS cloned;
            SELECT
                (SELECT count(*) FROM cloned.transactions) AS clone_rows,
                (SELECT count(*) FROM cloned.marker) AS clone_marker,
                (SELECT count(*) FROM main_raw.transactions) AS source_rows,
                (SELECT count(*) FROM main_raw.transactions AT (VERSION => 1)) AS source_snapshot_rows,
                (SELECT count(*) FROM information_schema.tables
                 WHERE table_catalog = 'main_raw' AND table_name = 'marker') AS source_marker;
        