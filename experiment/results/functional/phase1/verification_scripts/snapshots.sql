SET differential_repository = 'experiment/repository';
SET differential_auto_gc = false;

        SELECT snapshot_id, snapshot_name, snapshot_time, retired, branch_id, database_id
        FROM differential_snapshots('bank')
        ORDER BY snapshot_id;
    