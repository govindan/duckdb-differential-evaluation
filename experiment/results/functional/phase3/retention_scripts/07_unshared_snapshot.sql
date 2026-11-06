SET differential_repository = 'experiment/lifecycle/retention/repository';
SET differential_auto_gc = false;

            ATTACH 'differential:retention' AS discard (BRANCH 'discard');
            SELECT snapshot_id,
                   (SELECT count(*) FROM discard.bulk WHERE body LIKE 'UNSHARED-%') AS unshared_rows
            FROM differential_create_snapshot('discard', name => 'unshared', message => 'discard-only payload');
        