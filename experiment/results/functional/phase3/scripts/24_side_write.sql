SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;

            ATTACH 'differential:lifecycle' AS side (BRANCH 'side');
            INSERT INTO side.transactions VALUES
                ('LC-SIDE', 'C-SIDE', DATE '2024-06-03', 'A-SIDE', 'PAYMENT', 'AUD', 3.00);
        