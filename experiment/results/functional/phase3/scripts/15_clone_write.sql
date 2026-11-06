SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;

            ATTACH 'differential:lifecycle_clone' AS cloned;
            CREATE TABLE cloned.marker AS SELECT 1 AS id;
        