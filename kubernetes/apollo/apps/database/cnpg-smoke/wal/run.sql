BEGIN;
DO $$
BEGIN
    IF (SELECT jsonb_object_agg(id, payload) FROM smoke_records)
        IS DISTINCT FROM (SELECT jsonb_object_agg(id, md5('seed:' || id::text)) FROM generate_series(1, 1000) AS id) THEN
        RAISE EXCEPTION 'Seed dataset missing or changed';
    END IF;
END
$$;
UPDATE smoke_records SET payload = md5('wal:' || id::text) WHERE id <= 100;
DELETE FROM smoke_records WHERE id BETWEEN 901 AND 1000;
INSERT INTO smoke_records SELECT id, md5('wal:' || id::text) FROM generate_series(1001, 1100) AS id;
DO $$
BEGIN
    IF (SELECT jsonb_object_agg(id, payload) FROM smoke_records)
        IS DISTINCT FROM (SELECT jsonb_object_agg(id, md5(
            CASE WHEN id <= 100 OR id > 1000 THEN 'wal:' ELSE 'seed:' END || id::text))
            FROM generate_series(1, 1100) AS id WHERE id NOT BETWEEN 901 AND 1000) THEN
        RAISE EXCEPTION 'WAL dataset mismatch';
    END IF;
END
$$;
COMMIT;
SELECT count(*) AS rows, md5(string_agg(id::text || ':' || payload, ',' ORDER BY id)) AS checksum FROM smoke_records;
