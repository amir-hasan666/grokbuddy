"""The only seed rule source. Persisted immutable versions are authoritative at runtime."""
COMMON = ['independent_verification', 'requirements_and_scope', 'counterexamples_and_boundaries',
          'test_evidence', 'least_privilege', 'rollback', 'EVIDENCE_INSUFFICIENT_when_unproven']
PROFILE_RULES = {
    'generic': COMMON,
    'oracle_production': COMMON + [
        'sql_correctness', 'column_and_table_provenance', 'join_where_null_implicit_conversion',
        'indexes_function_indexes_selectivity_plan_cardinality_full_scan',
        'locks_deadlocks_transactions_commit_rollback_exceptions_concurrency_connection_pool',
        'awr_ash_vsql_sql_id_child_cursor_bind_variables', 'same_statistics_window_cumulative_vs_delta',
        'oracle_11g_compatibility', 'ddl_and_dml_scope', 'undo_redo_temp_cpu_io_shared_pool_latch_mutex',
        'backup_validation_sql_rollout', 'diagnostics_pack_license_before_collection'],
    'sql_server_production': COMMON + ['execution_plan_indexes', 'locks_transactions_concurrency', 'version_compatibility'],
    'python_backend': COMMON + ['api_schema', 'exceptions_concurrency_persistence', 'dependency_security'],
    'iis_windows': COMMON + ['app_pool_identity', 'connection_pool', 'configuration_permissions_logs', 'deployment_restart_approval'],
    'document': COMMON + ['sources_and_citations', 'metric_definitions', 'completeness_readability_version'],
}
