# 스키마 안내

이 폴더의 JSON Schema는 설정 파일과 실행 결과가 갖춰야 할 형식을 정의한다. JSON에는 일반적인 주석을 달 수 없으므로, 사람이 읽을 설명은 이 문서에 정리한다. 실제 필수 항목·자료형·허용 값은 각 `.schema.json` 파일이 기준이며, 실행 절차와 의미상의 제약은 [하네스 spec](../docs/specs/experiment-harness/spec.md)이 기준이다.

## 어떤 파일을 검사하는가?

| 스키마 | 검사 대상 | 의미 |
|---|---|---|
| [contract.schema.json](contract.schema.json) | 루트의 `chaos-contract.yaml` | 모든 problem에 공통으로 적용하는 하네스 설정 |
| [problem.schema.json](problem.schema.json) | `problems/<problem>/problem.yaml` | 비교할 업무 동작, 의존성, 판정 기준 |
| [scenario.schema.json](scenario.schema.json) | `problems/<problem>/scenarios/<scenario>/scenario.yaml` | 부하와 장애를 재현하는 실험 조건 |
| [impl.schema.json](impl.schema.json) | `problems/<problem>/impls/<impl>/impl.yaml` | 비교할 구현의 이미지와 실행 설정 |
| [run.schema.json](run.schema.json) | `results/<run-id>/run.json` | run 전체의 실행 결과와 요약 |
| [repeat.schema.json](repeat.schema.json) | `results/<run-id>/repeats/<n>/repeat.json` | 각 repeat의 단계별 기록과 판정 |

앞의 네 파일은 실행에 사용할 **입력**, 뒤의 두 파일은 하네스가 만드는 **결과**다. 새 impl을 작성할 때는 `impl.schema.json`과 해당 problem의 계약을 먼저 확인한다.

## JSON Schema 읽는 법

| 키 | 뜻 |
|---|---|
| `$schema` | 이 스키마가 따르는 JSON Schema 규격 |
| `$id` | 스키마를 구별하는 식별자. 검사할 앱의 주소가 아니다. |
| `title` | 스키마의 이름 |
| `type` | 허용하는 자료형. `object`는 키와 값의 묶음, `array`는 목록이다. |
| `properties` | 각 키에 적용할 규칙 |
| `required` | 반드시 있어야 하는 키 목록 |
| `additionalProperties: false` | 해당 객체에 정의되지 않은 키를 넣을 수 없다는 뜻 |
| `items` | 목록 안의 각 항목에 적용할 규칙 |
| `enum` / `const` | 허용 값 목록 / 반드시 사용해야 할 하나의 값 |
| `pattern` | 문자열이 따라야 할 정규식 |
| `minimum` / `exclusiveMinimum` / `maximum` | 최솟값 이상 / 최솟값 초과 / 최댓값 이하 |
| `minLength` / `maxLength` | 문자열 길이의 하한 / 상한 |
| `minItems` / `uniqueItems` | 목록의 최소 항목 수 / 중복 허용 여부 |
| `minProperties` | 객체에 필요한 최소 키 개수 |
| `oneOf` | 나열한 규칙 중 정확히 하나를 만족해야 한다는 뜻 |
| `allOf` | 나열한 규칙을 모두 만족해야 한다는 뜻 |
| `if` / `then` | 특정 조건에 해당하면 추가 규칙을 적용한다는 뜻 |

`properties`에 있다고 모두 필수는 아니다. 필수 여부는 해당 객체의 `required`를 확인한다. `additionalProperties: false`도 명시된 객체에만 적용되며, 파일 전체에 자동으로 적용되는 규칙은 아니다.

## impl: 구현 실행 설정

`impl.yaml`의 최상위 키는 아래 항목이 모두 필수이며, 임의의 최상위 키는 허용하지 않는다.

| 키 | 의미 |
|---|---|
| `contract_version` | 입력 계약 버전. 현재 `1` |
| `id` / `problem` | impl 이름 / 소속 problem 이름 |
| `description` | 구현을 설명하는 한 줄 문장 |
| `image` | `build`로 로컬 Docker 빌드 경로를 지정하거나, `digest`로 고정 이미지를 지정한다. 둘 중 하나만 사용한다. |
| `ports.business` / `ports.management` | 업무 API 포트 / 관리·관측용 포트 |
| `readiness_path` | 앱이 요청을 받을 준비가 됐는지 확인하는 경로 |
| `metrics_path` | 앱의 지표를 수집하는 경로 |
| `env` | 앱에 전달할 환경 변수. 이름은 대문자·숫자·밑줄 형식이며 숫자로 시작할 수 없고, 값은 문자열이다. |
| `extra_dependencies` | 이 impl만 추가로 사용하는 의존성. 없으면 `[]` |
| `provenance` | 구현의 출처·수정 이력을 기록한 문서 경로. 현재 예시는 `PROVENANCE.md` |

`env` 안의 `IMPL`, `LOOKUP_DEADLINE_MS` 등은 현재 Java 앱이 읽는 환경 변수이지, 모든 impl이 반드시 선언해야 하는 스키마 키는 아니다. 앱이 필요한 환경 변수를 추가할 수 있다.

예를 들어 현재 timeout impl의 핵심 설정은 다음과 같다. 아래는 설명용 발췌이며, 실행하려면 나머지 필수 항목도 필요하다.

```yaml
image: {build: ../../app}
env:
  IMPL: timeout
  LOOKUP_DEADLINE_MS: "300"
provenance: PROVENANCE.md
```

경로는 이 설정 파일이 있는 폴더를 기준으로 해석한다. 위 설정은 공통 앱을 빌드하고, 300ms 기한을 사용하는 모드로 실행하며, 같은 폴더의 출처 문서를 참조한다.

## scenario: 부하와 장애 조건

| 키 | 의미 |
|---|---|
| `contract_version`, `id`, `problem` | 입력 계약 버전, scenario 이름, 소속 problem 이름 |
| `workload.script` | k6 부하 스크립트 경로 |
| `workload.rate` | 초당 요청 도착률 |
| `workload.warmup_s` / `workload.measured_s` | 워밍업 시간 / 본 측정 시간 |
| `workload.graceful_stop_s` | 부하 전송이 끝난 뒤 진행 중인 작업의 종료를 기다리는 시간 |
| `workload.timeout_s` | 부하 클라이언트의 요청 시간 제한 |
| `workload.seed` | 재현 가능한 부하 데이터를 만드는 난수 시드 |
| `faults` | 장애 목록. 장애가 없으면 `[]` |
| `faults[].target` | 장애를 적용할 의존성 이름 |
| `faults[].action` | `latency`는 지연, `down`은 프록시 비활성화 |
| `faults[].value_ms` | 추가할 지연 시간. `latency`일 때 필수 |
| `faults[].apply_at_s` / `faults[].remove_at_s` | 본 측정 시작을 기준으로 장애를 적용 / 해제할 시점 |
| `phase_timeouts_s` | prepare·warmup·measured·recovery·collect·cleanup 단계별 최대 허용 시간 |

`_s`는 초, `_ms`는 밀리초다. 실험 시간과 단계의 최대 허용 시간은 별개다.

## problem: 업무 계약과 판정 기준

| 키 | 의미 |
|---|---|
| `contract_version`, `id`, `description` | 입력 계약 버전, problem 이름, 설명 |
| `dependencies` | 모든 impl이 공통으로 사용하는 DB·가짜 외부 API 등의 의존성 |
| `proxy_budget` | 장애 주입 프록시에 배정하는 CPU·메모리 |
| `openapi` | 앱이 지켜야 할 업무 API 계약 파일 경로 |
| `required_metrics` | 측정 신뢰성을 확인하기 위해 반드시 수집해야 하는 지표 이름 목록 |
| `inflight_metric` / `busy_metric` | 진행 중인 요청 / 처리 중인 작업을 확인하는 지표 이름 |
| `store` | 결과를 확인할 DB 의존성·테이블과 요청 식별자, cohort, 업무 필드, 가격 필드 등의 대응 관계 |
| `invariants` | 어떤 상황에서도 지켜야 할 규칙 목록. 현재 검사기가 지원하는 이름만 사용할 수 있다. |
| `slo.budget_ms` / `slo.success_ratio` | 성공 응답의 시간 한도 / 그 한도 안에 성공해야 하는 요청 비율 |
| `recovery.interval_s` / `recovery.max_s` / `recovery.consecutive` | 복구 확인 요청 간격 / 복구 허용 시간 / 복구로 인정할 연속 성공 횟수 |

`dependencies`와 `extra_dependencies`의 항목은 이름(`name`), 종류(`kind`), 고정 이미지(`image`), 자원 예산(`budget`), 포트(`port`)를 선언한다. 현재 종류는 `postgres`와 `http-fake`이며, 전자는 SQL 경로인 `schema`, 후자는 API 계약 경로인 `openapi`와 응답 정의 경로인 `stubs`가 추가로 필요하다. `budget.cpus`는 CPU 수, `budget.memory_mib`는 MiB 단위 메모리다.

## contract: 하네스 공통 설정

| 키 | 의미 |
|---|---|
| `contract_version` | 입력 계약 버전 |
| `repeats` | run당 repeat 수. 현재 공통 설정은 5회 |
| `vu_factor` | k6 가상 사용자(VU) 수를 산정할 때 사용하는 계수 |
| `images` | k6·Toxiproxy·Alloy·LGTM의 고정 이미지 |
| `budgets` | 앱·공통 도구의 CPU·메모리 예산과 problem 의존성의 예산 상한 |
| `k6_saturation` | 부하 생성기 포화 여부를 확인하는 시간 구간과 비율 기준 |
| `intervals_s` | 지표 스크레이프, 컨테이너 통계 수집, 서비스 탐색 간격 |
| `live` | 실시간 k6 지표 전송 주기·제한 시간과 Grafana annotation 대기열·제한 시간 |
| `metrics_missing` | 지표의 최소 수집 비율과 허용하는 최대 누락 구간 |
| `clock_ms` | 허용하는 시계 차이와 실행 중 차이의 변화량 |
| `fault_tolerance_s` | 계획한 장애 시점과 실제 적용·해제 시점의 허용 오차 |
| `collect_limits_s` | 요청 종료 대기, 지표 도착 대기, 자료 내보내기의 제한 시간 |
| `log_cap_bytes` | 로그 보존량의 전체 한도와 앞부분 보존량 |

스키마가 어떤 숫자를 허용한다고 해서 실험 계약상 자유롭게 바꿔도 된다는 뜻은 아니다. 공통 설정을 바꿀 때는 spec의 제약도 함께 확인한다.

## run·repeat: 실행 결과

이 파일들은 하네스가 생성한다. 보존된 연구 기록이므로 사람이 값을 고쳐 판정을 바꾸지 않는다.

| 파일 | 주요 키 | 의미 |
|---|---|---|
| `run.json` | `schema_version` | 결과 파일 형식 버전 |
| | `run_id`, `problem`, `scenario`, `impl` | 실행 식별자와 선택한 조합 |
| | `exit_code` | 실행 종료 코드. 결과 스키마는 0·1·3을 허용하며 상세 의미는 spec의 종료 코드 표를 따른다. |
| | `repeats` | repeat별 실행 완료·측정 신뢰성 요약 |
| | `identity` | 실행 환경과 입력 등을 식별하는 정보. `harness.commit`은 커밋, `harness.dirty`는 커밋되지 않은 변경 여부 |
| | `aggregate` | repeat들의 집계 결과 |
| | `live_status` | 실시간 관측 상태. `ok` 또는 `degraded` |
| | `cleanup` | 자원 정리 결과 |
| `repeat.json` | `schema_version`, `n` | 결과 파일 형식 버전과 repeat 순번 |
| | `verdicts.completion` | 실행 단계를 끝까지 마쳤는지 |
| | `verdicts.validity` | 측정값을 신뢰할 수 있는지 |
| | `verdicts.correctness` | 업무 규칙을 지켰는지 |
| | `verdicts.slo` | 서비스 수준 목표를 충족했는지 |
| | `phases` | 단계별 실행 기록 |

각 판정에는 판정 값인 `value`와 이유 목록인 `reasons`가 있다. 결과 스키마는 일부 세부 객체와 추가 필드를 열어 두고 있으므로, 위 표가 결과 파일의 모든 필드를 나열한 것은 아니다.

## 예시와 추가 검증

`examples/<종류>/valid/`에는 정상 입력·결과 예시, `invalid/`에는 거부돼야 하는 예시가 있다. 실제 작성 예시는 [external-api](../problems/external-api/)에서도 확인할 수 있다.

스키마 검사는 형식 검사다. 파일 존재 여부, 경로가 자기 problem 밖으로 벗어나는지, 디렉터리와 id가 일치하는지, 장애 시점이 올바른지 등은 하네스가 추가로 검사한다. 스키마만 통과했다고 실행 가능한 설정이 되는 것은 아니다.
