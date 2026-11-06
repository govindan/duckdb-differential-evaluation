SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;

            SELECT retired FROM differential_snapshots('lifecycle')
            WHERE snapshot_id = 5;
        