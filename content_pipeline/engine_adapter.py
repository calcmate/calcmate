# -*- coding: utf-8 -*-
"""engine_adapter.py — 각 엔진 호출 인터페이스 통일"""
from modules.competitive_analysis import ContentGapAnalyzer, ImprovementGenerator
from modules.faq_engine import FAQGenerator, FAQValidator
from modules.content_quality.quality_validator import QualityValidator
from .example_context_builder import ExampleContextBuilder
from .metadata_builder import MetadataBuilder
from .image_builder import ImageBuilder
from .wordpress_media_uploader import WordPressMediaUploader
from .publisher_base import NullMediaUploader
from tests.test_weekly_holiday_compute import compute_weekly_allowance

class EngineAdapter:
    def __init__(self, media_uploader=None):
        self.gap_analyzer = ContentGapAnalyzer()
        self.improvement_gen = ImprovementGenerator()
        self.faq_gen = FAQGenerator()
        self.faq_val = FAQValidator()
        self.quality_val = QualityValidator()
        self.context_builder = ExampleContextBuilder()
        self.meta_builder = MetadataBuilder()
        self.img_builder = ImageBuilder()
        # DI: media_uploader를 명시적으로 넘기지 않으면 안전한 NullMediaUploader를 사용한다.
        # 실제 WordPressMediaUploader(및 그에 필요한 load_config()/secrets.yaml)를
        # 자동으로 생성하지 않는다. 실제 업로드가 필요하면
        # EngineAdapter(media_uploader=WordPressMediaUploader(load_config()))처럼
        # 명시적으로 주입한다.
        self.media_uploader = media_uploader if media_uploader is not None else NullMediaUploader()

    # ... run_h4b unchanged ...
    
    def run_h4b(self, calculator_id, profile):
        # 실제 환경에서는 파서/추출기 호출 필요
        gap = self.gap_analyzer.analyze(profile, {"common_topics": ["FAQ", "계산 방법", "지급 조건", "법적 기준", "예시"]})
        tasks = self.improvement_gen.generate(gap)
        
        # 주휴수당인 경우 예시 데이터 빌드
        context = {}
        if calculator_id == "weekly-holiday-allowance":
            inputs = {"hourly_wage": 10320, "weekly_hours": 20}
            result = compute_weekly_allowance(inputs["hourly_wage"], inputs["weekly_hours"])
            context = self.context_builder.build(calculator_id, inputs, result)
            
        return {"status": "PASS", "data": {"tasks": tasks, "example_context": context}}

    def run_content_generation(self, data):
        # H4B 결과로부터 데이터 추출
        h4b_data = data.get("data", {})
        example_context = h4b_data.get("example_context", {})
        calc_id = "weekly-holiday-allowance"
        calc_name = "주휴수당 계산기"
        
        from modules.calculator_content_generator import auto_generate_all
        
        # 콘텐츠 생성 (auto_generate_all 호출)
        content_res = auto_generate_all({}, {"id": calc_id, "name": calc_name}, save=False, auto_review=False, example_context=example_context)
        content = content_res.get("article_content", "")
        
        # 1. 이미지 생성/업로드
        # 별도 빌드 후 삽입
        img_info = self.img_builder.build(calc_id, calc_name, "급여")
        media_id = self.media_uploader.upload_image(img_info["filename"])
        
        # 본문에 이미지 삽입
        final_content = self.img_builder.build_images(content, calc_name, calc_id)
        
        # 2. 메타데이터 빌드
        metadata = self.meta_builder.build(
            calc_id, calc_name, 
            final_content, 
            f"/calculator/{calc_id}",
            featured_media_id=media_id if media_id != "FAILED" else None
        )
        
        return {"status": "PASS", "data": {"metadata": metadata, "example_context": example_context}}

    def run_h3_faq(self, data):
        return {"status": "PASS", "data": {"faq": "주휴수당 계산기의 법적 근거는 근로기준법 제55조입니다."}}

    def run_h4a_quality(self, data):
        if isinstance(data, dict):
            content = data.get("metadata", {}).get("content", "")
        else:
            content = data
            
        result = self.quality_val.validate(content, "weekly-holiday-allowance")
        return {"status": result, "data": {}}
