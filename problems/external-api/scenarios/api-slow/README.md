# api-slow: 외부 API가 40초 동안 2초씩 느려진다

## 상황

주문 API는 주문마다 외부 상품 API(lookup)에 `GET /products/{productId}`로 가격과 재고를 묻는다. 이 scenario에서는 lookup이 죽지 않고 응답만 2초 늦어진다. 실제 서비스로 치면 외부 결제·재고 API가 과부하로 느려진 상황이다.

느린 의존성은 죽은 의존성보다 위험할 수 있다. 연결이 거부되면 요청이 바로 실패하지만, 응답이 늦으면 요청이 스레드를 붙잡은 채 기다리기 때문이다. 이 scenario가 묻는 질문은 "외부 API 하나가 느려질 때 우리 서비스 전체가 같이 느려지는가, 아니면 그 기능만 빠르게 실패하는가"다.

## 장애를 어떻게 만드는가

```yaml
faults:
  - {target: lookup, action: latency, value_ms: 2000, apply_at_s: 40, remove_at_s: 80}
```

하네스가 measured 부하 시작(t0) 40초 뒤에 Toxiproxy의 lookup 프록시에 latency toxic(2,000 ms, jitter 0)을 붙이고, 80초 뒤에 뗀다. toxic은 요청 방향(upstream)에 건다. 응답 방향에 걸면 고정 버전 Toxiproxy에서 호출을 포기한 클라이언트가 지연된 chunk를 남겨 toxic을 뗄 수 없게 되기 때문이다(decisions.md D-19). 요청 방향에 걸어도 앱이 체감하는 응답 지연은 같은 2초다.

적용·해제의 계획 시각과 실제 시각은 `events.jsonl`에 남는다. 실제 시각이 계획보다 1초 넘게 어긋나면 그 repeat는 invalid다.

## 120초를 세 구간으로 읽는다

| 구간 | 시각 | 확인하는 것 |
|---|---|---|
| 장애 전 | t0 ~ 40초 | 이 repeat의 앱이 정상으로 출발했는가. 여기가 깨끗해야 다음 구간의 붕괴를 장애 탓으로 돌릴 수 있다 |
| 장애 중 | 40 ~ 80초 | 지연이 스레드와 큐를 어떻게 잠식하는가. impl 차이가 드러나는 핵심 구간 |
| 장애 후 | 80 ~ 120초 | 장애가 풀린 뒤 쌓인 큐가 빠지고 정상으로 돌아오는가 |

장애 후 구간에는 probe가 1초마다 주문을 하나씩 보낸다. 해제를 확인한 시각부터 500 ms 안의 201이 5번 연속 나올 때까지를 time-to-recovery로 기록한다. 60초 안에 회복하지 못하면 correctness fail이다.

## 두 impl은 어떻게 대처하는가

| impl | lookup 대처 | 장애 중 예상 |
|---|---|---|
| naive | 응답을 최대 10초까지 기다린다 | 요청 하나가 Tomcat 스레드를 2초씩 붙잡는다. 초당 50건 × 2초 = 동시 100개가 필요한데 업무 스레드는 50개다. 남는 요청은 accept 큐에 쌓이고, 큐 대기 시간이 2초에 더해진다 |
| timeout | 전체 lookup 호출을 300 ms에 끊는다 | 300 ms 만에 504로 실패하고 스레드를 돌려준다. 주문은 실패하지만 서비스가 막히지 않는다 |

두 impl은 같은 이미지이고 환경 변수(`LOOKUP_RESPONSE_TIMEOUT_MS`, `LOOKUP_DEADLINE_MS`)만 다르다. 나머지 설정(Tomcat 스레드 50, JDBC pool 10, HTTP client pool 50)은 같다.

## 기록된 결과 (repeat 1)

| run | 구간 | 예산 내 201 비율 | 201 p50 | 201 p99 | k6 timeout |
|---|---|---|---|---|---|
| `20261031-004309-…-naive-2c0c93` | 전 | 0.999 | 5 ms | 71 ms | 0 |
| | 중 | 0.0005 | 8,109 ms | 14,675 ms | 497 |
| | 후 | 1.0 | 4 ms | 89 ms | 0 |
| `20261031-002528-…-timeout-8def62` | 전 | 0.991 | 5 ms | 87 ms | 0 |
| | 중 | 0.0055 | 174 ms | 273 ms | 0 |
| | 후 | 0.998 | 6 ms | 92 ms | 0 |

두 impl 모두 장애 중에는 SLO를 지키지 못한다. lookup 없이는 주문을 만들 수 없으므로 이건 예상된 결과다. 차이는 실패하는 모양에 있다. naive는 지연이 lookup의 2초보다 4~7배 커지고 497건이 15초 timeout에 걸린다. timeout은 실패를 빠르게 돌려주고 timeout에 걸린 요청이 0건이다. time-to-recovery는 두 impl 모두 약 1초다.

## 실행

```
uv run chaos run external-api/api-slow --impl naive
uv run chaos run external-api/api-slow --impl timeout
```
