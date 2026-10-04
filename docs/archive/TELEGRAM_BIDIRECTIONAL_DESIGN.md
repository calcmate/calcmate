# TELEGRAM_BIDIRECTIONAL_DESIGN.md

> 양방향 텔레그램(명령 수신 → 시스템 제어) **설계 문서**. SPRINT 2B 작업9.
> ⚠️ 본 Sprint에서는 **구현하지 않는다.** 설계/후속 과제 정의만.

## 1. 현재(단방향) 구조
```
시스템 → telegram_ops.notify_*() → telegram_notifier.send() → Telegram Bot API(sendMessage) → 운영자
```
- 발송 전용. 운영자가 텔레그램에서 **회신/명령**해도 시스템은 읽지 않음.
- 키: `TELEGRAM_BOT_TOKEN`(secrets.yaml) + `TELEGRAM_CHAT_ID`(secrets.yaml).
- 이벤트 게이팅: `config.yaml > TELEGRAM_EVENTS`(error/budget/daily_summary/publish_request).

## 2. 목표(양방향)
운영자가 텔레그램에서 명령을 보내 시스템을 제어/조회:
```
운영자 → Telegram → (수신 계층) → 명령 파서 → 액션 실행 → 결과 회신(sendMessage)
```

### 2.1 명령 세트(초안)
| 명령 | 동작 | 매핑 |
|------|------|------|
| `/status` | 헬스/오늘 발행·비용 요약 | health_last.json + scheduler.summarize + cost_manager.status |
| `/run` | 파이프라인 1회 실행 | main.run_once(max_count=1) |
| `/calc` | 계산기 글 1건 생성 | calculator_pipeline.run_calculator_once |
| `/pause` `/resume` | 예산/운영 일시정지·재개 | cost_manager 플래그 |
| `/approve <id>` | 발행 승인 | retry_queue / publisher |
| `/cost` | 오늘/이번달 비용 | logger.BudgetTracker |
| `/retry` | 재처리 대기 목록 | retry_queue.list_pending |

## 3. 수신 계층 — 2가지 방식
| 방식 | 장점 | 단점 | 권장 |
|------|------|------|------|
| **Long Polling**(`getUpdates`) | 인프라 불필요(아웃바운드만), 로컬/방화벽 환경 적합 | 상시 폴링 프로세스 필요(scheduler 루프에 통합 가능) | ✅ 1순위(현 운영=로컬 스케줄러) |
| **Webhook** | 실시간, 폴링 없음 | 공개 HTTPS 엔드포인트/인증서 필요(현재 미보유) | 2순위(서버 배포 후) |

> 현재 운영이 `run_scheduler.bat` 단일 상시 프로세스이므로, **scheduler 루프에 `getUpdates` 폴링 훅**을 추가하는 방식이 가장 적은 인프라로 가능. (단, 이는 scheduler 변경이므로 별도 Sprint·승인 필요)

## 4. 보안
- **화이트리스트**: 허용 `chat_id`만 명령 수락(그 외 무시/경고). 설정: `TELEGRAM_ADMIN_CHAT_IDS`.
- **파괴적 명령 확인**: `/run`·`/pause` 등은 확인 토큰(예: `/run yes`) 또는 2단계 회신.
- **레이트리밋**: 명령 빈도 제한(폭주 방지).
- **감사 로그**: 수신 명령·실행 결과를 pipeline.log/별도 로그에 기록.
- **토큰 보호**: 토큰은 secrets.yaml(이미 분리). webhook secret 토큰 사용 시 별도 보관.

## 5. 제안 모듈 구조(신규, 기존 무변경)
```
modules/telegram_bot.py (신규)
  - poll_updates(cfg, offset)        getUpdates 1회 폴링 → 업데이트 목록
  - parse_command(text)              "/cmd args" → (cmd, args)
  - dispatch(cfg, cmd, args, chat_id) 화이트리스트 검증 → 액션 → 결과 텍스트
  - reply(cfg, chat_id, text)        sendMessage(특정 chat_id)
```
- `telegram_notifier.send()`/`telegram_ops`는 **발송 전용으로 유지**, 신규 `telegram_bot.py`가 수신 담당(역할 분리).
- 통합 지점: scheduler 루프 폴링 틱마다 `poll_updates`→`dispatch`(옵션 플래그 `TELEGRAM_BOT_ENABLED`).

## 6. 단계별 도입(후속 과제)
1. **P1** `telegram_bot.py` + `/status`·`/cost`·`/retry`(읽기 전용 명령만, 무위험)
2. **P2** 화이트리스트/레이트리밋/감사 로그
3. **P3** `/run`·`/calc`·`/approve`(실행 명령, 확인 토큰 + 별도 승인)
4. **P4**(서버 배포 후) Webhook 전환

## 7. 단방향 측 미배선 이벤트(후속, 파이프라인 수정 필요)
현재 raw `tg_send` 크리티컬 알림만 존재. 아래는 호출 추가 필요(파이프라인 파일 수정 → 별도 Sprint):
- 프로그램 시작/종료, 발행 **성공**, 계산기 생성 **성공**, 개별 Retry 발생, `daily_summary`·`notify_publish_request` 배선.

---
> 본 문서는 설계 한정. 구현은 운영자 승인 후 별도 Sprint에서 진행.
