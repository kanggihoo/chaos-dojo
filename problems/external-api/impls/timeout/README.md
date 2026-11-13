# timeout: 외부 상품 API 호출 전체를 300 ms에서 끊는다

## 겨냥하는 요구사항

timeout이 지키려는 것은 장애 중에도 주문 API가 막히지 않는 것과 회복 조건이다([problem README의 요구사항](../../README.md#요구사항)). lookup이 느려지거나 죽어도 요청 하나가 업무 스레드를 오래 붙잡지 않게 해서, 장애 구간 밖의 요청과 장애 뒤의 요청이 정상으로 처리되게 한다. 불변 조건도 지킨다. 기한을 넘긴 lookup으로는 주문을 만들지 않는다.

포기하는 것은 장애 중의 주문 성공이다. lookup 응답이 300 ms 안에 오지 않으면 그 주문은 실패한다. 그래서 장애 중 SLO 비율은 naive보다 나아지지 않는다. lookup이 300 ms를 조금 넘는 정도로만 느려져도 정상 주문을 버리게 된다는 비용도 받아들인다.

## 왜 이 방식인가

같은 요구사항을 노리는 방법으로 circuit breaker, bulkhead, retry가 있다([problem README의 대응 방법](../../README.md#대응-방법)). 그중 lookup 호출에 기한을 두는 것을 먼저 고른 이유는, 다른 방법들이 모두 이 기한을 전제로 하기 때문이다. circuit breaker는 "실패"를 세어야 열리는데 기한이 없으면 느린 호출은 실패로 끝나지 않고, retry는 기한 없이 다시 시도하면 기다리는 시간만 늘어난다. 기한 하나만 넣었을 때 무엇이 달라지는지를 먼저 확인해야 다음 방법의 효과를 나눠 볼 수 있다.

응답 대기 한도만 짧게 두지 않고 호출 전체에 기한을 둔 이유도 있다. 응답 대기 한도만 있으면 HTTP client pool에서 연결을 기다린 시간과 연결하는 시간은 한도에 들어가지 않는다. 그러면 lookup이 느려져 pool이 꽉 찼을 때 요청이 pool 앞에서 최대 2초를 기다리고, 빨리 실패한다는 목표가 깨진다.

## 작동 원리

공통 앱(`../../app`)을 `IMPL=timeout`으로 실행한다. naive와 같은 이미지이고, lookup 호출 설정만 다르다. 값은 같은 폴더의 [`impl.yaml`](impl.yaml)이 정하고, 출처는 [PROVENANCE.md](PROVENANCE.md)에 있다.

lookup 호출을 시작할 때 300 ms 기한이 시작된다. 이 기한에는 HTTP client pool에서 연결을 얻는 시간, 연결하는 시간, 응답을 받는 시간이 모두 들어간다. `Deadline` 부품이 300 ms가 지나면 진행 중인 호출을 취소하고, 앱은 504(`urn:chaos-lab:problem:upstream-timeout`)를 돌려준다. 연결 timeout 1초와 pool 획득 timeout 2초는 naive와 같지만, 300 ms 기한이 먼저 끝나므로 실제로는 닿지 않는다. 기한 전에 연결이 거부되면 503(`urn:chaos-lab:problem:upstream-unavailable`)으로 바로 실패한다.

이렇게 하면 lookup이 아무리 느려져도 요청 하나가 업무 스레드를 붙잡는 시간은 약 300 ms다. 초당 50건이 들어오면 동시에 필요한 업무 스레드는 15개 정도이고, 업무 스레드 50개 안에 들어온다. 그래서 요청이 큐에 쌓이지 않는다.

## 해결하는 것과 해결하지 못하는 것

해결하는 것은 느린 lookup이 주문 API 전체를 막는 일이다. 실패가 빨리 돌아오고 업무 스레드가 바닥나지 않으므로, 장애가 그 구간 밖으로 번지지 않는다. 클라이언트가 응답을 기다리다 먼저 끊는 일도 없어서, 실패로 알린 주문이 저장되는 ambiguous outcome도 생기지 않는다.

해결하지 못하는 것은 장애 중의 주문 성공이다. lookup 없이는 주문을 만들 수 없다는 점은 naive와 같다. 장애가 계속되는 동안 모든 요청이 300 ms씩 lookup을 기다렸다가 실패한다는 점도 그대로다. 지연이 기한 근처일 때 정상 주문을 얼마나 버리는지는 아직 확인하지 않았다.

결과 해석을 바꾸는 수치: api-slow에서 예산 안 201 비율의 run 수준 값은 timeout 0.665, naive 0.666으로 거의 같았다(20261031-002528-external-api-api-slow-timeout-8def62, 20261031-004309-external-api-api-slow-naive-2c0c93, 2026-11-13). SLO 판정만 보면 timeout은 아무것도 바꾸지 않은 것처럼 보인다. 차이는 구간 값에서만 보인다.

## 꼬리 질문

- Q. 300 ms 기한을 두면 lookup이 느려져도 주문 API가 막히지 않나? — 답함 · 20261031-002528-external-api-api-slow-timeout-8def62 (2026-11-13): api-slow 장애 구간에서 k6 요청 timeout은 0건, 201 p99는 293 ms였고, 장애 전과 장애 후 구간의 예산 안 201 비율은 0.999와 0.994였다(repeat별 구간 값에서 중앙값을 직접 구함).
- Q. 기한을 두면 SLO 판정이 naive보다 나아지나? — 답함 · 20261031-002528-external-api-api-slow-timeout-8def62, 20261031-004309-external-api-api-slow-naive-2c0c93 (2026-11-13): 나아지지 않는다. 예산 안 201 비율의 run 수준 값은 0.665와 0.666이고 둘 다 missed다.
- Q. 장애 중에도 주문 일부를 받으려면? — 열림 · 후보: cache fallback impl, 마지막으로 받은 가격으로 주문을 만든다.
- Q. 장애가 계속되는 동안 매 요청이 300 ms씩 lookup을 기다릴 필요가 있나? — 열림 · 후보: circuit breaker impl, 실패가 이어지면 lookup 호출을 잠시 멈춘다.
- Q. lookup이 300 ms를 조금 넘게 느려지면 정상 주문을 얼마나 버리나? — 열림 · 후보: 지연을 300~500 ms로 거는 새 scenario.
- Q. lookup 연결이 거부될 때도 실패가 빨리 돌아오나? — 열림 · 후보: api-down scenario를 timeout으로 repeat 다섯 개 모두 실행한 run.
