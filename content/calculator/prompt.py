# -*- coding: utf-8 -*-
"""
modules/calculator_prompt_manager.py — 계산기 프롬프트 중앙 관리 (SalaryMate 자동생성, 신규)

SEO/FAQ/본문/CTA/이미지 프롬프트를 한 곳에서 관리. 각 함수는 (system, user) 튜플 반환.
품질 규칙(AI 티 표현 금지, 키워드 스팸 금지)을 모든 시스템 프롬프트에 주입.
"""
import json
from datetime import datetime

# 연도 동적 주입(하드코딩 금지). 모듈 로드 시점의 현재 연도.
CURRENT_YEAR = datetime.now().year

# 공통 품질 규칙 (모든 프롬프트에 포함)
QUALITY = (
    "[작성 규칙]\n"
    "- 'AI가 작성했습니다', 'ChatGPT', 'Claude', 'Gemini' 등 AI 관련 표현 절대 금지.\n"
    "- 키워드 스팸/과도한 SEO 반복 금지. 자연스러운 한국어.\n"
    "- 실제 사용자의 검색의도를 충족하는 실용 정보 중심. 광고성 과장 금지.\n"
    f"- 연도는 하드코딩 금지. 연도가 필요하면 현재 연도({CURRENT_YEAR})만 사용한다. '2023년'·'2022년' 등 고정 연도 금지.\n"
    "- 법령·요율(최저임금·보험료율·퇴직금 기준 등)은 입력/시스템 제공 값만 사용하고, 확인되지 않은 수치·변경사항은 추측하지 않는다.\n"
    "- 업데이트 내역·콘텐츠 생성일·검수일 등 내부 운영 정보 표기 절대 금지."
)

# 계산기 카테고리 → intent 매핑 (기존 category를 intent로 매핑)
_CATEGORY_TO_INTENT = {
    # health_metric: BMI, 체질량지수 등 건강 지표
    '건강/체질량지수': 'health_metric',
    '건강': 'health_metric',
    '건강/피트니스': 'health_metric',
    
    # labor_money: 퇴직금, 연차수당, 주휴수당 등 근로 급여
    '퇴직/연차': 'labor_money',
    '퇴직/연차/기타': 'labor_money',
    '노무/급여': 'labor_money',
    '노무/급여/기타': 'labor_money',
    
    # welfare_benefit: 실업급여, 육아휴직급여 등 복지 급여
    '고용/실업': 'welfare_benefit',
    '고용/실업/기타': 'welfare_benefit',
    # '고용/보험'은 4대보험 등 사회보험으로 tax_insurance로 분류
    '고용/보험': 'tax_insurance',
    
    # tax_insurance: 세금, 사회보험, 연말정산, 4대보험
    '세금': 'tax_insurance',
    '세금/환급': 'tax_insurance',
    '사회보험': 'tax_insurance',
    '세금/기타': 'tax_insurance',
    '세금/정부혜택': 'tax_insurance',
    
    # housing_finance: 전세/월세, 부동산중개보수
    '부동산': 'housing_finance',
    '부동산/중개': 'housing_finance',
    '부동산/임대': 'housing_finance',
    
    # general_calculator: 나머지 계산기들
    '기타': 'general_calculator',
    '기타/일반': 'general_calculator',
    '연차/휴가': 'general_calculator',
    '기타/일반/기타': 'general_calculator',
    '건강/기타': 'general_calculator',
    '노동/고용법': 'general_calculator',
}

def _get_intent_from_category(calc: dict) -> str:
    """계산기 카테고리에서 intent를 결정한다."""
    category = calc.get('category', '') or ''
    return _CATEGORY_TO_INTENT.get(category.strip(), 'general_calculator')


def _ctx(calc: dict) -> str:
    return (f"계산기명: {calc.get('name','')}\n"
            f"카테고리: {calc.get('category','')}\n"
            f"설명: {calc.get('seo_desc','') or calc.get('seo_description','')}\n"
            f"계산공식: {calc.get('formula','')}\n"
            f"입력항목: {calc.get('input_schema','')}\n"
            f"출력항목: {calc.get('output_schema','')}")


def get_seo_prompt(calc: dict) -> tuple:
    system = ("너는 SEO 전문가다. 계산기에 대한 검색 최적화 제목과 메타설명을 작성한다.\n"
              f"제목 28~40자(연도가 필요하면 {CURRENT_YEAR}만 사용, 고정 연도 금지), 메타설명 70~120자.\n"
              + QUALITY + "\n"
              '순수 JSON만 반환: {"seo_title":"","seo_description":""}')
    return system, _ctx(calc)


def get_faq_prompt(calc: dict, n_min: int = 6, n_max: int = 8, law_ssot_block: str = "") -> tuple:
    ssot_prefix = (law_ssot_block.strip() + "\n\n") if law_ssot_block.strip() else ""
    # intent 결정: category 기반 자동 결정
    intent = _get_intent_from_category(calc)
    
    # intent별 FAQ 필수 항목 정의
    if intent == "health_metric":
        # 건강 지표: 지급 조건 제외, 계산/판정/해석/주의/오해/관련지표
        faq_requirements = (
            "①계산 방법(공식·단계·예시) ②판정 기준(수치별 등급/구간 해석) "
            "③해석 방법(결과 수치의 의미와 활용) ④주의사항(측정 시 주의점과 한계) "
            "⑤자주 틀리는 부분(흔한 오해·실수·단위 오류) ⑥관련 지표/건강 관리(다른 지표와의 연계)."
        )
    elif intent == "labor_money":
        # 근로 급여: 지급 조건 포함
        faq_requirements = (
            "①지급 조건(대상 조건·제외 조건·중요 기준) ②예외 사항(받지 못하는 경우) "
            "③계산 기준(정확한 계산 방법) ④자주 틀리는 부분(흔한 오해·실수) "
            "⑤법적 근거(관련 법령 조항) ⑥실무 팁(사용 시 주의사항)."
        )
    elif intent == "welfare_benefit":
        # 복지 급여: 지급 조건 포함
        faq_requirements = (
            "①지급 조건(수급 자격·제외 대상·중요 기준) ②예외 사항(받지 못하는 경우) "
            "③계산 기준(급여 산정 공식과 단계) ④자주 틀리는 부분(흔한 오해·실수) "
            "⑤법적 근거(관련 법령 조항) ⑥실무 팁(신청·활용 시 주의사항)."
        )
    elif intent == "tax_insurance":
        # 세금/사회보험: 납부/공제 기준 포함
        faq_requirements = (
            "①납부/공제 기준(과세표준·공제항목·세율/요율) ②예외 사항(감면·면제·예외) "
            "③계산 기준(정확한 계산 방법) ④자주 틀리는 부분(흔한 오해·실수) "
            "⑤법적 근거(관련 법령 조항) ⑥실무 팁(신고·납부 시 주의사항)."
        )
    elif intent == "housing_finance":
        # 주택/금융: 비교/판단 기준 포함
        faq_requirements = (
            "①비교 기준(유불리 판단 핵심 지표) ②예외 사항(적용 제외·제한) "
            "③계산 기준(정확한 계산 방법) ④자주 틀리는 부분(흔한 오해·실수) "
            "⑤법적 근거(관련 법령 조항) ⑥실무 팁(선택·계약 시 주의사항)."
        )
    else:
        # general_calculator 등 나머지: 기존 범용 구조 유지
        faq_requirements = (
            "①지급 조건(누가·언제 받는가) ②예외 사항(받지 못하는 경우) ③계산 기준(정확한 계산 방법) "
            "④자주 틀리는 부분(흔한 오해·실수) ⑤법적 근거(관련 법령 조항) ⑥실무 팁(사용 시 주의사항)."
        )
    
    system = (ssot_prefix +
              f"너는 해당 분야 전문가다. 사용자가 실제로 궁금해하는 FAQ를 {n_min}~{n_max}개 작성한다.\n"
              f"반드시 다음 6가지를 모두 포함한다: {faq_requirements}\n"
              "각 답변은 구체적인 수치·조건·예외를 포함하고 2~4문장으로 작성한다. "
              "'~할 수 있습니다', '~중요합니다' 같은 공허한 답변 금지.\n"
              "[FAQ 역할 분리]\n"
              "- 본문을 읽은 뒤 사용자가 추가로 궁금해할 질문, 예외 상황, 적용 조건, "
              "계산·신청 과정에서 헷갈리기 쉬운 실무 질문을 우선한다.\n"
              "- 본문의 문장이나 문단을 그대로 복사하거나 어미만 바꿔 반복하지 않는다.\n"
              "- 법률상 핵심 사실을 다시 확인해야 하는 경우에는 본문과 동일한 사실의 반복을 허용한다.\n"
              "- 차별화를 위해 법률·수치·기간을 임의로 변경하거나 새로운 사실을 만들어내지 않는다.\n"
              + QUALITY + "\n"
              '순수 JSON만 반환: {"faq":[{"question":"","answer":""}]}')
    return system, _ctx(calc)


# SalaryMate에 실제 존재하는 계산기 목록 (SSOT: DB calculators 테이블, 2026-08 기준).
# A-3 게이트: 이 목록 외 계산기를 언급/링크하는 것을 원천 차단하기 위해 프롬프트에 주입한다.
# STEP125: get_article_prompt()가 valid_calculators를 명시적으로 받으면 그 값을 우선 사용한다
# (content/calculator/writer.py::generate_article()가 SQLite MAIN calculators에서 동적으로
# 만들어 전달함). 이 상수는 valid_calculators 미전달 시(호출자가 없거나 DB 조회 실패 시)의
# 안전한 폴백으로만 남긴다 — 삭제하지 않음.
_VALID_CALCULATORS = (
    "- 연차수당 계산기 (annual-leave-allowance)\n"
    "- 연차 잔여일 계산기 (annual-leave-remaining)\n"
    "- 4대보험 계산기 (four-insurances)\n"
    "- 프리랜서 3.3% 원천징수 계산기 (freelancer-tax-3p3)\n"
    "- 전세 vs 월세 비교 계산기 (jeonse-vs-monthly)\n"
    "- 군인 전역일 계산기 (military-discharge-date)\n"
    "- 퇴직금 계산기 (severance-pay)\n"
    "- 실업급여 계산기 (unemployment-benefit)\n"
    "- 주휴수당 계산기 (weekly-holiday-allowance)\n"
    "- 연말정산 환급액 계산기 (연말정산_환급액_계산기)\n"
    "- 육아휴직 급여 계산기 (육아휴직_급여_계산기)\n"
)

_NO_LINK_RULE = (
    "[계산기 링크 금지 — 반드시 준수]\n"
    "- 관련 계산기 섹션을 본문에 작성하지 않는다. 관련 계산기/관련 글 링크는 시스템이 자동 삽입한다.\n"
    "- 본문에 다른 계산기를 언급하거나 <a href> 링크를 생성하지 않는다.\n"
    "- 위 목록 외에 존재하지 않는 계산기(시급 계산기, 연봉 계산기, 상여금 계산기, 세금 계산기 등)를 "
    "언급하거나 링크하지 않는다.\n"
    "- CTA(계산기 사용하기) 섹션은 작성하지 않는다. 시스템이 본문 뒤에 자동 삽입한다.\n"
)

_H2_RULE = (
    "[H2 제목 규칙 — 반드시 준수]\n"
    "- 각 섹션의 <h2> 제목은 아래 지정된 이름 그대로만 사용한다. 임의 변경 절대 금지.\n"
    "- <h2> 안에 숫자 prefix(예: '1. ', '2. ', '3. ')를 절대 포함하지 않는다.\n"
    "- 'CTA', '행동 유도', '할인 혜택', '계산기 연결' 같은 내부 작업 용어를 "
    "<h2> 제목으로 사용하지 않는다.\n"
)

_HTML_OUTPUT_RULE = (
    "[HTML 출력 규칙 — 반드시 준수]\n"
    "- Markdown 문법을 절대 사용하지 않는다.\n"
    "- 강조 표현에 '**bold**' 사용 금지. 강조는 반드시 <strong>...</strong> 태그로 작성한다.\n"
    "- 일반적인 계산식·수식에 <pre> 태그를 사용하지 않는다. 계산식은 <p> 태그의 짧은 문장으로 작성한다.\n"
    "- 긴 한 줄 텍스트를 <pre>에 담지 않는다. <pre>는 실제 코드 또는 고정폭이 반드시 필요한 "
    "다중 라인 내용에만 사용한다(일반 계산 공식에는 사용하지 않는다).\n"
    "- 생성하는 HTML은 모바일 화면(폭 375px 기준)에서 가로 스크롤이 발생하지 않는 구조여야 한다. "
    "긴 문장은 자연스럽게 줄바꿈되는 <p>로 작성하고, 고정폭 요소로 감싸지 않는다.\n"
)


def get_article_prompt(calc: dict, seo: dict = None, faq: list = None, example_context: dict = None, intent: str = None, law_ssot_block: str = "", valid_calculators: str = None) -> tuple:
    seo = seo or {}
    example_str = json.dumps(example_context, ensure_ascii=False) if example_context else "제공된 계산 데이터 없음"

    # intent 결정: 명시적 intent > category 기반 자동 결정
    if intent is None:
        intent = _get_intent_from_category(calc)

    # 템플릿 분기 — intent별 H2 구조 정의
    if intent == "eligibility":
        structure = (
            "<h2>지급 대상</h2> — 대상자 중심 문제제기 및 수급 자격 요건\n"
            "<h2>근로시간 조건</h2> — 주 15시간 이상 등 충족해야 할 기준\n"
            "<h2>제외 대상</h2> — 지급받지 못하는 예외 상황\n"
            "<h2>계산 방법</h2> — 공식+계산 근거+법적 근거\n"
            "<h2>계산 예시</h2> — 실제 데이터 기반 구체적 계산 과정\n"
            "<h2>주의사항</h2> — 자주 발생하는 오류와 한계\n"
            "<h2>FAQ</h2> — <dl><dt>...</dt><dd>...</dd></dl> 형식, 최소 5문항\n"
        )
        system_instructions = (
            "작성 규칙: 'eligibility' 의도로 작성하라. "
            "본문 최상단은 짧은 도입 문단(p태그)으로 시작하고, 바로 뒤에 위 H2 순서대로 구성하라. "
            "FAQ <h2> 제목은 반드시 'FAQ'를 그대로 사용한다('자주 묻는 질문' 등 변경 금지)."
        )
    elif intent == "documents":
        structure = (
            "<h2>필수 서류 목록</h2> — 제출 서류의 종류와 중요성\n"
            "<h2>서류 발급 방법</h2> — 각 서류의 발급 절차\n"
            "<h2>제출 기한 및 절차</h2> — 제출 방법과 기한\n"
            "<h2>주의사항</h2> — 서류 미비 시 발생하는 문제\n"
            "<h2>FAQ</h2> — <dl><dt>...</dt><dd>...</dd></dl> 형식, 최소 5문항\n"
        )
        system_instructions = "작성 규칙: 'documents' 의도에 맞춰, 제출 서류와 발급/제출 절차를 상세히 서술하라."
    elif intent == "howto":
        structure = (
            "<h2>이용 절차</h2> — 단계별 이용 방법 설명\n"
            "<h2>계산 예시</h2> — 실제 데이터 기반 예시(제공된 데이터만 사용)\n"
            "<h2>주의사항</h2> — 자주 발생하는 오류와 주의점\n"
            "<h2>FAQ</h2> — <dl><dt>...</dt><dd>...</dd></dl> 형식, 최소 5문항\n"
        )
        system_instructions = "작성 규칙: 'howto' 의도에 맞춰, 계산기 사용 절차와 예시를 상세히 서술하라."
    elif intent == "calculator":
        structure = (
            "<h2>계산 원리</h2> — 계산 공식 유래와 계산 원리\n"
            "<h2>지급 조건</h2> — 대상 조건, 제외 조건, 중요 기준\n"
            "<h2>계산 예시</h2> — 실제 데이터 기반 구체적 계산 과정\n"
            "<h2>주의사항</h2> — 자주 발생하는 오류와 한계\n"
            "<h2>FAQ</h2> — <dl><dt>...</dt><dd>...</dd></dl> 형식, 최소 5문항\n"
        )
        system_instructions = "작성 규칙: 'calculator' 의도에 맞춰, 계산 원리, 지급 조건, 계산 예시를 상세히 다룬다."
    elif intent == "health_metric":
        # BMI, 체질량지수 등 건강 지표 계산기
        structure = (
            "<h2>계산 원리</h2> — 계산 원리 설명(공식의 유래·역사적 배경은 이용자의 이해에 실질적으로 도움이 될 때만 1~2문장 이내로 간단히 언급하고, 그 외에는 계산 방법과 원리 자체에 집중한다)\n"
            "<h2>계산 방법</h2> — 단계별 계산 절차와 예시\n"
            "<h2>판정 기준</h2> — 결과 수치별 등급/구간 해석\n"
            "<h2>해석 방법</h2> — 결과 수치의 의미와 활용법\n"
            "<h2>주의사항</h2> — 측정 시 주의점과 한계\n"
            "<h2>FAQ</h2> — <dl><dt>...</dt><dd>...</dd></dl> 형식, 최소 5문항\n"
        )
        system_instructions = "작성 규칙: 건강 지표 계산기 특성에 맞춰 계산 원리, 판정 기준, 해석 방법을 상세히 다룬다."
    elif intent == "labor_money":
        # 퇴직금, 연차수당, 주휴수당 등 근로 급여 계산기
        structure = (
            "<h2>계산 원리</h2> — 법적 근거 첫 문장 명시 + 계산 단계 설명 + 예시 2개\n"
            "<h2>지급 조건</h2> — 대상 조건, 제외 조건, 중요 기준\n"
            "<h2>계산 방법</h2> — 공식+계산 단계 설명+예시 2개\n"
            "<h2>계산 예시</h2> — 실제 데이터 기반 구체적 계산 과정\n"
            "<h2>주의사항</h2> — 자주 발생하는 오류, 잘못 이해하는 부분(3항목 이상)\n"
            "<h2>FAQ</h2> — <dl><dt>...</dt><dd>...</dd></dl> 형식, 최소 5문항\n"
        )
        system_instructions = "작성 규칙: 근로 급여 계산기 특성에 맞춰 계산 원리, 지급 조건, 계산 방법, 예시를 상세히 다룬다."
    elif intent == "welfare_benefit":
        # 실업급여, 육아휴직급여 등 복지 급여
        structure = (
            "<h2>지급 조건</h2> — 수급 자격, 제외 대상, 중요 기준\n"
            "<h2>지급 대상</h2> — 수급 자격 요건과 대상자 범위\n"
            "<h2>계산 방법</h2> — 급여 산정 공식과 계산 단계\n"
            "<h2>신청 방법</h2> — 신청 절차, 필요 서류, 기한\n"
            "<h2>주의사항</h2> — 자주 발생하는 오류와 주의점\n"
            "<h2>FAQ</h2> — <dl><dt>...</dt><dd>...</dd></dl> 형식, 최소 5문항\n"
        )
        system_instructions = "작성 규칙: 복지 급여 계산기 특성에 맞춰 지급 조건, 대상, 계산 방법, 신청 방법을 상세히 다룬다."
    elif intent == "tax_insurance":
        # 세금, 사회보험, 연말정산, 4대보험
        structure = (
            "<h2>계산 원리</h2> — 법적 근거와 계산 원리\n"
            "<h2>납부/공제 기준</h2> — 과세 표준, 공제 항목, 세율/보험료율\n"
            "<h2>계산 예시</h2> — 실제 데이터 기반 구체적 계산 과정\n"
            "<h2>주의사항</h2> — 자주 발생하는 오류와 한계\n"
            "<h2>FAQ</h2> — <dl><dt>...</dt><dd>...</dd></dl> 형식, 최소 5문항\n"
        )
        system_instructions = "작성 규칙: 세금/보험 계산기 특성에 맞춰 계산 원리, 납부/공제 기준, 계산 예시를 상세히 다룬다."
    elif intent == "housing_finance":
        # 전세/월세, 부동산중개보수
        structure = (
            "<h2>계산 원리</h2> — 계산 공식과 산출 근거\n"
            "<h2>적용 기준</h2> — 적용 대상, 조건, 기준 금액\n"
            "<h2>계산 예시</h2> — 실제 데이터 기반 구체적 계산 과정\n"
            "<h2>주의사항</h2> — 자주 발생하는 오류와 한계\n"
            "<h2>FAQ</h2> — <dl><dt>...</dt><dd>...</dd></dl> 형식, 최소 5문항\n"
        )
        system_instructions = "작성 규칙: 주택/금융 계산기 특성에 맞춰 계산 원리, 적용 기준, 계산 예시를 상세히 다룬다."
    else:  # general_calculator (기본값)
        structure = (
            "<h2>계산 원리</h2> — 계산 공식 유래와 계산 원리\n"
            "<h2>계산 방법</h2> — 단계별 계산 절차와 예시\n"
            "<h2>계산 예시</h2> — 실제 데이터 기반 구체적 계산 과정\n"
            "<h2>주의사항</h2> — 자주 발생하는 오류와 한계\n"
            "<h2>FAQ</h2> — <dl><dt>...</dt><dd>...</dd></dl> 형식, 최소 5문항\n"
        )
        system_instructions = "작성 규칙: 계산기 중심의 구조를 유지하며, 계산 원리와 주의사항을 상세히 다룬다."

    ssot_block = (
        "[현재 SalaryMate에 존재하는 계산기 목록 (SSOT — 이 목록 외에는 존재하지 않는다)]\n"
        + (valid_calculators if valid_calculators is not None else _VALID_CALCULATORS)
    )

    law_ssot_prefix = (law_ssot_block.strip() + "\n\n") if law_ssot_block.strip() else ""
    system = (
        law_ssot_prefix
        + "너는 10년차 SEO 콘텐츠 에디터다. 아래 계산기 주제로 블로그 글을 작성한다.\n"
        f"[필수 구조 — 아래 H2 이름을 그대로 사용하고 순서를 지킨다]\n{structure}\n"
        f"{system_instructions}\n\n"
        + _H2_RULE
        + _HTML_OUTPUT_RULE
        + _NO_LINK_RULE
        + ssot_block + "\n\n"
        "[검증된 계산 데이터]\n"
        f"{example_str}\n\n"
        "[숫자 보호 규칙]\n"
        "- 숫자를 임의로 생성하거나 변경하지 않는다.\n"
        "분량 공백 포함 1900자 이상. HTML로 출력하되, "
        "본문 전체를 반드시 [BODY_HTML_START] 로 시작하고 [BODY_HTML_END] 로 끝낸다. "
        "이 두 표시는 HTML 태그가 아니라 본문 경계를 나타내는 출력 구분자이므로, "
        "<h2>, <p> 같은 실제 HTML 요소와 혼동해 꺾쇠괄호(<>)로 바꾸지 말고 "
        "반드시 대괄호([]) 형식 그대로 출력한다.\n"
        + QUALITY
    )
    user = (
        _ctx(calc)
        + f"\nSEO제목: {seo.get('seo_title','')}\n메타설명: {seo.get('seo_description','')}\n"
        + f"FAQ: {json.dumps(faq or [], ensure_ascii=False)}"
    )
    return system, user


def get_cta_prompt(calc: dict) -> tuple:
    system = ("계산기 사용을 유도하는 자연스러운 CTA 문장 1~2개를 작성한다. 과장/광고 금지.\n" + QUALITY +
              "\n순수 텍스트만 반환.")
    return system, _ctx(calc)


def get_image_prompt(calc: dict) -> tuple:
    system = ("너는 이미지 프롬프트 디자이너다. 블로그 썸네일/본문용 영문 이미지 프롬프트를 작성한다.\n"
              "사실적·전문적. 텍스트 삽입 지시 금지.\n"
              '순수 JSON만 반환: {"thumbnail":"","body":""}')
    return system, _ctx(calc)
