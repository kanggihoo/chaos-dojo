# timeout 출처

## 출처

chaos-lab을 위해 직접 작성한 구현이다. 외부에서 가져온 원본 코드는 없다. 코드는 naive impl과 함께 쓰는 공통 앱 `../../app`에 있고, 환경 변수 `IMPL=timeout`이 이 impl의 lookup 호출 방식을 고른다. 호출 전체에 기한을 거는 부품은 `orders.Deadline`이고, `orders.Impls`가 이 부품으로 HTTP 호출을 감싸 timeout impl을 만든다.

## 수정 이력

원본이 없으므로 원본 대비 수정 이력도 없다.
