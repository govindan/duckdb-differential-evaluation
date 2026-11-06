SET differential_repository = 'experiment/lifecycle/repository';
SET differential_auto_gc = false;

            SELECT database_id FROM differential_databases() WHERE database_name = 'lifecycle';
        