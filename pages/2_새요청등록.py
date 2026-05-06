"""새 요청 등록 페이지 — docs/03_ui_design.md 3.6 + docs/07_scenarios.md 7.5.

좌우 분할 레이아웃: 좌측 = 이미지 입력 / 우측 = 폼.
카테고리는 우측 컬럼 안 / st.form 바깥에 두어 종속 selectbox 즉시 반영.
폼 nonce 패턴으로 위젯 key 를 회전시켜 제출 후 입력 초기화.

이미지 입력은 세 경로:
  1) file_uploader (다중) — 항상 동작
  2) streamlit_paste_button — HTTPS/localhost 만 동작 (Async Clipboard API)
  3) HTTP+IP 호환 paste 위젯 — paste 이벤트 + base64 우회 (Secure Context 무관)

3) 의 흐름 (2-step paste): iframe 안에서 Ctrl+V 로 paste 이벤트 발생 →
JS 가 clipboardData.items 에서 이미지 blob 추출 → base64 문자열로 textarea 에 채움 →
사용자가 그 base64 를 복사 → 외부 Streamlit text_area 에 붙여넣기 (텍스트 paste 는 OK) →
Python 이 base64 → bytes → PIL.Image 로 디코딩하여 첨부.
"""

from __future__ import annotations

import base64
import io
import re

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image as PILImage

from core import paths, repository
from core.images import ALLOWED_EXT, MAX_FILE_MB, MAX_IMAGES_PER_ITEM
from core.models import Role, Urgency
from ui.auth import get_or_init_user, require_user

# streamlit_paste_button 은 옵션 의존성. 미설치/import 실패면 None.
try:  # pragma: no cover - 환경 의존
    from streamlit_paste_button import paste_image_button as _paste_button
except Exception:  # noqa: BLE001
    _paste_button = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# HTTP+IP 호환 paste 위젯용 HTML — paste 이벤트는 Secure Context 가 불필요하므로
# 사내 IP + HTTP 환경에서도 정상 동작한다. 단 iframe → outer Streamlit 으로의
# 직접적 데이터 전달 채널이 없어, base64 텍스트를 사용자가 한 번 더 붙여넣는
# "2-단계 paste" 패턴을 사용한다.
# ---------------------------------------------------------------------------

_PASTE_AREA_HTML = """
<div id="paste-host" style="font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;">
  <div id="paste-area" tabindex="0"
       style="border:2px dashed #3B82F6; border-radius:8px; padding:14px;
              text-align:center; cursor:text; outline:none; user-select:text;
              background:#F8FAFC; min-height:70px;">
    <strong>여기를 클릭</strong>하고 <code>Ctrl+V</code> 로 이미지 붙여넣기
    <div id="paste-status" style="margin-top:6px; font-size:12px; color:#475569;">
      대기 중&hellip;
    </div>
  </div>
  <canvas id="paste-preview"
          style="max-width:100%; margin-top:8px; display:none;
                 border:1px solid #E2E8F0; border-radius:6px;"></canvas>
  <div id="paste-output-wrap" style="display:none; margin-top:8px;">
    <div style="font-size:12px; color:#475569; margin-bottom:4px;">
      아래 base64 문자열을 <strong>전체 선택 (Ctrl+A) → 복사 (Ctrl+C)</strong> 한 뒤,
      페이지 아래 <em>"클립보드 base64 입력"</em> 칸에 붙여넣고 <em>"이미지 디코드"</em> 버튼을 누르세요.
    </div>
    <textarea id="paste-b64" readonly
              style="width:100%; height:84px; font-family:monospace; font-size:11px;
                     border:1px solid #CBD5E1; border-radius:6px; padding:6px;
                     background:#FFFFFF; resize:vertical;"></textarea>
    <button id="paste-copy-btn" type="button"
            style="margin-top:6px; padding:6px 12px; border:0; border-radius:6px;
                   background:#3B82F6; color:#fff; cursor:pointer; font-size:13px;">
      base64 자동 선택
    </button>
  </div>
</div>
<script>
(function() {
  const area = document.getElementById('paste-area');
  const status = document.getElementById('paste-status');
  const canvas = document.getElementById('paste-preview');
  const outWrap = document.getElementById('paste-output-wrap');
  const out = document.getElementById('paste-b64');
  const copyBtn = document.getElementById('paste-copy-btn');

  // 영역에 자동 포커스 (클릭 없이도 1차로 포커스를 잡아 둔다)
  setTimeout(function(){ try { area.focus(); } catch (e) {} }, 100);

  area.addEventListener('click', function(){ try { area.focus(); } catch (e) {} });

  area.addEventListener('paste', function(e) {
    const cd = e.clipboardData || window.clipboardData;
    if (!cd) {
      status.textContent = 'clipboardData 를 사용할 수 없는 브라우저입니다.';
      return;
    }
    const items = cd.items || [];
    let handled = false;
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      if (item.type && item.type.indexOf('image/') === 0) {
        const blob = item.getAsFile();
        if (!blob) continue;
        handled = true;
        const reader = new FileReader();
        reader.onload = function(ev) {
          const dataUrl = ev.target.result;  // data:image/png;base64,...
          // 미리보기 그리기
          const img = new Image();
          img.onload = function() {
            const maxW = 480;
            const ratio = Math.min(1, maxW / img.width);
            canvas.width = Math.round(img.width * ratio);
            canvas.height = Math.round(img.height * ratio);
            canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
            canvas.style.display = 'block';
          };
          img.src = dataUrl;
          // base64 textarea 에 채우기
          out.value = dataUrl;
          outWrap.style.display = 'block';
          status.textContent = '이미지 인식 완료 (' + Math.round(blob.size/1024) + ' KB). 아래 base64 를 복사하세요.';
        };
        reader.readAsDataURL(blob);
        break;
      }
    }
    if (!handled) {
      status.textContent = '클립보드에 이미지가 없습니다. 화면 캡처 후 다시 시도하세요.';
    }
  });

  copyBtn.addEventListener('click', function() {
    out.focus();
    out.select();
    try {
      // execCommand('copy') 는 HTTP 에서도 동작 (legacy API)
      const ok = document.execCommand('copy');
      copyBtn.textContent = ok ? '복사됨! (이제 아래 칸에 붙여넣기)' : '자동 선택만 완료 - Ctrl+C 로 복사';
      setTimeout(function(){ copyBtn.textContent = 'base64 자동 선택'; }, 2500);
    } catch (e) {
      copyBtn.textContent = '자동 선택만 완료 - Ctrl+C 로 복사';
    }
  });
})();
</script>
"""


# ---------------------------------------------------------------------------
# base64 데이터 URL 디코더 — 사용자가 외부 text_area 에 붙여넣은 문자열을
# bytes / PIL.Image 로 변환한다. 잘못된 입력에 대해 ValueError 를 던진다.
# ---------------------------------------------------------------------------

_DATA_URL_RE = re.compile(r"^data:image/[A-Za-z0-9.+-]+;base64,", re.IGNORECASE)


def _decode_pasted_b64(text: str) -> tuple[PILImage.Image, bytes, str]:
    """data:image/...;base64,... 또는 순수 base64 문자열을 (PIL, bytes, mime) 로 디코드.

    공백/개행 모두 허용. 잘못된 형식이면 ValueError.
    """
    if not text:
        raise ValueError("입력이 비어 있습니다.")
    cleaned = "".join(text.split())
    mime = "image/png"
    m = _DATA_URL_RE.match(cleaned)
    if m:
        header = m.group(0)
        # data:image/png;base64, 에서 image/png 추출
        try:
            mime = header.split(":", 1)[1].split(";", 1)[0]
        except Exception:  # noqa: BLE001
            mime = "image/png"
        cleaned = cleaned[len(header):]
    try:
        raw = base64.b64decode(cleaned, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"base64 디코드 실패: {exc}") from exc
    if not raw:
        raise ValueError("디코드된 바이트가 비어 있습니다.")
    try:
        img = PILImage.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"이미지로 열 수 없습니다: {exc}") from exc
    return img, raw, mime


# ---------------------------------------------------------------------------
# 페이지 설정 + 부트스트랩
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="새 요청 등록 — Daily View",
    layout="wide",
    initial_sidebar_state="expanded",
)

paths.ensure_data_dirs()

get_or_init_user()
user = require_user()

name: str = user["name"]
role_str: str = user.get("role", "reviewer")


# ---------------------------------------------------------------------------
# 헤더 + 안내
# ---------------------------------------------------------------------------

st.title("새 요청 등록")

if role_str != "reviewer":
    st.warning("주로 검토자가 등록하지만 개발자도 가능합니다.")


# ---------------------------------------------------------------------------
# 폼 nonce — 제출 후 위젯 초기화용
# ---------------------------------------------------------------------------

st.session_state.setdefault("new_form_nonce", 0)
nonce: int = int(st.session_state["new_form_nonce"])


# ---------------------------------------------------------------------------
# 담당 개발자 후보 (인덱스 전체에서 unique 추출)
# ---------------------------------------------------------------------------

# 너무 복잡하지 않게 — 등장한 적이 있는 모든 author/assignee 이름을 후보로.
existing_entries = repository.list_issues(include_archived=True)
known_names: set[str] = set()
for e in existing_entries:
    if e.assignee:
        known_names.add(e.assignee)
    # 등록자도 다음 후보로 등장 가능 (개발자가 직접 등록한 경우 등).
    if e.author:
        known_names.add(e.author)
known_names.discard(name)  # 자기 자신은 후보에서 제외 (등록자=담당자 케이스 방지)
# 담당자 필수화: "(미지정)" 옵션을 제거하여 None 저장이 불가능하도록 함.
# known_names 가 비어있으면 ["(직접 입력)"] 만 남아 사용자가 직접 입력을 강제받는다.
assignee_options = sorted(known_names) + ["(직접 입력)"]

# 직전에 지정한 담당자를 기본값으로 — "두 명만 쓰는" 환경에선 매번 같은 사람이라
# 매 등록마다 다시 고르게 하는 건 번거롭다. 직전 값이 후보에 없으면 첫 번째.
_last_assignee = st.session_state.get("_last_assignee")
if _last_assignee and _last_assignee in assignee_options:
    _default_assignee_idx = assignee_options.index(_last_assignee)
else:
    _default_assignee_idx = 0  # 첫 번째 담당자 (또는 "(직접 입력)")


# ---------------------------------------------------------------------------
# 카테고리 트리 — 후속 처리에서 사용
# ---------------------------------------------------------------------------

_cat_tree = repository.list_categories()  # {l1: {l2: {l3,...}}}
_NONE = "(선택 안 함)"


def _resolve_category(level_key: str, options: list[str]) -> str | None:
    """selectbox + text_input 를 한 줄에 나란히 표시.

    text_input 이 비어있지 않으면 그 값을, 아니면 selectbox 의 선택값을 사용.
    selectbox 에서 (선택 안 함) 을 고르고 text_input 도 비었으면 None.
    """
    sel_col, txt_col = st.columns([1, 1])
    with sel_col:
        pick = st.selectbox(
            f"{level_key} (기존)",
            options=options,
            key=f"new_cat_{level_key}_select_{nonce}",
            label_visibility="collapsed",
        )
    with txt_col:
        manual = st.text_input(
            f"{level_key} (직접 입력)",
            key=f"new_cat_{level_key}_input_{nonce}",
            placeholder=f"{level_key} 직접 입력",
            label_visibility="collapsed",
        )
    manual_clean = (manual or "").strip()
    if manual_clean:
        return manual_clean
    if pick == _NONE:
        return None
    return pick


# ---------------------------------------------------------------------------
# 좌우 분할 — 좌측: 이미지 / 우측: 카테고리 + 폼
# ---------------------------------------------------------------------------

left, right = st.columns([1, 1], gap="large")


# ---------------------------------------------------------------------------
# 좌측: 이미지 입력 (file_uploader + paste-button + 미리보기)
# ---------------------------------------------------------------------------

with left:
    st.markdown("##### 스크린샷")
    st.caption(
        f"파일 업로드(다중 가능) 또는 클립보드 붙여넣기. "
        f"항목당 최대 {MAX_IMAGES_PER_ITEM}장, 1장당 {MAX_FILE_MB}MB 이내. "
        f"허용 확장자: {', '.join(sorted(ALLOWED_EXT))}"
    )

    img_col1, img_col2 = st.columns([1, 1])

    # 파일 업로드
    with img_col1:
        st.markdown("**파일에서**")
        uploaded_files = st.file_uploader(
            "이미지 업로드",
            type=["png", "jpg", "jpeg", "webp", "gif"],
            accept_multiple_files=True,
            key=f"new_files_{nonce}",
            label_visibility="collapsed",
        )

    # 클립보드 붙여넣기 — 두 경로:
    #   (a) streamlit-paste-button (HTTPS/localhost 전용, Async Clipboard API)
    #   (b) HTTP+IP 호환 paste 위젯 (paste 이벤트 + base64 우회)
    # 둘 다 설치/표시하고, 결과는 동일한 paste_image 변수에 합류시킨다.
    paste_image: PILImage.Image | None = None
    with img_col2:
        st.markdown("**클립보드 (Ctrl+V)**")
        if _paste_button is None:
            st.caption("`streamlit-paste-button` 미설치 — 아래 HTTP 호환 위젯을 사용하세요.")
        else:
            try:
                paste_result = _paste_button(
                    label="붙여넣기 (HTTPS/localhost)",
                    key=f"new_paste_{nonce}",
                    text_color="#ffffff",
                    background_color="#3B82F6",
                    hover_background_color="#2563EB",
                    errors="ignore",
                )
                if paste_result is not None and getattr(paste_result, "image_data", None) is not None:
                    paste_image = paste_result.image_data
            except Exception as exc:  # pragma: no cover - 컴포넌트 환경 의존
                st.caption(f"붙여넣기 버튼 오류: {exc}")
            st.caption("위 버튼은 HTTPS/localhost 전용. HTTP+IP 환경에선 아래 위젯을 사용.")

    # ----- HTTP+IP 호환 paste 위젯 (좌측 컬럼 전체 폭) -----
    # paste 이벤트 자체는 Secure Context 가 불필요 → 사내 IP+HTTP 환경에서 정상 동작.
    # iframe 내부에서 클립보드 이미지를 base64 로 추출하여 textarea 에 노출 →
    # 사용자가 그 base64 를 복사하여 외부 text_area 에 붙여넣으면 Python 이 디코드.
    st.markdown("**HTTP+IP 호환 붙여넣기 (2-단계)**")
    components.html(_PASTE_AREA_HTML, height=320, scrolling=False)

    pasted_b64 = st.text_area(
        "클립보드 base64 입력",
        key=f"new_paste_b64_{nonce}",
        height=80,
        placeholder="위 영역에 Ctrl+V 한 후, 표시된 base64 를 복사해서 여기에 붙여넣으세요.",
        help="data:image/...;base64,XXXX 형식 또는 순수 base64 모두 허용됩니다.",
    )
    decode_clicked = st.button(
        "이미지 디코드",
        key=f"new_paste_decode_{nonce}",
        help="입력한 base64 를 이미지로 변환하여 미리보기/첨부 대기열에 추가합니다.",
        use_container_width=True,
    )

    # 디코드한 결과를 session_state 에 보관 — rerun 사이에도 유지하여
    # 폼 제출 시 함께 첨부될 수 있도록 한다.
    _decoded_key = f"_decoded_paste_image_{nonce}"
    if decode_clicked and (pasted_b64 or "").strip():
        try:
            _img, _, _ = _decode_pasted_b64(pasted_b64)
            st.session_state[_decoded_key] = _img
            st.success("이미지가 인식되었습니다. 아래 미리보기에서 확인하세요.")
        except ValueError as exc:
            st.error(f"디코드 실패: {exc}")
            st.session_state.pop(_decoded_key, None)

    # 디코드한 paste 이미지를 paste_image (기존 pipeline) 으로 합류
    if paste_image is None and st.session_state.get(_decoded_key) is not None:
        paste_image = st.session_state[_decoded_key]

    with st.expander("HTTP+IP 환경에서의 사용법 / 안내"):
        st.markdown(
            "**핵심**: 이 페이지는 HTTP+IP (예: `http://192.168.x.x:8501`) 환경에서도 "
            "클립보드 붙여넣기가 동작합니다. "
            "기존 `streamlit-paste-button` 은 `navigator.clipboard.read()` (Async Clipboard API) "
            "를 사용해 Secure Context (HTTPS/localhost) 가 필수이지만, "
            "위의 **HTTP+IP 호환 위젯** 은 브라우저의 `paste` 이벤트를 사용하므로 "
            "Secure Context 가 필요하지 않습니다.\n\n"
            "**사용 흐름 (2-단계)**\n\n"
            "1. 화면 캡처 (`Win+Shift+S` 또는 `PrtScn`) — 클립보드에 이미지가 들어감\n"
            "2. 위 점선 영역(파란 점선)을 한 번 클릭하여 포커스 부여\n"
            "3. `Ctrl+V` — 영역 내부에 미리보기 + base64 텍스트가 나타남\n"
            "4. 표시된 base64 를 복사 (`base64 자동 선택` 버튼 → `Ctrl+C`)\n"
            "5. 아래 *클립보드 base64 입력* 칸에 `Ctrl+V` (텍스트 붙여넣기는 항상 OK)\n"
            "6. **이미지 디코드** 버튼 클릭 → 미리보기에 합류 → 폼 등록\n\n"
            "**왜 2-단계인가?** Streamlit `components.html` 은 iframe 으로 격리되어 "
            "iframe 내부 JS 가 직접 Python 으로 데이터를 보낼 수 없습니다 "
            "(cross-origin postMessage 제약). 텍스트(base64) 한 번 더 붙여넣기를 "
            "거치면 일반 `text_area` 의 입력 채널을 그대로 사용할 수 있습니다.\n\n"
            "**대안**: PC 직접 접속 시 `http://localhost:8501` 또는 "
            "`http://127.0.0.1:8501` 로 접속하면 Secure Context 로 인정되어 "
            "위쪽 *HTTPS/localhost* 버튼이 즉시 동작합니다."
        )

    # 미리보기
    preview_files: list = list(uploaded_files or [])
    preview_total = len(preview_files) + (1 if paste_image is not None else 0)
    if preview_total:
        st.caption(f"미리보기 — {preview_total}장")
        cols = st.columns(min(preview_total, 4))
        idx = 0
        if paste_image is not None:
            with cols[idx % len(cols)]:
                st.image(paste_image, caption="(클립보드)", use_container_width=True)
            idx += 1
        for f in preview_files:
            with cols[idx % len(cols)]:
                st.image(f, caption=f.name, use_container_width=True)
            idx += 1


# ---------------------------------------------------------------------------
# 우측: 카테고리 (폼 바깥) + 본 폼
# ---------------------------------------------------------------------------

with right:
    # ------- 프로젝트 (st.form 바깥, 카테고리 위) -------
    st.markdown("##### 프로젝트")
    st.caption(
        "기존 프로젝트에서 고르거나 우측 칸에 직접 입력하세요. "
        "직접 입력 칸이 채워져 있으면 그 값이 우선 사용됩니다. 비워둬도 무방."
    )

    projects = repository.list_projects()
    default_proj = st.session_state.get("_current_project") or ""

    proj_sel_col, proj_txt_col = st.columns([1, 1])
    with proj_sel_col:
        proj_options = [_NONE] + projects
        proj_default_idx = (
            proj_options.index(default_proj) if default_proj in proj_options else 0
        )
        proj_pick = st.selectbox(
            "프로젝트 (기존)",
            options=proj_options,
            index=proj_default_idx,
            key=f"new_proj_select_{nonce}",
            label_visibility="collapsed",
        )
    with proj_txt_col:
        proj_manual = st.text_input(
            "프로젝트 (직접 입력)",
            value=default_proj if default_proj and default_proj not in projects else "",
            key=f"new_proj_input_{nonce}",
            placeholder="새 프로젝트 이름",
            label_visibility="collapsed",
        )

    # 우선순위: text_input > selectbox
    proj_value: str | None
    if proj_manual.strip():
        proj_value = proj_manual.strip()
    elif proj_pick == _NONE:
        proj_value = None
    else:
        proj_value = proj_pick

    # ------- 카테고리 (st.form 바깥, 종속 selectbox 즉시 반영) -------
    st.markdown("##### 카테고리")
    st.caption(
        "기존에서 고르거나 우측 칸에 직접 입력하세요. "
        "직접 입력 칸이 채워져 있으면 그 값이 우선 사용됩니다. 비워둬도 무방."
    )

    # 평면 카테고리: 대분류와 무관하게 모든 unique 중분류·소분류를 노출.
    # "대분류가 달라도 중분류 이름이 같으면 다 보고 싶다"는 요구사항 반영.
    _all_l1, _all_l2, _all_l3 = repository.flat_categories(_cat_tree)

    l1_options = [_NONE] + _all_l1
    cat_l1 = _resolve_category("대분류", l1_options)

    l2_options = [_NONE] + _all_l2
    cat_l2 = _resolve_category("중분류", l2_options)

    l3_options = [_NONE] + _all_l3
    cat_l3 = _resolve_category("소분류", l3_options)

    # ------- 본 폼 -------
    st.markdown("##### 요청 내용")
    with st.form(key=f"new_request_form_{nonce}", clear_on_submit=False):
        title_input = st.text_input(
            "제목 *",
            max_chars=120,
            key=f"new_title_{nonce}",
            placeholder="간단명료한 한 줄 요약",
        )
        description_input = st.text_area(
            "설명 *",
            height=180,
            key=f"new_desc_{nonce}",
            help="마크다운 지원. 재현 절차/기대 동작/실제 동작을 적어주세요.",
        )

        urgency_value = st.radio(
            "긴급도 *",
            options=[u.value for u in Urgency],
            format_func=lambda v: {"high": "긴급", "normal": "보통", "low": "낮음"}[v],
            horizontal=True,
            index=1,  # 보통
            key=f"new_urgency_{nonce}",
        )

        assignee_choice = st.selectbox(
            "담당 개발자",
            options=assignee_options,
            index=_default_assignee_idx,  # 직전 등록 담당자가 기본값 (없으면 미지정)
            key=f"new_assignee_select_{nonce}",
        )

        assignee_manual = st.text_input(
            "담당자 직접 입력",
            key=f"new_assignee_manual_{nonce}",
            placeholder="위에서 (직접 입력) 선택 시 사용",
            help="후보 목록에 없는 새로운 담당자를 지정할 때만 입력하세요.",
        )

        submit = st.form_submit_button("등록", type="primary", use_container_width=True)


# ---------------------------------------------------------------------------
# 폼 밖: 취소 링크
# ---------------------------------------------------------------------------

if st.button("취소", key=f"new_cancel_{nonce}"):
    st.switch_page("pages/1_요청목록.py")


# ---------------------------------------------------------------------------
# 제출 처리
# ---------------------------------------------------------------------------

if submit:
    title = (title_input or "").strip()
    description = (description_input or "").strip()

    if not title or not description:
        st.error("제목과 설명은 필수입니다.")
        st.stop()

    # 담당자 결정 — 미지정 옵션을 제거했으므로 항상 값이 있어야 한다.
    final_assignee: str | None = None
    if assignee_choice == "(직접 입력)":
        manual = (assignee_manual or "").strip()
        final_assignee = manual or None
    else:
        final_assignee = (assignee_choice or "").strip() or None

    # 담당자 필수 검증: 빈 값이면 등록 차단
    if not final_assignee:
        st.error("담당 개발자를 지정해주세요.")
        st.stop()

    # 역할 정규화 (저장된 user["role"] 은 문자열 "reviewer"/"developer")
    try:
        author_role = Role(role_str)
    except ValueError:
        author_role = Role.reviewer

    # 1) 이슈 생성
    try:
        issue = repository.create_issue(
            title=title,
            description=description,
            urgency=Urgency(urgency_value),
            author=name,
            author_role=author_role,
            assignee=final_assignee,
            category_l1=cat_l1,
            category_l2=cat_l2,
            category_l3=cat_l3,
            project=proj_value,
        )
    except Exception as exc:  # noqa: BLE001
        st.error(f"등록 실패: {exc}")
        st.stop()

    # 다음 등록을 위해 직전 담당자 기억 (final_assignee 가 None 이면 그대로 유지)
    if final_assignee:
        st.session_state["_last_assignee"] = final_assignee

    # 직전 프로젝트도 기억 — None 이면 기존 값 유지 (담당자와 동일 패턴)
    if proj_value:
        st.session_state["_current_project"] = proj_value

    # 2) 이미지 첨부 — 실패해도 이슈 자체는 살린다 (개별 메시지)
    image_errors: list[str] = []

    if paste_image is not None:
        try:
            repository.add_image_from_pil(
                issue.id, paste_image, "pasted.png", name
            )
        except Exception as exc:  # noqa: BLE001
            image_errors.append(f"클립보드 이미지 실패: {exc}")

    for f in preview_files:
        try:
            data = bytes(f.getbuffer())
            repository.add_image_from_bytes(issue.id, data, f.name, name)
        except Exception as exc:  # noqa: BLE001
            image_errors.append(f"{f.name} 첨부 실패: {exc}")

    if image_errors:
        for msg in image_errors:
            st.warning(msg)

    # 3) 성공 토스트 + 폼 초기화 + 상세보기 이동
    st.toast("등록되었습니다", icon="✅")
    # 디코드된 paste 이미지 캐시 제거 — 다음 폼에 재첨부되지 않도록.
    st.session_state.pop(f"_decoded_paste_image_{nonce}", None)
    st.session_state["new_form_nonce"] = nonce + 1
    # st.switch_page 가 query_params 를 유실하는 케이스가 있어
    # session_state 로도 함께 전달 (상세보기에서 둘 다 체크).
    st.session_state["_detail_item_id"] = issue.id
    st.query_params["id"] = issue.id
    st.switch_page("pages/3_상세보기.py")
