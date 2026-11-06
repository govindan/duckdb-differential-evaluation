SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;
ATTACH 'differential:lifecycle' AS main_raw (BRANCH 'main');

            SELECT database_id, snapshot_id, state
            FROM differential_clone_database('lifecycle', 'lifecycle_clone', snapshot => 1);
        