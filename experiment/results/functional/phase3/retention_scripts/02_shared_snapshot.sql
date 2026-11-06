SET differential_repository = 'experiment/lifecycle/retention/repository';
SET differential_auto_gc = false;

            ATTACH 'differential:retention' AS main_raw (BRANCH 'main');
            SELECT snapshot_id FROM differential_create_snapshot(
                'main_raw', name => 'shared-base', message => 'shared retention base');
        