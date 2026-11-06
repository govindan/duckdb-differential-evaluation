SET differential_repository = 'experiment/lifecycle/retention/repository';
SET differential_auto_gc = false;

            ATTACH 'differential:retention' AS discard (BRANCH 'discard');
            CREATE TABLE discard.bulk AS
            SELECT range AS id, 'UNSHARED-' || repeat('x', 2000) AS body
            FROM range(3000);
        