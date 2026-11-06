SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;

            ATTACH 'differential:lifecycle' AS side (BRANCH 'side');
            INSERT INTO side.transactions VALUES
                ('LC-SIDE-2', 'C-SIDE', DATE '2024-06-04', 'A-SIDE', 'PAYMENT', 'AUD', 4.00);
        