# chaos-lab 기획서

> 부하와 장애를 내가 제어해서 만들어 내고, 그걸 버티는 백엔드를 여러 방식으로 구현·비교하며 아키텍처 선택 안목을 기르는 학습 프로젝트.
> 처음 합의안(2026-10-29)을 실험 하네스 설계(2026-10-31)에 맞춰 고쳐 썼다. 세부 규칙은 이 문서에 복제하지 않고 아래 spec과 결정 기록을 따른다.

- 계약(명령, 결과 배치, 판정, 수치): [experiment-harness spec](specs/experiment-harness/spec.md)
- 결정과 그 이유: [decisions.md](specs/experiment-harness/decisions.md), [ADR 0001](adr/0001-problems-as-data-generated-compose.md)
- 용어: [GLOSSARY.md](../GLOSSARY.md)

## 1. 목적

- **학습 + 포트폴리오.** 서비스 운영이 목적이 아니다.
- 실제 서비스엔 트래픽도 장애도 없다 → **부하와 장애를 직접 만들어 낸다.**
- AI로 구현을 싸고 빠르게 만들 수 있다 → 실무에선 바꾸기 어려운 스택·아키텍처를 여러 개 시도하고 **수치로 비교**한다.
- 한 번 하고 끝이 아니라 **problem과 scenario가 계속 쌓이는 구조.** 어떤 scenario든 같은 명령, 같은 결과 형식, 같은 리포트로 다시 돌린다.

### 우선순위

1. 백엔드 실험 (중심)
2. Rust 학습 (보조 — 지금의 Python CLI를 나중에 Rust CLI나 데스크톱 앱으로 옮긴다)

## 2. 핵심 개념

- **problem**: 하나의 업무 동작을 둘러싼 장애 상황의 묶음. 예: "외부 API가 느려지거나 죽는다".
- **scenario**: problem의 실행 가능한 변형. 예: baseline, api-slow, api-down.
- **impl**: problem의 풀이. 같은 problem의 모든 scenario에 돌릴 수 있다. 예: naive, timeout.
- **run**: scenario 하나를 impl 하나로 실행한 것과 그 결과 묶음. **repeat** 5회로 이뤄진다.

| 고정 (problem·scenario = 계약) | 교체 (impl) |
|---|---|
| API 계약(OpenAPI), 상태 코드 표, 오류 형식(RFC 9457) | 해당 문제 영역의 구현만 |
| 워크로드(k6, open model), 장애 타임라인 | 대기·재시도·락·큐·캐시 전략 |
| 불변식, SLO | 의존성 추가도 비교 변수 (비용과 함께 기록) |
| 자원 예산, 이미지 digest | |

- **변수 하나만 바꾼다.** 같은 problem의 impl끼리는 대기 정책처럼 그 impl을 정의하는 설정만 다르다.
- problem·scenario·impl은 언어 중립 데이터(YAML + 스키마)이고, 하네스 코드는 problem마다 바뀌지 않는다.
- 공개 범위: 저장소에 problem 정의 + impl + 로컬 실행 명령까지. 제출 서비스·랭킹·자동 채점은 만들지 않는다.

## 3. 판정

repeat마다 네 판정을 따로 기록한다: completion, measurement validity, correctness, SLO. 정의와 규칙은 spec의 "판정"과 GLOSSARY를 따른다.

- 단순 등식("200 응답 수 = DB 주문 수")은 쓰지 않는다. 불변식은 request id 단위로 판정하고, 클라이언트가 확인하지 못한 결과는 위반이 아니라 **ambiguous**로 따로 센다.
- 장애가 있는 scenario에서는 장애 해제 후 probe로 **time-to-recovery**를 잰다.
- 통계는 complete이면서 valid인 repeat의 repeat별 값 중앙값과 CV로만 만든다. 요청을 repeat 사이에 합치지 않는다.
- 로컬 결과는 "같은 환경 내 상대 비교"로만 표기한다.

## 4. 구현 공정성

- impl마다 `PROVENANCE.md`에 출처와 수정 이력을 남긴다.
- 서버·클라이언트·풀 설정은 고정 수치로 두고 impl별로 튜닝하지 않는다.
- 결론 문구는 항상 **"이 구현·이 설정·이 환경에서"**로 한정한다.

## 5. 학습 루프

매 실험: **예측 → 측정 → 해설.** 구현은 AI가 짜도 가설과 해설은 직접 쓴다.

- `chaos run ... --predict <파일>`로 예측을 결과에 함께 남기고, 리포트에서 결과와 나란히 본다.
- 발견은 수치와 적용 조건을 함께 쓴다. (예: "이 워크로드·자원 한도에서 lookup이 2초 느려지면 …")

## 6. 스택

| 항목 | 값 |
|---|---|
| 백엔드 | Spring Boot 4, Java 21, JdbcTemplate (JPA 없음), 플랫폼 스레드 위의 동기 MVC |
| DB | PostgreSQL, READ COMMITTED, JDBC pool 10 |
| 하네스 | uv 기반 Python CLI `chaos` (OS별 스크립트 없음) |
| 환경 | repeat마다 생성하는 Docker Compose, 이미지 digest 고정 |
| 부하 | k6 (constant-arrival-rate) |
| 장애 주입 | Toxiproxy (모든 의존성 경로), 외부 API 가짜는 WireMock |
| 관측 | Grafana Alloy → grafana/otel-lgtm (지표·로그·trace), 판정은 결과 파일로만 |

정확한 버전과 수치는 spec의 Constraints가 정본이다.

## 7. 지금 범위

첫 problem `external-api`: 주문 API가 외부 상품 API에 가격·재고를 묻는데, 그 API가 느려지거나(api-slow) 죽는다(api-down). baseline과 함께 scenario 3개, impl 2개(naive, timeout).

완료 조건은 spec의 수용 기준을 따른다: 6개 조합이 같은 명령 하나로 돌고, macOS arm64에서 기록된 run이 남는다.

## 8. 향후 방향

| 순서 | 주제 | 포인트 |
|---|---|---|
| 1 | 동시성 | 재고 경합 problem: naive(read-modify-write) vs 원자적 UPDATE, 비관락, 낙관락+재시도, Redis DECR. 경합률 축(상품 1/10/100개) |
| 2 | 런타임 변수 | 같은 problem에서 Java 21 vs 25, virtual threads on/off, OTel Java agent on/off 오버헤드 |
| 3 | 외부 장애 · 멱등성 | 가짜 결제 API(지연/5xx/timeout/늦은 승인), 재시도·서킷 브레이커·bulkhead·멱등 키, Outbox |
| 4 | 인프라 장애 | DB 장애, 앱 kill·포화, 복제 지연. 이때 `up=0` 무효 규칙을 다시 본다 (ADR 0001) |
| 5 | 보안 | BOLA 하나부터. 공격 결과·로그 증거·알림을 따로 판정 |

### 시간 규칙

도구 작업은 전체 시간의 **30% 이하.** 2주 연속 초과 시 도구 기능 동결.

## 9. 디렉터리 구조

```
chaos-contract.yaml          # 모든 problem이 공유하는 하네스 상수
chaos/                       # Python CLI
schemas/                     # JSON Schema (Python·Rust CLI 공용) + 예시
harness/                     # Alloy 설정, Grafana 대시보드, k6 공통 래퍼
problems/<problem>/          # problem.yaml, scenarios/, impls/, OpenAPI, stub, SQL, k6
results/<run-id>/            # 실행 결과 (커밋)
reports/                     # chaos report 출력 (git 무시)
docs/                        # 기획, 로드맵, spec, ADR
```
