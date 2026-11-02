# chaos-lab

같은 백엔드 환경을 필요할 때마다 다시 구성하고, 부하와 장애를 주어 여러 구현이 동일한 조건에서 어떻게 동작하는지 비교하는 실험실.

## 실험 구성

**Problem**:
하나의 업무 동작을 중심으로 묶은 장애 상황의 범주. 예를 들어 “외부 API가 느려지거나 응답하지 않는 상황”을 하나의 problem으로 다룬다.
_사용하지 않는 표현_: kata, drill, case

**Scenario**:
하나의 problem에서 부하, 장애, 확인 항목을 구체적으로 정해 실행할 수 있게 만든 실험 조건. baseline, api-slow, api-down이 이에 해당한다.
_사용하지 않는 표현_: test case, kata variant

**Impl**:
하나의 problem을 해결하는 구현으로, 해당 problem에 속한 모든 scenario에서 실행할 수 있다. naive, timeout이 이에 해당한다.
_사용하지 않는 표현_: strategy, variant, solution

**Run**:
하나의 scenario를 하나의 impl에 대해 실행하는 단위. 실행 후 보존하는 결과 묶음까지 포함한다.
_사용하지 않는 표현_: experiment, session

**Repeat**:
run 안에서 매번 새 환경을 구성해 독립적으로 수행하는 한 차례의 실행. 하나의 run은 repeat 다섯 개로 구성된다.
_사용하지 않는 표현_: iteration, trial

**Cohort**:
요청을 보낸 목적에 따라 나눈 그룹. 워밍업용(warmup), 측정용(measured), 복구 확인용(recovery probe)으로 구분한다.
_사용하지 않는 표현_: phase (phase는 시간 구간을 뜻하며, 요청을 목적별로 묶은 그룹과는 구별한다.)

## 결과 판정

**Completion**:
repeat가 모든 실행 단계를 끝까지 마쳤는지에 대한 판정.

**Measurement validity**:
repeat에서 얻은 측정값을 신뢰할 수 있는지에 대한 판정. 측정값이 좋은 결과를 나타내는지와는 별개다.
_사용하지 않는 표현_: success, health

**Correctness**:
repeat가 problem에 정의된 불변 조건, 즉 어떤 상황에서도 지켜야 하는 규칙을 모두 지켰는지에 대한 판정.
_사용하지 않는 표현_: validity

**SLO**:
repeat가 problem에 정의된 서비스 수준 목표를 충족했는지에 대한 판정. 정해진 응답 시간 한도 안에 성공한 요청의 비율과 성공 요청의 지연 시간을 기준으로 한다.
_사용하지 않는 표현_: performance pass

**Ambiguous outcome**:
서버에는 결과가 저장됐지만 클라이언트는 그 결과를 확인하지 못한 상태. 클라이언트의 요청 시간이 초과된 뒤 주문이 저장된 경우 등이 해당하며, 규칙 위반이나 통과로 판정하지 않고 별도로 보고한다.
_사용하지 않는 표현_: phantom order

**Time-to-recovery**:
장애를 해제한 시점부터, 정해진 응답 시간 한도 안에 성공하는 요청이 연속해서 나타나기 시작한 시점까지 걸린 시간.
_사용하지 않는 표현_: MTTR
