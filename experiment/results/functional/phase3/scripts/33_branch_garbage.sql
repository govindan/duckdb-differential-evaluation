SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;
ATTACH 'differential:lifecycle' AS main_raw (BRANCH 'main');

            SELECT branch_id FROM differential_create_branch(
                'lifecycle', 'garbage', snapshot => 1);
        