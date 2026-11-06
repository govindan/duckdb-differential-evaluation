SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;

            ATTACH 'differential:lifecycle' AS garbage (BRANCH 'garbage');
            SELECT snapshot_id, (SELECT count(*) FROM garbage.bulk) AS bulk_rows
            FROM differential_create_snapshot('garbage', name => 'bulk', message => 'unshared payload');
        