# FILE_STRUCTURE.md — 파일 구조 및 역할

> 실제 소스 코드 기준(2026-06-30, Sprint 2A/2B + Calculator Reviewer 개선 반영). Python 85개. 상태: ✅완료 · 🟡부분 · ❌stub.

```
블로그자동_v12/
├─ main.py                  12단계 파이프라인 진입점
│                           플래그: --dry-run/--once/--scheduler/--strategy-room/
│                                   --calculator/--seed-calculators/--instance
├─ api/                     FastAPI 공식 Dashboard Backend(routers/ · services/)
├─ frontend/                React + Vite 공식 Dashboard UI(src/pages · src/components)
├─ start_dashboard.bat      FastAPI(127.0.0.1:8000) + React(127.0.0.1:5173) 기동
├─ health_check.py          ★헬스체크(OpenAI/Claude/Gemini/Sheet/Drive/WP/SA)
├─ requirements.txt / credentials.json / .gitignore
├─ config/
│   ├─ config.yaml          일반 설정(모델/예산/Google/WP URL/CALC_REVIEW_*/TELEGRAM_EVENTS 등)
│   ├─ secrets.yaml         🔐 민감정보(API키/앱비번/봇토큰 + wordpress_profiles/ai_keys) — gitignore
│   ├─ secrets.example.yaml 시크릿 예시(추적)
│   ├─ score_weights.yaml · site_mode.yaml
├─ prompts/calculator_writer_prompt.txt
├─ templates/
│   ├─ calculators/calculator_v1.html   계산기 공통 UI({{변수}} 치환)
│   └─ library/*.json (retirement/annual_leave/weekly_allowance/unemployment/insurance) 골드 템플릿
├─ modules/  (아래 표)
├─ repositories/  article·site·calculator·template _repository
├─ adapters/  db/{sheets,sqlite,postgres*} · storage/{drive,local,s3*}
├─ scripts/  install·run_pipeline·run_scheduler·run_dryrun·run_strategy_room·
│            sync_cache(.bat)·repair_google_setup.py
├─ data/  logs(pipeline.log,budget.json,health_last.json) · outputs · schedule · cache ·
│         assistant(memory.json/tasks.json/backups) · dlq
├─ docs/  CALCULATOR_REVIEWER_FIX_RESULT.md
└─ (문서) README·ARCHITECTURE·FILE_STRUCTURE·ROADMAP·MIGRATION_NOTES·
          SPRINT_2A_REPORT·SPRINT_2B_REPORT·AI_ASSISTANT_ANALYSIS·
          TELEGRAM_BIDIRECTIONAL_DESIGN·CHANGELOG_AI·CALCULATOR_* 등
```

## 루트
| 파일 | 역할 | 의존 |
|------|------|------|
| `main.py` | `parse_args`(7플래그) · `run_once`+`_process_one`(12단계) | 전 파이프라인 모듈, scheduler/calculator_pipeline(지연), health_check, config_loader |
| `health_check.py` | 6서비스+서비스계정 점검 → health_last.json | openai/anthropic/google.genai/googleapiclient |

## modules/ — 파이프라인 단계
| 파일 | 역할 | 상태 |
|------|------|------|
| `cleaner.py` | STEP2 정제 + STEP9 파싱 | ✅ |
| `duplicate_checker.py` | STEP3 임베딩+코사인+AI judge | ✅ |
| `strategist.py` / `strategist_calculator.py` | STEP5 M0 전략 / 계산기 키워드 점수 | ✅ |
| `planner.py` | STEP6 SEO 기획(M1) | ✅ |
| `writer.py` | STEP7 본문(source_type별) | ✅ |
| `editor.py` | STEP8 검수(Claude→GPT fallback) | ✅ |
| `image_generator.py` | STEP10 Pollinations→Drive | ✅ |
| `publisher.py` | STEP11 WordPress REST(미구축 graceful skip) | 🟡 |
| `history_loader.py` / `rss_collector.py` | STEP4 최근 제목 / 레거시 RSS fallback | ✅ |

## modules/collector/
| 파일 | 역할 | 상태 |
|------|------|------|
| `base.py`·`factory.py` | 추상 + source_type 라우팅 | ✅ |
| `policy.py` / `calculator.py` | RSS 수집 / calculators DB→키워드 | ✅ |
| `finance.py`·`affiliate.py` | `return []` | ❌ stub |

## modules/ — 계산기 엔진
| 파일 | 역할 | 상태 |
|------|------|------|
| `formula_engine.py` | AST 안전 수식 | ✅ |
| `calculator_form_engine.py` / `calculator_template_engine.py` | 입력폼 스키마 / 위젯 HTML | ✅ |
| `app_generator.py` / `app_factory.py` | index/style/script 생성 / 자동 계산기 생성 | ✅ |
| `calculator_reviewer.py` | **GPT 검수(CALC_REVIEW_*) + total 항목평균 정규화 + auto_review_and_fix** | ✅ |
| `calculator_{seo,faq,content,image_prompt}_generator.py` | SEO/FAQ/본문/이미지프롬프트 | ✅ |
| `calculator_prompt_manager.py` / `calculator_pipeline.py` | 프롬프트 중앙관리 / 계산기 파이프라인 | ✅ |
| `calculator_seed.py` | 초기 5종 시드(**upsert_by_slug로 본문 보존**, `main.py --seed-calculators` → `seed_all`). 구 `calculator_seeder.py`는 삭제됨 | ✅ |
| `github_deployer.py` / `internal_link_engine.py` / `site_mode_manager.py` | 배포 / 내부링크 / 노출모드 | 🟡/✅/✅ |

## modules/ — AI/공통/운영
| 파일 | 역할 |
|------|------|
| `ai_provider.py` | OpenAI/Claude/Gemini 추상화 + 역할 라우팅 + retry |
| `ai_roles.py` | 확장기능 역할표(App Factory/AI Workspace) |
| `logger.py` | 로깅 + BudgetTracker(모델별 비용) |
| `config_loader.py` | **config.yaml+secrets.yaml 병합(merge_secrets)** + 검증 + WP키 정규화 + split_secrets/save_secrets_flat |
| `utils/parser.py` / `json_utils.py` | LLM JSON 파서 + shim |
| `sheet_sync.py`·`db_manager.py`·`site_manager.py` | Repository 브릿지 |
| `scheduler.py` | 슬롯/랜덤예약/실패모드3/즉시발행/요약 |
| `setup_wizard.py`·`google_provisioner.py` | 6단계 마법사 + Sheets/Drive 자동생성 |
| `site_wizard.py` | 사이트/계산기 생성·관리(create_site/upsert 경로) |
| `ai_assistant.py` | AI 운영비서(채팅+파일도구+승인게이트+메모리+태스크+분석) |
| `ai_workspace.py` / `pipeline_status.py` / `dashboard_cache.py` | 대시보드 AI/파이프라인 상태/캐시 |
| `cost_manager.py` / `retry_queue.py` / `image_fallback.py` | 예산 통제 / 재발행 / 이미지 폴백 |
| `telegram_ops.py` / `telegram_notifier.py` | 표준화 알림+이벤트 게이팅 / 저수준 발송 |
| `backup_manager.py` / `strategy_room.py` | 백업 / 운영 분석 |

## repositories/
| 파일 | 역할 |
|------|------|
| `article_repository.py` | 마스터_DB CRUD |
| `site_repository.py` | sites + secrets WP/AI 프로필 조회/저장 |
| `calculator_repository.py` | calculators CRUD + **get_by_slug/upsert_by_slug**(본문 보존) + update_generated |
| `template_repository.py` | app_templates |

## adapters/
| 파일 | 상태 |
|------|------|
| `db/sheets_adapter.py`(기본)·`db/sqlite_adapter.py` | ✅ (update 시 신규 컬럼 자동 추가) |
| `db/postgres_adapter.py` | ❌ stub |
| `storage/drive_adapter.py`(기본)·`storage/local_adapter.py` | ✅ |
| `storage/s3_adapter.py` | ❌ stub |

## scripts/ (.bat = cp949/CRLF, venv 직접호출)
install · run_pipeline(--once) · run_scheduler(--scheduler) · run_dryrun(--dry-run) · run_strategy_room(--strategy-room) · sync_cache(미러 워밍) · repair_google_setup.py

> 참고: Legacy `run_schedule.bat`/`run_dashboard_new.bat`/`dashboard_ui_refactor.py`는 v12 Lite에서 **삭제됨**(존재하지 않음). Streamlit launcher `run_dashboard.bat`/`start_dashboard_autostart.bat`도 삭제됨(CALCMATE-STREAMLIT-LAUNCHER-CLEANUP-01) — 대시보드 실행은 루트 `start_dashboard.bat`(React+FastAPI). Streamlit `dashboard.py`와 `dashboard_backup.py`/`dashboard_backup_ui.py`도 삭제됨(`6c9f78c`), Streamlit 전용 테마 `assets/css/dashboard.css`도 삭제됨 — 대시보드는 `api/` + `frontend/`.
