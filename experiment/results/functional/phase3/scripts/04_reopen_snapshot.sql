SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;

            ATTACH 'differential:lifecycle' AS hist (SNAPSHOT_NAME 'raw-input');
            SELECT id AS snapshot_id, (SELECT count(*) FROM hist.transactions) AS n
            FROM hist.current_snapshot();
        