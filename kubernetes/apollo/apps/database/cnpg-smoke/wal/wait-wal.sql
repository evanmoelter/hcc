DO $$
DECLARE
    committed_wal text := pg_walfile_name(pg_current_wal_lsn() - 1);
    archived_wal text;
BEGIN
    FOR attempt IN 1..120 LOOP
        PERFORM pg_stat_clear_snapshot();
        SELECT last_archived_wal INTO archived_wal FROM pg_stat_archiver;
        IF archived_wal ~ '^[0-9A-F]{24}$' AND archived_wal >= committed_wal THEN
            RAISE NOTICE 'WAL archived: committed=%, archived=%', committed_wal, archived_wal;
            RETURN;
        END IF;
        PERFORM pg_sleep(5);
    END LOOP;
    RAISE EXCEPTION 'WAL archive timeout for % (last archived: %)', committed_wal, archived_wal;
END
$$;
