SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;

            SELECT state FROM differential_branches('lone') WHERE branch_name = 'main';
        