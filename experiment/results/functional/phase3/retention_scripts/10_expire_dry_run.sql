SET differential_repository = 'experiment/lifecycle/retention/repository';
SET differential_auto_gc = false;

            SELECT snapshot_id, dry_run FROM differential_expire_snapshots(
                'retention', versions => [2], dry_run => true);
        