SET differential_repository = 'experiment/repository';
SET differential_auto_gc = false;
ATTACH 'differential:bank' AS main_raw (BRANCH 'main');
ATTACH 'differential:bank' AS baseline (BRANCH 'baseline');
ATTACH 'differential:bank' AS candidate (BRANCH 'candidate');

        SELECT branch_name, source_snapshot_id
        FROM differential_branches('bank')
        WHERE branch_name IN ('baseline', 'candidate')
        ORDER BY branch_name;
    