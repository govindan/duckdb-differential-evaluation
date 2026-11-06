SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;

            SELECT snapshot_id, dry_run FROM differential_expire_snapshots(
                'lifecycle', versions => [5], dry_run => true);
        