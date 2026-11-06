SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;
ATTACH 'differential:lifecycle' AS main_raw (BRANCH 'main');

            SELECT snapshot_id FROM differential_create_snapshot(
                'main_raw', name => 'revised', message => 'one extra row');
        