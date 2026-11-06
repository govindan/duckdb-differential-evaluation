SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;
ATTACH 'differential:lifecycle' AS main_raw (BRANCH 'main');

            SELECT
                (SELECT count(*) FROM main_raw.transactions) AS live_rows,
                (SELECT count(*) FROM main_raw.transactions AT (VERSION => 1)) AS version_raw,
                (SELECT count(*) FROM main_raw.transactions AT (VERSION => 2)) AS version_revised;
        