SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;

            ATTACH 'differential:lifecycle' AS work (BRANCH 'work');
            INSERT INTO work.transactions VALUES
                ('LC-WORK', 'C-WORK', DATE '2024-06-02', 'A-WORK', 'CASH', 'AUD', 2.00);
        