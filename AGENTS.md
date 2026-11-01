# chaos-lab

부하와 장애를 같은 조건으로 다시 만들어 백엔드 구현(impl)들을 비교하는 실험 하네스. 사용자에게는 한국어로 답한다.

## 먼저 읽을 것

- 지금 어디까지 왔고 다음에 무엇을 하는가: [docs/STATUS.md](docs/STATUS.md)
- 하네스 동작을 바꾸거나 판단이 필요할 때 (계약): [docs/specs/experiment-harness/spec.md](docs/specs/experiment-harness/spec.md), 이유는 같은 폴더의 `decisions.md`
- 용어: [GLOSSARY.md](GLOSSARY.md). 이름은 chaos-lab, 명령은 `chaos`, 단위는 problem · scenario · impl · run · repeat 를 그대로 쓴다.

## 명령

```
uv run pytest                 # 단위·흐름, 수 초. 변경마다 돌린다
uv run pytest -m docker       # 실제 Docker 엔진
uv run pytest -m e2e          # results/의 기록 점검
uv run pytest tests/test_generate.py --update-expected   # Compose 생성 결과를 의도적으로 바꿨을 때 기대 파일 갱신
uv run chaos run external-api/<scenario> --impl <impl>   # 실제 실행: run 하나에 약 25분, 엔진당 한 번에 하나
```

실제 실행은 오래 걸리므로 백그라운드로 돌리고, 첫 repeat의 `results/<run-id>/repeats/1/repeat.json`을 확인해 결함을 일찍 잡는다.

## 작업 규칙

- **spec이 계약이다.** 수용 기준, 인터페이스, 제약을 바꿔야 하는 코드는 쓰기 전에 사용자에게 해당 문구와 이유를 보여 주고 결정을 받는다. 바꾸기로 하면 `decisions.md` 항목과 spec을 고치고 `node ~/.claude/skills/wf-artifacts/check.mjs spec experiment-harness --require-approved`가 PASS인지 확인한 뒤, 사용자 승인을 받고 `Spec-Amended:` 트레일러로 커밋한다.
- 브랜치 `feat/experiment-harness`의 모든 커밋은 `Spec: docs/specs/experiment-harness/spec.md` 트레일러로 끝난다. AC 체크박스는 테스트나 기록된 run이 증명했을 때만 체크한다.
- 검토는 Codex에게 받고, Codex가 최종 승인하면 다음 단계로 넘어간다.
- 필요한 것만 구현한다: 가장 작은 완전한 변경, 이미 있는 helper 재사용, 의존성 추가 없이.
- 고정 스택: Spring Boot 4, Java 21, JdbcTemplate(JPA 아님), 하네스는 uv 기반 Python. OS별 분기 코드는 쓰지 않는다(OS 차이는 psutil·platformdirs 안에서만).
- problem·scenario·impl은 데이터(YAML)다. problem별 Python 코드나 손으로 쓴 Compose 파일 없이, 하네스가 Compose를 생성한다.
- `results/`는 연구 기록이다. 실패하거나 중단된 run도 지우거나 고쳐 쓰지 않고 커밋한다.
- 결과 파일에는 홈 경로, 호스트 이름, 생성된 자격 증명이 들어가지 않는다. 자격 증명은 Compose에 `${CHAOS_…}` 변수 참조로만 넣는다.
- `.claude/`, `.agents/`는 사용자의 로컬 에이전트 설정이다. 건드리지 않는다.

## 엔진 함정 (실제 실행에서 겪은 것)

- OrbStack은 Docker 네트워크끼리 라우팅을 막지 않는다(`--internal`도). 격리는 네트워크 분리가 아니라 리슨 주소로 한다: Toxiproxy API는 컨테이너 loopback에만 열고 하네스는 `docker exec … /toxiproxy-cli`로 제어한다. CLI에는 상태 지정이 없고 `toggle`만 있다.
- containerd 이미지 저장소에서 `docker build -q`가 출력한 ID는 저장된 이미지를 가리키지 않을 수 있다. 태그로 빌드하고 태그로 조회한 `Id`를 쓴다.
- 앱 이미지는 재현 빌드다(같은 소스 → 같은 ID). 빌드 설정을 바꾸면 두 impl이 같은 이미지라는 AC-30이 깨지지 않는지 확인한다.
- k6 per-request 로그를 Alloy가 tail하면 Alloy CPU가 바닥나 스크레이프가 빠지고 repeat가 invalid가 된다.
