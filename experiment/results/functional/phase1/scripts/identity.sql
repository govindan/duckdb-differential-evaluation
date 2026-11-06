SET differential_repository = 'experiment/repository';
SET differential_auto_gc = false;

        SELECT version() AS duckdb_version,
               current_setting('differential_auto_gc') AS auto_gc,
               current_setting('differential_repository') AS repository;
    