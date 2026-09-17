# WordPress Secret 연결 수정 및 인증 전수검증 결과

**DATE**: 2026-08-20  
**VERDICT**: PASS

---

## WordPress URL

```
http://salarymate.test
```

(Laragon에서 호스팅, hosts 파일에 `127.0.0.1 SALARYMATE.test` 등록)

---

## Secret 로딩 구조

```
config/config.yaml
  WORDPRESS_URL: http://salarymate.test        ← PRESENT
  WORDPRESS_USERNAME: geminia                   ← PRESENT

config/secrets.yaml
  wordpress:
    username: (PRESENT)                         ← PRESENT
    app_password: (PRESENT)                     ← PRESENT

modules/config_loader.py
  load_config()
    → config.yaml 로드
    → secrets.yaml 병합 (secrets 우선)
    → flat + nested 키 모두 cfg에 존재

modules/publisher.py
  _wp_auth(cfg)
    → cfg["WORDPRESS_USERNAME"] 또는 cfg["wordpress"]["username"]
    → cfg["WORDPRESS_APP_PASSWORD"] 또는 cfg["wordpress"]["app_password"]
```

---

## 설정 상태

| 항목 | 상태 |
|------|------|
| WORDPRESS_URL | PRESENT (`http://salarymate.test`) |
| WORDPRESS_USERNAME | PRESENT (`geminia`) |
| WORDPRESS_APP_PASSWORD (flat) | EMPTY |
| wordpress.nested.app_password | PRESENT |
| is_wordpress_ready() | **True** |

**NOTE**: `config/wordpress.yaml`의 빈 credentials는 `config_loader`에서 로드하지 않으므로 publisher에 영향 없음.

---

## WordPress 인증 테스트

```
GET /wp-json/wp/v2/users/me
Auth: (geminia, ***)
Response: HTTP 200
user_id: 1
name: SalaryMate
```

**RESULT: PASS**

---

## 기존 게시물 검사

```
GET /wp-json/wp/v2/posts?slug=severance-pay
Response: HTTP 200, count=0
```

**severance-pay slug 중복: 없음**

---

## DB 불변성

```
calculators rows: 14
Golden 10 article_content: ALL PRESENT
DB hash: UNCHANGED
```

---

## Calculator Scheduler

```
Status: OFF
run_scheduler.bat: .disabled
```

---

## Draft 발행 테스트

**STATUS: NOT RUN** (인증까지 검증 완료, 실제 발행은 별도 지시 필요)

---

## 최종 판정

| 항목 | 결과 |
|------|------|
| WordPress URL | `http://salarymate.test` |
| Secret username | PRESENT |
| Secret app_password | PRESENT |
| Publisher credential loading | PASS |
| /users/me authentication | PASS |
| Draft creation | NOT RUN |
| Database | UNCHANGED |
| Golden 10 | UNCHANGED |
| Calculator Scheduler | OFF |

**NEXT STEP**: `severance-pay` 1건 Draft 발행 테스트 진행 가능
