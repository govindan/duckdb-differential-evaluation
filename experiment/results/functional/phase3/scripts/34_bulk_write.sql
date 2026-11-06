SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;

            ATTACH 'differential:lifecycle' AS garbage (BRANCH 'garbage');
            CREATE TABLE garbage.bulk AS
            SELECT range AS id, repeat('x', 2000) AS body FROM range(3000);
        