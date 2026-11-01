# chaos-lab

부하와 장애를 직접 만들어 내고, 그걸 버티는 백엔드를 여러 방식(impl)으로 구현해 같은 조건에서 비교하는 학습 프로젝트.
(저장소 이름은 `chaos-dojo`로 남아 있다.)

## 필요한 것

Docker 엔진(Compose v2 포함)과 [uv](https://docs.astral.sh/uv/)만 있으면 된다. macOS와 Windows에서 같은 명령으로 동작한다.

## 명령

```
uv run chaos run external-api/api-slow --impl naive          # 한 scenario를 한 impl로 5회 반복 실행
uv run chaos run external-api/api-slow --impl timeout --predict notes/predict.md
uv run chaos report results/<run-id-1> results/<run-id-2>    # 저장된 결과로 비교 리포트
uv run chaos clean                                           # 끝난 run의 잔여물 정리
```

실행 중에는 출력된 Grafana 주소에서 실시간 지표·로그·trace를 보고, 끝나면 `results/<run-id>/report.html`을 연다.

## 문서

- [진행 현황과 이어서 할 일](docs/STATUS.md)
- [기획서](docs/PLAN.md)
- [장기 로드맵](docs/ROADMAP.md)
- [실험 하네스 spec](docs/specs/experiment-harness/spec.md) · [결정 기록](docs/specs/experiment-harness/decisions.md)
- [용어](GLOSSARY.md)
