SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;

            ATTACH 'differential:lifecycle' AS gone (BRANCH 'drop_me');
        