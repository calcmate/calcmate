/* analytics.js — smTrack() GA4 이벤트 훅 · A/B 테스트 (Phase E-1, E-2)
   _JS_ORDER의 첫 번째 — 다른 모듈에서 smTrack()을 호출하기 전에 로드됨 */
(function (w, d) {
  "use strict";
  var CFG = w.SM_CONFIG || {};

  // ── E-1: GA4 gtag 전송 ───────────────────────────────────────────
  function _ga4(name, params) {
    if (typeof w.gtag === "function") {
      w.gtag("event", name, params || {});
    }
  }

  // smTrack: 모든 이벤트의 단일 진입점
  w.smTrack = function (event_name, params) {
    var p = Object.assign({}, {
      calc_name: CFG.name || "",
      calc_slug: CFG.slug || ""
    }, params || {});
    _ga4(event_name, p);
    if (w.SM_TRACK_DEBUG || (w.location && w.location.hostname === "localhost")) {
      console.log("[smTrack]", event_name, p);
    }
  };

  // ── E-2: A/B 테스트 — CTA 변형 (A=대조군 / B=실험군) ────────────
  var SM_AB_VARIANT = "A";
  try {
    var _sk = "sm_cta_v_" + (CFG.slug || "all");
    var _stored = sessionStorage.getItem(_sk);
    if (!_stored) {
      _stored = Math.random() < 0.5 ? "A" : "B";
      sessionStorage.setItem(_sk, _stored);
    }
    SM_AB_VARIANT = _stored;
  } catch (e) { /* sessionStorage 불가 시 기본값 "A" */ }
  w.SM_AB_VARIANT = SM_AB_VARIANT;

  // ── E-1: calculator_view + 위임 이벤트 리스너 ────────────────────
  function _initAnalytics() {
    w.smTrack("calculator_view", { page_path: w.location.pathname });

    // E-2: cta_variant data-ph 스팬 업데이트 + AB impression
    d.querySelectorAll('[data-ph="cta_variant"]').forEach(function (el) {
      el.textContent = SM_AB_VARIANT;
    });
    w.smTrack("ab_impression", { variant: SM_AB_VARIANT });

    // cta_click — 결과 카드 내 CTA 링크
    d.addEventListener("click", function (e) {
      var t = e.target;
      var el = t.closest ? t.closest(".sm-result-cta-link") : null;
      if (el) {
        w.smTrack("cta_click", {
          href: el.getAttribute("href") || "",
          label: (el.textContent || "").trim(),
          variant: SM_AB_VARIANT
        });
      }
    }, true);

    // related_calculator_click — 관련 계산기 링크
    d.addEventListener("click", function (e) {
      var t = e.target;
      var el = t.closest ? t.closest(".sm-related-item") : null;
      if (el) {
        var nm = el.querySelector(".sm-related-name");
        w.smTrack("related_calculator_click", {
          href: el.getAttribute("href") || "",
          label: nm ? (nm.textContent || "").trim() : ""
        });
      }
    }, true);

    // share_click — 카카오 공유 버튼
    d.addEventListener("click", function (e) {
      var t = e.target;
      var el = t.closest ? t.closest('.sm-action-btn[data-action="share"]') : null;
      if (el) w.smTrack("share_click", { method: "kakao" });
    }, true);

    // copy_result — 결과 저장 버튼
    d.addEventListener("click", function (e) {
      var t = e.target;
      var el = t.closest ? t.closest('.sm-action-btn[data-action="result_save"]') : null;
      if (el) w.smTrack("copy_result", {});
    }, true);
  }

  if (d.readyState === "loading") {
    d.addEventListener("DOMContentLoaded", _initAnalytics);
  } else {
    _initAnalytics();
  }
})(window, document);

/* number_input.js — 금액 입력 천단위 콤마 실시간 표시(표시만, 계산은 숫자) */
(function (w, d) {
  "use strict";
  function fmt(el) {
    var raw = String(el.value).replace(/[^\d.]/g, "");
    if (raw === "") { el.value = ""; return; }
    var parts = raw.split(".");
    var intp = parts[0].replace(/^0+(?=\d)/, "");
    var f = Number(intp || "0").toLocaleString();
    el.value = (parts.length > 1) ? (f + "." + parts[1]) : f;
  }
  w.smInitNumberInputs = function () {
    d.querySelectorAll(".sm-input[data-comma]").forEach(function (el) {
      el.addEventListener("input", function () { fmt(el); });
    });
  };
  w.smGetNumber = function (el) { return parseFloat(String(el.value).replace(/,/g, "")) || 0; };
})(window, document);

/* result_save.js — 결과 카드만 PNG 저장(html2canvas 지연 로드, 클릭 시에만) */
(function (w, d) {
  "use strict";
  var LIB = "https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js";
  function load() {
    return new Promise(function (res, rej) {
      if (w.html2canvas) return res(w.html2canvas);
      var s = d.createElement("script"); s.src = LIB;
      s.onload = function () { res(w.html2canvas); }; s.onerror = rej;
      d.head.appendChild(s);
    });
  }
  function ts(sep) {
    var n = new Date(), p = function (x) { return (x < 10 ? "0" : "") + x; };
    // 파일명용: YYYYMMDD_HHMM (초 제외)
    var fname = "" + n.getFullYear() + p(n.getMonth() + 1) + p(n.getDate()) + "_" + p(n.getHours()) + p(n.getMinutes());
    var human = n.getFullYear() + "-" + p(n.getMonth() + 1) + "-" + p(n.getDate()) + " " + p(n.getHours()) + ":" + p(n.getMinutes());
    return sep ? human : fname;
  }
  w.saveResultPng = function () {
    var card = d.getElementById("result-card");
    if (!card || !card.classList.contains("show")) { alert("먼저 계산을 실행해주세요."); return; }
    var cfg = w.SM_CONFIG || {};
    // 캡처용 임시 정보(계산기명 · 계산일시 · CalcMate) — 본문/광고 미포함
    var tag = d.createElement("div");
    tag.style.cssText = "margin-top:12px;font-size:12px;opacity:.85;line-height:1.6";
    tag.innerHTML = (cfg.name || "계산 결과") + "<br>" + ts(true) + " · CalcMate";
    card.appendChild(tag);
    load().then(function (h2c) {
      return h2c(card, { backgroundColor: null, scale: 2 });
    }).then(function (canvas) {
      if (tag.parentNode) card.removeChild(tag);
      var a = d.createElement("a");
      a.href = canvas.toDataURL("image/png");
      a.download = (cfg.name || "calculator").replace(/\s+/g, "") + "_" + ts(false) + ".png";
      a.click();
    }).catch(function (e) {
      if (tag.parentNode) card.removeChild(tag);
      console.error(e); alert("이미지 저장에 실패했습니다.");
    });
  };
})(window, document);

/* share.js — 카카오 공유(SDK 연동 구조 + 미설정 시 안전 폴백, 오류 없음) */
(function (w, d) {
  "use strict";
  w.kakaoShare = function () {
    var cfg = w.SM_CONFIG || {};
    var valEl = d.getElementById("out_" + cfg.primaryOutput);
    var val = valEl ? valEl.textContent : "";
    var text = (cfg.name || "계산 결과") + " 결과: " + val + (cfg.resultUnit || "");
    try {
      if (cfg.kakao_js_key && w.Kakao && w.Kakao.Share &&
          w.Kakao.isInitialized && w.Kakao.isInitialized()) {
        w.Kakao.Share.sendDefault({
          objectType: "text", text: text,
          link: { mobileWebUrl: location.href, webUrl: location.href }
        });
        return;
      }
    } catch (e) { console.error(e); }
    // SDK 미설정/미초기화 → 안전 폴백
    try {
      if (navigator.share) { navigator.share({ title: cfg.name || "계산 결과", text: text, url: location.href }); return; }
      if (navigator.clipboard) {
        navigator.clipboard.writeText(text + "\n" + location.href)
          .then(function () { alert("결과가 클립보드에 복사됐습니다."); });
        return;
      }
    } catch (e) { console.error(e); }
    alert(text);
  };
})(window, document);

/* pwa.js — 홈 화면 추가(beforeinstallprompt). 설치 가능 환경에서만 버튼 노출 */
(function (w, d) {
  "use strict";
  var deferred = null;
  w.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault(); deferred = e;
    var b = d.getElementById("pwa-btn"); if (b) b.style.display = "flex";
  });
  w.smInitPwa = function () {
    var b = d.getElementById("pwa-btn");
    if (b && !deferred) b.style.display = "none";  // 설치 불가 환경: 프롬프트 전까지 숨김
  };
  w.pwaInstall = function () {
    if (deferred) { deferred.prompt(); deferred.userChoice.then(function () { deferred = null; }); }
    else { alert("브라우저 주소창의 설치 아이콘을 눌러 홈 화면에 추가할 수 있습니다."); }
  };
})(window, document);

/* faq.js — FAQ 아코디언 토글 + ARIA (Phase C) */
(function (w, d) {
  "use strict";

  w.toggleFaq = function (btn) {
    var item = btn && btn.parentElement;
    if (!item) return;
    var isOpen = item.classList.toggle("open");
    btn.setAttribute("aria-expanded", isOpen ? "true" : "false");
    var ans = item.querySelector(".sm-faq-a");
    if (ans) ans.hidden = !isOpen;
    // E-1: faq_open 이벤트 (열릴 때만)
    if (isOpen && w.smTrack) {
      w.smTrack("faq_open", { q: (btn.textContent || "").trim().replace(/[+−]/g, "").trim() });
    }
  };

  function initFaqAria() {
    var idx = 0;
    d.querySelectorAll(".sm-faq-item").forEach(function (item) {
      var btn = item.querySelector(".sm-faq-q");
      var ans = item.querySelector(".sm-faq-a");
      if (!btn || !ans) return;
      var id = "faq-a-" + (idx++);
      ans.id = id;
      ans.hidden = true;
      btn.setAttribute("aria-expanded", "false");
      btn.setAttribute("aria-controls", id);
      btn.setAttribute("type", "button");
    });
  }

  if (d.readyState === "loading") d.addEventListener("DOMContentLoaded", initFaqAria);
  else initFaqAria();
})(window, document);

/* related.js — 관련 계산기(서버 렌더). 향후 slug 기반 동적 생성 훅(UI 동일) */
(function (w, d) {
  "use strict";
  // app_generator가 관련 계산기 앵커를 서버 렌더링함. 필요 시 동적 재구성 지원.
  w.smBuildRelated = function (items) {
    var host = d.querySelector(".sm-related-grid");
    if (!host || !items) return;
    host.innerHTML = items.map(function (it) {
      return '<a class="sm-related-item" href="' + (it.href || "#") + '">' +
        '<span class="sm-related-emoji">' + (it.emoji || "🧮") + '</span>' +
        '<span class="sm-related-name">' + (it.name || "") + "</span></a>";
    }).join("");
  };
})(window, document);

/* components.js — SalaryMate 공통 컴포넌트 (Phase C: notices / step accordion)
   계산 로직 없음. calculate()→computeResult()(계산기별)→renderResult()(공통 UI).
   계산기가 늘어나도 calculate()/renderResult()는 수정하지 않는다. */
(function (w, d) {
  "use strict";
  var CFG = w.SM_CONFIG || {};

  function num(v) { return (typeof v === "number") ? v : (parseFloat(String(v).replace(/,/g, "")) || 0); }
  // STEP 28-6: Math.round(-0.4) 등에서 나오는 -0이 그대로 "-0"으로 표시되는 것을 방지
  // (-0 + 0 === 0, toLocaleString()은 부호까지 그대로 반영하므로 +0으로 정규화 필요).
  // STEP 28-149: decimals 생략(기존 계산기 전부 해당)이면 이전과 완전히 동일한
  // 정수 표시를 유지한다. decimals>0인 계산기(현재 BMI만 해당)만 pyRound()로
  // 반올림한 뒤 최대 decimals자리까지 표시한다(37.5처럼 후행 0은 강제하지 않음 —
  // 기존 BMI Contract test_cases가 이미 이 형식을 전제로 확정돼 있다).
  function comma(n, decimals) {
    if (!decimals) return (Math.round(n) + 0).toLocaleString();
    var r = pyRound(n, decimals) + 0;
    return r.toLocaleString(undefined, { maximumFractionDigits: decimals });
  }

  // STEP 28-140: Python round(x, N)을 계산기 formula에서 그대로 옮기면 JS Math.round()가
  // 두 번째 인자(자릿수)를 조용히 무시해 소수점이 사라진다(_to_js()가 round(x,N)을
  // pyRound(x,N) 호출로 바꿔 여기로 연결한다 — modules/app_generator.py 참고).
  // Math.round(value * 10**digits) / 10**digits 방식은 채택하지 않는다 — 곱셈이
  // 이진 부동소수점 오차를 그대로 증폭시켜 pyRound(1.005, 2)가 1.01이 아니라 1이
  // 되는 등 잘 알려진 경계값 오류가 있다. 대신 숫자를 10진 문자열로 바꾼 뒤
  // 지수 표기("1.005e2")로 소수점을 옮겨 다시 파싱한다 — JS 엔진이 10진 리터럴에서
  // 직접 이진 근사값을 구하므로 곱셈 방식보다 원래 값에 더 가깝게 반올림된다.
  // 정책: JS Math.round()와 동일하게 0.5는 항상 양의 무한대 방향으로 반올림한다
  // (Python의 round-half-to-even과 다를 수 있음 — 대부분의 소수 리터럴은 이진수로
  // 정확히 .5가 아니므로 실제로는 거의 항상 일치하지만, 완전히 동일하다고 가정하지
  // 않는다. 계산기 도메인의 재무/측정값에서 정확히 .5 tie가 문제되는 사례는
  // 현재 없음 — STEP 28-140 진단 기준).
  function pyRound(value, digits) {
    digits = digits || 0;
    if (typeof value !== "number" || !isFinite(value)) return value;
    var shifted = Number(value.toString() + "e" + digits);
    if (!isFinite(shifted)) return value; // 극단적 자릿수/크기 방어(안전 폴백)
    var rounded = Math.round(shifted);
    return Number(rounded.toString() + "e" + (-digits));
  }

  // STEP 28-136: calculate()의 기존 가드(!isFinite(num(outputs[CFG.primaryOutput])))는
  // primaryOutput 한 필드만 검사한다. renderResult()는 CFG.outputs 전체(다중 출력)를
  // 화면에 렌더링하므로, primaryOutput이 아닌 다른 출력 필드가 NaN/Infinity/-Infinity가
  // 되면 가드를 통과해 그대로("NaN원", "∞" 등) 화면에 노출될 수 있다. 이 함수는 그
  // 간극을 메우는 순수 안전성 검사로, 특정 계산기의 Validation 정책이 아니라
  // outputs object 전체(문자열/배열/notices 등은 건드리지 않고 숫자 타입 값만)를
  // 대상으로 하는 계산기 공통 방어다.
  function _hasNonFiniteNumericOutput(outputs) {
    for (var k in outputs) {
      if (Object.prototype.hasOwnProperty.call(outputs, k) &&
          typeof outputs[k] === "number" && !isFinite(outputs[k])) {
        return true;
      }
    }
    return false;
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  // 입력 수집: number → 숫자(콤마제거), date → 문자열, boolean(checkbox) → 1/0
  function collectInputs() {
    var inputs = {};
    (CFG.inputs || []).forEach(function (f) {
      var el = d.getElementById("in_" + f.name);
      if (!el) { inputs[f.name] = (f.type === "date") ? "" : 0; return; }
      // STEP 28-11: checkbox는 value가 아니라 checked로 상태를 판정해야 하며,
      // 값은 기존 computeResult()가 기대하는 1(적용)/0(미적용)으로 넘긴다.
      if (f.type === "boolean") { inputs[f.name] = el.checked ? 1 : 0; return; }
      inputs[f.name] = (f.type === "date") ? el.value : num(el.value);
    });
    return inputs;
  }

  // 카운트업 애니메이션 (디자인 유지)
  // STEP 28-6: requestAnimationFrame은 배경 탭에서 스로틀/정지될 수 있어(Chrome 표준 동작),
  // 애니메이션 시작 전에 최종값을 먼저 동기적으로 표시한다 — rAF가 전혀 돌지 않아도
  // "0"/"-0"에 고착되지 않고 항상 정답이 남아있도록 하는 안전장치. rAF가 정상 동작하면
  // 이 즉시값은 같은 틱에서 애니메이션 시작 프레임(0)으로 바로 덮어써지므로 화면상
  // 기존 카운트업 효과는 그대로 유지된다.
  function countUp(el, target, decimals) {
    if (!el) return;
    el.textContent = comma(target, decimals);
    var dur = 600, start;
    function step(now) {
      if (start === undefined) start = now;
      var p = Math.min((now - start) / dur, 1);
      var ease = 1 - Math.pow(1 - p, 3);
      el.textContent = comma(ease * target, decimals);
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  // Phase C: notices 렌더 (계산 결과의 안내 메시지 목록)
  function renderNotices(notices) {
    var host = d.getElementById("notices-container");
    if (!host) return;
    if (!notices || !notices.length) {
      host.classList.remove("show");
      return;
    }
    host.innerHTML = notices.map(function (n) {
      return '<div class="sm-notice-item">'
        + '<span class="sm-notice-item-icon" aria-hidden="true">ℹ️</span>'
        + '<span>' + esc(n) + '</span>'
        + '</div>';
    }).join("");
    host.classList.add("show");
  }

  // Phase C: 계산 과정 step accordion 렌더
  // 항목이 2개 이상일 때 아코디언, 그 미만은 기존 detail-row 형태
  function renderSteps(detail, formula) {
    var host = d.getElementById("steps-list");
    var card = d.getElementById("steps-card");
    if (!host || !card) return;
    if (!detail || !detail.length) { card.style.display = "none"; return; }

    if (detail.length >= 3) {
      // 아코디언 형태 (연말정산 11단계 등)
      var idx = 0;
      host.innerHTML = detail.map(function (r) {
        var bid = "step-btn-" + (idx);
        var aid = "step-ans-" + (idx);
        idx++;
        var labelText = esc(r.label || "");
        var valueText = esc(r.value || "");
        var formulaHtml = formula
          ? '<div class="sm-steps-formula">' + esc(formula) + '</div>'
          : "";
        return '<div class="sm-steps-item">'
          + '<button class="sm-steps-q" id="' + bid + '" '
          + 'aria-expanded="false" aria-controls="' + aid + '" type="button" '
          + 'onclick="smToggleStep(this)">'
          + '<span class="sm-steps-label">' + labelText + '</span>'
          + '<span class="sm-steps-value">' + valueText + '</span>'
          + '<span class="sm-steps-icon" aria-hidden="true">+</span>'
          + '</button>'
          + '<div class="sm-steps-a" id="' + aid + '" hidden>'
          + '<strong>' + labelText + '</strong>: ' + valueText
          + formulaHtml
          + '</div>'
          + '</div>';
      }).join("");
      card.style.display = "block";
    } else {
      // 단순 목록 형태 (항목 수 적은 계산기)
      host.innerHTML = detail.map(function (r) {
        return '<div class="sm-detail-row">'
          + '<span class="sm-detail-label">' + esc(r.label) + '</span>'
          + '<span class="sm-detail-value">' + esc(r.value) + '</span>'
          + '</div>';
      }).join("");
      card.style.display = "block";
    }
  }

  // Phase C: step accordion 토글 (공통)
  w.smToggleStep = function (btn) {
    var item = btn && btn.parentElement;
    if (!item) return;
    var isOpen = item.classList.toggle("open");
    btn.setAttribute("aria-expanded", isOpen ? "true" : "false");
    var ans = item.querySelector(".sm-steps-a");
    if (ans) ans.hidden = !isOpen;
  };

  // STEP 28-157: BMI 전용 개인화 판정 등급(대한비만학회 2018 기준, 명확한 비교
  // 연산만 사용 — 경계 임의 보정 없음). registry/Contract/DB output_schema에
  // 새 필드를 추가하지 않고 out.bmi 값으로부터 화면 표시 전용으로 파생한다.
  // BMI slug에만 적용되며 다른 계산기의 renderResult() 동작에는 전혀 관여하지 않는다.
  function _bmiGrade(bmi) {
    if (bmi < 18.5) return "저체중";
    if (bmi < 23) return "정상체중";
    if (bmi < 25) return "비만전단계";
    if (bmi < 30) return "1단계 비만";
    if (bmi < 35) return "2단계 비만";
    return "3단계 비만";
  }

  function _renderBmiGrade(outputs) {
    if (CFG.slug !== "bmi-calculator") return;
    var bmi = num(outputs.bmi);
    if (!isFinite(bmi)) return;
    var el = d.getElementById("bmi-grade");
    if (!el) {
      var host = d.getElementById("result-formula");
      if (!host || !host.parentNode) return;
      el = d.createElement("div");
      el.id = "bmi-grade";
      el.className = "sm-result-sub";
      host.parentNode.insertBefore(el, host.nextSibling);
    }
    el.textContent = "판정: " + _bmiGrade(bmi);
  }

  // STEP 28-165: BMI 전용 적정 체중 범위. 정상체중 기준(18.5≤BMI<23) 중
  // 화면 표시 상한은 22.9를 사용한다(175cm → 56.7kg~70.1kg 예시와 일치).
  // weight_kg/out.bmi와 무관하게 height_cm만으로 항상 파생 가능하므로
  // inputs(=renderResult의 첫 번째 인자, collectInputs() 결과)만 사용한다.
  // 반올림/표시 형식은 기존 pyRound()/comma()를 그대로 재사용 — 새 반올림
  // 로직을 만들지 않는다. registry/Contract/DB output_schema 미변경.
  function _renderBmiWeightRange(inputs) {
    if (CFG.slug !== "bmi-calculator") return;
    var h = num(inputs && inputs.height_cm);
    if (!isFinite(h) || h <= 0) return;
    var hm = h / 100;
    var minW = 18.5 * hm * hm;
    var maxW = 22.9 * hm * hm;
    var el = d.getElementById("bmi-weight-range");
    if (!el) {
      var host = d.getElementById("bmi-grade");
      if (!host || !host.parentNode) return;
      el = d.createElement("div");
      el.id = "bmi-weight-range";
      el.className = "sm-result-sub";
      host.parentNode.insertBefore(el, host.nextSibling);
    }
    el.textContent = "적정 체중: " + comma(minW, 1) + "kg ~ " + comma(maxW, 1) + "kg";
  }

  // STEP 28-166: BMI 전용 6단계 시각 게이지(대한비만학회 2018 기준과 동일한
  // 경계값). 표시 범위는 BMI 15~40으로 고정하고, marker 위치는 반드시
  // 0~100%로 clamp한다(15 미만은 0%, 40 초과는 100%). 공유 CSS 파일은
  // 건드리지 않고 인라인 스타일만 사용 — 다른 계산기에는 아무 영향이 없다.
  function _renderBmiGauge(outputs) {
    if (CFG.slug !== "bmi-calculator") return;
    var bmi = num(outputs.bmi);
    if (!isFinite(bmi)) return;
    var GMIN = 15, GMAX = 40;
    var pct = (bmi - GMIN) / (GMAX - GMIN) * 100;
    if (pct < 0) pct = 0;
    if (pct > 100) pct = 100;

    var wrap = d.getElementById("bmi-gauge");
    if (!wrap) {
      var host = d.getElementById("bmi-weight-range") || d.getElementById("bmi-grade");
      if (!host || !host.parentNode) return;
      wrap = d.createElement("div");
      wrap.id = "bmi-gauge";
      wrap.style.cssText = "position:relative;margin-top:12px;padding-top:10px;";
      var bar = d.createElement("div");
      bar.style.cssText = "display:flex;width:100%;height:8px;border-radius:4px;overflow:hidden;";
      // 저체중/정상체중/비만전단계/1·2·3단계 비만 — 경계값(18.5/23/25/30/35)을
      // BMI 15~40 범위 기준 폭(%)으로 환산: 14/18/8/20/20/20.
      var segs = [
        [14, "#93C5FD"], [18, "#4ADE80"], [8, "#FBBF24"],
        [20, "#FB923C"], [20, "#F87171"], [20, "#DC2626"]
      ];
      segs.forEach(function (s) {
        var seg = d.createElement("div");
        seg.style.cssText = "flex:0 0 " + s[0] + "%;background:" + s[1] + ";";
        bar.appendChild(seg);
      });
      wrap.appendChild(bar);
      var marker = d.createElement("div");
      marker.id = "bmi-gauge-marker";
      marker.style.cssText = "position:absolute;top:0;width:4px;height:16px;"
        + "background:#1E293B;border-radius:2px;transform:translateX(-50%);";
      wrap.appendChild(marker);
      host.parentNode.insertBefore(wrap, host.nextSibling);
    }
    var markerEl = d.getElementById("bmi-gauge-marker");
    if (markerEl) markerEl.style.left = pct + "%";
  }

  // 결과 UI 렌더 (계산 로직 없음 — 표시만)
  function renderResult(inputs, outputs) {
    outputs = outputs || {};
    var primary = CFG.primaryOutput;
    var pv = num(outputs[primary]);

    var card = d.getElementById("result-card");
    if (card) { card.classList.remove("show"); void card.offsetWidth; card.classList.add("show"); }
    // 결과 카드 내 모든 출력 요소(primary + 추가 출력)를 countUp으로 업데이트
    (CFG.outputs || []).forEach(function(o) {
      var el = d.getElementById("out_" + o.key);
      if (el) countUp(el, num(outputs[o.key]), o.decimals);
    });

    var sub = d.getElementById("result-formula");
    if (sub) sub.textContent = outputs._formula || "";

    // STEP 28-157: BMI 전용 판정 등급(slug 조건부, 다른 계산기는 즉시 return)
    _renderBmiGrade(outputs);
    // STEP 28-165: BMI 전용 적정 체중 범위(slug 조건부, 다른 계산기는 즉시 return)
    _renderBmiWeightRange(inputs);
    // STEP 28-166: BMI 전용 시각 게이지(slug 조건부, 다른 계산기는 즉시 return)
    _renderBmiGauge(outputs);

    var actions = d.getElementById("result-actions");
    if (actions) actions.classList.add("show");

    // Phase C: notices 표시
    renderNotices(outputs.notices);

    // Phase C: 계산 과정 step accordion
    renderSteps(outputs._detail || [], outputs._formula || "");

    // Phase D-1: article_content placeholder 치환
    updateArticlePlaceholders(inputs, outputs);
    // Phase D-3: 조건 기반 CTA 업데이트
    renderDynamicCta(inputs, outputs);
    // Phase D-4: 동적 FAQ 삽입
    renderDynamicFaq(inputs, outputs);

    // E-1: result_view 이벤트
    if (w.smTrack) {
      w.smTrack("result_view", { primary_key: primary, primary_value: pv });
    }

    // 기존 계산 상세 (detail-card) — steps-card와 중복 방지: steps-card 있으면 detail-card 숨김
    if (!d.getElementById("steps-card")) {
      var rows = [];
      (CFG.inputs || []).forEach(function (f) {
        var v = inputs[f.name];
        var disp = (f.type === "date") ? (v || "-") : (comma(num(v)) + (f.unit || ""));
        rows.push([f.label || f.name, disp]);
      });
      (outputs._detail || []).forEach(function (r) { rows.push([r.label, r.value]); });
      (CFG.outputs || []).forEach(function (o) {
        rows.push([o.label || o.key, comma(num(outputs[o.key])) + (o.unit || "")]);
      });
      if (CFG.show_detail !== false) {
        var host = d.getElementById("detail-rows");
        if (host) {
          host.innerHTML = rows.map(function (r) {
            return '<div class="sm-detail-row"><span class="sm-detail-label">' + esc(r[0]) +
              '</span><span class="sm-detail-value">' + esc(r[1]) + "</span></div>";
          }).join("");
          var dc = d.getElementById("detail-card"); if (dc) dc.style.display = "block";
        }
      }
    }
  }

  // Phase D-1: article_content 내 <span data-ph> 를 계산 결과로 치환
  function updateArticlePlaceholders(inputs, outputs) {
    d.querySelectorAll("[data-ph]").forEach(function (el) {
      var key = el.getAttribute("data-ph");
      var fmt = el.getAttribute("data-fmt") || "text";
      // inputs 우선, 없으면 outputs 에서 읽기
      var raw = (outputs && outputs[key] != null) ? outputs[key]
              : (inputs  && inputs[key]  != null) ? inputs[key]
              : null;
      if (raw == null || raw === "" || raw === 0 && key !== "family_count") return;
      var display;
      if (fmt === "currency") {
        display = Math.round(num(raw)).toLocaleString() + "원";
      } else if (fmt === "currency_signed") {
        var n = Math.round(num(raw));
        display = (n >= 0 ? "+" : "") + n.toLocaleString() + "원";
      } else if (fmt === "number") {
        display = num(raw).toLocaleString();
      } else {
        display = String(raw);
      }
      el.textContent = display;
    });
  }

  // Phase D-3: SM_CTA_RULES 조건 평가 → #sm-result-cta 동적 업데이트
  function renderDynamicCta(inputs, outputs) {
    var host = d.getElementById("sm-result-cta");
    var rules = w.SM_CTA_RULES;
    if (!host || !rules) return;
    var matched = null;
    var ruleList = rules.rules || [];
    for (var i = 0; i < ruleList.length; i++) {
      try {
        var ok = (new Function("inputs", "outputs", "return !!(" + ruleList[i].condition + ");"))(inputs, outputs);
        if (ok) { matched = ruleList[i]; break; }
      } catch (e) { /* 조건 평가 실패 시 다음 룰 */ }
    }
    var rule = matched || rules.default;
    if (!rule) return;
    var linksHtml = (rule.links || []).map(function (l) {
      return '<a class="sm-result-cta-link" href="' + esc(l.href) + '">' + esc(l.label) + '</a>';
    }).join("");
    host.innerHTML =
      '<p class="sm-result-cta-text">' + esc(rule.text || "") + '</p>' +
      '<div class="sm-result-cta-links">' + linksHtml + '</div>';
    // Analytics 훅 (Phase E에서 실제 연동)
    if (rule.analytics && w.smTrack) { w.smTrack(rule.analytics, {inputs: inputs, outputs: outputs}); }
  }

  // Phase D-4: SM_DYNAMIC_FAQ 조건 평가 → #sm-dynamic-faq 에 우선순위 순으로 삽입
  function renderDynamicFaq(inputs, outputs) {
    var host = d.getElementById("sm-dynamic-faq");
    var items = w.SM_DYNAMIC_FAQ;
    if (!host || !items || !items.length) return;
    // 우선순위(1→4) 정렬 후 조건 평가
    var sorted = items.slice().sort(function (a, b) { return (a.priority || 4) - (b.priority || 4); });
    var matched = [];
    sorted.forEach(function (item) {
      try {
        var ok = (new Function("inputs", "outputs", "return !!(" + item.condition + ");"))(inputs, outputs);
        if (ok) matched.push(item);
      } catch (e) { /* skip */ }
    });
    if (!matched.length) return;
    var idx = 9000; // dynamic FAQ id prefix (정적 FAQ와 겹치지 않게)
    host.innerHTML = matched.map(function (item) {
      var bid = "faq-dyn-btn-" + idx;
      var aid = "faq-dyn-ans-" + (idx++);
      return '<div class="sm-faq-item sm-faq-dynamic">' +
        '<button class="sm-faq-q" id="' + bid + '" type="button" ' +
        'aria-expanded="false" aria-controls="' + aid + '" onclick="toggleFaq(this)">' +
        esc(item.q || "") +
        '<span class="sm-faq-icon" aria-hidden="true">+</span></button>' +
        '<div class="sm-faq-a" id="' + aid + '" hidden>' + esc(item.a || "") + '</div>' +
        '</div>';
    }).join("");
  }

  // E-1: calculate 호출 횟수 (retry 감지)
  var _calcCount = 0;

  // 공통 계산 진입점 — 계산기별 computeResult(inputs)만 교체하면 재사용
  function calculate() {
    _calcCount++;
    // E-1: calculator_submit (첫 번째) / retry_calculation (2번째~)
    if (w.smTrack) {
      w.smTrack(_calcCount > 1 ? "retry_calculation" : "calculator_submit", {});
    }
    var inputs = collectInputs();
    var outputs;
    try {
      outputs = (typeof w.computeResult === "function") ? w.computeResult(inputs) : null;
    } catch (e) { console.error(e); outputs = null; }
    if (!outputs || !isFinite(num(outputs[CFG.primaryOutput])) || _hasNonFiniteNumericOutput(outputs)) {
      var errEl = d.getElementById("calc-error");
      if (!errEl) {
        errEl = d.createElement("p");
        errEl.id = "calc-error";
        errEl.style.cssText = "color:#DC2626;font-size:14px;margin-top:8px;font-weight:600;";
        var btn = d.querySelector(".sm-btn");
        if (btn && btn.parentNode) btn.parentNode.insertBefore(errEl, btn.nextSibling);
      }
      errEl.textContent = "입력값을 확인해주세요.";
      return;
    }
    var errEl2 = d.getElementById("calc-error");
    if (errEl2) errEl2.textContent = "";
    renderResult(inputs, outputs);
  }

  // 초기화: show_* 플래그 반영 + 기능 모듈 init
  function init() {
    if (CFG.show_adsense) toggleAll(".sm-adsense", true);
    if (CFG.show_cpa) toggleAll(".sm-cpa", true);
    hideActionIf("result_save", CFG.show_result_save === false);
    hideActionIf("share", CFG.show_share === false);
    hideActionIf("pwa", CFG.show_pwa === false);
    if (CFG.show_faq === false) hideEl("#faq-card");
    if (CFG.show_notice === false) hideEl(".sm-notice");
    if (CFG.show_related === false) hideEl("#related-card");
    if (CFG.show_article === false) hideEl(".sm-article");
    if (w.smInitNumberInputs) w.smInitNumberInputs();
    if (w.smInitPwa) w.smInitPwa();
  }

  function hideEl(sel) { var el = d.querySelector(sel); if (el) el.style.display = "none"; }
  function toggleAll(sel, on) { d.querySelectorAll(sel).forEach(function (el) { el.style.display = on ? "block" : "none"; }); }
  function hideActionIf(action, hide) {
    if (!hide) return;
    var b = d.querySelector('.sm-action-btn[data-action="' + action + '"]');
    if (b) b.style.display = "none";
  }

  w.calculate = calculate;
  w.smRenderResult = renderResult;
  // STEP 28-140: 계산기별 생성 코드(이 IIFE 바깥 전역 스코프에서 정의되는
  // computeResult 함수)가 pyRound()를 호출해야 하므로 명시적으로 전역에
  // 노출한다(기존 calculate/smRenderResult와 동일한 export 방식).
  w.pyRound = pyRound;
  if (d.readyState === "loading") d.addEventListener("DOMContentLoaded", init);
  else init();
})(window, document);


window.computeResult = function(inputs){
  var monthly_wage = inputs["monthly_wage"] || 0;
  var insured_days = inputs["insured_days"] || 0;
  var use_6plus6   = inputs["use_6plus6"]   || 0;
  var leave_month = inputs["leave_month"] || 0;
  if (monthly_wage <= 0 || insured_days <= 0 || leave_month <= 0) { return null; }
  var out = {};
  out.notices = [];
  var MIN_INSURED = 180;
  if (insured_days < MIN_INSURED) {
    out["monthly_allowance"] = 0;
    out.notices.push("피보험단위기간이 " + insured_days + "일로 180일 미만이면 육아휴직급여를 받을 수 없습니다(고용보험법 제70조 제1항).");
    out._formula = "피보험단위기간 " + insured_days + "일 — 180일 미만으로 수급 불가";
    return out;
  }
  var GEN_RATE  = 0.8;
  var GEN_CEIL  = 1500000;
  var GEN_FLOOR = 700000;
  var SP_RATE   = 1.0;
  var SP_MAX_MO = 6;
  var SP_CEILS  = [2000000,2500000,3000000,3500000,4000000,4500000];
  function determine_leave_mode(use_sp, mo) {
    if (use_sp >= 1 && mo >= 1 && mo <= SP_MAX_MO) { return "SPECIAL_6_PLUS_6"; }
    return "GENERAL";
  }
  function calculate_general(wage) {
    var raw = wage * GEN_RATE;
    var applied = Math.min(Math.max(raw, GEN_FLOOR), GEN_CEIL);
    return { raw: raw, applied: applied, ceiling: GEN_CEIL, floor: GEN_FLOOR, rate_pct: "80%" };
  }
  function calculate_6plus6(wage, mo) {
    var raw = wage * SP_RATE;
    var ceiling = SP_CEILS[mo - 1];
    var applied = Math.min(Math.max(raw, GEN_FLOOR), ceiling);
    return { raw: raw, applied: applied, ceiling: ceiling, floor: GEN_FLOOR, rate_pct: "100%" };
  }
  var mode = determine_leave_mode(use_6plus6, leave_month);
  if (use_6plus6 >= 1 && leave_month > SP_MAX_MO) {
    out.notices.push("6+6 특례는 1～" + SP_MAX_MO + "개월에만 적용됩니다. " + leave_month + "개월째는 일반 육아휴직급여(통상임금 80%)가 적용됩니다(고용보험법 시행령 제95조의2).");
  }
  var cr = (mode === "SPECIAL_6_PLUS_6") ? calculate_6plus6(monthly_wage, leave_month) : calculate_general(monthly_wage);
  out["monthly_allowance"] = cr.applied;
  var _mn = [];
  if (cr.raw > cr.ceiling) {
    _mn.push("통상임금 기준 급여(" + Math.round(cr.raw).toLocaleString() + "원)가 상한액(" + cr.ceiling.toLocaleString() + "원)을 초과하여 상한액이 적용됩니다(고용보험법 시행령 제95조).");
  } else if (cr.raw < cr.floor) {
    _mn.push("통상임금 기준 급여(" + Math.round(cr.raw).toLocaleString() + "원)가 하한액(" + cr.floor.toLocaleString() + "원)보다 낮아 하한액이 적용됩니다(고용보험법 시행령 제95조).");
  }
  out.notices = [].concat(out.notices, _mn);
  var ml = (mode === "SPECIAL_6_PLUS_6") ? ("6+6 특례 " + leave_month + "개월차") : "일반";
  var fs = ml + " — 통상임금 " + monthly_wage.toLocaleString() + "원 × " + cr.rate_pct + " = " + Math.round(cr.raw).toLocaleString() + "원";
  if (cr.raw > cr.ceiling) { fs += " → 상한 적용(" + cr.ceiling.toLocaleString() + "원) → " + Math.round(cr.applied).toLocaleString() + "원"; }
  else if (cr.raw < cr.floor) { fs += " → 하한 적용(" + cr.floor.toLocaleString() + "원) → " + Math.round(cr.applied).toLocaleString() + "원"; }
  out._formula = fs;
  return out;
};

window.SM_CTA_RULES = {"default": {"text": "육아휴직 관련 정보", "links": [{"label": "6+6 특례 자세히 보기", "href": "/blog/6plus6-parental-leave-guide/"}, {"label": "전체 계산기", "href": "/"}], "analytics": "cta_pl_default"}, "rules": [{"condition": "outputs.monthly_allowance > 0", "text": "육아휴직 급여를 받을 수 있습니다", "links": [{"label": "신청 절차 안내", "href": "/blog/parental-leave-benefit-apply/"}, {"label": "6+6 특례 알아보기", "href": "/blog/6plus6-parental-leave-guide/"}], "analytics": "cta_pl_eligible"}, {"condition": "outputs.monthly_allowance === 0", "text": "피보험단위기간 180일 이상이어야 합니다", "links": [{"label": "수급 조건 자세히 보기", "href": "/blog/parental-leave-benefit-apply/"}, {"label": "전체 계산기", "href": "/"}], "analytics": "cta_pl_ineligible"}]};
window.SM_DYNAMIC_FAQ = [{"priority": 1, "condition": "outputs.monthly_allowance === 0 && (outputs.notices||[]).length > 0", "q": "피보험단위기간 180일 미만이라 육아휴직 급여를 받을 수 없나요?", "a": "고용보험법 제70조 제1항에 따라 육아휴직 개시일 이전 피보험단위기간이 합산 180일 이상이어야 합니다. 복수 사업장 근무 기간을 합산할 수 있습니다."}, {"priority": 2, "condition": "(outputs.notices||[]).some(function(n){return n.indexOf('상한')>=0;})", "q": "통상임금이 높은데 상한액이 적용된 이유는?", "a": "일반 육아휴직급여는 월 최대 150만원(고용보험법 시행령 제95조), 6+6 특례는 1~6개월차별로 200만~450만원의 상한이 적용됩니다."}, {"priority": 3, "condition": "outputs.monthly_allowance > 0", "q": "6+6 부모 육아휴직 특례란 무엇인가요?", "a": "2024년 1월 시행된 제도로 부모가 함께 육아휴직을 사용할 때 최대 6개월간 급여를 높게 지급하는 특례입니다. 배우자도 육아휴직 중이어야 하며, 순서는 무관합니다(고용보험법 시행령 제95조의2)."}];
