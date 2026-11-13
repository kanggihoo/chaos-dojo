# baseline: 장애 없는 비교 기준

## 브리핑

### 상황

장애 없음. lookup은 처음부터 끝까지 정상으로 응답한다.

k6가 초당 50건의 주문을 일정하게 보낸다. 30초 warmup 뒤 120초 동안 측정하고, k6는 15초 안에 응답을 받지 못한 요청을 끊는다. 부하는 api-slow, api-down과 같으므로, 결과 차이는 장애 유무에서만 나온다. 이 밖의 설정은 같은 폴더의 [`scenario.yaml`](scenario.yaml)에 있다.

이 scenario는 다른 scenario의 비교 기준이다. api-slow와 api-down의 결과를 읽을 때 "장애가 없었다면 이 impl은 원래 어땠는가"에 답한다. 장애 scenario의 장애 전 40초를 기준으로 쓰지 않고 이 scenario를 따로 두는 이유는, 같은 run의 앞 구간에는 시간 경과와 warmup의 영향이 섞여 깨끗한 기준이 되지 못하기 때문이다(experiment-harness decisions.md D-19).

### 클리어 조건

repeat 하나가 아래를 모두 만족하면 클리어다. 기준은 하네스 판정과 같다([problem README의 요구사항](../../README.md#요구사항)).

- repeat가 complete이고 measurement validity가 valid다.
- SLO: measured 요청 전체 가운데 500 ms 안에 201로 끝난 요청의 비율이 0.99 이상이고, 201의 p99가 500 ms 이하다.
- 회복 조건: 해당 없음. 장애가 없으므로 하네스는 회복을 확인하지 않는다.
- 불변 조건: 확인된 위반이 없고 증거가 완전하다. 회복을 다루는 6번은 해당 없다. ambiguous outcome은 위반으로 세지 않고 따로 보고된다.

naive와 timeout 모두 이 scenario를 클리어해야 한다. 클리어하지 못하면 impl보다 측정 환경을 먼저 의심한다.

### 보조 목표

하네스가 판정하지 않음. 장애가 없어 구간 값이 없으므로, 사람이 measured 전체 값을 보고 판단한다.

- naive와 timeout의 예산 안 201 비율, 201 p50, 201 p99가 비슷하다. 두 impl은 lookup 대기 한도만 다르고, lookup이 빠르게 응답하면 그 한도에 닿지 않기 때문이다. 차이가 크면 측정 환경을 먼저 의심한다.
- 같은 impl의 repeat 다섯 개 사이에서 값이 크게 흔들리지 않는다. 리포트의 "조사 신호"(CV 10% 초과)가 없어야 한다.

## 보여 주지 못하는 것

- 장애가 있을 때의 동작 전부. 이 scenario에서는 두 impl이 같은 결과를 내야 정상이므로, impl의 장애 대응 차이는 api-slow와 api-down에서만 보인다.
- 초당 50건보다 높은 부하에서의 한계.

## 꼬리 질문

- Q. 장애가 없을 때 naive와 timeout은 같은 성능인가? — 열림 · 후보: baseline scenario를 naive와 timeout으로 repeat 다섯 개 모두 실행한 run.
- Q. 부하가 초당 50건보다 높아지면 장애 없이도 SLO를 놓치나? — 열림 · 후보: 초당 요청 수를 올린 새 scenario.
