# 하네스 (experiment-harness) 결정 사항

Glossary: [GLOSSARY.md](../../../GLOSSARY.md) · ADRs: [0001](../../adr/0001-problems-as-data-generated-compose.md)

## D-1 이 기능의 범위
- Status: settled
- Decision: 하네스(CLI, 데이터 형식, 환경 생성, run 수명 주기, 판정, 결과, 리포트)와 첫 problem 하나, "외부 HTTP API가 느려지거나 죽는다"를 만든다. 동시성 주제는 나중에 다룬다. PLAN, ROADMAP, README는 이 결정에 맞춰 고치고, PLAN은 규칙을 복제하지 않고 spec을 링크한다(spec: Existing code).
- Rejected: harness + A1 stock contention + naive/atomic-update (PLAN season0) → 사용자는 주요 scenario를 먼저 끝내고 어려운 동시성 주제는 나중에 다루기를 원한다 · harness만 만들기 → 실제로 end to end로 돌아가는 것이 없다

## D-2 완료 기준
- Status: settled
- Decision: 첫 problem의 모든 scenario × impl이 명령 하나로 실행되고 같은 리포트를 렌더링하면, macOS arm64에서 검증 run을 하나 기록한 뒤 완료로 본다. 플랫폼 동등성은 설계상의 의무다. 코드 경로는 하나이고 OS별 부분은 없다. 플랫폼마다 검증 run을 따로 기록할 필요는 없다.
- Rejected: Windows에서 기록한 run을 완료 조건으로 요구 → 사용자는 Mac과 Windows PC를 오가며 쓰고, OS별 부분이 없기를 원하며, 플랫폼별 공식 승인을 원하지 않는다 · Windows 전용 또는 Mac 전용 스크립트나 설정 → 사용자가 피하려는 바로 그것이다

## D-3 스택
- Status: settled
- Decision: Spring Boot 4, Java 21, JdbcTemplate, PostgreSQL READ COMMITTED, JDBC pool 10, platform thread 위의 동기 MVC를 쓴다. 서버, 클라이언트, pool 설정은 고정하고 모든 impl에서 똑같이 둔다. 다만 각 impl을 정의하는 lookup 대기 정책만 다르게 둔다. 추적은 Spring Boot 4 OpenTelemetry starter로 하고 Java agent는 쓰지 않는다.
- Rejected: OpenTelemetry Java agent → agent가 executor를 바이트코드 수준에서 계측하는데, 그 executor가 바로 thread 고갈 실험의 대상이다. agent를 켜고 끄는 비교는 나중 실험으로 미룬다 · Java 25를 지금 사용 → Java 21과 25의 비교는 나중 실험이다 · virtual thread 켜기 → 스레드 모델은 별도의 나중 변수다 · framework 기본값 → 버전이 바뀌면 조용히 달라질 수 있다

## D-4 이름과 용어
- Status: settled
- Decision: 일본어에서 온 이름은 쓰지 않는다. 프로젝트 이름 `chaos-lab`은 문서에서만 쓰고, CLI는 `chaos`로 한다. problem, scenario, impl, run, repeat는 GLOSSARY.md의 정의대로 쓴다.
- Rejected: `dojo` CLI, "kata" → 사용자가 기각했다 · `drill` → 도구처럼도, problem 계열처럼도 읽힌다

## D-5 호스트 요구 사항과 플랫폼
- Status: settled
- Decision: 호스트에는 Docker(Compose v2)와 uv만 있으면 된다. 나머지는 버전을 고정한 multi-arch 컨테이너에서 돈다. macOS arm64와 Windows x86_64는 같은 파일과 코드를 쓰며 OS별 변형이 없다. 파일과 환경 규칙으로 run이 호스트 설정과 무관하게 독립적으로 돌도록 한다.
- Rejected: 호스트에 JDK나 k6를 직접 설치 → OS마다 설정이 갈라진다 · Linux 호스트를 지금 대상으로 삼기 → 아직 필요하지 않다

## D-6 CLI 표면과 종료 코드
- Status: settled
- Decision: 명령은 세 개다. `run <problem>/<scenario> --impl <impl> [--predict]`, `report`, `clean [--run]`. 종료 코드는 모든 problem에서 같은 의미로 고정하며, 프롬프트는 띄우지 않는다.
- Rejected: Makefile 진입점 → 기본 상태의 Windows에는 make가 없다 · up/down/check 명령 → 아직 필요하지 않다 · correctness 실패 시 0이 아닌 종료 코드 → 탐지된 약점은 예상된 결과다

## D-7 problem을 데이터로 두기와 탐색 규칙
- Status: settled
- Decision: problem, scenario, impl은 언어에 중립적인 데이터이며, 정해진 디렉터리 규칙 아래에 둔다. 커밋된 버전 관리 JSON Schema로 검증하고, 이 스키마는 Python CLI와 앞으로 만들 Rust CLI가 함께 쓴다. YAML은 strict하게 파싱하고 id와 경로 규칙을 엄격히 적용하며, 실행 가능한 자산은 정해진 범위 안에만 둔다. 잘못된 입력은 어떤 자원도 만들기 전에 거부한다. 새 요구는 공통 어휘와 계약 버전을 늘려서 반영한다.
- Rejected: 저장소 전체에서 scenario id를 유일하게 → 모든 problem이 `baseline` 같은 이름을 원하므로, problem을 하나 추가하면 다른 problem이 깨진다 · YAML 1.1 파싱(PyYAML 기본값) → `no`, `off`, `010`이 Python CLI와 Rust CLI에서 서로 다른 뜻이 된다 · 실행할 때마다 저장소의 모든 manifest를 검증 → 작업 중인 problem 하나가 모든 run을 막는다 · problem별 Python 모듈이나 hook 파일 → Rust 재작성과 같은 명령 규칙을 깨뜨린다 · 루트 registry 파일 → 시간이 지나면 실제 파일과 어긋난다 · 형식 문서를 markdown으로만 작성 → Python의 우연한 동작이 사실상 계약이 된다
- ADR: [0001](../../adr/0001-problems-as-data-generated-compose.md)

## D-8 impl descriptor와 이미지 계약
- Status: settled
- Decision: `--impl`은 exec hook이 없는 선언형 descriptor로 풀린다. descriptor에는 image, 시작 설정, 선언된 환경 변수, 추가 의존성, provenance가 들어간다. 앱은 업무 트래픽을 한 포트에서 처리하고, readiness와 metrics는 별도의 management 포트에서 작은 전용 executor로 처리한다. 워커가 고갈되어도 관측이 살아 있게 하려는 것이다. 필수 metrics는 고정하며, 하나라도 없으면 run이 invalid가 된다. 첫 problem의 두 impl은 이미지 하나를 공유한다.
- Rejected: impl마다 Dockerfile과 image를 하나씩 두는 것을 하네스 규칙으로 → provenance나 impl별 의존성에 필요하지 않다 · metrics를 업무 포트에 두기 → naive가 api-slow에서 Tomcat 워커를 모두 소진하면 scrape가 실패한다

## D-9 환경 생성과 격리
- Status: provisional
- Decision: CLI가 repeat마다 manifest로부터 새 Compose 프로젝트를 만들고(run마다 관측 스택 하나), 생성한 파일을 그대로 저장한다. repeat끼리는 DB 상태를 공유하지 않는다. Docker 엔진 하나에서는 원자적 엔진 lock으로 run을 하나만 돌린다. cleanup과 `clean`은 하네스가 만든 자원만 건드린다.
- Default: repeat마다 새 환경을 쓴다. 준비 시간 측정값이 병목이고 reset 완전성 검사가 정의되었을 때에만 제자리 reset(in-place reset)을 다시 검토한다.
- Rejected: 오래 살아 있는 컨테이너에서 repeat 사이에 DB를 reset → reset이 완전하다는 것을 증명하지 못했다 · 동시 run → CPU와 메모리 경합이 결과를 흐린다
- ADR: [0001](../../adr/0001-problems-as-data-generated-compose.md)

## D-10 의존성 연결과 장애
- Status: settled
- Decision: 앱의 외부 의존성은 모두 장애를 계획했는지와 상관없이 Toxiproxy를 거친다. Toxiproxy는 타임라인에 따라 네트워크 장애를 넣는다. 외부 API는 버전을 고정한 WireMock 이미지와 stub 데이터로 흉내 낸다. 하네스 자신의 경로는 프록시하지 않는다.
- Rejected: 장애가 걸리는 경로에만 proxy를 두기 → baseline과 fault run의 네트워크 경로가 달라진다 · 하네스가 직접 만든 가짜 API 하나 → 결제 같은 의미는 status code만으로 표현할 수 없다 · Toxiproxy API를 하네스 전용 네트워크에 두기 → OrbStack 같은 일부 엔진은 bridge 네트워크 사이를 라우팅해서 앱과 k6가 API에 닿았다. 그래서 API는 컨테이너 loopback에서만 리슨하고, 하네스는 `docker exec toxiproxy-cli`로 제어한다

## D-11 run 수명 주기
- Status: provisional
- Decision: 모든 scenario가 같은 고정 phase 순서를 따르며, phase마다 timeout이 있다. warmup이 끝나면 quiescence 경계를 두고, measured load가 끝나면 제한된 시간의 drain을 둔다. interrupt나 실패가 나면 부분 결과를 기록한다. phase timeout을 넘긴 repeat는 불완전으로 기록하고 정리한 뒤 run을 계속하며, run은 exit 3으로 끝난다.
- Default: manifest에 선언한 고정 warmup 시간을 쓴다. 모든 impl에서 같고, `warmup_policy=fixed`로 기록한다. 안정성을 검증했다고 주장하지 않는다. 첫 백엔드의 데이터가 어떤 지표와 구간을 써야 하는지 보여 주면, 그때 안정성 규칙으로 다시 검토한다.
- Rejected: 지금 안정성 기반 warmup을 쓰기 → 지표, 구간, 허용 오차를 아직 정하지 않았다

## D-12 부하 모델과 집계
- Status: settled
- Decision: 고정 rate와 고정 기간의 open model constant-arrival-rate 부하를 쓴다. 지표는 repeat마다 계산하고, 완료되고 유효한 repeat들의 중앙값(median)으로 집계한다. repeat끼리는 합치지 않는다(pool). 누락되었거나 중간에 끊긴 iteration이 있으면 그 repeat는 invalid다.
- Rejected: repeat 사이에 요청을 합치기 → 분산을 가리고, 일부 repeat에 가중치가 쏠린다

## D-13 관측과 지표 수집
- Status: settled
- Decision: Grafana Alloy가 유일한 수집 지점이다. 버전을 고정한 `grafana/otel-lgtm` 하나가 metrics, logs, traces를 저장하고 실시간으로 보여 주며, localhost에만 바인딩한다. 정식 증거(k6 원본 출력, 내보낸 앱 metrics, 컨테이너 로그, 이벤트)는 repeat가 끝날 때마다 결과 파일로 내보낸다. 저장하는 로그에서는 AC-37이 금지한 문자열만 치환한다. 리포트는 파일만 읽는다. 실시간 사본은 판정에 쓰지 않는다.
- Rejected: k6 remote-write push에 2 s timeout을 두기 → 고정한 k6에는 그런 설정이 없다. push는 부하 생성과 분리되어 실행되므로, push가 느려도 실시간 사본만 degraded로 표시된다 · 컨테이너 로그를 바이트 그대로 저장 → 컨테이너 label에 절대 작업 디렉터리가 들어가서 홈 경로가 커밋된 결과에 노출된다 · Prometheus가 앱을 직접 scrape하고 collector는 두지 않기 → 로그와 trace는 별도 경로가 필요하다. 사용자는 세 신호를 collector 하나로 모으기를 원했다 · Prometheus, Loki, Tempo, Grafana를 각각 컨테이너로 → 같은 로컬 화면을 위해 컨테이너가 네 개 필요하다. otel-lgtm의 쓰지 않는 부분이 그보다 싸다 · traces를 필수 증거로 → 완전성이 sampling, buffer, impl이 HTTP client를 만드는 방식에 달려 있다 · PLAN의 Prometheus + cAdvisor → OrbStack과 WSL2에서 cAdvisor는 검증되지 않았고, Docker stats와 중복된다 · repeat마다 관측 스택을 띄우기 → trace, 로그, 실시간 화면이 repeat 사이에 사라진다 · 리포트를 만들 때 백엔드를 읽기 → 백엔드가 없으면 리포트를 다시 만들 수 없다

## D-14 자원 예산
- Status: settled
- Decision: 모든 컨테이너에 고정된 유한 CPU와 메모리 한도를 둔다. k6와 관측 스택도 포함한다. 모든 problem이 공유하는 값은 버전이 붙은 하나의 하네스 계약 파일에 두며, 이 파일은 비교 식별자(comparison identity)의 일부다. 엔진이 감당할 수 없는 run은 시작 전에 거부하고, 한도를 줄여서 실행하지 않는다.
- Rejected: 앱에만 한도를 두기 → 포화(saturation)의 분모가 호스트마다 달라진다

## D-15 판정 축
- Status: settled
- Decision: repeat마다 네 가지 판정(completion, measurement validity, correctness, SLO)을 따로 낸다. SLO는 두 부분으로 이뤄진다. 허용 시간 안에 성공한 요청의 비율과, 성공 요청의 p99다. 완료되고 유효한 repeat만 통계에 들어간다. correctness나 SLO가 unknown이라고 해서 repeat가 빠지지는 않는다.
- Rejected: SLO 위반을 correctness 실패로 기록 → "느림"과 "틀림"이 섞인다 · 지연 시간만 보는 SLO → 빠르게 실패하는 요청이 이기게 된다

## D-16 결과, 식별자, git
- Status: settled
- Decision: run마다 커밋된 `results/` 아래에 새 디렉터리를 만든다. 이 디렉터리는 덮어쓰지 않는다. 모든 이미지와 입력의 정확한 식별자를 기록한다. 변경이 남은(dirty) 트리도 허용하되 표시한다. 입력은 run 시작 시점에 고정한다.
- Rejected: git이 무시하는 results와 수동 승격 → 사용자가 결과를 커밋하기로 했다 · dirty 트리 거부 → 빠른 반복 작업 흐름이 느려진다

## D-17 리포트와 비교
- Status: settled
- Decision: Python CLI는 모든 scenario에 같은 HTML 리포트 레이아웃을 쓰며, 저장된 결과 파일만 읽어서 만든다. `chaos report`는 git이 무시하는 `reports/` 아래에 새 파일을 쓰고, 결과 디렉터리는 건드리지 않는다. 비교하려면 식별자가 일치해야 한다. 환경이 다른 결과를 함께 보여 줄 때는 순위를 매기지 않는다.
- Rejected: 별도의 Rust 리포트 생성기를 지금 만들기(PLAN week 4) → Rust CLI로 재작성하기 전까지는 언어를 하나로 유지한다 · `run`이 impl 여러 개를 받기 → run은 impl 하나로 유지해서 각각 독립적으로 보존한다

## D-18 첫 problem: API와 데이터 계약
- Status: settled
- Decision: `POST /orders`는 트랜잭션 바깥에서 외부 API로 가격과 재고를 조회한 뒤, 짧은 트랜잭션 하나로 주문을 저장하고 201로 응답한다. 모든 실패는 공통 RFC 9457 problem 타입으로 매핑하며, 이때 주문을 저장하지 않는다. problem은 app, k6, stub, checker가 공유하는 OpenAPI 계약을 커밋한다. k6는 각 요청에 cohort를 담은 header를 붙이고, 앱은 이 header를 lookup 요청에 전달하며 metric label로도 쓴다.
- Rejected: 주문 저장과 외부 결제를 함께 → 시간 초과된 결제는 결과를 알 수 없다(멱등성과 대사는 나중 problem이다) · DB를 쓰지 않는 읽기 전용 견적 → JdbcTemplate과 저장 상태 기반 판정이 쓰이지 않는다

## D-19 첫 problem: scenario와 impl
- Status: settled
- Decision: scenario 세 개(baseline, api-slow, api-down)가 workload와 topology를 공유한다. impl 두 개는 이미지 하나에 담는다. `naive`는 길고 명시적인 lookup 한도를, `timeout`은 짧은 deadline을 쓴다. 숫자는 spec에 있다.
- Rejected: naive를 라이브러리 기본값인 무한 timeout으로 → k6가 먼저 요청을 끊어서 지연 시간 측정이 잘린다(censor) · baseline을 장애 전 구간에서 가져오기 → 시간 효과와 warmup 효과가 섞인다 · api-slow 지연을 downstream(응답) 스트림에 주기 → 고정 버전 Toxiproxy에서는 호출을 포기한 클라이언트(300 ms에서 끊는 timeout impl)가 지연된 chunk를 남겨서, toxic을 영원히 제거할 수 없게 된다. 요청 스트림에 지연을 주면 응답도 같은 2 s만큼 늦어지지만 이런 hang은 생기지 않는다

## D-20 첫 problem: 불변식과 복구
- Status: settled
- Decision: 불변식은 복구와 quiescence가 끝난 뒤 일관된 snapshot에서 한 번 검사한다. 클라이언트가 확정 응답을 받지 못한 주문은 위반이 아니라 ambiguous로 따로 보고한다. 복구 probe는 남은 측정 부하와 함께, 계획된 제거 시점부터 1초마다 보낸다. 확정된 제거 시점부터 복구 시간(time-to-recovery)을 1초 단위로 잰다. ambiguous 주문이 있고 위반이 없는 repeat는 correctness 통과로 보되, ambiguous 수를 함께 보여 준다.
- Rejected: 측정 부하가 끝난 뒤에야 probe를 시작 → 복구 시간이 항상 남은 부하 구간보다 길게 나온다 · ambiguous 주문 때문에 correctness를 unknown으로 두기 → naive의 api-slow repeat 거의 전부가 비교에서 빠진다 · phantom check(클라이언트 timeout과 주문이 함께 있으면 모두 위반으로 보기) → 응답이 유실되었다고 해서 서버가 실패한 것은 아니다(RFC 9110 §9.2.2)

## D-21 절대 일어나면 안 되는 것
- Status: settled
- Decision: 다음 일은 절대 일어나면 안 된다. 불완전하거나 포화된 측정에 대해 유효한 판정을 내리는 것, 적용되지 않은 장애를 장애 run으로 보고하는 것, 숨겨진 위반, 덮어쓰거나 버린 결과, problem마다 다른 명령이나 리포트 모양, 다른 자원의 정리, 판정 근거로 쓰인 실시간 대시보드, 그리고 spec에 나열된 첫 problem의 위반 사항이다.
