# Frozen Design Decisions

1. Primary subject is DuckDB Differential, not a DAF product.
2. Workload is a synthetic banking transaction classification pipeline.
3. Baseline and candidate branches must originate from one common raw-input snapshot.
4. Original and modified transformations execute independently.
5. DuckDB SQL performs output comparison.
6. Conventional DuckDB independent copies provide the control.
7. Storage and performance are measured across dataset sizes and controlled changed-row percentages.
8. Business classification changes and controlled storage-write changes are separate workloads.
9. Python orchestration remains thin.
10. Use Git, DuckDB SQL, Differential, CSV and Markdown only unless an additional dependency is demonstrably necessary.
11. Clone, restore, expiry and GC are tested only after actual extension semantics are verified.
12. Reliability/destructive tests use disposable repositories only.
13. Report demonstrated, documented and unverified capabilities distinctly.
14. Exclude enterprise DAF, canonical model, Soda, policy/metadata frameworks, fee calculation and S3 from core MVP.
15. Cursor must work in phases and stop for approval between phases.
