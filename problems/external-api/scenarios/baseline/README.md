# baseline: 장애 없는 기준선

## 무엇을 재는가

외부 상품 API(lookup)가 정상일 때 주문 API(`POST /orders`)가 내는 기준 성능을 잰다. api-slow, api-down 결과를 읽을 때 "장애가 없었다면 이 impl은 원래 어땠는가"를 이 scenario가 답한다.

장애 scenario의 장애 전 40초 구간을 기준선으로 쓰지 않고 이 scenario를 따로 두는 이유는 decisions.md D-19에 있다. 같은 run 안의 앞 구간은 시간 경과와 warmup 효과가 섞여서 깨끗한 기준이 되지 못한다.

## 부하

`scenario.yaml`의 `workload`가 정한다. 세 scenario가 모두 같은 값을 쓰므로, 결과 차이는 장애 유무에서만 나온다.

| 항목 | 값 |
|---|---|
| k6 스크립트 | `../../k6/orders.js` (`POST /orders`, 상품 `p-001`~`p-020`, quantity 1~10, seed 42) |
| 방식 | constant-arrival-rate, 초당 50건 |
| warmup | 30초, 1,500건. 끝나면 orders 테이블과 WireMock journal을 비운다 |
| measured | 120초, 6,000건 |
| k6 timeout | 15초 |

## 장애

없다(`faults: []`). 그래도 앱의 DB 연결과 lookup 연결은 Toxiproxy를 거친다(AC-20). 장애 scenario와 네트워크 경로를 똑같이 맞추기 위해서다. recovery check는 "해당 없음"으로 기록된다.

## 기대하는 결과

두 impl 모두 SLO(500 ms 안에 끝난 201 비율 ≥ 0.99, 201의 p99 ≤ 500 ms)를 만족해야 한다. naive와 timeout은 lookup 대기 한도만 다르고 lookup이 빠르게 응답하면 한도에 닿지 않으므로, 두 impl의 수치는 비슷해야 한다. 여기서 차이가 크게 나면 impl 차이보다 측정 환경을 먼저 의심한다.

## 기록 상태

2026-11-11 기준, 끝까지 완료된 baseline run은 없다. `results/20261101-212951-external-api-baseline-naive-f2a699`는 중단(`interrupted`)된 기록이다.

## 실행

```
uv run chaos run external-api/baseline --impl naive
uv run chaos run external-api/baseline --impl timeout
```
