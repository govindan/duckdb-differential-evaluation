SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;
ATTACH 'differential:lifecycle' AS main_raw (BRANCH 'main');

            SELECT snapshot_id, state FROM differential_create_snapshot(
                'main_raw', name => 'raw-input', message => 'lifecycle raw input');
        