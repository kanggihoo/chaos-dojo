# problem 문서 (problem-docs)

Status: approved
Decisions: [decisions.md](decisions.md) · Glossary and ADRs: [GLOSSARY.md](../../../GLOSSARY.md) · ADRs: none

## Problem

`problems/` 아래의 problem, scenario, impl은 YAML 데이터라서 하네스는 읽을 수 있지만 사람은 읽기 어렵다. `scenario.yaml`에는 숫자만 있고, impl에는 한 줄 `description`과 출처 문서(`PROVENANCE.md`)뿐이다. 이 scenario가 어떤 장애 상황이고 무엇을 해내야 하는지, 이 impl이 왜 그 대응 방식을 골랐고 무엇을 해결하지 못하는지가 어디에도 없다.

이번 세션에 손으로 쓴 README 5개는 형식이 제각각이다. 새 problem·scenario·impl이 추가될 때마다 문서가 같은 질문에 같은 순서로 답하도록 형식을 템플릿으로 고정하고, 문서끼리 "이 방식은 무엇을 해결하지 못하나 → 그러면 어떻게 하나"로 이어지게 하려 한다.

## Assumptions

1. problem의 요구사항은 `problem.yaml`의 `slo`, `recovery`, `invariants` 세 필드가 값을 정하고, 판정 규칙(예산 안 201만 성공으로 세는 것, p99 계산 방식, 회복 판정 창)은 experiment-harness spec이 정한다. 하네스는 repeat마다 completion, measurement validity, correctness, SLO를 따로 판정한다. SLO는 measured cohort 요청 전체로 판정하고, 장애 전·중·후 구간 값은 표시만 한다(experiment-harness AC-23). 장애가 없는 scenario에는 구간 값이 없다.
2. scenario·impl 폴더의 README와 PROVENANCE는 scenario 해시와 앱 이미지에 들어가지 않는다. scenario 해시는 `scenario.yaml`과 k6 스크립트로만 계산하고(`chaos/runner.py` `hash_closure` 호출부), 앱 이미지는 `problems/external-api/app`에서만 빌드한다. 다만 run마다 problem 폴더 전체가 `inputs/`로 복사되므로 문서도 run 기록에 함께 남는다.
3. `chaos run`의 입력 검증은 각 `impl.yaml`의 `provenance`가 가리키는 파일이 problem 폴더 안에 있는지 확인한다(`chaos/validate.py` `asset`). 내용은 검사하지 않는다.
4. 2026-11-12 기준 problem은 `external-api` 하나, scenario는 baseline·api-slow·api-down, impl은 naive·timeout이다. repeat 다섯 개가 모두 기록된 run은 api-slow의 `20261031-004309-external-api-api-slow-naive-2c0c93`과 `20261031-002528-external-api-api-slow-timeout-8def62` 두 개뿐이다.

## Usage

- 새 impl(예: circuit breaker)을 추가하는 사람은 `docs/templates/`의 impl README와 PROVENANCE 템플릿을 복사해 채운다. "겨냥하는 요구사항"은 problem README의 요구사항 설명으로 링크하고, 꼬리 질문은 다른 impl README의 `열림` 질문에서 이어받는다.
- scenario 결과를 처음 보는 사람은 scenario README의 브리핑을 읽고, 클리어 조건(하네스가 판정하는 기준)과 보조 목표(사람이 수치로 판단하는 목표)를 리포트와 나란히 놓고 본다.
- 다음에 무엇을 만들지 고르는 사람은 problem README의 꼬리 질문 목차에서 각 README로 가서 `열림` 질문과 그 후보를 따라간다.

## Acceptance criteria

- [ ] AC-1: `docs/templates/`에 problem README, scenario README, impl README, PROVENANCE 템플릿 네 개가 있고, 각 템플릿은 H1 제목과 아래 Interfaces의 해당 섹션만 같은 순서로 갖추며 섹션마다 무엇을 쓰는지 안내한다; 템플릿을 따라 쓴 문서에는 그 안내문이 주석으로도 남지 않는다. (D-1, D-2)
- [ ] AC-2: `problems/external-api/README.md`가 problem README 템플릿 형식으로 존재한다; 요구사항 세 가지(SLO, 회복 조건, 불변 조건)를 각각 AC-4와 같은 판정 기준으로 값과 함께 문장으로 풀고 기준을 둔 이유를 적으며, 값의 출처로 같은 폴더의 `problem.yaml`을, 판정 규칙의 출처로 experiment-harness spec을 가리킨다; 대응 방법 목록에는 구현된 impl(naive, timeout)과 미구현 방법이 구현 여부와 겨냥하는 요구사항과 함께 있다; 미구현 방법에는 적어도 retry, circuit breaker, bulkhead, cache fallback이 들어가고 더 넣어도 된다; naive는 "대응하지 않는 비교 기준"으로 적는다; 장애 범주에는 아직 scenario가 없는 범주를 "scenario 없음"으로 표시해 넣어도 되고, baseline은 장애 범주가 아니라 "장애 없는 비교 기준"으로 따로 적는다. (D-4)
- [ ] AC-3: scenario README 3개(baseline, api-slow, api-down)가 scenario README 템플릿 형식이다; scenario README는 장애를 앱이 보는 증상으로 적고 장애 주입 도구와 그 동작은 적지 않는다; api-down은 "lookup 연결이 거부되거나 끊겨 응답을 기다리지 않고 실패한다"는 증상을 적고, "연결은 되지만 응답이 오지 않는" 장애를 보여 주지 못한다고 적는다; 장애가 없는 baseline은 상황에 장애 크기와 시점 대신 "장애 없음"과 다른 scenario의 비교 기준이라는 역할을 적고, 보여 주지 못하는 것에는 장애가 있을 때의 동작을 적는다. (D-5)
- [ ] AC-4: 각 scenario README의 클리어 조건은 repeat 하나에 대한 하네스 판정과 같은 기준을 숫자로 적는다(repeat가 complete이고 measurement validity가 valid일 것, 응답 예산, 예산 안 201 비율 임계값, 201 p99 한도, 회복 조건, 불변 조건); 회복 조건은 하네스 판정대로 "장애 해제를 확인한 뒤 60초 창 안에 예산 안 201이 연속 5번 도착한다"로 적고 time-to-recovery 한도로 적지 않는다; 불변 조건은 확인된 위반이 없고 증거가 완전하면 지킨 것이며 ambiguous outcome은 위반으로 세지 않고 따로 보고된다는 점까지 적는다; 장애가 없는 baseline은 회복 조건을 "해당 없음"으로 적는다; SLO가 measured 요청 전체로 판정된다는 점을 적는다; api-slow와 api-down은 lookup 응답이 있어야만 주문을 만드는 impl로는 SLO를 클리어할 수 없다고 적고, 그 근거는 장애 길이와 measured 길이의 산술로 적는다(이 산술은 run 결론이 아니므로 run id를 붙이지 않는다); 보조 목표는 "하네스가 판정하지 않음"이라는 표시와 함께 어느 구간의 어떤 수치로 판단하는지 적는다; 장애가 있는 scenario는 장애 전·중·후 구간을, baseline은 measured 전체를 쓴다. (D-6)
- [ ] AC-5: impl README 2개(naive, timeout)가 impl README 템플릿 형식이다; 겨냥하는 요구사항에는 지키려는 것과 포기하는 것을 모두 적고 problem README의 요구사항 설명으로 링크한다; naive의 "왜 이 방식인가"는 대응하지 않았을 때를 기록하는 비교 기준이라고 적는다. (D-7)
- [ ] AC-6: PROVENANCE 2개가 PROVENANCE 템플릿 형식이고 파일 이름과 위치가 그대로이며, `uv run pytest tests/test_validate.py::test_valid_closure_passes`의 결과가 이 feature 시작 전과 같다. (D-2)
- [ ] AC-7: 모든 scenario·impl README의 꼬리 질문은 각각 `답함` 또는 `열림` 상태를 가진다; `답함`에는 답한 run의 전체 run id가 하나 이상, `열림`에는 답할 후보 impl이나 scenario가 붙는다; 이 feature의 모든 문서에서 기록된 run으로 확인한 결론 문장에는 전체 run id와 그 결론을 적은 날짜가 붙는다; 결론의 근거가 되는 run은 repeat 다섯 개가 모두 complete이고 measurement validity가 valid인 run뿐이고, 결론에 쓰는 수치는 그 run의 run 수준 값, 곧 repeat 다섯 개의 값의 중앙값이다(experiment-harness AC-27); 하네스가 run 수준으로 모으지 않는 값(장애 전·중·후 구간 값, k6 timeout 수 등)은 repeat별 값에서 중앙값을 손으로 구해 쓰고 그렇게 구했다고 밝힌다; 그런 run이 없는 질문은 `열림`으로 두고, 중단된 run의 수치와 run id는 결론이든 참고든 어디에도 적지 않는다; problem README의 꼬리 질문 목차는 뿌리 질문과 각 README로 가는 링크만 두고 질문 본문을 복제하지 않는다. (D-8)
- [ ] AC-8: 템플릿 네 개와 이 feature가 만들거나 고친 `problems/` 아래 문서 어디에도 `results/`의 결과나 YAML 설정을 옮긴 표나 code block이 없다; 측정값과 설정값은 문장 안에만 나오고, 허용되는 것은 장애의 크기와 시점, 부하(초당 요청 수, warmup·measured 길이, k6 요청 timeout), 요구사항과 클리어 조건의 값, impl이 장애 중 어떻게 동작하는지를 정하는 값(예: timeout의 기한, 두 impl이 공유하는 업무 스레드 수, pool 크기, 연결·pool 획득 timeout), 결론의 근거 숫자, impl README의 "해결하는 것과 해결하지 못하는 것"에 두는 결과 해석을 바꾸는 수치 한 줄이다(측정값이면 AC-7의 결론 규칙을 따른다); 그 밖의 설정은 같은 폴더의 YAML 파일을 가리킨다; 상태 코드, run id, 날짜, AC 번호 같은 식별자는 이 제한을 받지 않는다. (D-9)
- [ ] AC-9: AGENTS.md의 작업 규칙에 "problem 데이터 문서는 `docs/templates/`의 템플릿을 따른다"는 규칙이 한 곳에 있다; 트레일러 경로를 `docs/specs/experiment-harness/spec.md`로 고정하고 AC 체크 근거를 테스트와 기록된 run으로 한정한 줄은 없다; "spec이 계약이다" 줄의 check 명령은 experiment-harness 대신 `<feature>` 자리 표시로 작업 중인 feature를 가리킨다; AGENTS.md의 나머지는 바뀌지 않는다. (D-2, D-3)
- [ ] AC-10: 이 feature의 변경 뒤 `uv run pytest`의 실패 목록이 변경 전과 같다(새 실패 없음). 이 feature는 `.md` 파일만 만들거나 고치고, 문서 형식을 검사하는 테스트나 스크립트를 어디에도 추가하지 않는다. (D-3)

## Interfaces

템플릿 네 개의 섹션 구성. 템플릿과 그 템플릿을 따른 문서는 H1 제목 아래에 이 섹션만 이 순서로 갖는다. 다른 문서로 가는 링크는 해당 섹션 안에 둔다. 섹션 제목의 정확한 문구, 제목 수준(브리핑 세 섹션을 하위 제목으로 묶을지), 안내문의 표기 방식은 구현자 재량이지만, 템플릿과 이를 따른 문서 사이에서는 같은 제목 문구를 쓴다.

**problem README** (`problems/<problem>/README.md`)

| 순서 | 섹션 | 담는 것 |
|---|---|---|
| 1 | 업무 상황 | 이 problem의 업무 동작과 의존 관계 |
| 2 | 요구사항 | SLO, 회복 조건, 불변 조건을 값과 함께 문장으로 풀고 각 기준을 둔 이유. 값의 출처로 같은 폴더 `problem.yaml`을, 판정 규칙의 출처로 experiment-harness spec을 가리킨다 |
| 3 | 장애 범주 | 이 업무가 약한 장애의 종류와 scenario 목록(각 README 링크). 장애 없는 비교 기준 scenario는 따로 표시한다 |
| 4 | 대응 방법 | 방법마다 구현 여부(impl README 링크 또는 "미구현"), 겨냥하는 요구사항, 효과가 있는 장애 한 줄. 비교 기준 impl은 효과가 있는 장애 대신 비교 기준임을 적는다 |
| 5 | 꼬리 질문 목차 | 뿌리 질문 하나와, 각 scenario·impl README로 가는 링크 |

**scenario README** (`problems/<problem>/scenarios/<scenario>/README.md`)

| 순서 | 섹션 | 담는 것 |
|---|---|---|
| 1 | 브리핑: 상황 | 앱이 보는 증상, 실제 서비스에서 언제 일어나는지, 장애 크기와 시점, 부하. 이 장애 유형을 고른 이유를 한두 문장 포함(장애 없는 scenario는 비교 기준이라는 역할) |
| 2 | 브리핑: 클리어 조건 | AC-4의 기준. 지금 impl로 클리어할 수 없으면 그 사실 |
| 3 | 브리핑: 보조 목표 | "하네스가 판정하지 않음" 표시, 목표, 판단에 쓰는 구간과 수치 |
| 4 | 보여 주지 못하는 것 | 이 scenario로는 관찰할 수 없는 장애나 조건 |
| 5 | 꼬리 질문 | 꼬리 질문 형식(아래) |

**impl README** (`problems/<problem>/impls/<impl>/README.md`)

| 순서 | 섹션 | 담는 것 |
|---|---|---|
| 1 | 겨냥하는 요구사항 | problem 요구사항 중 지키려는 것과 포기하는 것. problem README로 링크 |
| 2 | 왜 이 방식인가 | 같은 요구사항을 노리는 다른 방법 대신 이것을 고른 이유 |
| 3 | 작동 원리 | 장애 중에 이 impl이 요청을 어떻게 처리하는지. 설정 값은 AC-8 범위 안에서 문장으로 쓰고 같은 폴더 `impl.yaml`과 `PROVENANCE.md`를 가리킨다. 실행 명령은 적지 않는다(AGENTS.md에 있다) |
| 4 | 해결하는 것과 해결하지 못하는 것 | 둘 다 적는다. 결과 해석을 바꾸는 수치가 있으면 그 수치와 이유를 한 줄 |
| 5 | 꼬리 질문 | 꼬리 질문 형식(아래) |

**PROVENANCE** (`problems/<problem>/impls/<impl>/PROVENANCE.md`)

| 순서 | 섹션 | 담는 것 |
|---|---|---|
| 1 | 출처 | 원본의 위치와 버전, 또는 chaos-lab을 위해 직접 작성했다는 사실 |
| 2 | 수정 이력 | 원본 대비 바꾼 것과 이유. 원본이 없으면 그렇다고 적는다 |

**꼬리 질문 형식** (scenario·impl README 공통)

```
- Q. <질문> — 답함 · <전체 run id>[, <전체 run id>…] (<결론을 적은 날짜 YYYY-MM-DD>): <결론 한두 문장>
- Q. <질문> — 열림 · 후보: <impl 또는 scenario 이름과 한 줄 설명>
```

결론을 적은 날짜는 그 문장을 쓴 날이다. 기존 문서의 결론을 옮겨 쓰면 옮겨 쓴 날을 적는다.

## Constraints

- 템플릿 위치는 `docs/templates/`다. `problems/` 아래에 두지 않는다. (D-2)
- 형식은 템플릿, AGENTS.md 규칙, Codex 검토로 지킨다. 형식 검사 코드를 추가하지 않는다. 형식 위반이 검토에서 반복되면 이 결정을 다시 검토한다. (D-3)
- 숫자 규칙은 AC-8을 따른다. 수치를 고른 이유는 필수가 아니며, 결과 해석을 바꾸는 수치일 때만 한 줄 적는다. (D-9)
- 하네스 코드, 스키마, `problem.yaml`·`scenario.yaml`·`impl.yaml`은 바꾸지 않는다. (D-1)
- 구현의 첫 commit은 AGENTS.md 변경(AC-9)이다. 이 commit을 포함해 승인 뒤 모든 commit은 `Spec: docs/specs/problem-docs/spec.md` 트레일러를 단다. 그래야 트레일러와 Codex 검토로 체크하는 AC가 바뀐 AGENTS.md 규칙과 맞는다. (D-2)

## Existing code

| Locator | Action | Obligation | Decision |
|---|---|---|---|
| none | modify | `problems/external-api/`의 scenario README 3개(baseline, api-slow, api-down)와 impl README 2개(naive, timeout)를 템플릿 형식으로 다시 쓴다 | D-2 |
| none | modify | naive·timeout의 `PROVENANCE.md`를 템플릿 형식으로 다시 쓰되, 각 `impl.yaml`의 `provenance: PROVENANCE.md`가 가리키는 파일 이름과 위치는 유지한다 | D-2 |
| `AGENTS.md#작업 규칙` | modify | 템플릿을 따르라는 규칙 한 줄을 추가하고, "모든 커밋은 `Spec: docs/specs/experiment-harness/spec.md` 트레일러로 끝난다. AC 체크박스는…" 줄을 지우고, "spec이 계약이다" 줄의 check 명령에서 experiment-harness를 작업 중인 feature로 바꾼다. 그 밖은 그대로 둔다 | D-2 |

## Seams & test plan

- Codex 검토 (manual), AC-1~AC-5, AC-6(템플릿 형식과 파일 이름·위치), AC-7, AC-8, AC-9, AC-10(`.md` 외 변경 없음): 템플릿과 문서를 Interfaces 표와 대조하고, 클리어 조건의 숫자를 `problem.yaml`과 experiment-harness spec의 판정 규칙(AC-23, AC-25, recovery 규칙)과 대조하고, `답함`의 run id가 `results/`에 있고 repeat 다섯 개가 모두 complete·valid인지, 인용한 수치가 그 run의 `run.json` aggregate 값이나 repeat별 값의 중앙값과 같은지 확인하고, 문서에 중단된 run id가 없는지, 안내문 흔적(`<!--` 등)이 남지 않았는지 검색하고, 숫자를 AC-8의 허용 목록과 대조하고, diff에 `.md` 외 파일이 없는지 본다. 잡는 것: 섹션 누락·순서·추가, 판정과 다른 클리어 조건, 결과 표 복제, 남은 안내문, 근거가 될 수 없는 run, 틀린 인용 수치. 놓치는 것: 꼬리 질문이 실제로 좋은 다음 질문인지.
- `uv run pytest tests/test_validate.py::test_valid_closure_passes` (example), AC-6: 실제 `problems/external-api`를 복사한 저장소에서 api-slow·naive 입력 검증이 통과하는지 확인해 naive의 PROVENANCE 참조가 깨지지 않았음을 잡는다. 놓치는 것: timeout의 참조(Codex 검토가 파일 이름·위치 불변으로 확인한다), PROVENANCE 내용. Prior art: 기존 테스트 그대로.
- `uv run pytest` 전체 (example), AC-10: 첫 commit 전에 실패 목록을 받아 두고, 마지막 commit 뒤 목록과 비교한다. 이 PC에는 변경 전부터 실패하는 테스트가 17개 있다(Windows symlink 권한, cp949 인코딩). 잡는 것: 문서 변경이 하네스 동작을 건드린 경우. 놓치는 것: 없음(문서만 바뀐다).

## Out of scope

- `docs/STATUS.md`, `docs/PLAN.md`, `docs/ROADMAP.md`, 루트 `README.md`, `schemas/README.md`의 형식. (D-1)
- 문서 형식 검사 테스트나 스크립트. (D-3)
- `scenario.yaml`에 `description` 필드 추가 같은 스키마 변경. (D-1)
- 미구현 대응 방법(retry, circuit breaker 등)의 impl 구현과 새 scenario 추가. 이들은 `열림` 꼬리 질문의 후보로만 적는다. (D-4, D-8)
- `GLOSSARY.md`에 문서 관련 용어 추가.

## Open questions

none
