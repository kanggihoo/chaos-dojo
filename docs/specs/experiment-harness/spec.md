# 실험 하네스 (experiment-harness)

Status: approved
Decisions: [decisions.md](decisions.md) · Glossary and ADRs: [GLOSSARY.md](../../../GLOSSARY.md) · [0001](../../adr/0001-problems-as-data-generated-compose.md)

## Problem

부하와 장애 상황을 여러 개 만들어 두고, 같은 조건에서 여러 impl이 어떻게 버티는지 비교하고 싶다. 상황 예시는 "외부 API가 느려지면?", "중간에 죽으면?"이고, 나중에는 동시성 문제도 다룬다. 지금은 상황마다 환경을 손으로 띄워야 하고, 상황마다 명령과 결과 형식이 달라질 위험이 있다. 사용자는 Mac과 Windows PC를 오가며 이 저장소를 쓰므로 OS마다 절차가 달라지는 것도 원하지 않는다.

이 기능은 하네스와 첫 problem을 만든다.
- 하네스: problem, scenario, impl이 무엇이든 같은 명령 하나로 깨끗한 환경을 새로 만들고, 정해진 단계로 부하와 장애를 넣고, 같은 형식의 결과와 리포트를 남긴다.
- 첫 problem: "외부 HTTP API가 느려지거나 죽는다". 하네스 위에서 돈다.

## Assumptions

1. 호스트에는 Linux 컨테이너를 돌리는 Docker 엔진, Compose v2, uv가 있다. 지원 엔진(macOS arm64의 OrbStack이나 Docker Desktop, Windows x86_64의 Docker Desktop)은 컨테이너 안에 `/var/run/docker.sock`으로 엔진 소켓을 마운트할 수 있다.
2. 사용하는 서드파티 이미지는 모두 arm64와 amd64를 함께 담은 index digest가 있다. 대상은 PostgreSQL, Toxiproxy, WireMock, k6, Grafana Alloy, grafana/otel-lgtm, Gradle/JDK 빌드 이미지다.
3. 고정한 버전에서 다음 기능이 문서대로 동작한다.
   - k6: constant-arrival-rate executor, Prometheus remote-write output, `console.log`의 컨테이너 로그 출력
   - Alloy: `discovery.docker`, `prometheus.scrape`, `prometheus.receive_http`, `loki.source.docker`, `otelcol.receiver.otlp`
   - otel-lgtm: 내장 collector의 OTLP 입력, Prometheus·Loki·Tempo 질의 API, Grafana 서비스 계정 API
   - WireMock: admin API의 basic auth
   - Toxiproxy: API 리슨 주소 지정, 같은 이미지에 든 `toxiproxy-cli`의 프록시 생성·toggle·toxic 추가·제거
4. Spring Boot 4의 `spring-boot-starter-opentelemetry`는 auto-configured `RestClient.Builder`로 만든 HTTP client 호출에 client span을 만든다.
5. 저장소에는 지금 문서(README.md, docs/PLAN.md, docs/ROADMAP.md)만 있고, 코드·`.gitignore`·`.gitattributes`는 없다.

## Usage

```
# 첫 problem의 api-slow 장애를 naive impl로 5회 반복 실행
uv run chaos run external-api/api-slow --impl naive

# 예측을 함께 남기기
uv run chaos run external-api/api-down --impl timeout --predict notes/predict-api-down.md

# 같은 scenario의 두 run을 한 페이지로 비교
uv run chaos report results/<run-id-1> results/<run-id-2>

# 끝난 run의 잔여물 정리, 또는 끝났는지 확인할 수 없는 run을 직접 해제
uv run chaos clean
uv run chaos clean --run <run-id>
```

- **실행 중**: `chaos run`이 출력한 Grafana 주소에서 앱 지표, k6 지표, 로그, trace, 장애 시점을 본다.
- **실행 후**: run 디렉터리의 `report.html`을 연다.
- **확장**: 새 scenario는 `problems/` 아래에 데이터 파일만 추가한다. 새 impl은 앱 코드와 `impl.yaml`을 추가한다. 어느 경우에도 하네스(CLI) 코드는 고치지 않는다.

## Acceptance criteria

### CLI와 입력 검증

- [ ] AC-1: 첫 problem의 3개 scenario × 2개 impl, 6개 조합이 모두 `uv run chaos run <problem>/<scenario> --impl <impl>` 하나로 실행되고, 각 run은 repeat 5회를 수행해 새 run 디렉터리와 `report.html`을 남긴다; 명령 형태, 결과 파일 구조, 리포트 레이아웃은 6개 조합에서 같다. (D-2, D-6, D-17, D-19)
- [x] AC-2: 모든 명령의 종료 코드는 Interfaces의 종료 코드 표를 따르며, `run`에서는 3이 1보다 우선한다; 불변식 fail, SLO miss, correctness·SLO unknown은 종료 코드를 바꾸지 않는다. (D-6)
- [x] AC-3: Interfaces "실행 전 거부" 목록에 해당하는 입력은 이유와 함께 거부되고 exit 2로 끝난다; 이때 컨테이너, 네트워크, 볼륨, lock, 결과 디렉터리는 하나도 만들어지지 않는다. (D-6, D-7, D-9, D-10, D-18)
- [x] AC-4: 다른 problem의 manifest가 스키마 위반이어도 정상 problem의 scenario 실행은 그 때문에 막히지 않는다. (D-7)
- [x] AC-5: 커밋된 JSON Schema(problem·scenario manifest, impl descriptor, 하네스 계약 파일, 결과 파일)마다 valid/invalid 예시 파일이 있고, 하네스 테스트가 모든 예시를 기대대로 판정한다; 예시에는 `010`(거부), boolean 자리의 `no`·`off`(거부), id 자리의 `no`(허용), 끝에 줄바꿈이 붙은 id(거부)가 포함된다. (D-7)
- [x] AC-6: `--predict` 파일은 입력 검증 때 한 번 읽어 메모리에 둔다; run 디렉터리를 만들 때 그 내용을 결과에 복사하고 해시를 기록하며, 이 사건은 run 수준 `events.jsonl`에서 어떤 measured load보다 앞선다; 이후 원본은 다시 읽지 않는다; `--predict`가 있든 없든 validity 판정은 같다; 표준 입력이 닫혀 있어도 CLI는 끝까지 동작한다. (D-6)
- [x] AC-7: 엔진의 전체 CPU 수나 메모리가 repeat 중 동시에 도는 모든 컨테이너(앱, problem 의존성, impl 추가 의존성, k6, Alloy, otel-lgtm) 예산의 합보다 작으면, lock을 잡은 직후 다른 자원을 만들기 전에 이유를 남기고 lock을 푼 뒤 exit 3으로 끝난다; 예산을 줄여서 실행하지 않는다. (D-14)

### 환경 생성과 격리

- [x] AC-8: 각 repeat는 다른 repeat와 겹치지 않는 새 Compose 프로젝트 이름과 새 볼륨으로 실행된다; 결과에 저장된 `compose.yaml`은 Compose에 넘긴 파일과 해시가 같다; 그 파일에 든 경로는 run 디렉터리 기준 상대 경로와 Docker 소켓 경로뿐이다; 모든 입력 마운트는 run의 `inputs/` 스냅샷을 가리킨다. (D-5, D-9, D-16)
- [x] AC-9: 다음 repeat의 첫 자원 생성은 이전 repeat의 소유 자원이 모두 삭제된 것을 확인한 뒤에만 일어난다; 삭제에 실패하면 run을 멈추고 그때까지의 결과를 보존한 채 exit 3으로 끝난다. (D-9)
- [x] AC-10: 한 엔진에서 run이 진행 중일 때 다른 `chaos run`은 lock 외의 자원을 만들기 전에 exit 3으로 거부된다; 다른 checkout에서 실행한 run도 마찬가지다. (D-9)
- [x] AC-11: 정리에 성공한 run은 종료 코드와 상관없이 그 run id 라벨이 붙은 컨테이너, 네트워크, 볼륨, lock을 하나도 남기지 않는다; 정리에 실패한 run은 lock을 남기고, 그다음 `chaos run`은 `chaos clean`을 안내하며 exit 3으로 거부된다. (D-9, D-21)
- [x] AC-12: `chaos clean`과 `chaos clean --run <id>`는 Interfaces "clean 규칙"을 따른다; 둘 다 라벨이 없는 자원이나 이 기기에서 살아 있다고 확인된 run의 자원은 지우지 않는다; `--run`은 생존을 확인할 수 없는 run을 사용자가 책임지고 해제하는 수단이다. (D-6, D-9, D-21)
- [ ] AC-13: 호스트에 `DOCKER_DEFAULT_PLATFORM`, `COMPOSE_FILE`, `COMPOSE_PROFILES`를 설정하거나 현재 디렉터리에 `.env`를 두어도, 생성되거나 사용되는 Compose 구성은 바뀌지 않는다; 시작 때 정한 엔진의 신원과 하위 프로세스에 넘긴 환경 변수 이름은 결과에 기록된다. (D-5, D-9)
- [x] AC-14: 저장소에는 OS별 실행 파일·스크립트(`.sh`, `.ps1`, `.bat`, `.cmd`, Gradle wrapper), OS별 설정, OS별 실행 안내가 없다; 하네스 소스에는 `sys.platform`, `os.name`, `platform.system` 같은 OS 판별 분기가 없다; `.gitattributes`는 컨테이너가 읽는 텍스트 asset에 LF를 강제하고 `results/**`를 `-text`로 지정한다; `.gitignore`는 `reports/`를 무시한다. (D-2, D-5)

### 실행 단계와 부하

- [x] AC-15: 모든 repeat는 prepare → warmup → measured load → recovery check → convergence → collect → cleanup 순서로 진행한다; 단계마다 resolved timeout과 실제 시작·종료 시각이 기록된다; 적용되지 않는 단계는 이유와 함께 기록된다(첫 problem의 convergence, baseline의 recovery check); 이미지 빌드·pull은 첫 repeat 전에 하고, 단계 timeout과 별도로 기록된다. (D-11)
- [x] AC-16: warmup은 고정 시간이고 `warmup_policy=fixed`로 기록된다; warmup이 끝나면 하네스는 warmup cohort의 quiescence 확인 → orders 테이블 비우기 → WireMock journal 비우기 → 경계 기록 순서로 진행한 뒤 measured load를 시작하고, 각 사건은 그 순서대로 `events.jsonl`에 남는다; quiescence가 30초 안에 확인되지 않으면 그 repeat를 invalid로 기록하고 같은 순서로 나머지 단계를 계속 진행한다. (D-11)
- [x] AC-17: measured load는 scenario의 rate로 constant-arrival-rate executor가 건다; `dropped_iterations > 0`이거나 gracefulStop에 잘린 iteration이 있는 repeat는 invalid다; 잘린 iteration과 k6 timeout 요청은 개수와 이유를 기록하되 성공 latency 표본에는 넣지 않는다. (D-11, D-12)
- [x] AC-18: Ctrl+C, 장애 적용·해제 API 호출 실패, Docker 엔진 API 호출의 오류 응답(데몬 연결 불가, 컨테이너·네트워크·볼륨의 생성·시작 요청 실패 포함) 중 하나가 일어나면 하네스는 새 부하와 이후 repeat를 멈추고, 부분 결과와 실행하지 않은 repeat를 이유와 함께 기록하고, 소유 자원 정리를 시도하고, 정리 결과까지 담아 `run.json`을 확정한 뒤 그 결과로 `report.html`을 쓰고 exit 3으로 끝난다. (D-11, D-21)
- [ ] AC-19: api-slow는 lookup 프록시에 latency toxic을 걸고, api-down은 lookup 프록시를 비활성화하며, 둘 다 t0 기준 계획 시각에 적용하고 해제한다; 계획 시각, 실제 시각(Toxiproxy 제어 호출이 성공으로 끝난 시각, 호출 시각도 함께), 결과는 `events.jsonl`에 남는다; 실제 시각이 계획보다 1초 넘게 어긋난 repeat는 invalid다. (D-10, D-19, D-21)
- [ ] AC-20: baseline을 포함한 모든 scenario에서 앱의 DB 연결과 lookup 연결은 toxic이 없을 때도 Toxiproxy를 거친다; 결과에는 최종 topology와 프록시 버전·설정이 기록된다; 앱 컨테이너와 k6 컨테이너는 Toxiproxy API 포트에 연결할 수 없다; 하네스의 제어·수집 경로는 프록시를 거치지 않는다. (D-10)
- [x] AC-21: 단계 timeout을 넘기거나, repeat 안의 컨테이너가 생성·시작된 뒤 준비 상태에 이르지 못하거나 비정상 종료한 repeat는 이유와 함께 incomplete가 되고 그 validity는 unknown이다; 하네스는 그 repeat를 정리하고 다음 repeat로 넘어간다; incomplete repeat가 하나라도 있으면 run은 exit 3으로 끝난다. (D-6, D-11)

### 판정

- [x] AC-22: 각 repeat에는 completion, measurement validity, correctness, SLO 네 판정이 따로 기록된다; 비교 통계에서 빠지는 것은 complete가 아니거나 valid가 아닌 repeat뿐이고, 빠진 repeat는 이유와 함께 표시된다; correctness나 SLO가 unknown이어도 통계에서 빠지지 않으며, 계산할 수 없는 지표는 그 지표의 n에서만 빠진다. (D-15)
- [x] AC-23: SLO는 measured cohort에서 두 조건을 모두 만족할 때만 met이다: (a) 예산 안에 끝난 201 수 ÷ 발행한 measured 요청 수 ≥ 임계값, (b) 201의 p99(nearest-rank) ≤ 예산; 201이 0건이면 p99를 계산하지 않고 missed다; 발행이 0건이거나 필요한 증거가 없으면 unknown이다; 장애 전·중·후 구간 값도 함께 표시되며, 구간은 요청 발행 시각과 실제 장애 적용·해제 시각으로 나눈다. (D-15)
- [x] AC-24: 불변식 검사기는 Interfaces "첫 problem 불변식"의 각 위반을 위반으로 보고하고, ambiguous 항목은 따로 센다; 확인된 위반이 하나라도 있으면 다른 증거가 없더라도 correctness는 fail이고 확인된 위반은 각각 기록된다; 확인된 위반이 없고 증거가 완전하면 pass이며 ambiguous 수를 함께 표시한다; 확인된 위반이 없고 증거가 모자라면 unknown이다. (D-20, D-21)
- [x] AC-25: 장애가 있는 scenario에서는 Interfaces "recovery 규칙"대로 probe를 보내고 time-to-recovery를 기록한다; 60초 안에 회복하지 않으면 correctness fail이다; probe 요청은 measured 지표와 SLO에서 빠지지만, 불변식 검사에는 자기 cohort로 들어간다. (D-20)
- [x] AC-26: Interfaces "measurement validity" 목록 중 하나라도 해당하면 그 repeat는 invalid다; 실시간 사본(k6 remote-write, Grafana annotation)의 실패만으로는 판정이 바뀌지 않고, `live_status=degraded`와 원인만 기록된다; annotation은 `events.jsonl`에 먼저 기록한 뒤 유한한 queue와 timeout으로 비동기 게시하므로, Grafana가 응답하지 않아도 장애 적용·해제 시각은 늦어지지 않는다. (D-12, D-13, D-15, D-21)
- [x] AC-27: run 수준 값은 complete이면서 valid인 repeat별 값의 중앙값이다(n이 짝수면 가운데 두 값의 평균); 값에는 "repeat별 p99의 중앙값"처럼 이름이 붙는다; CV는 표본 표준편차 ÷ 평균이며 n<2이거나 평균이 0이면 계산하지 않는다; 요청은 repeat 사이에 합치지 않는다; 리포트는 계획·실행·complete·valid 수, 지표별 집계 n, 제외 이유를 보여 주고, n<5면 "완전한 5회 결과 아님", CV>10%면 "조사 신호"로 표시한다. (D-12)

### 첫 problem 앱

- [x] AC-28: 앱은 Interfaces의 HTTP 계약과 상태 코드 표의 판정 순서를 그대로 따른다; lookup이 성공하고 짧은 트랜잭션 하나가 commit된 뒤에만 201을 준다; 400·409·502·503·504 응답에서는 새 주문을 저장하지 않는다(409 `duplicate-request`는 이미 저장된 주문만 있다는 뜻이다). (D-18)
- [x] AC-29: lookup 호출은 트랜잭션 밖에서, DB 연결을 잡지 않은 채 이루어진다; 요청 하나의 lookup이 지연되는 동안 JDBC pool active 수는 0이다. (D-18)
- [ ] AC-30: naive와 timeout은 같은 이미지를 쓰고 `impl.yaml`의 환경 변수만 다르다; 결과에 기록된 resolved Tomcat·HTTP client·JDBC 설정은 lookup 대기 정책(`IMPL`과 그 한도)을 빼면 두 impl이 같다; virtual threads는 꺼져 있다(`spring.threads.virtual.enabled=false`); 이미지 ID와 resolved 설정은 run 결과에 기록된다. (D-3, D-8, D-19)
- [ ] AC-31: naive가 api-slow에서 업무 Tomcat 스레드를 모두 소진한 동안에도 관리 포트의 readiness와 Prometheus 엔드포인트는 응답한다; Interfaces "필수 지표"는 api-slow와 api-down 중에도 수집된다; 내보낸 지표 어디에도 request id 라벨은 없다. (D-8, D-13)
- [x] AC-32: readiness는 앱과 DB가 준비됐을 때 성공하고, lookup 상태와는 무관하다; api-down 중에도 성공한다. (D-8)

### 관측

- [x] AC-33: Alloy의 스크레이프 대상은 run 네트워크에 있는 app 관리 포트뿐이며, 대상 목록이 결과에 기록된다; 하네스는 새 repeat의 앱에서 첫 스크레이프가 성공한 것을 확인한 뒤에 warmup을 시작한다. (D-13)
- [ ] AC-34: `chaos run`은 실행 중 `127.0.0.1`에 묶인 Grafana 주소를 출력한다; Grafana는 익명 읽기 전용으로 열리고 기본 admin 계정(`admin/admin`)으로는 로그인할 수 없다; 저장소에 커밋된 대시보드에서 현재 run·repeat의 앱 지표, k6 실시간 지표, 컨테이너 로그, trace, 단계·장애 annotation을 볼 수 있다; 실시간 k6 percentile에는 추정치라는 표시가 붙는다. (D-13)
- [x] AC-35: 각 repeat 결과에는 Interfaces "결과 파일 배치"의 필수 파일이 있다; 로그는 파일별 상한과 보존 규칙을 지키고, UTF-8 글자 경계에서 자르며, 잘린 경우 그 사실을 표시한다; 관측 스택을 지운 뒤 `chaos report <run>`이 만든 HTML은 그 run의 `report.html`과 바이트 단위로 같다. (D-13, D-17)
- [x] AC-36: repeat 시작과 끝에 호스트와 엔진의 시계 차이를 재서 기록한다; 엔진 시계를 쓰는 모든 소스(k6, Prometheus, Docker stats, 로그)의 시각은 그 값으로 호스트 UTC로 바꾼다; 차이나 드리프트가 한도를 넘으면 그 repeat는 invalid다. (D-13)
- [x] AC-37: 하네스가 생성하는 결과 파일(사용자가 작성한 `inputs/` 사본과 dirty patch는 원본 그대로 복사하므로 제외)에는 다음이 들어가지 않는다: 사용자 홈 경로나 사용자 이름이 든 절대 경로, 호스트 이름, 생성된 자격 증명 값(DB, Grafana, WireMock), 서비스 계정 토큰, request id 지표 라벨. (D-5, D-13, D-21)

### 결과와 리포트

- [x] AC-38: 각 run은 `results/` 아래에 배타적으로 새로 만든 디렉터리를 가진다; 이름이 겹치면 덮어쓰지 않고 새 무작위 접미사로 다시 만든다; 결과에는 Interfaces "신원 정보" 항목이 모두 있다; dirty 상태는 결과와 리포트에 표시된다; `results/`, `reports/`, `.wf-grill/`은 빌드 입력과 dirty 스냅샷에서 빠진다. (D-16)
- [x] AC-39: `chaos report`는 저장된 결과 파일만 읽고 결과 디렉터리를 바꾸지 않는다; 출력은 새 파일 `reports/<YYYYMMDD-HHMMSS>-<무작위>.html`에 쓰고 그 경로를 출력한다; 부분 run(exit 3)의 결과도 읽는다; 같은 scenario이면서 비교 신원이 같은 run끼리만 한 페이지로 비교한다; 환경 신원만 다르면 비교를 거부하지만, `--allow-cross-env`를 주면 승자나 순위 없이 나란히 보여 준다; 그 밖의 신원이 다르면 언제나 거부한다. (D-17)
- [x] AC-40: 리포트는 모든 scenario에서 같은 레이아웃이다; problem별 항목은 공통 항목 배열로 표시하고, 해당 없는 항목은 그렇다고 표시한다; 예측이 있으면 결과와 함께 보여 준다; impl의 `description`과 추가 의존성을 비교 변수와 그 비용으로 보여 준다; repeat별 관측 스택 자원 사용량과 "관측 스택은 run 동안 유지됨"이라는 한계를 표시한다; 재현 명령에는 절대 경로나 셸 문법이 없다; 생성 시각, 무작위 값, 현재 저장소 상태처럼 결과 파일 밖의 값은 HTML에 넣지 않는다. (D-17)
- [x] AC-41: 결과 파일은 자기 스키마 버전을 담는다; 리포트는 지금까지 공개된 모든 결과 스키마 버전을 읽는다(이번 iteration에서는 버전 1 하나). (D-6, D-7)

### 문서와 완료

- [ ] AC-42: docs/PLAN.md, docs/ROADMAP.md, README.md 세 파일에서 이번 결정과 어긋나는 내용(스택, 관측, 결과 배치, 디렉터리 구조, 명령, 용어, 범위, 리포트 생성기 등)은 모두 고쳐진다; 프로젝트 이름은 `chaos-lab`, 용어는 problem/scenario/impl/run/repeat, 명령은 `chaos`를 쓴다; 세 파일에 kata, Makefile 진입점, `dojo`는 남지 않는다(로컬 디렉터리 이름과 원격 저장소 이름 `chaos-dojo`를 가리킬 때는 예외); 뒷 시즌 계획은 새 용어로 고쳐 쓴 "향후 방향"으로 남을 수 있다; PLAN은 세부 규칙을 복제하지 않고 이 spec과 decisions.md를 링크한다. (D-1, D-4)
- [ ] AC-43: macOS arm64에서 6개 조합의 run 6개가 각각 exit 0으로 끝나 `results/`에 기록되어 있다; 정해진 수치로는 exit 0을 낼 수 없다면, 두 impl에 공통인 수치를 고치는 spec 수정 승인을 먼저 거친다. (D-2, D-5)

## Interfaces

### CLI

| 명령 | 인자 | 동작 |
|---|---|---|
| `uv run chaos run <problem>/<scenario> --impl <impl> [--predict <file>]` | problem·scenario·impl id | 아래 실행 순서 |
| `uv run chaos report <run dir>… [--allow-cross-env]` | run 디렉터리 1개 이상 | 저장된 결과로 `reports/` 아래에 새 리포트 파일 |
| `uv run chaos clean [--run <run id>]` | — | clean 규칙 |

- 명령은 저장소 루트에서 실행한다. 이 기능에는 다른 명령이 없다.
- `reports/`는 git이 무시하고, `results/`는 커밋한다.

**`run` 실행 순서**:
1. 입력을 검증한다. 실패하면 exit 2이고, 아무것도 만들지 않는다.
2. 엔진을 정한다. Docker CLI 규칙(`DOCKER_HOST`, `DOCKER_CONTEXT`, 현재 context 순)으로 한 번 정하고, 이후 모든 호출에 명시해서 넘긴다.
3. engine lock을 잡는다. 충돌하거나 남은 lock이 있으면 exit 3.
4. 엔진 용량을 검사한다. 부족하면 lock을 풀고 exit 3.
5. run 디렉터리와 `inputs/` 스냅샷을 만들고, 예측 파일을 복사한다.
6. 이미지를 빌드하거나 pull한다.
7. 관측 스택을 띄운다.
8. repeat 1–5를 실행한다.
9. 집계한다.
10. 관측 스택 로그를 저장하고 관측 스택과 run 네트워크를 정리한다.
11. 정리 결과와 종료 코드까지 담아 `run.json`을 확정한다.
12. 확정된 결과 파일만으로 `report.html`을 쓴다.
13. 소유 자원이 남지 않았으면 lock을 푼다.

**종료 코드**:

| 명령 | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| `run` | 계획한 repeat가 모두 complete이고 valid | 모두 complete지만 invalid repeat가 있음 | 실행 전 입력 거부 | 하네스·인프라 오류, Docker 엔진 호출 오류, lock 충돌·잔여 lock, 용량 부족, 중단, 장애 동작 실패, incomplete repeat, 정리 실패 |
| `report` | 리포트 작성 | — | 없는 디렉터리, 결과 스키마 위반, 비교 거부 | 그 밖의 오류 |
| `clean` | 정리 완료, 정리할 것 없음, 살아 있는 run을 건너뜀 | — | 형식이 잘못된 run id, 살아 있는 run에 대한 `--run` | 정리 실패 |

**clean 규칙**:
- `clean`
  - 라벨 자원 가운데 그 run이 끝났다고 확인된 것만 지운다. lock이 없는 run은 끝난 것으로 본다.
  - 끝난 run의 lock도 지운다.
  - 살아 있는 run의 자원은 건너뛰고, 건너뛰었다고 출력한다.
- `clean --run <id>`
  - 같은 기기에서 그 run의 프로세스가 살아 있으면 거부한다.
  - 그렇지 않으면 그 run id 라벨이 붙은 자원과 lock을 지운다.
  - 지울 것이 없으면 exit 0이다.

### 저장소 배치 (작성자 계약)

```
chaos-contract.yaml                # 하네스 계약 상수(수치표의 "하네스 상수"), 버전 있음
harness/                           # 하네스가 마운트하는 자체 파일(Alloy 설정, Grafana 대시보드, k6 공통 래퍼) — 위치는 재량
problems/<problem>/problem.yaml
problems/<problem>/scenarios/<scenario>/scenario.yaml
problems/<problem>/impls/<impl>/impl.yaml
problems/<problem>/impls/<impl>/PROVENANCE.md
problems/<problem>/...             # SQL, k6 스크립트, OpenAPI, WireMock stub, fixture
results/<run-id>/                  # 커밋
reports/                           # git 무시
```

**id**
- 적용 대상은 problem, scenario, impl, 의존성, 서비스 이름이다.
- 스키마에서는 `pattern: "^[a-z][a-z0-9-]*$"`와 `maxLength: 40`으로 검사한다.
- 하네스 의미 검사에서는 추가로 다음을 거부한다.
  - `[a-z0-9-]` 밖의 문자. 줄바꿈 같은 제어 문자도 포함한다.
  - Windows 예약 장치 이름: `con`, `prn`, `aux`, `nul`, `com1`–`com9`, `lpt1`–`lpt9`
- problem·scenario·impl id는 디렉터리 이름이다. manifest 안의 id와 소속 problem 필드는 디렉터리와 같아야 한다.
- scenario·impl id는 problem 안에서 유일하다.
- 디렉터리는 manifest 파일이 있을 때만 scenario나 impl로 친다.

**예약 이름**: `alloy`, `lgtm`, `toxiproxy`, `k6`, 그리고 `chaos-`로 시작하는 이름은 하네스 전용이다.

**YAML**
- YAML 1.2 core schema를 쓰고, JSON 호환 타입만 허용한다.
- boolean은 `true`/`false`만 허용한다.
- 다음은 거부한다: 앞에 0이 붙은 정수, 중복 키, anchor/alias, merge key, 태그, `.inf`/`.nan`, ±2^53 밖 정수.

**JSON Schema**
- draft 2020-12를 쓴다.
- `pattern`은 ECMA-262 의미(multiline 플래그 없음, `$`는 입력 끝에서만 맞음)로 해석하므로 스키마만으로 끝 줄바꿈 id를 거부한다. 스키마 예시 테스트는 스키마 검증만 따로 돌려 이를 확인하고, Python 쪽 검증기도 이 의미에 맞춘다.
- `format`은 assertion으로 쓰지 않는다.

**asset 참조**
- 참조하는 manifest 기준 상대 경로를 쓰고, 구분자는 `/`만 쓴다.
- 참조 대상은 자기 problem 디렉터리 안에 있어야 한다.
- 파일 이름은 ASCII이고, 디렉터리 목록과 대소문자까지 같아야 한다.
- 심볼릭 링크는 거부한다.

**계약 버전**
- manifest는 현재 계약 버전(1)만 받는다.
- 버전을 올릴 때는 같은 커밋에서 모든 problem을 새 버전으로 옮긴다.
- 실행할 때는 `chaos-contract.yaml`, 그 problem의 `problem.yaml`, 선택한 scenario와 impl의 manifest, 그리고 이들이 참조하는 asset만 검증한다. 같은 problem 안의 다른 scenario·impl은 디렉터리 이름(id 규칙과 중복)만 본다.

**런타임 값 참조**
- manifest와 `impl.yaml`의 값에는 하네스가 실행 시점에 채우는 다음 참조만 쓸 수 있다. 다른 참조는 거부한다.
  - `${chaos.dep.<의존성>.host}`, `${chaos.dep.<의존성>.port}`: Toxiproxy 리스너 주소
  - `${chaos.dep.<의존성>.user}`, `${chaos.dep.<의존성>.password}`: 생성된 DB 자격 증명
  - `${chaos.otlp.endpoint}`
  - `${chaos.run_id}`, `${chaos.repeat}`
- 의존성 주소를 참조 대신 직접 적으면 "Toxiproxy를 거치지 않는 경로"로 거부한다.

### 실행 전 거부 (exit 2)

- 없는 problem·scenario·impl
- 스키마 위반
- 지원하지 않는 계약 버전·action·의존성 종류
- 없는 참조
- 규칙에 맞지 않는 asset 참조
- 금지된 YAML 구성
- id 규칙 위반, 디렉터리와 id 불일치
- 예약 이름 사용
- 알 수 없는 런타임 값 참조
- impl에 없는 의존성을 장애 대상으로 삼는 scenario
- Toxiproxy를 거치지 않는 의존성 경로
- problem 의존성 예산 합계가 infra 상한을 넘음
- OpenAPI 문서 오류
- 계약에 맞지 않는 stub 응답이나 fixture
- 읽을 수 없는 `--predict` 파일

### Manifest 필드 (필수 항목. 이름과 세부 구조는 스키마로 확정)

- **`problem.yaml`**
  - 계약 버전, id, 설명
  - 공통 의존성: 이름, 종류(`postgres` | `http-fake`), 이미지 digest, CPU·메모리 예산
  - 공통 asset: SQL 스키마, OpenAPI, stub, fixture
  - 필수 지표 목록
  - 불변식 목록: 공통 검사 어휘에서 고른다
  - SLO: 응답 예산(ms), 성공률 임계값
  - recovery 설정: 간격, 최대 시간, 연속 성공 수
- **`scenario.yaml`**
  - 계약 버전, id, 소속 problem
  - workload: k6 스크립트 참조, rate, warmup 시간, measured 시간, gracefulStop, k6 timeout, seed
  - 장애 목록: 대상 의존성, action(`latency` | `down`), 값, t0 기준 적용·해제 시각
  - 단계별 timeout
- **`impl.yaml`**
  - 계약 버전, id, 소속 problem, 한 줄 `description`
  - 이미지: 로컬 빌드 컨텍스트 경로 또는 digest
  - 포트와 경로: business port, 관리 port, readiness 경로, 지표 경로
  - 실험 관련 환경 변수 전체: 이름, 값 또는 런타임 값 참조
  - 추가 의존성(예산 포함), provenance 참조
  - exec hook 필드는 없다.

### 결과 파일 배치

**이름 규칙**
- `run-id`: `<YYYYMMDD>-<HHMMSS>-<problem>-<scenario>-<impl>-<무작위 6자>`. 시각은 UTC이고, 소문자·숫자·`-`만 쓴다.
- repeat의 Compose 프로젝트 이름: `chaos-<무작위 6자>-r<n>`
- 관측 스택의 Compose 프로젝트 이름: `chaos-<무작위 6자>-obs`

```
results/<run-id>/
  run.json                 결과 스키마 버전, 판정 요약, 집계(지표별 중앙값·CV·n), 제외 이유, 종료 코드, 신원 정보, live_status
  events.jsonl             run 수준 사건 (예측 복사, 이미지 준비, 관측 스택 기동·정리)
  inputs/                  실행 시점 입력 스냅샷: chaos-contract.yaml, 하네스 자체 마운트 파일, 모든 manifest·asset·descriptor·예측 + 해시 목록
  run-compose.yaml         관측 스택 Compose (자격 증명은 변수 참조만)
  logs/                    관측 스택 컨테이너 로그 (run 단위)
  repeats/<n>/
    repeat.json            4개 판정과 이유, 단계별 시각·timeout, cohort별 수, 시계 차이·드리프트, 스크레이프 대상, 로그 잘림 정보, 관측 스택 자원 사용량
    compose.yaml           Compose에 넘긴 파일과 같은 내용
    events.jsonl           단계·장애·경계 사건 (seq, 종류, 계획 시각, 실제 시각, 결과)
    k6/                    k6 원본 결과: 요청별 outcome, request id, cohort, 발행 시각, 응답 시각 (warmup·measured·probe)
    metrics/               내보낸 필수 지표 시계열, Docker stats 시계열
    logs/<service>.log     repeat 컨테이너 로그 (ANSI 코드 포함 원본 바이트. AC-37 금지 문자열만 치환하고 그 횟수를 repeat.json에 기록)
    traces/summary.json    span 수(샘플링·내보냄·버림)와 trace 요약 (진단용)
    wiremock-journal.json  cohort를 구별할 수 있는 journal (진단용)
    checks.json            불변식별 결과(pass/fail/unknown, 위반 목록, ambiguous 목록)
  report.html
```

- **필수 파일**: `repeat.json`, `compose.yaml`, `events.jsonl`, `k6/`, `metrics/`, `logs/`, `checks.json`.
- **진단용 파일**: trace 요약과 journal은 없어도 판정에 영향이 없고, 없었다는 사실만 기록된다.
- **부분 run(exit 3)**: 실행하지 않은 repeat는 `repeat.json` 없이 `run.json`에 이유와 함께 적힌다. 결과 스키마는 이런 부분 run을 허용한다.

### 신원 정보 (run.json)

- **엔진**: 제품 이름(`docker info`의 OperatingSystem, 예: Docker Desktop, OrbStack), 서버 버전, OS 종류, 아키텍처, CPU 수, 전체 메모리. 호스트 이름, `docker info`의 Name, 소켓 경로는 기록하지 않는다.
- **이미지**
  - pull한 이미지: index digest, 플랫폼, 플랫폼 manifest digest, local image ID
  - 로컬 빌드: image ID, 플랫폼, 커밋, dirty 여부, 빌드 입력 해시, dirty patch(빌드 컨텍스트 안의 tracked 변경과 untracked 파일)
- **입력**: 모든 입력 파일의 사본(`inputs/`)과 해시
- **실행 조건**
  - seed, 컨테이너별 자원 예산
  - 도구 버전: Python CLI, uv, Docker, Compose, k6, 각 이미지
  - 하네스 커밋과 dirty 여부. dirty는 `problems/`·`results/`·`reports/` 밖의 tracked 변경과 untracked 파일로 판단한다.
  - 시작 시점에 엔진에서 돌던 다른 컨테이너의 수와 이미지 이름

**비교 신원**: `report`가 두 run을 한 페이지로 비교하려면 다음이 모두 같아야 한다.
- scenario 내용 해시: `scenario.yaml`과 그것이 참조하는 모든 asset
- problem 내용 해시: `problem.yaml`과 그것이 참조하는 모든 asset·이미지 digest
- workload, seed
- `chaos-contract.yaml`의 버전과 내용 해시: 판정·수집 정책
- 환경 신원: 엔진 제품 이름, 서버 버전, OS 종류, 아키텍처, CPU 수, 전체 메모리

하네스 git 커밋은 표시만 하고 비교 조건에 넣지 않는다. impl과 그 추가 의존성은 비교 변수다.

### 첫 problem HTTP API (`problems/external-api/` 아래 OpenAPI가 정본)

| 항목 | 값 |
|---|---|
| 요청 | `POST /orders`. 헤더 `X-Request-Id: <소문자 UUIDv4>`, `X-Chaos-Cohort: warmup` \| `measured` \| `probe`. 본문 `{ "productId": "p-001"…"p-020", "quantity": 1–10 }` |
| 201 본문 | `{ "orderId": int64, "requestId", "productId", "quantity", "unitPrice": int64, "total": int64, "currency": "KRW" }`. 금액은 최소 통화 단위 정수이고 `total = unitPrice × quantity` |
| lookup | `GET /products/{productId}`. 앱은 `X-Request-Id`와 `X-Chaos-Cohort`를 그대로 전달하고, 리다이렉트를 따라가지 않는다. 응답은 200 `{ "productId", "price": int64 (1–1,000,000), "currency": "KRW", "available": boolean }` |
| 오류 본문 | RFC 9457 problem: `type`, `title`, `status`, `detail`, `requestId` |
| request id | 상관 키일 뿐, 멱등성을 보장하지 않는다 |
| cohort | 앱은 이 값을 처리 중 업무 요청 지표의 라벨로 쓴다. 세 값 외에는 400이다 |

**판정 순서**: 위에서부터 처음 맞는 행 하나만 적용한다.

| 순서 | 상황 | 상태 | problem type |
|---|---|---|---|
| 1 | 헤더 누락·형식 오류, cohort 값 오류, 상품 id 형식 오류, quantity 범위 밖 | 400 | `urn:chaos-lab:problem:invalid-request` |
| 2 | lookup 응답 대기 한도 초과. `timeout` impl은 전체 호출 기한 초과도 포함한다(pool 획득 중이어도) | 504 | `urn:chaos-lab:problem:upstream-timeout` |
| 3 | lookup 연결 거부·리셋·도달 불가, pool 획득 timeout | 503 | `urn:chaos-lab:problem:upstream-unavailable` |
| 4 | lookup 404 (없는 상품) | 400 | `urn:chaos-lab:problem:invalid-request` |
| 5 | lookup이 200 외의 상태(그 밖의 4xx·5xx, 3xx, 200이 아닌 2xx)로 응답 | 502 | `urn:chaos-lab:problem:upstream-error` |
| 6 | lookup 2xx 본문을 쓸 수 없음 (형식 깨짐, 필드 누락·타입 오류, 다른 상품, 가격 범위 밖) | 502 | `urn:chaos-lab:problem:invalid-upstream-response` |
| 7 | 유효한 본문의 `available=false` | 409 | `urn:chaos-lab:problem:product-unavailable` |
| 8 | insert의 request id UNIQUE 위반 | 409 | `urn:chaos-lab:problem:duplicate-request` |
| 9 | 그 밖의 DB 오류 (insert·commit 실패) | 500 | `urn:chaos-lab:problem:db-error` |

정의되지 않은 경로와 메서드에는 프레임워크 기본 404·405를 RFC 9457 형식으로 돌려준다.

### 첫 problem 저장 구조

```sql
CREATE TABLE orders (
  id          BIGSERIAL PRIMARY KEY,
  request_id  UUID        NOT NULL UNIQUE,
  cohort      TEXT        NOT NULL,
  product_id  TEXT        NOT NULL,
  quantity    INTEGER     NOT NULL CHECK (quantity BETWEEN 1 AND 10),
  unit_price  BIGINT      NOT NULL,
  total       BIGINT      NOT NULL,
  currency    CHAR(3)     NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- 격리 수준 READ COMMITTED
```

### 필수 지표 (첫 problem, `problem.yaml`이 선언)

| 지표 | 내용 |
|---|---|
| `http_server_requests` | 업무 요청 수와 지연, 상태별 |
| `http_client_requests` | lookup 호출 수와 지연, 결과별 |
| `hikaricp_connections_active`, `hikaricp_connections_pending` | JDBC pool |
| `jvm_threads_live` | JVM 스레드 수 |
| `tomcat_threads_busy`, `tomcat_threads_config_max` | 업무 커넥터 스레드 |
| `chaos_business_inflight{cohort}` | cohort별 처리 중 업무 요청 수. 요청 종료는 DB 트랜잭션이 끝난 뒤로 잡는다 |

**누락 기준**: 다음 중 하나에 해당하면 그 지표는 누락이다.
- measured 구간에서 샘플이 있는 시각이 기대 스크레이프 시각의 95% 미만이다.
- 5초를 넘는 공백이 있다.

### 첫 problem 불변식

**검사 시점**: recovery check가 끝나고, measured·probe cohort의 quiescence를 확인한 뒤 collect 단계에서 한 번 검사한다. `REPEATABLE READ READ ONLY` 트랜잭션 하나(앱 트랜잭션의 READ COMMITTED와 별개)의 스냅샷을 쓴다.

**판정 단위**: request id 단위로 판정한다. k6는 id를 다시 쓰지 않는다.

**위반**:
1. 그 id에 201 응답이 있는데, 그 id의 주문이 없거나 2개 이상이다.
2. 201 주문의 payload(상품, 수량, 단가, 합계, 통화, cohort)가 요청·응답과 다르다.
3. 그 id의 응답이 모두 400, 409 `product-unavailable`, 502, 503, 504 중 하나인데 주문이 있다.
4. 저장된 단가가 그 상품의 stub 가격과 다르다.
5. 그 repeat의 measured·probe cohort에서 발행하지 않은 id의 주문이 있다.
6. 장애가 있는 scenario에서 60초 안에 회복하지 않았다.

**따로 세는 항목**: 위반은 아니지만 pass로 숨기지도 않는다.
- `ambiguous: persisted without client confirmation`: 클라이언트가 응답을 받지 못한 id(k6 timeout, 연결 리셋, gracefulStop에 잘림)의 주문.
- `persisted despite server error`: 500 응답을 받은 id의 주문. 단, 앱이 그 요청의 rollback 완료를 기록했다면 위반이다.

**증거 부족**: k6 원본 결과나 DB 스냅샷을 얻지 못하면 correctness는 unknown이다. WireMock journal은 앱의 lookup 성공 증거로 쓰지 않는다.

**quiescence**: 하네스가 연속 두 번의 스크레이프에서 다음 두 조건을 모두 확인한 상태다.
- 대상 cohort의 `chaos_business_inflight`가 0이다. 대상 cohort는 warmup 뒤에는 warmup, 검사 전에는 measured와 probe다.
- 업무 커넥터의 `tomcat_threads_busy`가 0이다.

quiescence를 기다리는 한도는 30초다. 넘기면 다음과 같이 처리하며, 어느 경우도 단계 timeout으로 보지 않는다.
- warmup 뒤라면 그 repeat는 invalid다.
- 검사 전이라면 correctness는 unknown이다.

### k6 실행과 recovery 규칙

**k6 실행 구성**
- warmup은 k6 실행 하나로 돈다.
- measured와 probe는 같은 k6 실행 안의 두 scenario이고, 이 실행은 경계를 기록한 뒤에 시작한다.

**t0와 measured load의 끝**
- k6는 measured scenario의 첫 iteration에서 시작 표시를 로그로 남긴다.
- 하네스는 k6 로그 스트림에서 그 표시를 읽어 t0로 삼고, 장애 스케줄은 t0를 기준으로 움직인다.
- measured load는 measured scenario가 발행을 멈추고, 진행 중인 iteration이 gracefulStop까지 끝난 시각에 끝난다.

**recovery check**
- 적용 범위: 장애가 있는 scenario에만 적용한다. baseline에서는 "해당 없음"으로 기록한다.
- probe 발행:
  - probe scenario(cohort `probe`)는 계획된 해제 시각(t0 + 80 s)부터 1초마다 주문 요청 하나를 보낸다.
  - 62초 동안(판정 창 60초 + 해제 시각 허용 오차 1초 + 여유 1초) 보내고, 실제 해제 확인 시각 이후로 예산 안 201을 연속 5번 받으면 멈춘다.
  - 실제 해제 확인 시각보다 먼저 발행된 probe 요청은 회복 판정에서 뺀다.
- 판정:
  - time-to-recovery는 실제 해제 확인 시각부터, 연속 5번 성공 중 첫 요청의 발행 시각까지다.
  - 판정 창은 실제 해제 확인 시각부터 60초다. 실제 해제 확인 시각 이후에 발행된 요청만 세고, 연속 5번째 성공 응답(예산 안 201)이 창이 닫히기 전에 도착하면 회복이고, 아니면 불변식 6 위반이다.
  - probe는 계획 시각 기준 1초 격자로 발행하므로 time-to-recovery의 해상도는 1초다(실제 해제가 격자 사이에 오면 첫 유효 probe는 다음 격자 시각이다).
- recovery check 단계는 measured load가 끝난 뒤 probe scenario가 끝날 때까지 기다리는 단계다.

### measurement validity (하나라도 해당하면 invalid)

- k6 포화
- `dropped_iterations > 0`
- gracefulStop에 잘린 iteration
- 필수 스크레이프 실패(`up=0`)
- 필수 지표 누락
- 시계 차이·드리프트 한도 초과
- 결과 내보내기 timeout이나 필수 파일 누락
- 장애 적용·해제 시각이 계획보다 1초 넘게 어긋남
- warmup 뒤 quiescence 실패
- 검사 시점에 warmup cohort의 주문이 남아 있음 (경계 위반)
- 도착 확인 실패: 30초 안에 모든 필수 지표에서 measured load 끝 이후 시각의 샘플이 저장소(Prometheus 질의 API)에 보이지 않음. trace와 journal은 도착 확인 대상이 아니다

incomplete인 repeat의 validity는 unknown이다. valid로 기록되는 일은 없다.

collect 단계 안에는 하위 한도가 있다: quiescence 30 s, 도착 확인 30 s, 내보내기 120 s. 이 하위 한도를 넘기면 위 판정대로 unknown이나 invalid가 된다. repeat가 incomplete가 되는 경우는 collect 단계 전체 timeout(180 s)을 넘길 때뿐이다.

### impl 환경 변수 (첫 problem 공유 이미지)

`impl.yaml`이 모든 값을 리터럴이나 런타임 값 참조로 선언한다.

- **DB**: URL, 계정·비밀번호(참조)
- **lookup**
  - base URL(참조)
  - `IMPL`(`naive` | `timeout`): 공유 코드에서 lookup 대기 정책을 고른다
  - 응답 대기 한도(ms)
  - 전체 호출 기한(ms): `timeout`만
  - 연결 timeout(ms)
- **풀**: HTTP client pool 크기와 획득 timeout, JDBC pool 크기와 연결 timeout
- **Tomcat**: max-threads, accept-count, max-connections
- **관측**
  - 관리 포트, 관리 executor 크기
  - OTLP endpoint(참조), trace 샘플링 비율
  - 서비스 이름, run id·repeat id 리소스 속성(참조)

### 소유 라벨과 lock

**라벨**: 하네스가 만드는 모든 컨테이너·네트워크·볼륨·lock 객체에 다음 라벨을 붙인다. 정리와 Alloy 탐색은 이 라벨로만 대상을 고른다.
- `chaos-lab.run-id`
- `chaos-lab.repeat`: run 단위 자원에는 없다
- `chaos-lab.role`

**lock**: 이름이 `chaos-lab-lock`으로 고정된, 실행하지 않는 컨테이너 객체다.
- 같은 이름이 이미 있으면 생성이 실패하는 것으로 lock을 잡는다.
- 라벨에 run id, 기기 id, 프로세스 id, 프로세스 시작 시각을 담는다.
- 기기 id는 사용자 데이터 디렉터리에 둔 무작위 id다.
- lock은 자원 예산 합계에 들어가지 않는다.

## Constraints

- **스택** (D-3)
  - Spring Boot 4, Java 21, JdbcTemplate(JPA 없음), PostgreSQL READ COMMITTED, JDBC pool 10, 플랫폼 스레드 위의 동기 Spring MVC. `spring.threads.virtual.enabled=false`를 명시한다.
  - Tomcat·HTTP client·JDBC 설정은 아래 수치로 둔다. lookup 대기 정책 외에는 두 impl이 같게 두고, 원하는 결과를 얻으려고 impl별로 조정하지 않는다. resolved 값과 Tomcat·JDK 버전을 기록한다.
  - trace는 공유 앱 코드의 `spring-boot-starter-opentelemetry`로 붙인다. Java agent는 쓰지 않고, 스타터의 OTLP 지표 push는 끈다.
  - 앱 빌드와 테스트는 고정된 Gradle 이미지 안에서 돈다. Gradle wrapper는 쓰지 않는다.
- **이름** (D-4)
  - 일본어 유래 이름을 쓰지 않는다.
  - 프로젝트 이름은 `chaos-lab`이고 문서에만 쓴다. 로컬 디렉터리와 원격 저장소 이름은 그대로 둔다.
  - 명령은 `chaos`이고, 용어는 GLOSSARY.md를 따른다.
- **호스트** (D-5)
  - 요구하는 것은 Docker 엔진, Compose v2, uv뿐이다. make, bash, 호스트 JDK는 쓰지 않는다.
  - 서드파티 이미지는 두 아키텍처를 담은 index digest로 고정한다. impl 이미지는 엔진 아키텍처로 빌드하고, 없는 아키텍처를 에뮬레이션으로 대신하지 않는다.
  - 같은 파일과 코드로 macOS arm64와 Windows x86_64를 함께 지원하고, OS별 변형을 두지 않는다. 호스트·엔진 조합은 그곳에서 기록된 run이 있을 때만 "검증됨"으로 표시한다.
  - 하네스가 띄우는 Docker·Compose 하위 프로세스에는 다음 환경 변수만 넘긴다.
    - 허용 목록: `PATH`, `HOME`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, `SYSTEMROOT`, `TEMP`, `TMP`, `DOCKER_CONFIG`, `DOCKER_CERT_PATH`, `DOCKER_TLS_VERIFY`
    - 하네스가 명시적으로 넣는 값: 정한 엔진의 `DOCKER_HOST`, 생성된 자격 증명
  - 프로세스 생존 확인이나 사용자 데이터 디렉터리 위치 같은 OS 차이는 psutil, platformdirs 같은 서드파티 라이브러리 안에서만 처리한다.
- **데이터와 실행 코드 asset** (D-7, ADR 0001)
  - problem·scenario·impl은 언어 중립 데이터이고, problem별 Python hook이 없다.
  - JSON Schema는 Python CLI와 이후 Rust CLI가 함께 쓴다.
  - 실행 코드가 들어 있는 asset은 다음처럼 가둔다.
    - Toxiproxy API는 Toxiproxy 컨테이너 안의 loopback(`127.0.0.1`)에만 리슨하고 공개 포트가 없다. 하네스는 같은 고정 이미지에 든 `toxiproxy-cli`를 `docker exec`로 실행해 제어한다. 네트워크 분리에 기대지 않는다: 브리지 네트워크끼리 라우팅을 막지 않는 엔진(OrbStack)이 있다. (D-10)
    - WireMock admin API는 run마다 생성한 basic auth 자격 증명을 요구한다.
    - 검사 SQL은 읽기 전용 트랜잭션에서 돈다.
    - WireMock webhook과 확장 기능은 끈다.
- **환경 생성** (D-9, ADR 0001)
  - CLI가 Compose 파일을 생성한다. repeat마다 하나, run마다 관측 스택용 하나다. 손으로 쓴 problem별 Compose나 override는 없다.
  - Compose 프로젝트 디렉터리는 run 디렉터리다.
  - 이미지가 선언한 볼륨은 이름과 라벨이 붙은 볼륨으로 선언한다.
  - 생성된 자격 증명(DB, Grafana admin, WireMock admin)은 Compose 파일에 변수 참조로만 쓰고, 실제 값은 하위 프로세스 환경으로만 넘긴다.
  - 하네스 자체 마운트 파일도 `inputs/`에 스냅샷한 뒤 거기서 마운트한다.
- **lock과 정리** (D-9)
  - 같은 기기에서 lock에 기록된 프로세스가 없으면 그 run은 끝난 것이다.
  - exit 3 때의 정리 순서는 repeat 잔여물 → 관측 스택 → run 네트워크다. 소유 자원이 남으면 lock을 유지한다.
  - 나이만 보고 지우지 않고, 범용 prune을 쓰지 않는다.
- **의존성 연결** (D-10)
  - 앱의 모든 실험 의존성은 장애 계획이 없어도 Toxiproxy를 거친다.
  - 하네스의 제어 경로는 Toxiproxy를 거치지 않는다: 스크레이프, collector로 가는 텔레메트리, Docker 제어, prepare·검사 DB 접근, Toxiproxy·WireMock 관리.
  - 하네스는 DB와 관리 API에 `127.0.0.1`에 공개된 포트로 접근한다.
  - 외부 API 가짜는 고정된 WireMock 이미지와 stub 파일로 만든다. 직접 만든 가짜 서버 코드는 없다.
  - 실험용 stub에는 기본 지연을 두지 않는다. 앱 계약 테스트의 in-process WireMock 지연은 이 규칙에 해당하지 않는다.
- **관측** (D-13)
  - **수집과 저장**
    - Alloy가 유일한 수집 지점이고, otel-lgtm 하나가 저장과 화면을 맡는다.
    - Alloy는 run id 라벨로 컨테이너를 찾고(갱신 5초), run 네트워크의 관리 포트 대상만 남긴다. 그리고 모든 신호를 OTLP로 otel-lgtm 내장 collector에 보낸다.
    - 내장 collector는 파이프라인의 일부이므로, 도착 확인은 내장 collector를 거쳐 저장소에 도착한 필수 지표로 판단한다.
    - Pyroscope는 끌 수 없으므로 쓰지 않는 채로 관측 예산에 넣는다. cAdvisor는 쓰지 않는다.
  - **노출과 권한**
    - 공개 포트는 모두 `127.0.0.1`에, 엔진이 고른 포트로 연다.
    - Grafana admin 비밀번호는 run마다 생성하고, 하네스는 이 비밀번호로 서비스 계정 토큰만 만든다. annotation은 그 토큰으로 쓴다.
    - 시청자는 익명 읽기 전용이다. 비밀번호와 토큰은 결과에 남기지 않는다.
  - **수집 방식**
    - Docker stats는 컨테이너별 스트림을 동시에 읽는다.
    - 로그 드라이버는 `json-file`이다.
  - **정본**
    - 정본은 다음 넷이다: k6 원본 결과, repeat마다 내보낸 필수 지표, repeat를 정리하기 전에 Docker API로 읽은 로그, `events.jsonl`.
    - Grafana 화면과 실시간 사본은 판정 근거가 아니다.
- **결과** (D-16, D-17)
  - `results/`는 커밋한다.
  - run 시작 시점에 입력과 이미지를 고정하고, 모든 repeat가 그대로 쓴다.
  - 리포트는 Python CLI가 결과 파일만 읽어서 만든다.

### 수치

| 항목 | 값 | 위치 | 근거 |
|---|---|---|---|
| repeat 수 | 5 | 하네스 상수 | D-12 |
| 부하 | constant-arrival-rate 50 req/s, iteration당 요청 1개 | scenario | D-12, D-19 |
| warmup / measured | 30 s / 120 s, 같은 rate | scenario | D-11 |
| 장애 구간 | t0 + 40 s 적용, t0 + 80 s 해제 | scenario | D-19 |
| api-slow toxic | lookup 프록시 upstream(요청 방향) latency 2,000 ms | scenario | D-19 |
| 응답 예산 (SLO) | 500 ms. 예산 내 201 비율 ≥ 0.99, 201 p99 ≤ 500 ms. 두 impl 공통 | problem | D-15 |
| naive lookup 응답 대기 한도 | 10,000 ms | impl | D-19 |
| timeout lookup | 전체 호출 기한 300 ms(pool 획득 + 연결 + 응답), 응답 대기 한도 300 ms | impl | D-19 |
| lookup 연결 timeout | 1,000 ms (두 impl 같음) | impl | D-3 |
| HTTP client pool | 최대 50 연결, 획득 timeout 2,000 ms (두 impl 같음) | impl | D-3 |
| naive 최악 lookup 시간 | 2,000 + 1,000 + 10,000 = 13,000 ms (k6 timeout보다 짧음) | — | D-19 |
| k6 timeout / gracefulStop | 15 s / 20 s | scenario | D-11, D-12 |
| k6 VU | preAllocated = maxVUs = rate × k6 timeout × 1.2 = 900 | 하네스 상수(배수 1.2) | D-12 |
| Tomcat | max-threads 50, accept-count 100, max-connections 200 | impl | D-3 |
| JDBC | pool 10, 연결 timeout 5,000 ms | impl | D-3 |
| 관리 포트 executor | 고정 4 스레드, 앱 예산에 포함 | impl | D-8 |
| recovery | 1 s 간격, 최대 60 s, 연속 5회 | problem | D-20 |
| 자원 예산: app | 1 CPU / 512 MiB | 하네스 상수 | D-14 |
| 자원 예산: problem 의존성 | 합계 상한 1 CPU / 1 GiB. 첫 problem 배분은 Postgres 0.5 CPU / 512 MiB, Toxiproxy 0.25 / 128, WireMock 0.25 / 384 | 상한은 하네스 상수, 배분은 problem | D-14 |
| 자원 예산: impl 추가 의존성 | impl이 선언. 상한과 별도이고, 엔진 용량 검사에 포함되며, 비용으로 표시 | impl | D-14, D-17 |
| 자원 예산: k6 | 2 CPU / 1 GiB | 하네스 상수 | D-14 |
| 자원 예산: Alloy | 0.5 CPU / 512 MiB | 하네스 상수 | D-14 |
| 자원 예산: otel-lgtm | 1.5 CPU / 2 GiB | 하네스 상수 | D-14 |
| k6 포화 | measured 단계(drain 포함) 안의 어떤 연속 10 s 창에서든, k6 CPU 평균이 k6 예산(실시간 출력 포함)의 70%를 넘음 | 하네스 상수 | D-13, D-15 |
| 수집 주기 | 스크레이프 1 s, Docker stats 1 s, Alloy 탐색 5 s | 하네스 상수 | D-13 |
| 실시간 전송 | k6 push 5 s(push timeout은 k6 기본값. 고정한 k6에는 설정이 없다), annotation queue 100건·timeout 2 s | 하네스 상수 | D-13 |
| 필수 지표 누락 기준 | 기대 샘플의 95% 미만, 또는 5 s를 넘는 공백 | 하네스 상수 | D-8, D-13 |
| 시계 | 호스트·엔진 차이 ≤ 100 ms, repeat 중 드리프트 ≤ 50 ms | 하네스 상수 | D-13 |
| 장애 시각 허용 오차 | 1 s | 하네스 상수 | D-10 |
| collect 하위 한도 | quiescence 30 s, 도착 확인 30 s, 내보내기 120 s | 하네스 상수 | D-13, D-20 |
| 로그 상한 | 파일당 5 MiB, 앞 1 MiB + 뒤 4 MiB 보존 | 하네스 상수 | D-13 |
| trace 샘플링 | 1.0 | impl | D-13 |
| 단계 timeout | prepare 300 s, warmup 60 s, measured 160 s, recovery 70 s, collect 180 s, cleanup 120 s | scenario | D-11 |
| fixture | 상품 `p-001`–`p-020`, 모두 available, 가격은 결정적. k6는 seed로 상품과 수량을 고름 | problem | D-18 |

## Existing code

| Locator | Action | Obligation | Decision |
|---|---|---|---|
| `docs/PLAN.md#chaos-lab` | modify | 이번 결정과 어긋나는 내용을 모두 고쳐 쓰고, 세부 규칙은 spec과 decisions.md 링크로 대신한다 | D-1 |
| `docs/ROADMAP.md#chaos-lab` | modify | 용어, 프로젝트 이름, 이번 결정과 어긋나는 내용을 고친다 | D-1 |
| `README.md#chaos-lab` | modify | 프로젝트 이름 `chaos-lab`, 명령, 문서 링크 | D-1 |

## Seams & test plan

하네스 테스트는 `uv run pytest`로 돌린다.
- 입력 fixture는 테스트마다 임시 디렉터리에 저장소 형태(`chaos-contract.yaml`, `problems/`)로 복사하고, 그곳을 현재 디렉터리로 삼아 CLI를 실행한다.
- Docker를 쓰지 않는 테스트는 엔진 클라이언트 경계 하나를 가짜로 바꾼다. 엔진 정보와 모든 Docker·Compose 호출이 이 경계를 지나며, 가짜는 호출을 순서대로 기록한다.

**입력 검증** (example), AC-3, AC-4, AC-5, AC-12
- "실행 전 거부" 목록의 항목마다 fixture를 만들어 다음을 확인한다.
  - exit 2와 거부 이유가 나온다.
  - 엔진 클라이언트 호출이 0회다.
  - 결과 디렉터리가 생기지 않는다.
- 커밋된 모든 스키마 예시 파일을 기대대로 판정하는지 확인한다.
- `clean`의 exit 2 경우를 확인한다.

**입력 검증** (property, Hypothesis), AC-3, AC-5
- 무작위 id 문자열과 YAML 스칼라로 id 규칙과 YAML 거부 규칙을 확인한다.
- 끝 줄바꿈, 제어 문자, 예약어, 길이, 앞자리 0을 포함한다.

**실행 흐름과 종료 코드** (example, 가짜 엔진 클라이언트), AC-2, AC-6, AC-7, AC-9, AC-11, AC-15, AC-16, AC-18, AC-21, AC-33
- 호출 순서:
  - 단계 순서, 해당 없는 단계의 이유
  - warmup 뒤 quiescence → 비우기 → 경계 → measured
  - 첫 스크레이프 확인 뒤 warmup
  - 이전 repeat 삭제 확인 뒤 다음 repeat 생성
  - repeat마다 다른 프로젝트 이름
  - 빌드는 단계 timeout과 별도로 기록
- 종료 코드:
  - invariant fail만 있으면 exit 0. SLO miss만, correctness unknown만, SLO unknown만 있어도 exit 0
  - invalid만 있으면 exit 1
  - invalid와 incomplete가 함께 있으면 3
  - 단계 timeout은 incomplete가 되고 다음 repeat로 계속
  - 컨테이너가 시작된 뒤 준비 상태에 이르지 못한 경우와 비정상 종료한 경우는 각각 incomplete(validity unknown)가 되고, 정리 후 다음 repeat로 계속
  - 컨테이너 생성·시작 API 오류는 exit 3으로 중단
  - warmup quiescence 실패는 invalid로 기록되고 나머지 단계를 계속
  - `run.json` 확정과 `report.html` 작성이 정리 뒤에 일어남
  - Docker 호출 오류, 장애 API 실패, 용량 부족(lock 해제 포함), 삭제 실패는 exit 3
- 정리:
  - 정리에 성공하면 라벨 자원이 0개
  - 정리에 실패하면 lock이 유지되고 다음 run이 거부됨
- 예측과 입력:
  - 예측 사건이 measured보다 앞섬
  - 원본을 바꿔도 다시 읽지 않음
  - 해시 기록
  - 예측이 있든 없든 validity가 같음
  - 표준 입력이 닫혀 있어도 동작

**Compose와 k6 설정 생성** (example, 기대 파일 비교), AC-8, AC-13, AC-17, AC-20, AC-37
- manifest와 descriptor로 생성한 Compose와 k6 옵션을 기대 파일과 비교한다. 비교 대상:
  - run 디렉터리 기준 상대 경로, `inputs/` 마운트
  - 라벨, 런타임 값 참조 치환, 프록시 경로
  - Toxiproxy API 리슨 주소(loopback)와 공개 포트 없음
  - 자격 증명은 변수 참조로만 들어감
  - constant-arrival-rate와 rate·VU 값
  - probe scenario의 시작 시각(t0 + 80 s), 1초 간격, 62초 길이
- `DOCKER_DEFAULT_PLATFORM`, `COMPOSE_FILE`, `COMPOSE_PROFILES`, `.env`를 설정해도 생성 결과가 같은지 확인한다.
- 하위 프로세스 환경이 허용 목록과 같은지 확인한다.

**판정** (example, fixture 결과 파일), AC-17, AC-19, AC-22, AC-23, AC-24, AC-25, AC-26, AC-36
- 아래 fixture마다 기대 판정을 확인한다.
- 불변식:
  - 위반 1–6 각각
  - ambiguous 두 종류, rollback이 기록된 500 주문
  - 경계 위반
  - 증거 누락으로 인한 unknown
- SLO:
  - met, missed(비율), missed(p99), 201 0건, 발행 0건, 증거 누락
  - 구간 나누기(실제 장애 시각 기준)
- latency 표본: k6 timeout 요청과 잘린 iteration이 개수·이유와 함께 기록되고 성공 latency에서 빠짐
- validity:
  - 잘린 iteration, dropped, 포화 창
  - `up=0`, 필수 지표 누락(95%·5 s 공백)
  - 내보내기 timeout, 필수 파일 누락
  - 장애 시각 어긋남, 시계 초과·드리프트, 시각 변환
- recovery:
  - 회복 실패, time-to-recovery 계산
  - 해제 전 probe 제외, probe의 measured 제외
  - 실제 해제가 늦은 경우의 판정 창
  - 다섯 번째 성공이 창 안에서 발행됐지만 응답이 창이 닫힌 뒤 도착하면 회복이 아님
- live degraded만 있는 경우
- unknown correctness와 unknown SLO가 통계에 남는지
- 확인된 위반과 증거 누락이 함께 있으면 fail이고 위반이 각각 기록되는지
- 도착 확인 실패가 invalid인지

**annotation 비차단** (example), AC-26
- 응답하지 않는 가짜 Grafana를 두고, 장애 적용 호출 시각이 늦어지지 않는지 확인한다.

**집계** (example + property, Hypothesis), AC-27
- 중앙값(짝수 n), CV, 미산출 조건, 지표별 n을 확인한다.
- 요청을 합치지 않는지 확인한다.

**로그 상한** (example), AC-35
- 다음 입력에서 보존 범위와 잘림 표시를 확인한다.
  - 상한 경계
  - 여러 바이트 UTF-8 글자가 경계에 걸린 경우
  - 잘못된 바이트
  - ANSI 코드

**리포트** (example, 세 scenario와 부분 run의 fixture 결과), AC-35, AC-39, AC-40, AC-41
- 출력:
  - `report.html`과 `chaos report` 출력이 바이트 단위로 같음
  - 결과 디렉터리가 바뀌지 않음
  - 새 `reports/` 파일 이름과 출력된 경로
- 비교: 비교 거부, `--allow-cross-env` 표시
- 표시 항목:
  - 지표별 n과 제외 이유, n<5·CV>10% 표시
  - 예측, impl description과 비용
  - 관측 스택 사용량과 한계
  - 재현 명령 형식, 해당 없는 항목 표시
- 스키마 버전 읽기
- `report`와 `clean`의 종료 코드

**결과 디렉터리와 신원** (example, 가짜 엔진 클라이언트 + 임시 git 저장소), AC-38
- 이름 충돌 시 새 접미사로 만드는지 확인한다.
- 신원 항목이 모두 들어가는지 확인한다.
- dirty 표시와 patch를 확인한다.
- `results/`·`reports/`·`.wf-grill/`이 빠지는지 확인한다.

**lock과 정리** (example, 실제 Docker), AC-10, AC-11, AC-12
- 저장소를 두 곳에 복사했을 때 두 번째 run이 거부되는지
- 정리 실패를 주입했을 때 lock이 유지되는지
- `clean`이 살아 있는 run을 건너뛰는지
- `clean --run`이 살아 있는 run을 거부하는지
- 사용자 decoy 컨테이너·볼륨과 다른 run의 자원이 남는지

**앱 계약** (example, Compose로 띄운 Gradle 컨테이너 테스트), AC-28, AC-29, AC-30, AC-32
- 구성: PostgreSQL 컨테이너, 앱 테스트 안의 in-process WireMock. pytest가 실행한다.
- 확인할 것:
  - 판정 순서 표의 모든 행
  - 순서가 충돌하는 경우(예: 깨진 본문의 `available=false`)
  - 오류 응답 시 주문을 저장하지 않음
  - lookup 지연 중 JDBC active가 0
  - readiness가 lookup과 독립
  - 두 impl의 resolved 설정 비교, virtual threads 꺼짐

**전체 실행** (e2e, 실제 Docker, macOS arm64), AC-1, AC-8, AC-13, AC-14, AC-19, AC-20, AC-25, AC-30, AC-31, AC-33, AC-34, AC-35, AC-36, AC-37, AC-43
- 6개 조합을 실제로 돌린다. 한 번은 `DOCKER_DEFAULT_PLATFORM`과 `.env`를 둔 상태로 실행한다.
- 6개 run 사이의 일관성: 명령 형태, 결과 구조, 리포트 레이아웃이 같다.
- 실행 기록:
  - 단계 기록, 장애 시각, recovery
  - topology·프록시 기록
  - 저장한 `compose.yaml`의 해시, 결과에 기록된 이미지 ID와 resolved 설정
  - 스크레이프 대상 목록, 시계 기록
- 앱과 관측:
  - naive api-slow에서 `tomcat_threads_busy`가 `tomcat_threads_config_max`와 같은 동안 관리 포트의 readiness와 지표 응답이 성공함
  - probe 요청의 발행 간격과 연속 5회 성공 뒤 멈춤
  - 필수 지표와 라벨 이름(request id 없음)
- 격리와 보안:
  - 앱·k6 컨테이너에서 Toxiproxy API로 연결이 실패함
  - 공개 포트가 `127.0.0.1`에만 묶임
  - 하네스가 생성한 결과 파일 전체(`inputs/` 사본과 dirty patch 제외)에 금지 문자열(홈 경로, 호스트 이름, 생성된 자격 증명, 토큰)이 없음

**중단** (e2e), AC-18
- measured load 중 인터럽트를 보낸다.
- 부분 결과, 실행하지 않은 repeat 기록, 부분 `report.html`, 정리, exit 3을 확인한다.

**관측 화면** (manual), AC-34
- run 중 출력된 주소를 연다.
- 익명 읽기 전용인지, `admin/admin` 로그인이 실패하는지 확인한다.
- 대시보드 각 패널, annotation, 추정치 표시를 확인한다.

**저장소 점검** (example + manual), AC-14, AC-42
- example:
  - OS 판별 분기 검색
  - OS별 스크립트 확장자와 Gradle wrapper 검색
  - `.gitattributes`·`.gitignore` 규칙 확인
- manual:
  - 세 문서에서 금지어 검색
  - PLAN 검토

## Out of scope

- 동시성 problem(PLAN의 A1 재고 경합), Java 21 vs 25 비교, virtual threads 비교 (D-1, D-3)
- retry, circuit breaker, bulkhead, 호출 중 트랜잭션을 유지하는 impl (D-19)
- 결제·멱등성 problem과 그 불변식 (D-18)
- DB 장애 scenario, 앱 kill·포화 scenario (D-9, ADR 0001)
- OTel Java agent 켜고 끄기에 따른 오버헤드 실험 (D-3)
- 안정성 기반 warmup. D-11의 provisional default를 바꿀 때 다룬다
- repeat 사이의 in-place DB 리셋. D-9의 provisional default를 바꿀 때 다룬다
- Rust CLI·데스크톱 앱, Rust 리포트 생성기 (D-17)
- Windows에서의 검증 run. 완료 조건이 아니다 (D-2)
- 여러 run을 동시에 돌리기, Linux 호스트 지원 (D-5, D-9)
- `up`, `down`, `check` 같은 추가 명령 (D-6)
- 클라이언트(k6)가 기다리다 포기한 뒤에 앱의 DB commit을 취소하는 것. 알려진 한계로 두고, 이런 주문은 ambiguous로 보고한다 (D-19, D-20)
