SET differential_repository = 'experiment/repository';
SET differential_auto_gc = false;
ATTACH 'differential:bank' AS main_raw (BRANCH 'main');
ATTACH 'differential:bank' AS baseline (BRANCH 'baseline');
ATTACH 'differential:bank' AS candidate (BRANCH 'candidate');

        SELECT table_catalog, column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'classification'
          AND table_catalog IN ('baseline', 'candidate')
        ORDER BY table_catalog, ordinal_position;
    