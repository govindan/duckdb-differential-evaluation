SET differential_repository = 'experiment/lifecycle/retention/repository';
SET differential_auto_gc = false;

            ATTACH 'differential:retention' AS gone (SNAPSHOT_VERSION 2);
            SELECT count(*) FROM gone.bulk;
        