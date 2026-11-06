SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;

            ATTACH 'differential:lifecycle' AS side (BRANCH 'side');
            SELECT count(*) FROM side.transactions AT (VERSION => 5);
        