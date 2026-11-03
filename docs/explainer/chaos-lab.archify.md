# chaos-lab은 어떻게 돌아가는가 {#chaos-lab-how}

chaos-lab은 YAML로 정한 부하·장애 조건을 매번 새 Docker 환경에서 반복 실행하고, backend impl들의 응답과 저장 결과를 같은 기준으로 비교하는 실험 하네스다.

- 실험 조건은 코드가 아니라 데이터다. problem·scenario·impl이 모두 YAML이고, 하네스 Python 코드는 problem을 모른다.[](source:adr-0001)
- Compose 파일은 손으로 쓰지 않는다. `chaos/compose.py`가 repeat마다 생성하고, 앱은 그 안의 Toxiproxy를 거쳐 DB와 상품 API에 닿는다.[](source:compose-resolve)
- repeat 하나는 7단계다. measured 부하가 도는 도중 정해진 시각에 장애를 넣고 뺀다.[](source:runner-repeat)
- 결과는 판정 4개와 원시 기록으로 `results/<run-id>/`에 남는다. 실패하거나 중단된 run도 지우지 않는다.[](source:status)

@answer scope="현재 코드: 커밋 2065d36 · 실측: api-slow run 2개(naive 2c0c93, timeout 8def62)의 repeat 1 · 두 run은 재현 빌드 이전 기록이라 앱 이미지 동일성은 증명되지 않음"
@meta locale=ko repo_url=https://github.com/kanggihoo/chaos-dojo repo_revision=2065d36a332c769d11617f86cd418af3c565308d
@source adr-0001 title="ADR 0001: problem은 데이터, Compose는 생성" path=docs/adr/0001-problems-as-data-generated-compose.md
@source status title="진행 현황 STATUS.md" path=docs/STATUS.md
@source glossary title="용어 GLOSSARY.md" path=GLOSSARY.md
@source contract title="하네스 상수 chaos-contract.yaml" path=chaos-contract.yaml lines=1:23
@source problem title="problem.yaml (external-api)" path=problems/external-api/problem.yaml lines=1:41
@source scenario-slow title="scenario.yaml (api-slow)" path=problems/external-api/scenarios/api-slow/scenario.yaml lines=1:14
@source impl-naive title="impl.yaml (naive)" path=problems/external-api/impls/naive/impl.yaml lines=15:18
@source compose-resolve title="compose.resolve_value: 참조를 Toxiproxy 주소로 치환" path=chaos/compose.py lines=32:45
@source compose-repeat title="compose.repeat_compose: repeat용 Compose 생성" path=chaos/compose.py lines=52:115
@source compose-generated title="생성된 compose.yaml (naive repeat 1, app 서비스)" path=results/20261031-004309-external-api-api-slow-naive-2c0c93/repeats/1/compose.yaml lines=90:99
@source runner-execute title="Run.execute: 이미지 → 관측 스택 → repeat 5회" path=chaos/runner.py lines=388:429
@source runner-repeat title="Repeat.run: 7단계" path=chaos/runner.py lines=626:651
@source runner-warmup title="Repeat.warmup: 경계와 초기화" path=chaos/runner.py lines=851:870
@source runner-fault title="Repeat.fault_schedule: 장애 적용·해제" path=chaos/runner.py lines=926:959
@source runner-k6 title="Repeat.k6_config: cohort와 probe" path=chaos/runner.py lines=773:798
@source orders-controller title="OrdersController.create" path=problems/external-api/app/src/main/java/lab/chaos/orders/OrdersController.java lines=48:104
@source lookup-find title="Lookup.find와 실패 분류" path=problems/external-api/app/src/main/java/lab/chaos/orders/Lookup.java lines=80:121
@source lookup-deadline title="Lookup.DeadlineFactory: 300 ms 뒤 호출 취소" path=problems/external-api/app/src/main/java/lab/chaos/orders/Lookup.java lines=136:156
@source verdict-latency title="verdict.latency_summary: k6 timeout(1050) 분류" path=chaos/verdict.py lines=32:44
@source verdict-invariants title="verdict.invariants: ambiguous 판정" path=chaos/verdict.py lines=95:151
@source repeat-naive title="repeat.json (naive repeat 1)" path=results/20261031-004309-external-api-api-slow-naive-2c0c93/repeats/1/repeat.json
@source repeat-timeout title="repeat.json (timeout repeat 1)" path=results/20261031-002528-external-api-api-slow-timeout-8def62/repeats/1/repeat.json
@source run-naive title="run.json (naive run)" path=results/20261031-004309-external-api-api-slow-naive-2c0c93/run.json
@source k6-naive title="k6 요청별 기록 (naive repeat 1)" path=results/20261031-004309-external-api-api-slow-naive-2c0c93/repeats/1/k6/measured.jsonl
@source k6-timeout title="k6 요청별 기록 (timeout repeat 1)" path=results/20261031-002528-external-api-api-slow-timeout-8def62/repeats/1/k6/measured.jsonl

## 실험 조건은 어디에 정의되고, 결과는 어디에 남나? {#where}

@tree id=repo-layout title="저장소와 결과 폴더"
| root | chaos-dojo | - |
| cli | chaos/ 하네스 CLI | root |
| contract | chaos-contract.yaml 공통 상수 | root |
| schemas | schemas/ YAML 검증 규칙 | root |
| harness | harness/ Alloy·Grafana·k6 wrapper | root |
| problems | problems/ 실험 과제 | root |
| extapi | external-api | problems |
| pyaml | problem.yaml 의존성·SLO·불변 조건 | extapi |
| scen | scenarios/ 부하·장애 조건 | extapi |
| sbase | baseline | scen |
| sslow | api-slow | scen |
| sdown | api-down | scen |
| impls | impls/ 구현 선택지 | extapi |
| inaive | naive | impls |
| itimeout | timeout | impls |
| app | app/ Spring Boot 주문 API | extapi |
| k6js | k6/orders.js 요청 생성 | extapi |
| stubs | stubs/ WireMock 상품 응답 | extapi |
| tests | tests/ pytest | root |
| results | results/ 실행 기록 | root |
| runid | run-id 폴더 | results |
| inputs | inputs/ 입력 스냅샷 | runid |
| runjson | run.json 5회 집계 | runid |
| report | report.html | runid |
| repeats | repeats/N | runid |
| rcompose | compose.yaml 생성물 | repeats |
| rjson | repeat.json 판정 | repeats |
| rk6 | k6/ 요청별 원시 기록 | repeats |
| rdb | db-snapshot.json | repeats |

| 구분 | 위치 | 누가 만드나 |
| --- | --- | --- |
| 원본 설정 | `problems/`, `chaos-contract.yaml`, `harness/` | 사람이 작성하고 커밋 |
| 생성물 | `results/<run-id>/repeats/N/compose.yaml`, `run-compose.yaml` | `chaos run`이 매번 생성 |
| 입력 스냅샷 | `results/<run-id>/inputs/` + `inputs-sha256.json` | 실행 시작 때 원본을 복사하고 해시를 남김 |
| 판정과 원시 기록 | `run.json`, `repeats/N/repeat.json`, `k6/`, `logs/`, `db-snapshot.json` | 실행 중 수집, 끝나고 판정 |

scenario와 impl은 부모·자식이 아니라 같은 problem 아래의 두 선택 축이다. scenario 하나와 impl 하나를 고른 조합을 실행한 것이 run이고, run은 매번 새 환경에서 repeat를 5회 돈다.[](source:contract)

| scenario \ impl | naive (최대 10 s 대기) | timeout (300 ms에서 끊음) |
| --- | --- | --- |
| baseline (장애 없음) | run | run |
| api-slow (t0+40~80 s, lookup +2,000 ms) | run {good:5회 완주} | run {good:5회 완주} |
| api-down (t0+40~80 s, lookup 차단) | run | run |

## 실행 중에는 무엇이 무엇과 연결되나? {#topology}

@architecture id=runtime-topology title="repeat 하나의 컨테이너 연결"
| cli | chaos CLI (호스트) | backend |
| k6 | k6 부하 생성기 | frontend |
| app | 주문 API | backend |
| toxi | Toxiproxy | security |
| pg | PostgreSQL | database |
| wm | WireMock 상품 API | external |
| alloy | Alloy 수집기 | messagebus |
| lgtm | Grafana LGTM | cloud |
| cli > k6 | 부하 시작 | |
| k6 > app | POST /orders | emphasis |
| app > toxi | lookup·DB | emphasis |
| toxi > wm | :20001 | |
| toxi > pg | :20000 | |
| cli > toxi | 장애 주입 | security |
| cli > pg | DB 스냅샷 | dashed |
| app > alloy | 지표·trace | dashed |
| k6 > alloy | 부하 지표 | dashed |
| alloy > lgtm | 저장 | dashed |

@steps id=topology-steps
| s-k6 | k6 부하 생성기 | 초당 50건씩 `POST /orders`를 보낸다. 요청마다 `X-Request-Id`와 cohort 헤더를 달고, 요청별 결과를 JSON 한 줄로 남긴다. | runtime-topology | k6 |
| s-app | 주문 API | 상품 가격·재고를 lookup으로 묻고, 성공하면 orders에 INSERT한다. 두 impl은 같은 이미지이고 환경 변수만 다르다. | runtime-topology | app |
| s-toxi | Toxiproxy | 앱과 의존성 사이의 TCP 프록시다. 앱은 DB와 상품 API를 `toxiproxy:20000`, `toxiproxy:20001`로 안다. | runtime-topology | toxi |
| s-cli | chaos CLI (호스트) | `docker exec … /toxiproxy-cli`로 지연 toxic을 넣거나 프록시를 toggle한다. Toxiproxy API는 컨테이너 loopback에만 열려 있어 앱과 k6는 닿지 못한다. | runtime-topology | cli |
| s-alloy | Alloy 수집기 | 앱의 `/actuator/prometheus`를 1 s마다 스크레이프하고, k6 remote-write와 앱 trace를 받아 LGTM에 넘긴다. | runtime-topology | alloy |

| 도구 | 이 실험에서 맡은 역할 |
| --- | --- |
| k6 | 부하 생성기. 정해진 rate로 요청을 보내고 요청별 원시 결과를 남긴다 |
| Toxiproxy | 장애 주입기. 지연(latency toxic)을 넣거나 연결을 끊는다(toggle) |
| WireMock | 외부 상품 API를 흉내 내는 가짜 서버. `stubs/`의 고정 응답을 돌려준다 |
| PostgreSQL | 주문 저장소. collect 단계에서 스냅샷을 떠 불변 조건을 검사한다 |
| Alloy | 지표·로그·trace 수집기 |
| Grafana LGTM | 저장(Prometheus·Loki·Tempo)과 실행 중 화면(Grafana)을 한 컨테이너에 담은 관측 스택 |

수명이 둘로 나뉜다. Alloy와 LGTM은 run 전체 동안 하나만 유지된다. 앱·DB·WireMock·Toxiproxy·k6는 repeat마다 새 Compose 프로젝트로 만들고 지운다.[](source:runner-execute)

앱이 장애를 모르고도 프록시를 거치는 이유는 주소 치환 하나다.

- impl.yaml에는 `${chaos.dep.lookup.host}` 같은 참조만 있다.
- `resolve_value`가 참조를 Toxiproxy 주소로 바꿔 compose.yaml에 넣는다.[](source:compose-resolve)

@code source=impl-naive language=yaml

@code source=compose-generated language=yaml

## `chaos run` 한 번은 어떤 순서와 시간으로 진행되나? {#timeline}

@steps id=run-steps
| v | 검증 | `validate.py`가 YAML을 스키마로 검사한다. 실패하면 아무것도 만들지 않고 exit 2. |
| lock | 엔진 lock | Docker 엔진 위에 lock 컨테이너를 띄운다. 엔진당 run은 하나만 돈다. |
| snap | 입력 스냅샷 | `results/<run-id>/inputs/`에 원본을 복사하고 SHA-256을 기록한다. |
| img | 이미지·관측 스택 | 앱 이미지를 재현 빌드하고 Alloy·LGTM을 띄운다. |
| loop | repeat 5회 | repeat마다 Compose를 생성하고 아래 7단계를 돈다. |
| fin | 집계와 리포트 | `run.json`, `report.html`을 쓰고 lock을 푼다. exit 0은 5회 모두 완주했다는 뜻이고, SLO 충족과는 무관하다. |

@diagram waterfall id=repeat-phases source=repeat-phases.waterfall.json title="repeat 1의 7단계 (api-slow × naive 실측)"

- warmup이 끝나면 하네스는 진행 중 요청이 0이 될 때까지 기다린 뒤 orders 테이블과 WireMock journal을 비우고 경계를 기록한다. 그래서 measured 판정에는 warmup 주문이 섞이지 않는다.[](source:runner-warmup)
- 장애 시각은 measured의 t0 기준이다. 계획은 t0+40 s와 t0+80 s이고, 실제 적용 확인은 t0+40.010 s였다.[](source:repeat-naive)
- probe cohort는 별도 단계가 아니다. 같은 k6 실행 안에서 장애 해제 시각부터 measured 부하와 겹쳐 돈다. recovery 단계는 그 k6가 끝나기를 기다릴 뿐이다.[](source:runner-k6)
- convergence 단계는 이 problem에서 N/A라 0 s로 지나간다.[](source:runner-repeat)

| cohort | 보내는 시점 | 쓰이는 곳 |
| --- | --- | --- |
| warmup | warmup 단계 30 s, 1,500건 | 판정에서 제외. JVM·연결 풀 예열 |
| measured | t0부터 120 s, 6,000건 | SLO, 지연, ambiguous, 불변 조건 |
| probe | 장애 해제부터 1 s 간격 | time-to-recovery와 불변 조건 |

## 주문 하나는 어떻게 처리되고, impl은 무엇을 바꾸나? {#order}

@sequence id=order-flow title="장애 구간의 주문 하나"
| actor k6 | k6 | frontend |
| actor app | 주문 API | backend |
| actor toxi | Toxiproxy | security |
| actor wm | WireMock | external |
| actor pg | PostgreSQL | database |
| k6 | app | POST /orders (X-Request-Id, cohort) |
| app | toxi | GET /products/p-007 |
| phase | 장애 구간: upstream +2,000 ms |
| toxi | wm | 요청 전달 (2,000 ms 늦게) | dashed |
| phase | timeout impl: 300 ms 경과 |
| app | k6 | 504 upstream-timeout, 저장 안 함 | return |
| phase | naive impl: 끝까지 기다림 |
| wm | toxi | 200 price·available | return |
| toxi | app | 상품 정보 | return |
| app | pg | INSERT orders (트랜잭션) | emphasis |
| pg | app | orderId | return |
| app | k6 | 201 Created (2 s 이상 뒤) | return |

@steps id=order-steps
| o-recv | 주문 API | 헤더와 본문을 검사한다. 잘못되면 400을 돌려주고 끝난다. | order-flow | app |
| o-lookup | Toxiproxy | lookup은 트랜잭션 밖에서 호출한다. 기다리는 동안 DB 연결을 잡지 않는다. | order-flow | toxi |
| o-fail | 주문 API | lookup이 실패하면 저장 없이 503 또는 504로 끝난다. 그래서 실패 응답에 주문이 남으면 불변 조건 위반이다. | order-flow | app |
| o-save | PostgreSQL | 성공하면 `request_id` UNIQUE 컬럼과 함께 INSERT한다. 같은 요청이 두 번 저장될 수 없다. | order-flow | pg |

두 impl의 차이는 아래가 전부다. 이미지와 나머지 설정은 같다.

```diff title="impls/naive/impl.yaml → impls/timeout/impl.yaml"
-  IMPL: naive
+  IMPL: timeout
-  LOOKUP_RESPONSE_TIMEOUT_MS: "10000"
+  LOOKUP_RESPONSE_TIMEOUT_MS: "300"
+  LOOKUP_DEADLINE_MS: "300"
-  SERVICE_NAME: orders-naive
+  SERVICE_NAME: orders-timeout
```

`IMPL=timeout`이면 `Lookup`이 `DeadlineFactory`를 쓴다. 이 factory는 요청을 만들 때 300 ms 뒤 취소 예약을 건다. 그래서 연결 풀 대기, 연결, 응답 대기를 합친 전체 호출이 300 ms를 넘지 못한다.[](source:lookup-find)

@code source=lookup-deadline language=java

## 결과는 무엇을 근거로 해석하나? {#results}

이 기록에서 두 impl 모두 SLO를 놓쳤다. 예산 안 201 비율도 거의 같았다. 차이는 실패하는 방식에서 나왔다.

- naive는 201을 더 많이 냈지만 1,486건이 예산 500 ms를 넘었다. 응답을 못 받은 513건 중 일부는 서버에 저장돼 ambiguous 99건이 됐다.
- timeout은 2,011건을 504로 빨리 거절했다. 대신 클라이언트 오류와 ambiguous는 0건이었다.

| 항목 (repeat 1) | naive | timeout |
| --- | --- | --- |
| completion · validity | complete · valid | complete · valid |
| correctness | pass (ambiguous 99) | pass |
| SLO | missed {bad:missed} | missed {bad:missed} |
| measured 발행 | 6,000 | 6,001 |
| 201 | 5,485 | 3,990 |
| 예산(≤500 ms) 안 201 | 3,999 | 3,990 |
| 예산 안 201 비율 | 3,999 / 6,000 = 0.6665 | 3,990 / 6,001 = 0.6649 |
| 504 upstream-timeout | 0 | 2,011 |
| 503 upstream-unavailable | 2 | 0 |
| k6 timeout (15 s, 코드 1050) | 497 {bad:497} | 0 {good:0} |
| 그 밖의 클라이언트 오류 (코드 1220) | 16 | 0 |
| ambiguous | 99 {bad:99} | 0 {good:0} |
| 201 p99 | 13,641 ms | 97 ms |
| time-to-recovery | 991 ms | 991 ms |

합계가 맞다. naive는 5,485 + 2 + 497 + 16 = 6,000이고, timeout은 3,990 + 2,011 = 6,001이다.[](source:repeat-naive)[](source:repeat-timeout)

```mermaid title="201 응답의 지연 구간별 건수 (repeat 1 실측, measured cohort, 실패 요청 제외)"
xychart-beta
  x-axis ["<100 ms", "100–500 ms", "500 ms 초과~2 s 미만", "2–5 s", "5 s 이상"]
  y-axis "201 건수" 0 --> 4500
  bar "naive" [3975, 24, 59, 307, 1120]
  bar "timeout" [3951, 39, 0, 0, 0]
```

구간 경계는 `<100`, `100≤d≤500`, `500<d<2,000`, `2,000≤d<5,000`, `≥5,000` ms다. 앞의 두 구간 합이 예산 안 201이다(naive 3,975 + 24 = 3,999).[](source:k6-naive)[](source:k6-timeout)

| 판정 | 묻는 것 | 이 기록에서 |
| --- | --- | --- |
| completion | 7단계를 끝까지 마쳤나 | 둘 다 complete |
| validity | 측정값을 믿을 수 있나. 결과가 좋은지와는 별개 | 둘 다 valid |
| correctness | 주문 불변 조건 6개를 지켰나. ambiguous는 위반이 아니라 따로 센다 | 둘 다 pass |
| SLO | 예산 안 201 비율 ≥ 0.99, 201 p99 ≤ 500 ms | 둘 다 missed |

ambiguous는 서버에는 주문이 저장됐지만 클라이언트는 결과를 확인하지 못한 상태다. 하네스는 k6 기록과 DB 스냅샷을 `request_id`로 맞춰서 이를 찾는다.[](source:verdict-invariants) 용어는 GLOSSARY를 따른다.[](source:glossary)

run 값은 repeat 값을 그대로 쓰지 않는다. naive repeat 1의 201 p99는 13,641 ms다. 반면 run의 값은 repeat 5개 p99의 중앙값인 13,820 ms다.[](source:run-naive)

@callout level=warning title="이 비교의 한계"
| 두 run은 재현 빌드를 고치기 전 기록이다. 그래서 두 impl이 같은 앱 이미지였다는 것(AC-30)이 증명되지 않았다. |
| 이 표는 api-slow 한 기록에서 관찰된 차이다. 어느 impl이 일반적으로 낫다고 결론 내리지 않는다. |
| 실행에서 겪은 함정과 남은 AC는 STATUS.md에 있다. |

## 직접 확인해 보기 {#check}

- [ ] `problems/external-api/scenarios/api-slow/scenario.yaml`에서 `apply_at_s: 40`, `remove_at_s: 80`, `value_ms: 2000`을 찾는다.
- [ ] 저장소에 docker-compose 파일이 없는 것을 확인하고, `chaos/compose.py`의 `repeat_compose`가 Compose를 만든다는 것을 본다.
- [ ] `results/20261031-004309-…-naive-2c0c93/repeats/1/compose.yaml`에서 `LOOKUP_BASE_URL: http://toxiproxy:20001`을 찾는다.
- [ ] 두 `impl.yaml`을 diff해서 `LOOKUP_RESPONSE_TIMEOUT_MS`와 `LOOKUP_DEADLINE_MS`만 다른지 본다.
- [ ] naive `repeats/1/repeat.json`에서 `faults[0].confirmed_ms - t0_ms`가 약 40,010 ms인지 계산한다.
- [ ] naive `run.json`의 `exit_code`가 0인데, `repeats/1/repeat.json`의 `verdicts.slo.value`는 `missed`인 것을 함께 확인한다.
- [ ] 같은 `repeat.json`의 `verdicts.slo.segments.during.in_budget_ratio`(0.0005)와 `before`(0.999)를 비교해 비율이 약 2/3가 된 이유를 본다.
- [ ] `values.p99_201_ms`(13641)와 `run.json`의 `aggregate.metrics.p99_201_ms.median`(13820)을 비교한다.
