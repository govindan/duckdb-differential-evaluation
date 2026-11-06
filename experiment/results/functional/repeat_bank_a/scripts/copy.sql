SET differential_repository = 'experiment/test/phase1';
SET differential_auto_gc = false;
ATTACH 'differential:bank_a' AS main_raw (BRANCH 'main');
COPY main_raw.transactions FROM 'experiment/test/bank_a.csv' (HEADER true);
