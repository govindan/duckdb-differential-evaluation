SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;

            ATTACH 'differential:lifecycle' AS work (BRANCH 'work');
            SELECT snapshot_id FROM differential_restore(
                'lifecycle', 1, branch => 'work');
        