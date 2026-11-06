SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;

            SELECT preservation_snapshot_id, snapshot_id, state
            FROM differential_drop_branch('lifecycle', 'drop_me');
        