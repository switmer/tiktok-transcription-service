-- Check existing constraints and indexes before running migrations
-- Run this to see what's already in place

-- 1. CHECK EXISTING CONSTRAINTS
SELECT 
    'CHECK CONSTRAINT' as type,
    cc.constraint_name,
    tc.table_name,
    cc.check_clause
FROM information_schema.check_constraints cc
JOIN information_schema.table_constraints tc 
    ON cc.constraint_name = tc.constraint_name
WHERE tc.table_name IN ('transcriptions', 'sms_users')
AND tc.constraint_type = 'CHECK'
ORDER BY tc.table_name, cc.constraint_name;

-- 2. CHECK EXISTING FOREIGN KEYS
SELECT 
    'FOREIGN KEY' as type,
    tc.constraint_name,
    tc.table_name,
    kcu.column_name,
    ccu.table_name AS foreign_table_name,
    ccu.column_name AS foreign_column_name
FROM information_schema.table_constraints AS tc 
JOIN information_schema.key_column_usage AS kcu
    ON tc.constraint_name = kcu.constraint_name
    AND tc.table_schema = kcu.table_schema
JOIN information_schema.constraint_column_usage AS ccu
    ON ccu.constraint_name = tc.constraint_name
    AND ccu.table_schema = tc.table_schema
WHERE tc.constraint_type = 'FOREIGN KEY' 
AND tc.table_name IN ('transcriptions', 'sms_users', 'transcript_jobs');

-- 3. CHECK EXISTING INDEXES
SELECT 
    'INDEX' as type,
    indexname,
    tablename,
    indexdef
FROM pg_indexes 
WHERE tablename IN ('transcriptions', 'sms_users')
AND indexname LIKE 'idx_%'
ORDER BY tablename, indexname;

-- 4. CHECK TABLE SIZES (to understand index impact)
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
FROM pg_tables 
WHERE tablename IN ('transcriptions', 'sms_users', 'transcript_jobs')
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;