BEGIN;
CREATE TABLE smoke_records (id integer PRIMARY KEY, payload text NOT NULL);
INSERT INTO smoke_records SELECT id, md5('seed:' || id::text) FROM generate_series(1, 1000) AS id;
DO $$
BEGIN
    IF (SELECT jsonb_object_agg(id, payload) FROM smoke_records)
        IS DISTINCT FROM (SELECT jsonb_object_agg(id, md5('seed:' || id::text)) FROM generate_series(1, 1000) AS id) THEN
        RAISE EXCEPTION 'Seed dataset mismatch';
    END IF;
END
$$;
COMMIT;
SELECT count(*) AS rows, md5(string_agg(id::text || ':' || payload, ',' ORDER BY id)) AS checksum FROM smoke_records;
