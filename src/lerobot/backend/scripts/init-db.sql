-- =============================================================================
-- LeRobot Backend - PostgreSQL 초기화 스크립트
-- =============================================================================
-- 이 스크립트는 PostgreSQL 컨테이너 최초 실행 시 자동으로 실행됩니다.
-- 테이블 생성은 SQLAlchemy가 담당하므로 여기서는 확장 기능만 설정합니다.
-- =============================================================================

-- UUID 확장 (필요시)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 타임존 설정
SET timezone = 'Asia/Seoul';

-- 기본 스키마 확인
SELECT current_schema();

-- 완료 메시지
DO $$
BEGIN
    RAISE NOTICE 'LeRobot Backend PostgreSQL initialization completed.';
END $$;
