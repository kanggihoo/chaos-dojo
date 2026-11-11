# naive: 외부 API를 오래 기다린다

## 이 impl이 대표하는 것

외부 API 호출에 짧은 기한을 따로 두지 않고, 응답이 올 때까지 넉넉하게 기다리는 구현이다. 많은 서비스가 처음에 이렇게 만든다. HTTP 클라이언트 기본값을 그대로 쓰거나 "느려도 결국 응답은 오겠지"라고 가정한 코드가 여기에 해당한다.

external-api problem에서 naive는 비교의 출발점이다. timeout impl이 "기한을 두면 무엇이 좋아지는가"를 보여 주려면, 기한이 없을 때 어떻게 되는지가 먼저 기록되어 있어야 한다.

## 동작

공통 앱(`../../app`)을 `IMPL=naive`로 실행한다. 차이는 `lab.chaos.orders.Lookup` 한 곳에만 있다.

| 설정 | 값 |
|---|---|
| lookup 응답 대기 한도 `LOOKUP_RESPONSE_TIMEOUT_MS` | 10,000 ms |
| lookup 연결 timeout | 1,000 ms (timeout impl과 같음) |
| HTTP client pool 획득 timeout | 2,000 ms (timeout impl과 같음) |
| 최악의 lookup 시간 | 2,000 + 1,000 + 10,000 = 13,000 ms |

한도를 무한으로 두지 않고 10초로 정한 이유는 측정 때문이다(decisions.md D-19). 앱이 무한히 기다리면 k6가 15초에 요청을 먼저 끊고, 그러면 실제 지연 시간이 기록되지 않고 잘려 버린다. 최악의 경우(13초)도 k6 timeout(15초)보다 짧게 맞췄다.

## 이 impl로 확인하려는 가설

lookup이 느려지면 요청 하나가 Tomcat 업무 스레드(50개)를 오래 붙잡는다. 초당 50건이 들어오고 lookup이 2초 걸리면 동시에 100개의 스레드가 필요하다. 스레드가 모자라면 요청이 accept 큐에 쌓이고, 큐에서 기다린 시간이 응답 시간에 더해진다. 결국 느린 의존성 하나가 서비스 전체의 응답을 늦춘다.

api-slow 기록이 이 가설을 보여 준다(`results/20261031-004309-…-api-slow-naive-2c0c93`, repeat 1). lookup 지연은 2초였는데 장애 구간의 201 p50은 8,109 ms, p99는 14,675 ms였고, 497건이 k6 timeout에 걸렸다.

이 impl에서 함께 확인하는 것이 하나 더 있다. 업무 스레드가 모두 소진되어도 관리 포트(readiness, Prometheus)는 계속 응답해야 한다(AC-31). 관리 포트를 별도 executor로 분리한 이유가 이 상황이다.

## 관련 문서

- 출처: [PROVENANCE.md](PROVENANCE.md)
- 비교 대상: [../timeout/README.md](../timeout/README.md)
- scenario 설명: `../../scenarios/*/README.md`
