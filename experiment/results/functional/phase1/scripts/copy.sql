SET differential_repository = 'experiment/repository';
SET differential_auto_gc = false;
ATTACH 'differential:bank' AS main_raw (BRANCH 'main');
COPY main_raw.transactions FROM 'experiment/data/transactions.csv' (HEADER true);
