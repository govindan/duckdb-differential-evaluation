SET differential_repository = 'experiment/lifecycle/retention/repository';
SET differential_auto_gc = false;

            SELECT dry_run, candidate_objects, candidate_bytes, deleted_objects
            FROM differential_cleanup_old_files(cleanup_all => true, max_objects => 10000);
        