SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;

            SELECT snapshot_id FROM differential_drop_branch('lone', 'main');
        