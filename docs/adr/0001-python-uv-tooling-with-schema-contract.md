---
status: accepted
---

# 하니스 도구는 Python + uv로 시작하고, JSON Schema 계약으로 Rust 이행을 보장한다

PLAN은 Rust 학습을 보조 목표로 두고 4주차 리포트 생성기와 시즌 1 오케스트레이터를 Rust로 계획했지만, 시즌 0의 실행기(오케스트레이터)와 리포트 생성기는 Python으로 만들고 uv로 고정한다. 사용자가 Windows와 macOS를 함께 쓰기 때문에 두 OS에 Docker Desktop과 uv만 설치하면 같은 명령으로 돌아야 하고, 지금은 도구보다 실험에 시간을 써야 하기 때문이다. Rust 이행은 학습 목적으로 나중에 한다. 그때 결과가 조용히 달라지지 않도록, 파일 형식의 정식 계약은 Python 코드가 아니라 언어와 무관한 JSON Schema(Draft 2020-12)와 fixture, golden 리포트(기대 출력 파일)로 둔다. Rust 구현도 같은 시험을 통과해야 한다.

## Considered Options

- **Makefile + bash**: PLAN의 DoD 문구(`make run ...`)에서 나온 안이다. Windows에는 make가 없고 macOS 기본 bash는 3.2라서, 호스트마다 make·bash 설치와 명령 차이(BSD 도구 포함)를 따로 관리해야 한다.
- **PowerShell(.ps1) + bash(.sh) 이중 스크립트**: 같은 업무 로직을 두 셸에 두 번 쓰게 되고 둘이 어긋난다.
- **runner 컨테이너 + 진입 스크립트**: 호스트 의존은 줄지만, 도커 소켓 마운트와 호스트 경로 변환이 추가로 필요하다.
- **지금 바로 Rust CLI**: PLAN의 원래 방향이다. 하지만 시즌 0에서 실험보다 도구에 시간이 더 든다.
- **Python 클래스로만 형식 정의**: 가장 빠르다. 하지만 Rust로 옮길 때 형식을 코드에서 거꾸로 읽어내야 하고, 두 구현이 조용히 어긋난다.

## Consequences

- Python 코드의 내부 구조는 계약이 아니다. 계약은 스키마, 의미 규칙 설명, 정상/오류 fixture의 기대 결과다.
- 스키마로 표현할 수 없는 의미 규칙(합계, 예측 hash, 환경 일치, CV·p99 계산)도 fixture로 고정해야 한다. 그래야 이행할 때 비교할 기준이 생긴다.
- Rust 학습 목표는 없어지지 않고 미뤄진다. 이행 대상은 이미 계약과 시험이 있는 도구라서, 학습할 때 "같은 출력이 나오는가"를 바로 확인할 수 있다.
- PLAN에서 4주차 "Rust 리포트 생성기", 시즌 1 "Rust 오케스트레이터 CLI 착수", 디렉터리 구조의 `tools/report/` 설명, DoD의 `make run` 문구는 이 결정에 맞게 고쳐야 한다(experiment-harness#D-1).
