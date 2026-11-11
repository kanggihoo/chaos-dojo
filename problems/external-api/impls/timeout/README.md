# timeout: 외부 API 호출 전체를 300 ms에서 끊는다

## 이 impl이 대표하는 것

외부 API 호출에 전체 기한(deadline)을 두고, 기한을 넘기면 기다리지 않고 바로 실패를 돌려주는 구현이다. 장애 대응 패턴 중 가장 기본인 fail fast다. circuit breaker, bulkhead, retry 같은 다른 패턴도 대부분 이 기한을 전제로 한다.

naive와 나란히 놓고, "기한 하나만 추가했을 때 장애 중 서비스가 얼마나 달라지는가"를 본다.

## 동작

공통 앱(`../../app`)을 `IMPL=timeout`으로 실행한다. 차이는 `lab.chaos.orders.Lookup` 한 곳에만 있다.

| 설정 | 값 |
|---|---|
| lookup 전체 호출 기한 `LOOKUP_DEADLINE_MS` | 300 ms |
| lookup 응답 대기 한도 `LOOKUP_RESPONSE_TIMEOUT_MS` | 300 ms |
| lookup 연결 timeout | 1,000 ms (naive와 같음) |
| HTTP client pool 획득 timeout | 2,000 ms (naive와 같음) |

300 ms 기한은 HTTP client pool에서 연결을 얻는 시간, 연결 시간, 응답을 받는 시간을 모두 포함한다. `Lookup.DeadlineFactory`가 요청을 시작할 때 타이머를 걸고, 300 ms가 지나면 진행 중인 호출을 취소한다. 그래서 연결 timeout(1,000 ms)이나 pool 획득 timeout(2,000 ms)이 300 ms보다 길어도, 실제로는 300 ms 안에 끝난다. 기한을 넘기면 앱은 504(`urn:chaos-lab:problem:upstream-timeout`)를 돌려준다.

응답 대기 한도만 짧게 두지 않고 전체 기한을 둔 이유가 있다. 응답 대기 한도만 있으면 pool 획득이나 연결에서 막힌 시간은 한도에 포함되지 않는다. 그러면 lookup이 느려져 pool이 꽉 찼을 때 요청이 pool 앞에서 최대 2초를 기다리고, fail fast가 깨진다.

## 이 impl로 확인하려는 가설

lookup이 느려지거나 죽어도 요청 하나가 Tomcat 업무 스레드를 최대 약 300 ms만 붙잡는다. 초당 50건 × 0.3초 = 동시 15개 정도면 충분하므로 업무 스레드(50개)가 소진되지 않는다. 주문은 실패하지만 실패가 빨리 돌아오고, 큐가 쌓이지 않으므로 장애가 끝나면 바로 정상화된다.

api-slow 기록이 이 가설을 보여 준다(`results/20261031-002528-…-api-slow-timeout-8def62`, repeat 1). 장애 구간에서 201은 11건뿐이라 SLO는 지키지 못했다. 하지만 k6 timeout에 걸린 요청은 0건이었고, 장애 전후 구간의 201 p99는 87 ms, 92 ms로 정상이었다.

이 impl이 감수하는 비용도 있다. lookup이 300 ms를 조금 넘는 정도로만 느려져도 주문이 실패한다. 이번 scenario는 지연을 2,000 ms로 크게 걸었기 때문에 이 비용은 드러나지 않는다. 기한 근처의 지연을 거는 scenario가 생기면 따로 확인해야 한다.

## 관련 문서

- 출처: [PROVENANCE.md](PROVENANCE.md)
- 비교 대상: [../naive/README.md](../naive/README.md)
- scenario 설명: `../../scenarios/*/README.md`
