SET differential_repository = 'experiment/test/phase1';
SET differential_auto_gc = false;

        SELECT extension_version
        FROM duckdb_extensions()
        WHERE extension_name = 'differential';
    