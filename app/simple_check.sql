-- Simple constraint and index check (compatible with all Postgres versions)

-- 1. LIST ALL CONSTRAINTS ON TRANSCRIPTIONS TABLE
SELECT 
    conname as constraint_name,
    contype as constraint_type,
    CASE contype 
        WHEN 'c' THEN 'CHECK'
        WHEN 'f' THEN 'FOREIGN KEY'
        WHEN 'p' THEN 'PRIMARY KEY'
        WHEN 'u' THEN 'UNIQUE'
        ELSE contype::text
    END as type_description
FROM pg_constraint 
JOIN pg_class ON pg_constraint.conrelid = pg_class.oid
WHERE pg_class.relname = 'transcriptions'
ORDER BY conname;

-- 2. LIST ALL CONSTRAINTS ON SMS_USERS TABLE  
SELECT 
    conname as constraint_name,
    contype as constraint_type,
    CASE contype 
        WHEN 'c' THEN 'CHECK'
        WHEN 'f' THEN 'FOREIGN KEY'
        WHEN 'p' THEN 'PRIMARY KEY'
        WHEN 'u' THEN 'UNIQUE'
        ELSE contype::text
    END as type_description
FROM pg_constraint 
JOIN pg_class ON pg_constraint.conrelid = pg_class.oid
WHERE pg_class.relname = 'sms_users'
ORDER BY conname;

-- 3. LIST ALL INDEXES ON TRANSCRIPTIONS
SELECT 
    indexname,
    indexdef
FROM pg_indexes 
WHERE tablename = 'transcriptions'
AND indexname != 'transcriptions_pkey'  -- Exclude primary key
ORDER BY indexname;

-- 4. CHECK IF SPECIFIC CONSTRAINTS EXIST
SELECT 
    CASE WHEN EXISTS (
        SELECT 1 FROM pg_constraint c
        JOIN pg_class t ON c.conrelid = t.oid
        WHERE t.relname = 'transcriptions' 
        AND c.conname = 'chk_transcriptions_status'
    ) THEN 'EXISTS' ELSE 'MISSING' END as status_constraint_exists;

SELECT 
    CASE WHEN EXISTS (
        SELECT 1 FROM pg_constraint c
        JOIN pg_class t ON c.conrelid = t.oid
        WHERE t.relname = 'sms_users' 
        AND c.conname = 'chk_sms_users_phone_format'
    ) THEN 'EXISTS' ELSE 'MISSING' END as phone_constraint_exists;

-- 5. COUNT RECORDS TO UNDERSTAND SCALE
SELECT 'transcriptions' as table_name, COUNT(*) as record_count FROM transcriptions
UNION ALL
SELECT 'sms_users' as table_name, COUNT(*) as record_count FROM sms_users;