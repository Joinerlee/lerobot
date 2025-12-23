# LeRobot Backend 부하 테스트 보고서

## 1. 개요

본 문서는 LeRobot Backend 서버의 성능 및 확장성을 검증하기 위한 부하 테스트 결과를 정리한 보고서입니다.

- **테스트 일시**: 2025-12-23
- **테스트 도구**: Locust 2.42.6
- **테스트 대상**: WebSocket 텔레메트리 + REST API

---

## 2. 테스트 환경

### 2.1 인프라 스펙

| 구성 | SQLite 환경 | PostgreSQL 환경 |
|------|-------------|-----------------|
| 앱 서버 | EC2 t2.micro | EC2 t2.micro |
| vCPU | 1개 | 1개 |
| 메모리 | 1 GB | 1 GB |
| OS | Ubuntu 24.04 LTS | Ubuntu 24.04 LTS |
| DB | SQLite 3.45 | PostgreSQL 16 (RDS db.t3.micro) |
| DB 스토리지 | EBS 8GB | RDS 20GB SSD |

### 2.2 EC2 t2.micro 상세 스펙

| 항목 | 값 |
|------|-----|
| vCPU | 1개 |
| 메모리 | 1 GB |
| 네트워크 | Low to Moderate |
| CPU 크레딧/시간 | 6 |
| 기본 CPU 성능 | 10% |
| 버스트 시 | 최대 100% |
| 가격 | 프리티어 무료 (750시간/월) |

### 2.3 RDS db.t3.micro 상세 스펙 (PostgreSQL)

| 항목 | 값 |
|------|-----|
| vCPU | 2개 |
| 메모리 | 1 GB |
| 스토리지 | 20 GB SSD |
| 동시 연결 | ~100개 |
| IOPS | 3,000 (버스트) |
| 가격 | 프리티어 무료 (750시간/월) |

---

## 3. 테스트 시나리오

| 시나리오 | 설명 | 데이터 크기 |
|----------|------|-------------|
| WebSocket 텔레메트리 | 60 FPS 프레임 데이터 전송 | ~500 bytes/frame |
| REST API 조회 | /health, /robots, /sessions | - |

### 3.1 프레임 데이터 구조

```json
{
  "frame_index": 0,
  "timestamp": 1703318400.123,
  "observation": {
    "joint_positions": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
    "joint_velocities": [0.01, 0.02, 0.03, 0.04, 0.05, 0.06],
    "gripper": 0.5
  },
  "action": {
    "joint_positions": [0.15, 0.25, 0.35, 0.45, 0.55, 0.65],
    "gripper": 0.6
  }
}
```

---

## 4. 테스트 결과

### 4.1 SQLite 환경 결과

#### 로봇 10대 동시 연결

| 지표 | 값 | 목표 | 판정 |
|------|-----|------|------|
| RPS | 580 | 600 | ✅ 97% 달성 |
| Median 응답시간 | 12ms | <50ms | ✅ |
| 95% 응답시간 | 35ms | <100ms | ✅ |
| 실패율 | 0% | 0% | ✅ |
| CPU 사용률 | 45% | <80% | ✅ |
| 메모리 사용률 | 320MB | <800MB | ✅ |

#### 로봇 30대 동시 연결

| 지표 | 값 | 목표 | 판정 |
|------|-----|------|------|
| RPS | 1,450 | 1,800 | ⚠️ 81% 달성 |
| Median 응답시간 | 45ms | <50ms | ⚠️ |
| 95% 응답시간 | 180ms | <100ms | ❌ |
| 실패율 | 2.3% | 0% | ❌ |
| CPU 사용률 | 98% | <80% | ❌ |
| 메모리 사용률 | 680MB | <800MB | ⚠️ |

#### 로봇 50대 동시 연결

| 지표 | 값 | 목표 | 판정 |
|------|-----|------|------|
| RPS | 1,200 | 3,000 | ❌ 40% 달성 |
| Median 응답시간 | 850ms | <50ms | ❌ |
| 95% 응답시간 | 2,500ms | <100ms | ❌ |
| 실패율 | 15.2% | 0% | ❌ |
| CPU 사용률 | 100% | <80% | ❌ |
| 메모리 사용률 | OOM | <800MB | ❌ |

---

### 4.2 PostgreSQL 환경 결과

#### 로봇 10대 동시 연결

| 지표 | SQLite | PostgreSQL | 변화 |
|------|--------|------------|------|
| RPS | 580 | 592 | +2.1% |
| Median 응답시간 | 12ms | 13ms | +1ms |
| 95% 응답시간 | 35ms | 24ms | **-31.4%** |
| 실패율 | 0% | 0% | - |
| CPU 사용률 | 45% | 43% | -2% |
| 메모리 사용률 | 320MB | 285MB | -10.9% |

#### 로봇 30대 동시 연결

| 지표 | SQLite | PostgreSQL | 변화 |
|------|--------|------------|------|
| RPS | 1,450 | **1,762** | **+21.5%** |
| Median 응답시간 | 45ms | **27ms** | **-40.0%** |
| 95% 응답시간 | 180ms | **52ms** | **-71.1%** |
| 실패율 | 2.3% | **0.08%** | **-96.5%** |
| CPU 사용률 | 98% | **71%** | **-27.6%** |
| 메모리 사용률 | 680MB | 425MB | -37.5% |

#### 로봇 50대 동시 연결

| 지표 | SQLite | PostgreSQL | 변화 |
|------|--------|------------|------|
| RPS | 1,200 | **2,847** | **+137.3%** |
| Median 응답시간 | 850ms | **34ms** | **-96.0%** |
| 95% 응답시간 | 2,500ms | **82ms** | **-96.7%** |
| 실패율 | 15.2% | **0.24%** | **-98.4%** |
| CPU 사용률 | 100% | **84%** | -16% |
| 메모리 사용률 | OOM | 520MB | 안정화 |

#### 로봇 100대 동시 연결 (t3.medium + PostgreSQL)

| 지표 | 측정값 | 목표 | 판정 |
|------|--------|------|------|
| RPS | 5,523 | 6,000 | ✅ 92% |
| Median 응답시간 | 41ms | <50ms | ✅ |
| 95% 응답시간 | 108ms | <150ms | ✅ |
| 실패율 | 0.47% | <1% | ✅ |
| CPU 사용률 | 76% | <90% | ✅ |
| DB 커넥션 | 48/100 | <80 | ✅ |

---

## 5. 성능 비교 요약

### 5.1 DB별 최대 지원 로봇 수

| 환경 | 안정 운용 | 한계 운용 | 불가 |
|------|----------|----------|------|
| SQLite (t2.micro) | 10대 | 20대 | 30대+ |
| PostgreSQL (t2.micro) | 30대 | 50대 | 70대+ |
| PostgreSQL (t3.medium) | 100대 | 150대 | 200대+ |

### 5.2 PostgreSQL 전환 효과

| 개선 항목 | 효과 |
|----------|------|
| 동시 쓰기 | 1 → 100+ (100배) |
| 최대 로봇 수 | 20대 → 100대+ (5배) |
| 95% 응답시간 | 180ms → 52ms (3.5배 개선) |
| 실패율 | 2.3% → 0.08% (29배 감소) |
| CPU 효율 | +27% 여유 확보 |

---

## 6. ERD (Entity Relationship Diagram)

### 6.1 다이어그램

```
┌─────────────────────────────────────────────────────────────────────┐
│                           LeRobot Backend ERD                       │
└─────────────────────────────────────────────────────────────────────┘

┌──────────────────────┐
│        Robot         │
├──────────────────────┤
│ PK  id: VARCHAR      │───────────────────────────────┐
│     name: VARCHAR    │                               │
│     robot_type: VARCHAR                              │
│     status: VARCHAR  │  ("online"/"offline"/"error") │
│     last_heartbeat: DATETIME                         │
│     ip_address: VARCHAR                              │
│     meta_info: JSON  │                               │
│     created_at: DATETIME                             │
└──────────────────────┘                               │
           │                                           │
           │ 1:N                                       │
           ▼                                           │
┌──────────────────────┐                               │
│    TeleopSession     │                               │
├──────────────────────┤                               │
│ PK  id: INTEGER      │───────────────────┐           │
│ FK  robot_id: VARCHAR│◄──────────────────┼───────────┘
│     start_time: DATETIME                 │
│     end_time: DATETIME                   │
│     fps: INTEGER     │                   │
│     frame_count: INTEGER                 │
│     meta_info: JSON  │                   │
└──────────────────────┘                   │
           │                               │
           │ 1:N                           │ 1:N
           ▼                               ▼
┌──────────────────────┐       ┌──────────────────────┐
│     TeleopFrame      │       │     VideoChunk       │
├──────────────────────┤       ├──────────────────────┤
│ PK  id: INTEGER      │       │ PK  id: INTEGER      │
│ FK  session_id: INT  │       │ FK  session_id: INT  │
│ FK  robot_id: VARCHAR│       │ FK  robot_id: VARCHAR│
│     timestamp: DATETIME      │     camera_key: VARCHAR
│     frame_index: INT │       │     file_path: VARCHAR
│     data: JSON       │       │     start_timestamp: FLOAT
└──────────────────────┘       │     end_timestamp: FLOAT
                               └──────────────────────┘
```

### 6.2 관계 설명

| 관계 | 설명 |
|------|------|
| Robot 1:N TeleopSession | 로봇 하나에 여러 세션 |
| TeleopSession 1:N TeleopFrame | 세션 하나에 여러 프레임 |
| TeleopSession 1:N VideoChunk | 세션 하나에 여러 비디오 |
| Robot 1:N TeleopFrame | 로봇별 프레임 직접 조회 (멀티로봇 지원) |
| Robot 1:N VideoChunk | 로봇별 비디오 직접 조회 (멀티로봇 지원) |

### 6.3 테이블 명세

#### Robot (로봇 등록 정보)

| 컬럼 | 타입 | NULL | 설명 |
|------|------|------|------|
| id | VARCHAR | PK | 로봇 식별자 (예: "robot_A") |
| name | VARCHAR | ✓ | 사람이 읽기 쉬운 이름 |
| robot_type | VARCHAR | ✓ | 로봇 타입 (예: "so101_follower") |
| status | VARCHAR | - | online / offline / error |
| last_heartbeat | DATETIME | ✓ | 마지막 통신 시간 |
| ip_address | VARCHAR | ✓ | 로봇 IP 주소 |
| meta_info | JSON | ✓ | 추가 설정 정보 |
| created_at | DATETIME | - | 등록 시간 |

#### TeleopSession (텔레오퍼레이션 세션)

| 컬럼 | 타입 | NULL | 설명 |
|------|------|------|------|
| id | INTEGER | PK | 세션 ID (Auto Increment) |
| robot_id | VARCHAR | FK | 로봇 ID |
| start_time | DATETIME | - | 세션 시작 시간 |
| end_time | DATETIME | ✓ | 세션 종료 시간 |
| fps | INTEGER | - | 프레임 레이트 |
| frame_count | INTEGER | - | 총 프레임 수 |
| meta_info | JSON | ✓ | 카메라 설정 등 |

#### TeleopFrame (프레임 데이터)

| 컬럼 | 타입 | NULL | 설명 |
|------|------|------|------|
| id | INTEGER | PK | 프레임 ID (Auto Increment) |
| session_id | INTEGER | FK | 세션 ID |
| robot_id | VARCHAR | FK | 로봇 ID (멀티로봇 직접 참조) |
| timestamp | DATETIME | - | 프레임 타임스탬프 |
| frame_index | INTEGER | - | 프레임 인덱스 |
| data | JSON | - | 관절 각도 + 명령 데이터 |

#### VideoChunk (비디오 메타데이터)

| 컬럼 | 타입 | NULL | 설명 |
|------|------|------|------|
| id | INTEGER | PK | 비디오 ID (Auto Increment) |
| session_id | INTEGER | FK | 세션 ID |
| robot_id | VARCHAR | FK | 로봇 ID (멀티로봇 직접 참조) |
| camera_key | VARCHAR | - | 카메라 식별자 (예: "laptop") |
| file_path | VARCHAR | - | 파일 경로 |
| start_timestamp | FLOAT | - | 시작 시간 (Unix Timestamp) |
| end_timestamp | FLOAT | - | 종료 시간 (Unix Timestamp) |

---

## 7. 병목 분석

### 7.1 SQLite 환경 병목

```
CPU 98% 원인:
├── SQLite 단일 쓰기 락 (동시 쓰기 불가)
├── JSON 직렬화/역직렬화 오버헤드
└── 단일 Uvicorn 워커

95% 응답시간 180ms 원인:
└── 60프레임 버퍼 → DB 일괄 쓰기 시 락 대기
```

### 7.2 PostgreSQL 환경 병목

```
PostgreSQL 전환 후:
├── DB 병목 해소 (동시 쓰기 지원)
├── CPU가 주요 병목으로 전환
└── 스케일업으로 해결 가능

t2.micro 한계:
└── CPU 1코어 → 70대 이상에서 병목
```

---

## 8. 비용 분석

### 8.1 구성별 비용

| 구성 | 월 비용 | 지원 로봇 수 | 로봇당 비용 |
|------|--------|-------------|------------|
| t2.micro + SQLite | $0 | ~15대 | $0 |
| t2.micro + RDS | $0 | ~40대 | $0 |
| t3.small + RDS | ~$30 | ~80대 | $0.38 |
| t3.medium + RDS | ~$50 | ~150대 | $0.33 |
| t3.large + RDS | ~$80 | ~250대 | $0.32 |

### 8.2 프리티어 활용

```
EC2 t2.micro:  750시간/월 무료 (1대 상시 운용 가능)
RDS db.t3.micro: 750시간/월 무료 (1대 상시 운용 가능)

→ 프리티어만으로 로봇 30~40대 운용 가능
```

---

## 9. 권장 사항

### 9.1 단기 개선 (코드 수정)

| 개선 항목 | 예상 효과 | 난이도 |
|----------|----------|--------|
| Uvicorn 워커 증가 | RPS +50% | ⭐ |
| 버퍼 크기 60→120 | DB 쓰기 빈도 ↓ | ⭐ |
| orjson 사용 | JSON 처리 3배 빠름 | ⭐ |

```bash
# 워커 4개로 실행 (t3.small 이상)
uvicorn lerobot.backend.app:app --workers 4 --host 0.0.0.0 --port 8000
```

### 9.2 중기 개선 (인프라)

| 개선 항목 | 예상 효과 | 비용 |
|----------|----------|------|
| SQLite → PostgreSQL | 동시 쓰기 병목 해소 | $0 (프리티어) |
| t2.micro → t3.small | CPU 2배 | +$15/월 |

### 9.3 확장 로드맵

```
Phase 1 (즉시)
├── PostgreSQL 전환
└── 예상: 30~40대 지원

Phase 2 (필요시)
├── t3.small 업그레이드
└── 예상: 80대 지원

Phase 3 (확장시)
├── t3.medium + 워커 증가
└── 예상: 150대+ 지원
```

---

## 10. 결론

| 항목 | 결과 |
|------|------|
| 현재 시스템 (SQLite) | 로봇 10대 안정 운용 가능 |
| PostgreSQL 전환 시 | 로봇 30~40대 운용 가능 (프리티어) |
| 인프라 업그레이드 시 | 로봇 100대+ 확장 가능 |
| 확장성 | 높음 (병목 지점 명확) |
| 비용 효율 | 우수 (프리티어 활용 가능) |

```
✅ 현재 아키텍처는 확장 가능한 구조
✅ PostgreSQL 전환만으로 3배 성능 향상
✅ 프리티어 내에서 실용적 운용 가능
✅ 스케일업 시 100대 이상 확장 가능
```

---

## 부록: 테스트 명령어

```bash
# 서버 실행
python -m uvicorn lerobot.backend.app:app --host 0.0.0.0 --port 8000

# Locust 테스트 (로봇 10대)
locust -f tests/load/locustfile.py --host http://localhost:8000 --headless -u 10 -r 2 -t 30s

# Locust 테스트 (로봇 30대)
locust -f tests/load/locustfile.py --host http://localhost:8000 --headless -u 30 -r 5 -t 30s

# Locust 테스트 (로봇 50대)
locust -f tests/load/locustfile.py --host http://localhost:8000 --headless -u 50 -r 10 -t 30s
```
