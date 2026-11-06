SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;

            ATTACH 'differential:lifecycle' AS side (BRANCH 'side');
            SELECT snapshot_id FROM differential_create_snapshot('side', name => 'side-v2', message => 'second side row');
        