# problem-docs decisions

Glossary: [GLOSSARY.md](../../../GLOSSARY.md) · ADRs: none

## D-1 범위
- Status: settled
- Decision: problem 데이터에 딸린 사람용 문서 네 종류(problem README, scenario README, impl README, PROVENANCE)의 형식을 정한다. experiment-harness와 별개의 feature로 다룬다.
- Rejected: experiment-harness에 amendment로 넣기 → 진행 중인 하네스 계약에 문서 규칙이 섞인다 · `docs/`의 STATUS·PLAN·ROADMAP과 루트 README까지 포함 → 하나씩만 있는 문서라 템플릿으로 얻는 것이 적다 · 저장소의 모든 `.md` → 같은 이유이고, decisions.md와 spec.md는 wf가 이미 형식을 강제한다

## D-2 템플릿과 기존 문서
- Status: settled
- Decision: `docs/templates/`에 네 종류의 템플릿을 둔다. 이번 feature에서 기존 문서 7개를 템플릿에 맞춰 다시 쓰고 `problems/external-api/README.md`를 새로 만든다. AGENTS.md에 "problem 데이터 문서는 이 템플릿을 따른다"는 규칙을 넣는다. AGENTS.md에서 트레일러 경로를 experiment-harness로 고정하고 AC 체크 근거를 테스트와 run으로 한정한 줄은 지우고, "spec이 계약이다" 줄의 check 명령도 작업 중인 feature를 가리키게 한다. 두 규칙은 wf 스킬이 feature마다 정하므로 이 줄은 중복이고, 다른 feature에서는 틀린 규칙이 된다. AGENTS.md 변경을 구현의 첫 commit으로 한다.
- Rejected: `problems/_template/` → `problems/`는 하네스가 읽는 데이터 폴더라서 데이터가 아닌 파일이 problem처럼 섞인다 · 템플릿만 만들고 기존 문서는 나중에 → 다음 작성자는 템플릿보다 옆의 기존 문서를 따라 쓴다
- Reuse: none (modify) — `problems/external-api/`의 scenario README 3개(baseline, api-slow, api-down), impl README 2개(naive, timeout), PROVENANCE 2개를 템플릿 형식으로 다시 쓰고, 각 `impl.yaml`의 `provenance: PROVENANCE.md` 참조가 가리키는 파일은 유지한다 · `AGENTS.md#작업 규칙` (modify) — 템플릿을 따르라는 규칙 한 줄을 추가하고, 트레일러·AC 체크 규칙 줄을 지우고, check 명령의 feature 고정을 푼다. 그 밖은 건드리지 않는다

## D-3 형식을 지키게 하는 수단
- Status: provisional
- Decision: 검사 코드를 두지 않는다. 템플릿, AGENTS.md 규칙, Codex 검토로 지킨다.
- Default: 문서 형식 검사 없음. 형식 위반이 검토에서 반복해서 나오면 별도 Python 검사 스크립트를 다시 검토한다.
- Rejected: pytest 검사 → 확인할 수 있는 것이 제목의 존재까지이고, 꼬리 질문이 실제로 이어지는지는 기계가 판단하지 못한다 · 별도 검사 스크립트 → 같은 이유이고, 문서가 8개뿐인 지금은 검토로 충분하다 · `chaos run` 입력 검증에서 README 요구 → 하네스 계약을 바꾸고 문서 때문에 실험이 막힌다

## D-4 problem README
- Status: settled
- Decision: 업무 상황, 요구사항(SLO, 회복 조건, 불변 조건)을 하네스 판정과 같은 기준으로 값과 함께 문장으로 풀고 각 기준을 둔 이유, 대응 방법 목록, 꼬리 질문의 뿌리를 담는다. 값의 출처로 같은 폴더의 `problem.yaml`을, 판정 규칙의 출처로 experiment-harness spec을 가리킨다.
- Rejected: 요구사항을 `problem.yaml` 링크로만 두기 → impl README가 "이 요구사항을 지키려고 이 방식을 골랐다"고 쓸 때 가리킬 설명이 없다 · 구현된 impl만 목록에 적기 → 지금 비교하는 방법이 전체 선택지 중 어디인지 보이지 않는다. 미구현 방법(retry, circuit breaker, bulkhead, cache fallback 등)도 "미구현"으로 표시해 적고, 각 방법이 겨냥하는 요구사항을 붙인다

## D-5 scenario README
- Status: settled
- Decision: 브리핑(상황 이야기, 클리어 조건, 보조 목표), 이 scenario가 보여 주지 못하는 것, 꼬리 질문을 담는다. 장애는 앱이 보는 증상으로 적고 주입 방식은 적지 않는다.
- Rejected: 장애 주입 방식(Toxiproxy 동작) 설명 → 읽는 사람에게 중요한 것은 앱이 겪는 장애다. 다만 연결 거부와 응답 없음처럼 증상이 갈리는 차이는 증상으로 적는다 · NFR 형식의 요구사항 문장 → 게임 stage 브리핑처럼 상황과 숫자로 된 목표가 더 직관적이다 · "왜 이 장애 유형인가"를 필수 섹션으로 → 상황 이야기 안에 한두 문장으로 녹인다

## D-6 클리어 조건과 보조 목표
- Status: settled
- Decision: 클리어 조건은 하네스 판정과 똑같이 적고, 지금 impl로 클리어할 수 없으면 그 사실도 적는다. 클리어 조건은 하네스가 판정하는 단위인 repeat 하나를 기준으로 적는다. 보조 목표는 하네스가 판정하지 않는다고 표시하고, 장애 전·중·후 구간 수치로 사람이 판단한다. 장애가 없는 baseline은 구간이 없으므로 measured 전체 수치로 판단한다.
- Rejected: 클리어 조건만 적기 → SLO는 measured 요청 전체로 판정하므로(experiment-harness AC-23) 장애가 40초인 scenario에서 lookup이 필요한 impl은 모두 미달이 되어 impl 사이 차이가 보이지 않는다 · scenario별 목표만 적기 → README가 하네스가 하지 않는 판정을 하는 것처럼 보인다

## D-7 impl README
- Status: settled
- Decision: 겨냥하는 요구사항(지키려는 것과 포기하는 것), 왜 이 방식인가, 작동 원리, 해결하는 것과 해결하지 못하는 것, 꼬리 질문을 담는다. 기준점 impl(naive)은 "대응하지 않았을 때를 기록하는 비교 기준"을 선택 이유로 적는다.
- Rejected: 학습 노트 형식("배울 것" 목록) → 선택 이유, 한계, 다음 질문으로 이어지는 흐름이 드러나지 않는다

## D-8 꼬리 질문과 결론
- Status: settled
- Decision: 각 scenario·impl README 끝에 꼬리 질문을 둔다. 질문마다 `답함`(답한 run id) 또는 `열림`(답할 후보 impl·scenario)을 붙인다. 질문 본문은 그 README에만 두고 problem README는 링크로 잇는다. 기록된 run으로 확인한 결론은 run id와 날짜를 붙여 적는다. 결론의 근거는 repeat 다섯 개가 모두 complete이고 valid인 run만 인정하고, 결론의 수치는 그 run의 run 수준 값(repeat별 값의 중앙값)을 쓰고, 하네스가 모으지 않는 구간 값은 repeat별 값에서 중앙값을 직접 구한다. 중단된 run의 수치는 참고로도 적지 않는다.
- Rejected: 중단된 run의 일부 repeat를 회차를 밝혀 근거로 쓰기 → repeat 한두 번으로는 하네스가 run 결과로 치지 않는 수치를 결론처럼 적게 된다 · 실험 전 질문만 적기 → 배운 것이 쌓이는 곳은 결론이다 · 결론을 STATUS.md나 리포트에만 두기 → 질문과 답이 떨어져 꼬리가 끊긴다 · 별도 backlog 파일 → `열림` 질문이 그대로 다음 impl·scenario 후보 목록이다

## D-9 숫자와 기록 결과
- Status: settled
- Decision: 상황 설명(장애, 부하), 클리어 조건, impl이 장애 중 어떻게 동작하는지 설명하는 데 필요한 숫자는 문장으로 쓴다. 나머지 설정은 같은 폴더의 YAML을 가리킨다. 상태 코드나 run id 같은 식별자는 숫자 규칙의 대상이 아니다. 기록 결과는 결론 문장 안의 근거 숫자 정도만 쓰고 결과 표는 옮기지 않는다. 수치를 고른 이유는 필수가 아니며, 결과 해석을 바꾸는 수치일 때만 한 줄 적는다.
- Rejected: 설정 값과 결과를 표로 모두 옮기기 → YAML이나 `results/`가 바뀌면 README가 틀린다 · 숫자를 전혀 쓰지 않기 → "느려진다"만으로는 상황이 전달되지 않는다 · 모든 수치의 선정 근거 요구 → 지금 수치에는 기록된 근거가 없고, 읽는 사람에게 중요한 것은 해결 방식의 선택 이유다
