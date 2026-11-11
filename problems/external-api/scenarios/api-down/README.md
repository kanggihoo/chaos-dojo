# api-down: 외부 API가 40초 동안 죽는다

## 상황

주문 API는 주문마다 외부 상품 API(lookup)에 가격과 재고를 묻는다. 이 scenario에서는 lookup에 아예 연결할 수 없게 된다. 실제 서비스로 치면 외부 API 서버가 내려가거나 배포 중에 사라진 상황이다.

api-slow와 비교해서 읽는다. 응답이 늦는 api-slow와 달리 여기서는 연결이 거부되거나 끊기므로, 요청이 스레드를 오래 붙잡지 않고 빨리 실패할 것으로 기대한다. 이 scenario가 묻는 질문은 "외부 API가 죽었을 때 우리 서비스가 빠르고 정확하게 실패를 알리는가, 그리고 API가 돌아오면 바로 정상화되는가"다.

## 장애를 어떻게 만드는가

```yaml
faults:
  - {target: lookup, action: down, apply_at_s: 40, remove_at_s: 80}
```

하네스가 measured 부하 시작(t0) 40초 뒤에 Toxiproxy의 lookup 프록시를 비활성화하고, 80초 뒤에 다시 활성화한다. `toxiproxy-cli`에는 상태를 지정하는 명령이 없고 `toggle`만 있으므로, 하네스는 toggle 뒤에 프록시가 의도한 상태가 됐는지 확인한다. 의도와 다르면 장애 동작 실패로 run을 멈춘다.

프록시가 꺼지면 앱의 lookup 연결은 거부되거나 리셋된다. spec의 판정 순서상 이 경우 앱은 503(`urn:chaos-lab:problem:upstream-unavailable`)을 돌려줘야 한다.

적용·해제의 계획 시각과 실제 시각은 `events.jsonl`에 남는다. 실제 시각이 계획보다 1초 넘게 어긋나면 그 repeat는 invalid다.

## 120초를 세 구간으로 읽는다

| 구간 | 시각 | 확인하는 것 |
|---|---|---|
| 장애 전 | t0 ~ 40초 | 이 repeat의 앱이 정상으로 출발했는가 |
| 장애 중 | 40 ~ 80초 | 실패가 얼마나 빨리, 어떤 상태 코드로 돌아오는가. 실패한 요청이 주문을 남기지 않는가 |
| 장애 후 | 80 ~ 120초 | 끊긴 연결을 버리고 새 연결로 정상화되는가 |

장애 후 구간에는 probe가 1초마다 주문을 하나씩 보낸다. 해제를 확인한 시각부터 500 ms 안의 201이 5번 연속 나올 때까지를 time-to-recovery로 기록한다. 60초 안에 회복하지 못하면 correctness fail이다.

## 두 impl은 어떻게 대처하는가

| impl | lookup 대처 |
|---|---|
| naive | 응답을 최대 10초까지 기다린다. 연결 timeout은 1초다 |
| timeout | 전체 lookup 호출(pool 획득 + 연결 + 응답)을 300 ms에 끊는다 |

연결 거부는 대기 한도에 닿기 전에 바로 실패하므로, 두 impl의 차이는 api-slow보다 작을 것으로 본다. 다만 연결이 거부되지 않고 응답 없이 멈추는 경우에는 naive가 연결 timeout 1초, 응답 한도 10초까지 기다릴 수 있다. naive의 기록이 아직 없어서 이 부분은 확인하지 못했다.

## 기록된 결과 (repeat 1)

| run | 구간 | 예산 내 201 비율 | 201 p50 | 201 p99 | k6 timeout |
|---|---|---|---|---|---|
| `20261101-214655-…-timeout-546e1c` | 전 | 0.996 | 5 ms | 175 ms | 0 |
| | 중 | 0.0025 | 240 ms | 281 ms | 0 |
| | 후 | 0.994 | 5 ms | 219 ms | 0 |

이 run의 time-to-recovery는 714 ms다. run 전체는 중단(`interrupted`)으로 끝났고, 완료된 api-down run은 2026-11-11 기준 없다. naive impl의 api-down run(`20261101-212854-…-naive-740ee7`)은 이미지 조회 오류로 repeat를 시작하지 못했다.

## 실행

```
uv run chaos run external-api/api-down --impl naive
uv run chaos run external-api/api-down --impl timeout
```
