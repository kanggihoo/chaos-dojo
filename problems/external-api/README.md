# external-api: 외부 상품 API에 기대는 주문

## 업무 상황

사용자는 주문 API에 `POST /orders`로 상품과 수량을 보낸다. 주문 API는 주문마다 외부 상품 API(lookup)에 `GET /products/{productId}`로 그 상품의 가격과 재고를 묻는다. lookup이 가격을 돌려주면 주문 API는 단가와 합계를 계산해 Postgres의 orders 테이블에 주문을 저장하고 201을 돌려준다.

주문 API는 lookup 없이는 주문을 만들지 않는다. lookup에 연결할 수 없으면 503(`urn:chaos-lab:problem:upstream-unavailable`)을, 정해진 시간 안에 답을 받지 못하면 504(`urn:chaos-lab:problem:upstream-timeout`)를 돌려준다. 재고가 없으면 409(`product-unavailable`)다. 그래서 lookup이 느려지거나 죽으면, 주문 API는 그 동안 주문을 받을 수 없다. 이 problem이 다루는 것은 그때 주문 API가 얼마나 빨리, 얼마나 정확하게 실패하고, lookup이 돌아오면 스스로 정상화되는가다.

## 요구사항

값은 같은 폴더의 [`problem.yaml`](problem.yaml)이 정하고, 판정 규칙은 [experiment-harness spec](../../docs/specs/experiment-harness/spec.md)의 AC-23(SLO), AC-24(불변 조건), AC-25와 "k6 실행과 recovery 규칙"(회복)이 정한다. 하네스는 이 세 가지를 repeat마다 따로 판정한다.

**SLO.** measured 요청 전체 가운데 500 ms 안에 201로 끝난 요청의 비율이 0.99 이상이고, 201 응답의 p99(nearest-rank)가 500 ms 이하여야 met이다. 분모는 발행한 measured 요청 수라서, 실패한 요청과 500 ms를 넘긴 201은 모두 비율을 깎는다. 기준을 이렇게 둔 이유는 사용자에게 늦은 성공은 실패와 다르지 않기 때문이다. 주문 화면에서 몇 초씩 기다리게 하는 201은 사용자가 이미 포기한 뒤에 도착한다.

**회복 조건.** 장애가 있는 scenario에서, 하네스가 장애 해제를 확인한 시각부터 60초 창 안에 예산 안 201이 연속 5번 도착해야 회복이다. 확인용 요청(probe)은 1초 간격으로 보내고, 해제 확인 이후에 발행한 요청만 센다. 창이 닫힐 때까지 회복하지 못하면 불변 조건 6번 위반이다. 이 기준을 둔 이유는 외부 API가 돌아왔는데도 사람이 재시작해야 정상화되는 서비스라면, 장애 시간이 외부 API의 장애 시간보다 길어지기 때문이다.

**불변 조건.** 어떤 장애 중에도 아래 여섯 가지를 지켜야 한다.

1. 201을 받은 요청의 주문은 정확히 하나 저장되어 있다.
2. 201 주문의 상품, 수량, 단가, 합계, 통화, cohort가 요청·응답과 같다.
3. 400, 409, 502, 503, 504만 받은 요청의 주문은 저장되어 있지 않다.
4. 저장된 단가는 lookup이 그 상품에 돌려주는 가격과 같다.
5. 그 repeat에서 보내지 않은 요청의 주문은 없다.
6. 장애가 있는 scenario에서 위의 회복 조건을 지킨다.

확인된 위반이 없고 검사에 필요한 증거가 완전하면 지킨 것이다. 클라이언트가 응답을 받지 못했는데(예: k6 요청 timeout) 서버에는 주문이 저장된 경우는 ambiguous outcome이다. 하네스는 이것을 위반으로 세지 않지만 숨기지도 않고 따로 보고한다. 이 기준을 둔 이유는 돈과 재고가 걸린 주문에서, 실패라고 알린 주문이 저장되거나 틀린 가격으로 저장되는 것은 느린 것보다 나쁘기 때문이다.

## 장애 범주

- **응답 지연**: lookup이 죽지 않고 응답만 늦어진다. [api-slow](scenarios/api-slow/README.md)
- **연결 거부·끊김**: lookup에 연결할 수 없어 요청이 바로 실패한다. [api-down](scenarios/api-down/README.md)
- **응답 없음**: 연결은 되지만 응답이 오지 않는다. scenario 없음.
- **오류 응답**: lookup이 5xx를 돌려주거나 일부 요청만 실패한다. scenario 없음.

장애 없는 비교 기준: [baseline](scenarios/baseline/README.md). 장애 범주가 아니고, 다른 scenario의 결과를 읽을 때 "장애가 없었다면 이 impl은 원래 어땠는가"를 답한다.

## 대응 방법

- **naive** ([README](impls/naive/README.md)): 구현됨. 대응하지 않는 비교 기준이다. lookup 응답을 오래 기다린다.
- **timeout** ([README](impls/timeout/README.md)): 구현됨. 겨냥하는 요구사항은 장애 중에도 서비스가 막히지 않는 것과 회복 조건이다. 응답 지연과 응답 없음에서 효과가 있다.
- **retry**: 미구현. 겨냥하는 요구사항은 SLO 비율이다. 일부 요청만 실패하는 오류 응답에서 효과가 있고, 장애가 계속되는 동안에는 부하만 늘린다.
- **circuit breaker**: 미구현. 겨냥하는 요구사항은 회복 조건과 장애 중 자원 보호다. 장애가 계속될 때 lookup 호출 자체를 멈춰, 응답 지연과 응답 없음에서 기다리는 비용을 없앤다.
- **bulkhead**: 미구현. 겨냥하는 요구사항은 장애 중 자원 보호다. lookup 호출이 동시에 쓸 수 있는 스레드 수를 제한해, 응답 지연이 업무 스레드 전체로 번지지 않게 한다.
- **cache fallback**: 미구현. 겨냥하는 요구사항은 SLO 비율이다. lookup이 없을 때 마지막으로 받은 가격으로 주문을 만들어, 모든 장애 범주에서 주문을 계속 받는다. 대신 불변 조건 4번(stub 가격과 같은 단가)과 부딪칠 수 있다.

## 꼬리 질문 목차

뿌리 질문: 외부 API가 느려지거나 죽을 때, 주문 API는 무엇을 지키고 무엇을 포기해야 하는가?

- scenario: [baseline](scenarios/baseline/README.md#꼬리-질문), [api-slow](scenarios/api-slow/README.md#꼬리-질문), [api-down](scenarios/api-down/README.md#꼬리-질문)
- impl: [naive](impls/naive/README.md#꼬리-질문), [timeout](impls/timeout/README.md#꼬리-질문)
