# 진행 현황 (2026-11-02)

실험 하네스(`experiment-harness`) 구현이 어디까지 왔는지, 어떻게 돌리는지, 무엇이 남았는지를 정리한다.
규칙의 원본은 [spec](specs/experiment-harness/spec.md)이고, 이 문서는 그 위의 진행 기록이다.

## 한 줄 요약

하네스와 첫 problem(`external-api`)의 3개 scenario × 2개 impl이 모두 구현돼 있다.
api-slow는 두 impl 모두 5회 완주했다. 6개 조합 최종 실행은 하네스 결함 3개를 고친 뒤 다시 시작했다가, api-down·timeout repeat 1이 valid로 끝난 시점에 중단했다.

## 만든 것

| 위치 | 내용 |
|---|---|
| `chaos/` | Python CLI (`run`, `report`, `clean`). 검증 → Compose 생성 → 단계 실행 → 판정 → HTML 리포트 |
| `schemas/` | problem·scenario·impl·contract·결과 파일의 JSON Schema (이후 Rust CLI와 공유) |
| `chaos-contract.yaml` | 하네스 상수: 반복 5회, 고정 이미지 digest, 자원 예산 |
| `harness/` | Alloy 수집 설정, Grafana 대시보드, k6 wrapper |
| `problems/external-api/` | 주문 API(Spring Boot 4, Java 21, JdbcTemplate), WireMock 상품 API stub, k6 부하, scenario 3개, impl 2개 |
| `tests/` | 단위·흐름 테스트, 실제 Docker 테스트, 기록된 run 점검 |
| `results/` | 실제 실행 기록 (커밋함, 지우지 않음) |

- scenario: `baseline`(장애 없음), `api-slow`(lookup에 upstream 2,000 ms 지연, 40~80초), `api-down`(lookup 프록시 비활성화, 40~80초)
- impl: `naive`(lookup을 최대 10초 기다림), `timeout`(lookup 전체 호출을 300 ms에서 끊음). 같은 이미지를 쓰고 `impl.yaml`의 환경 변수만 다르다.

## 실행 방법

필요한 것: Docker 엔진(Compose v2 포함), uv. 개발은 macOS arm64 + OrbStack에서 했다.

```
uv sync                                                       # 처음 한 번
uv run chaos run external-api/api-slow --impl naive           # 5회 반복, 한 run에 약 25분
uv run chaos run external-api/api-down --impl timeout --predict notes/predict.md
uv run chaos report results/<run-id-1> results/<run-id-2>     # 같은 scenario의 run 비교 → reports/
uv run chaos clean                                            # 끝난 run의 잔여 컨테이너·네트워크 정리
uv run chaos clean --run <run-id>                             # 특정 run 강제 정리
```

- 실행 중: 터미널에 찍힌 `127.0.0.1` Grafana 주소에서 지표·로그·trace·장애 annotation을 본다(익명 읽기 전용).
- 실행 후: `results/<run-id>/report.html`.
- 종료 코드: 0 모든 repeat 완주(SLO를 놓쳐도 0), 2 입력 검증 실패(아무것도 만들지 않음), 3 그 밖의 실패·중단·incomplete repeat(부분 결과는 남음).
- 한 엔진에서 run은 하나만 돈다(Docker 위의 lock 컨테이너). 다른 run이 돌고 있거나 정리 안 된 lock이 있으면 exit 3이고, `chaos clean`이 안내된다.

테스트:

```
uv run pytest                  # 단위·흐름 (Docker 불필요, 수 초)
uv run pytest -m docker        # 실제 엔진: lock·clean, 앱 계약 테스트
uv run pytest -m e2e           # results/에 기록된 run 점검
```

## 실행 결과

api-slow (repeat별 값의 중앙값, 5/5 complete·valid, exit 0):

| 지표 | naive | timeout |
|---|---|---|
| 예산(500 ms) 안 201 비율 | 0.666 | 0.665 |
| 201 p99 | 13,820 ms | 97 ms |
| k6 timeout (repeat당) | 약 500 | 0 |
| ambiguous 주문 | 103 | 0 |
| time-to-recovery | 991 ms | 995 ms |

- run: `results/20261031-004309-…-api-slow-naive-2c0c93`, `results/20261031-002528-…-api-slow-timeout-8def62`
- 비교 리포트: `uv run chaos report` 으로 다시 만들 수 있다(`reports/`는 커밋하지 않음).
- 두 run은 재현 빌드와 이미지 ID 수정 이전이라 앱 이미지 ID를 서로 비교할 수 없다(AC-30은 새 run으로 증명해야 함).

api-down·timeout repeat 1 (`results/20261101-214655-…-api-down-timeout-546e1c`, 이후 중단):
complete·valid, 예산 안 201 비율 0.663, 201 p99 212 ms, k6 timeout 0, ambiguous 0, time-to-recovery 714 ms,
Toxiproxy API 격리 확인(앱·k6에서 연결 0건), 장애 적용·해제 지연 154 ms / 290 ms.

`results/`의 나머지 run은 하네스 결함으로 멈췄거나 일부러 중단한 기록이다. 결과는 버리지 않는다는 원칙(D-21)에 따라 남겨 두었다.

## 실제 실행에서 찾아 고친 것

테스트로는 드러나지 않았고, 다시 만들지 않도록 기록한다.

1. k6 VU가 연결을 계속 잡아 Tomcat 연결 한도를 채움 → `noVUConnectionReuse`.
2. Alloy가 k6 요청별 로그를 tail하다 CPU 예산을 다 씀 → k6 로그 제외, 신호별 exporter.
3. downstream 지연 toxic 제거가 timeout impl에서 멈춤 → upstream 지연 (spec 수정).
4. Grafana가 준비되자마자 서비스 계정 생성이 실패 → 준비 한도 안에서 재시도.
5. 같은 소스인데 이미지 ID가 매번 다름 → 재현 빌드(Gradle 설정, `SOURCE_DATE_EPOCH=0`, provenance·SBOM 끔).
6. containerd 이미지 저장소에서 `docker build -q`가 출력한 ID로 이미지를 찾지 못함 → 입력 해시 태그로 빌드하고 태그로 조회.
7. OrbStack은 Docker 네트워크끼리 라우팅을 막지 않아 앱·k6가 Toxiproxy API에 닿음 → API를 컨테이너 loopback에만 열고 `docker exec toxiproxy-cli`로 제어 (spec 수정).

## 남은 일

spec 수용 기준 43개 중 34개 체크. 남은 9개:

| AC | 무엇이 필요한가 |
|---|---|
| AC-1, AC-43 | 6개 조합을 모두 exit 0으로 완주 |
| AC-13 | 6개 중 한 run을 `.env`·`DOCKER_DEFAULT_PLATFORM`·`COMPOSE_FILE`·`COMPOSE_PROFILES`를 둔 채 실행 |
| AC-19, AC-31 | api-down 완주 기록 (repeat 1에서는 확인됨) |
| AC-20 | baseline 포함 모든 scenario에서 격리 점검 기록 |
| AC-30 | 같은 하네스로 돈 naive·timeout run의 이미지 ID가 같음 |
| AC-34 | 사람이 직접: Grafana 화면이 익명 읽기 전용인지, `admin/admin`이 막히는지, 패널·annotation 확인 |
| AC-42 | 사람이 직접: PLAN·ROADMAP·README가 spec과 어긋나지 않는지 검토 |

이어서 할 순서:

1. 6개 조합 실행 (약 2시간 반). 첫 run만 AC-13 조건으로:
   ```
   printf 'COMPOSE_FILE=hijack.yaml\nCOMPOSE_PROFILES=load\nCOMPOSE_PROJECT_NAME=hijack\nDOCKER_DEFAULT_PLATFORM=linux/amd64\n' > .env
   DOCKER_DEFAULT_PLATFORM=linux/amd64 COMPOSE_FILE=hijack.yaml COMPOSE_PROFILES=load uv run chaos run external-api/api-down --impl timeout
   rm .env
   for c in "api-down naive" "baseline naive" "baseline timeout" "api-slow naive" "api-slow timeout"; do
     set -- $c; uv run chaos run external-api/$1 --impl $2
   done
   ```
2. `uv run pytest -m e2e`, 결과 확인 후 해당 AC 체크, `results/` 커밋.
3. AC-34, AC-42 수동 확인.
4. `node ~/.claude/skills/wf-artifacts/check.mjs implement experiment-harness` 통과 → Codex 리뷰(wf-review) → `/wf-report experiment-harness`.
