SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;
ATTACH 'differential:lifecycle' AS main_raw (BRANCH 'main');

            INSERT INTO main_raw.transactions VALUES
                ('LC-EXTRA', 'C-EXTRA', DATE '2024-06-01', 'A-EXTRA', 'CARD', 'AUD', 1.00);
        