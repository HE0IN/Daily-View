"""재사용 카드/배지/카운트 컴포넌트.

docs/03_ui_design.md 3.4(요청 목록 카드) + 3.5(상세 페이지) 참고.
HTML은 모두 ``unsafe_allow_html=True`` 로 렌더되는 것을 전제로 한다.
"""

from __future__ import annotations

import base64
import html
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from ui.theme import (
    STATUS_COLORS,
    STATUS_LABELS,
    URGENCY_COLORS,
    status_badge_html,
    urgency_badge_html,
)


# ---------------------------------------------------------------------------
# 카드 썸네일: 1:1 cover 로 통일하기 위한 base64 data URL 변환
# ---------------------------------------------------------------------------


@st.cache_data(ttl=600, show_spinner=False)
def _thumb_data_url(thumb_path: str) -> str | None:
    """절대 경로의 이미지를 data URL 로 인코딩. 같은 경로는 캐시(10 분).

    실패 시 None 반환. 카드에서 ``<img src="...">`` 로 직접 넣어
    1:1 aspect-ratio + object-fit:cover 적용 → 모든 카드 썸네일 동일 크기.
    """
    try:
        p = Path(thumb_path)
        if not p.exists():
            return None
        ext = p.suffix.lower().lstrip(".")
        if ext == "jpg":
            ext = "jpeg"
        if ext not in {"png", "jpeg", "gif", "webp"}:
            ext = "png"
        with open(p, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        return f"data:image/{ext};base64,{data}"
    except Exception:
        return None


def render_badge(text: str, color: str) -> str:
    """간단한 색상 배지 span HTML."""
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
        f'background:{color};color:#fff;font-size:0.85em;font-weight:600;">'
        f"{text}</span>"
    )


def humanize_dt(dt_str: str | datetime) -> str:
    """상대 시간 한국어 표기. core.clock.humanize 의 wrapper.

    core 미설치/오류 시 ISO 문자열 또는 strftime fallback.
    """
    try:
        from core.clock import from_iso, humanize  # type: ignore[import-not-found]

        dt = from_iso(dt_str) if isinstance(dt_str, str) else dt_str
        return humanize(dt)
    except Exception:
        if isinstance(dt_str, datetime):
            return dt_str.strftime("%Y-%m-%d %H:%M")
        return str(dt_str)


def _stripe_html(color: str) -> str:
    """카드 좌측 색상 띠 (긴급도 색)."""
    return (
        f'<div style="position:absolute;left:0;top:0;bottom:0;'
        f'width:4px;background:{color};border-radius:4px 0 0 4px;"></div>'
    )


def _placeholder_html(text: str = "썸네일 없음") -> str:
    """썸네일 placeholder."""
    return (
        f'<div style="width:100%;aspect-ratio:1/1;background:#E5E7EB;'
        f'border-radius:4px;display:flex;align-items:center;justify-content:center;'
        f'color:#9CA3AF;font-size:0.7em;text-align:center;">{text}</div>'
    )


def render_card(
    item: dict[str, Any],
    *,
    key_prefix: str = "card",
    extra_buttons: list[tuple[str, str]] | None = None,
    checkbox: tuple[str, str] | None = None,
    buttons_inline: bool = False,
    top_badge_html: str | None = None,
) -> bool | dict:
    """요청목록 카드 렌더 (컴팩트).

    item은 IndexEntry 직렬화 dict. 누락 키는 안전 기본값 사용.

    옵션:
      - extra_buttons: [(라벨, 액션키), ...] — '열기' 아래 카드 안에 버튼 추가.
      - checkbox: (라벨, 위젯키) — '열기' 옆에 선택 체크박스 추가.
      - top_badge_html: 헤더줄(긴급도·상태 배지 옆)에 끼울 추가 배지 HTML
        (예: 성격 라벨 배지). None 이면 없음.

    반환:
      - 옵션이 없으면 bool ('열기' 클릭 여부, 기존 호환).
      - 옵션이 있으면 dict: {"open": bool, "checked": bool, "actions": {액션키: bool}}.

    레이아웃 (A 패턴): 좌측 작은 썸네일 (1) + 우측 정보 (2) 가로 분할.
    컴팩트 유지: 폰트/패딩 축소, 한 줄에 등록·담당·상태 모두 표시.
    썸네일은 ``thumb_path`` 가 있으면 사용, 없고 ``images_count > 0`` 이면
    placeholder, 0 이면 "사진 없음" 박스.
    """
    item_id = item.get("id", "")
    title = item.get("title", "(제목 없음)")
    urgency = item.get("urgency", "normal")
    status = item.get("status", "assignee_request")
    author = item.get("author", "-")
    assignee = item.get("assignee") or "-"
    created_at = item.get("created_at", "")
    # 등록 절대 날짜 (ISO 앞 10자 = YYYY-MM-DD). 카드에 상대시간과 함께 표기.
    created_date = str(created_at)[:10] if created_at else ""
    comments_count = int(item.get("comments_count", 0) or 0)
    images_count = int(item.get("images_count", 0) or 0)

    # 썸네일 절대 경로 변환: first_image_thumb (item_dir 기준 상대) → 절대.
    # 옛 인덱스 호환을 위해 thumb_path 키도 fallback 으로 받음.
    thumb_path: str | None = item.get("thumb_path")
    thumb_rel = item.get("first_image_thumb")
    if not thumb_path and thumb_rel and item_id:
        try:
            from core import paths as _paths  # 지연 import (테스트 격리)

            thumb_path = str(_paths.item_dir(item_id) / Path(thumb_rel))
        except Exception:
            thumb_path = None

    # XSS 방지: HTML로 렌더되는 사용자 입력은 모두 escape.
    safe_title = html.escape(str(title))
    safe_author = html.escape(str(author))
    safe_assignee = html.escape(str(assignee))
    safe_desc = html.escape(str(item.get("description_preview") or ""))

    # 카드 좌측 색상 띠 — 긴급도 색
    stripe_color = URGENCY_COLORS.get(urgency, "#9CA3AF")
    stripe_w = 3

    # height 인자 제거: 고정 220px 는 짧은 카드는 빈 공간, 긴 카드는 스크롤이
    # 생기는 문제 — 같은 행에서 가장 긴 카드의 자연스러운 높이로 통일하기 위해
    # 높이는 콘텐츠가 결정. 같은 행의 카드들이 동일 높이로 stretch 되도록
    # 페이지 측 (app.py / pages/1) 에서 _grid_stretch_css() 를 1 회 주입한다.
    with st.container(border=True):
        # 좌측 작은 썸네일 + 우측 정보 (1:2 가로 분할)
        thumb_col, info_col = st.columns([1, 2], gap="small")

        with thumb_col:
            # 썸네일은 1:1 정사각형 + object-fit:cover 로 강제 통일.
            # st.image 는 이미지 원본 비율로 세로가 달라져 카드마다 좌측 높이가
            # 달라짐 → 카드 전체 높이도 따라서 달라짐. 이 문제를 base64 data URL
            # + 명시적 aspect-ratio + object-fit:cover 로 해결.
            data_url: str | None = None
            if thumb_path:
                data_url = _thumb_data_url(thumb_path)
            if data_url:
                st.markdown(
                    f'<div style="width:100%;aspect-ratio:1/1;'
                    f"border-radius:4px;overflow:hidden;background:#E5E7EB;"
                    f'">'
                    f'<img src="{data_url}" '
                    f'style="width:100%;height:100%;object-fit:cover;'
                    f'display:block;" />'
                    f"</div>",
                    unsafe_allow_html=True,
                )
            elif images_count > 0:
                st.markdown(_placeholder_html(), unsafe_allow_html=True)
            else:
                st.markdown(
                    _placeholder_html("사진 없음"),
                    unsafe_allow_html=True,
                )

        with info_col:
            # 좌측 색상 띠 + 1줄 헤더(긴급도 배지 + 상태 배지 + 시간)
            st.markdown(
                f'<div style="position:relative;padding:2px 0 2px 10px;">'
                f'<div style="position:absolute;left:0;top:0;bottom:0;width:{stripe_w}px;'
                f'background:{stripe_color};border-radius:2px;"></div>'
                f"{urgency_badge_html(urgency)} {status_badge_html(status)} "
                f"{top_badge_html or ''} "
                f'<span style="color:#9CA3AF;font-size:0.75em;float:right;">'
                f"{humanize_dt(created_at) if created_at else ''}"
                f"</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

            # 제목 — 1 줄 line-clamp 로 고정 높이 (긴 제목도 ... 으로 잘라서
            # 카드마다 같은 줄 수 보장).
            st.markdown(
                f'<div style="font-weight:600;font-size:0.95em;line-height:1.3;'
                f"margin:4px 0 2px 0;display:-webkit-box;-webkit-line-clamp:1;"
                f"-webkit-box-orient:vertical;overflow:hidden;text-overflow:ellipsis;"
                f'word-break:break-all;">{safe_title}</div>',
                unsafe_allow_html=True,
            )

            # 한 줄 메타: 등록 · 담당 · 코멘트 N · 이미지 N — 한 줄로 강제 (nowrap).
            st.markdown(
                f'<div style="font-size:0.75em;color:#6B7280;line-height:1.4;'
                f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
                f"{safe_author} → {safe_assignee} · 📅 {created_date} · 💬 {comments_count} · 📷 {images_count}"
                f"</div>",
                unsafe_allow_html=True,
            )

            # 설명 미리보기 — 항상 2 줄 자리 차지 (있으면 line-clamp, 없으면 spacer).
            # 결과: 모든 카드의 우측 정보 영역이 동일 줄 수 → 동일 높이.
            if safe_desc:
                st.markdown(
                    f'<div style="font-size:0.8em;color:#475569;line-height:1.4;'
                    f"margin-top:4px;display:-webkit-box;-webkit-line-clamp:2;"
                    f"-webkit-box-orient:vertical;overflow:hidden;text-overflow:ellipsis;"
                    f'min-height:2.8em;">{safe_desc}</div>',
                    unsafe_allow_html=True,
                )
            else:
                # 빈 설명도 같은 높이 차지 (2.8em ≈ line-height 1.4 × 2 줄)
                st.markdown(
                    '<div style="margin-top:4px;min-height:2.8em;"></div>',
                    unsafe_allow_html=True,
                )

        _checked = False
        _actions: dict[str, bool] = {}
        # (4번) buttons_inline: '열기' + extra_buttons 를 한 행에 (폭 좁은 3열 등).
        if buttons_inline and extra_buttons and checkbox is None:
            _bcols = st.columns(1 + len(extra_buttons))
            with _bcols[0]:
                clicked = st.button(
                    "열기", key=f"{key_prefix}_{item_id}_detail", width="stretch"
                )
            for _i, (_lbl, _akey) in enumerate(extra_buttons, start=1):
                with _bcols[_i]:
                    _actions[_akey] = st.button(
                        _lbl,
                        key=f"{key_prefix}_{item_id}_{_akey}",
                        width="stretch",
                    )
        else:
            # (3번) 선택 체크박스 — 있으면 '열기' 옆에 함께 배치.
            if checkbox is not None:
                _cb_label, _cb_key = checkbox
                _cbc, _opc = st.columns([1, 3])
                with _cbc:
                    _checked = st.checkbox(
                        _cb_label, key=_cb_key, label_visibility="collapsed"
                    )
                with _opc:
                    clicked = st.button(
                        "열기",
                        key=f"{key_prefix}_{item_id}_detail",
                        width="stretch",
                    )
            else:
                clicked = st.button(
                    "열기",
                    key=f"{key_prefix}_{item_id}_detail",
                    width="stretch",
                )
            # (2번) 추가 버튼 — 카드 안, '열기' 아래(세로).
            if extra_buttons:
                for _lbl, _akey in extra_buttons:
                    _actions[_akey] = st.button(
                        _lbl,
                        key=f"{key_prefix}_{item_id}_{_akey}",
                        width="stretch",
                    )

    if extra_buttons is None and checkbox is None:
        return clicked
    return {"open": clicked, "checked": _checked, "actions": _actions}


# ---------------------------------------------------------------------------
# CSS 헬퍼 — 페이지 1 회 주입으로 같은 행 카드들이 같은 높이로 stretch 되게
# ---------------------------------------------------------------------------


def render_card_grid_css() -> None:
    """카드 그리드를 그리는 페이지에서 1 회 호출.

    같은 행 카드들이 가장 긴 카드 높이로 stretch 되도록 두 단계로 보강:

    1) **CSS flex stretch** — Streamlit columns DOM 의 모든 중간 div 를
       flex column 으로 만들고 height:100% / flex:1 적용.
    2) **JS ResizeObserver fallback** — CSS 가 Streamlit DOM 깊이를 따라
       잡지 못하는 경우를 대비, JS 가 같은 행 카드들의 offsetHeight 를 측정
       해 max 로 통일. ResizeObserver 로 콘텐츠 크기 변동에 자동 재계산.

    fragile 한 selector 들은 본 함수 한 곳에 모아둠. Streamlit 버전이
    바뀌어 selector 가 깨지면 여기만 수정.
    """
    st.markdown(
        """
        <style>
        /* 같은 행의 columns 가 stretch (가장 긴 카드 높이에 맞춤) */
        div[data-testid="stHorizontalBlock"] {
            align-items: stretch !important;
        }
        /* 컬럼 자체 + 안쪽 모든 div 를 height:100% 로 채우게 */
        div[data-testid="stHorizontalBlock"] > div[data-testid="column"],
        div[data-testid="stHorizontalBlock"] > div[data-testid="column"] > div,
        div[data-testid="stHorizontalBlock"] > div[data-testid="column"] > div > div {
            height: 100% !important;
            display: flex;
            flex-direction: column;
        }
        /* st.container(border=True) 의 wrapper 도 flex column */
        div[data-testid="stHorizontalBlock"]
            div[data-testid="stVerticalBlockBorderWrapper"] {
            flex: 1 1 auto !important;
            height: 100% !important;
            display: flex;
            flex-direction: column;
        }
        div[data-testid="stHorizontalBlock"]
            div[data-testid="stVerticalBlockBorderWrapper"] > div {
            flex: 1 1 auto;
            display: flex;
            flex-direction: column;
        }
        </style>

        <script>
        (function() {
            // CSS 만으로 stretch 가 안 잡히는 케이스 대비. 같은 행 카드
            // (stVerticalBlockBorderWrapper) 의 max offsetHeight 로 통일.
            // ResizeObserver 로 이미지 로드/콘텐츠 변동 감지 → 재계산.
            function equalize() {
                const rows = document.querySelectorAll(
                    'div[data-testid="stHorizontalBlock"]'
                );
                rows.forEach(function(row) {
                    const cards = row.querySelectorAll(
                        'div[data-testid="stVerticalBlockBorderWrapper"]'
                    );
                    if (cards.length < 2) return;
                    cards.forEach(function(c) { c.style.minHeight = ''; });
                    let maxH = 0;
                    cards.forEach(function(c) {
                        if (c.offsetHeight > maxH) maxH = c.offsetHeight;
                    });
                    if (maxH > 0) {
                        cards.forEach(function(c) {
                            c.style.minHeight = maxH + 'px';
                        });
                    }
                });
            }
            // 초기 + 지연 + 변동 감지 — Streamlit rerun 시 DOM 재구성에도
            // 안전하게 다시 측정.
            equalize();
            setTimeout(equalize, 100);
            setTimeout(equalize, 400);
            setTimeout(equalize, 1000);
            try {
                const ro = new ResizeObserver(function() { equalize(); });
                ro.observe(document.body);
            } catch (e) { /* 구형 브라우저 fallback */ }
            window.addEventListener('load', equalize);
        })();
        </script>
        """,
        unsafe_allow_html=True,
    )


def render_count_metric(
    label: str, count: int, color: str | None = None
) -> None:
    """대시보드용 숫자 카드. color가 있으면 좌측 띠로 색상 표시."""
    if color:
        st.markdown(
            f'<div style="position:relative;padding:8px 12px 8px 16px;'
            f'border-radius:6px;border:1px solid #E5E7EB;">'
            f'<div style="position:absolute;left:0;top:0;bottom:0;width:4px;'
            f'background:{color};border-radius:6px 0 0 6px;"></div>'
            f'<div style="font-size:0.8em;color:#6B7280;">{label}</div>'
            f'<div style="font-size:1.5em;font-weight:700;color:#111827;">{count}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        st.metric(label=label, value=count)



# ---------------------------------------------------------------------------
# 이미지 → 클립보드 복사 (HTTP+IP 환경 대응)
# ---------------------------------------------------------------------------

# 사내는 http://<사내IP>:8501 로 접속한다 = Secure Context 가 아니라서
# ``navigator.clipboard.write`` 를 쓸 수 없다 (components/paste_clipboard 가
# 붙여넣기에서 같은 이유로 paste 이벤트를 쓴 것과 동일한 제약).
# 그래서 두 경로를 순서대로 시도한다:
#   1) navigator.clipboard.write  — https / localhost (호스트 PC) 에서 동작.
#      진짜 image/png 로 들어가므로 그림판 등 어디든 붙는다.
#   2) contenteditable + document.execCommand("copy")  — Secure Context 무관.
#      선택 영역을 복사하는 옛 방식이라 HTTP+IP 에서도 된다. Word/메일/Teams
#      처럼 HTML 붙여넣기를 지원하는 곳에 붙는다.
_COPY_IMAGE_HTML = """
<!DOCTYPE html><html><head><meta charset="utf-8"><style>
  html,body{margin:0;padding:0;background:transparent;
    font-family:system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans KR",sans-serif;}
  #btn{width:100%;padding:9px 12px;border:1px solid #0071DB;border-radius:8px;
    background:#0071DB;color:#fff;font-size:14px;font-weight:600;cursor:pointer;}
  #btn:hover{background:#0061BD;border-color:#0061BD;}
  #btn:disabled{opacity:.6;cursor:default;}
  #status{margin-top:8px;font-size:12.5px;line-height:1.5;color:#475569;min-height:19px;}
  #status.ok{color:#15803D;font-weight:600;}
  #status.err{color:#B91C1C;}
  #holder{position:fixed;left:-99999px;top:0;}
</style></head><body>
  <button id="btn" type="button">__LABEL__</button>
  <div id="status">__HINT__</div>
  <div id="holder"><img id="src" alt=""></div>
<script>
(function () {
  var btn = document.getElementById("btn");
  var status = document.getElementById("status");
  var img = document.getElementById("src");
  var DATA_URL = "__DATA_URL__";
  var FILENAME = "__FILENAME__";
  img.src = DATA_URL;

  function say(msg, cls) { status.textContent = msg; status.className = cls || ""; }

  // --- 경로 1: copy 이벤트 + setData (HTTP 에서도 동작) --------------------
  // 클립보드에 무엇을 넣을지 직접 지정한다. 이미지 바이너리는 setData 로 넣을
  // 수 없지만(브라우저 제약), data URL 을 품은 <img> HTML 은 넣을 수 있고
  // 워드·메일·Teams·데일리뷰 붙여넣기 칸이 모두 이걸 읽는다.
  function copyViaEvent() {
    var wrote = false;
    function onCopy(e) {
      try {
        var cd = e.clipboardData;
        cd.setData("text/html", '<img src="' + DATA_URL + '" alt="' + FILENAME + '">');
        cd.setData("text/plain", FILENAME + " (Daily View 이미지)");
        e.preventDefault();
        wrote = true;
      } catch (err) { wrote = false; }
    }
    document.addEventListener("copy", onCopy, true);
    try {
      // execCommand("copy") 는 선택 영역이 있어야 발동한다 — 임시 textarea 사용.
      var ta = document.createElement("textarea");
      ta.value = " ";
      ta.style.cssText = "position:fixed;left:-99999px;top:0;";
      document.body.appendChild(ta);
      ta.select();
      var fired = document.execCommand("copy");
      ta.remove();
      return fired && wrote;
    } catch (err) {
      return false;
    } finally {
      document.removeEventListener("copy", onCopy, true);
    }
  }

  // --- 경로 2: 표준 클립보드 API (https / localhost 전용) ------------------
  // 진짜 image/png 로 들어가므로 그림판 등 어디에나 붙는다.
  function toPngBlob() {
    return new Promise(function (resolve, reject) {
      try {
        var c = document.createElement("canvas");
        c.width = img.naturalWidth; c.height = img.naturalHeight;
        c.getContext("2d").drawImage(img, 0, 0);
        c.toBlob(function (b) { b ? resolve(b) : reject(new Error("toBlob 실패")); }, "image/png");
      } catch (e) { reject(e); }
    });
  }

  function copyAsync() {
    if (!(window.isSecureContext && navigator.clipboard
          && window.ClipboardItem && navigator.clipboard.write)) {
      return Promise.reject(new Error("insecure-context"));
    }
    return toPngBlob().then(function (blob) {
      return navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
    });
  }

  btn.addEventListener("click", function () {
    if (!img.complete || !img.naturalWidth) {
      say("이미지를 아직 읽는 중입니다. 잠시 후 다시 눌러주세요.", "err");
      return;
    }
    btn.disabled = true;
    say("복사 중\u2026");
    // 동기 경로를 먼저 — user activation 이 살아 있을 때만 execCommand 가 허용된다.
    var evOk = copyViaEvent();
    copyAsync().then(function () {
      say("\u2705 복사됐습니다 (표준 방식) \u2014 어디에든 Ctrl+V 로 붙여넣으세요.", "ok");
    }).catch(function () {
      if (evOk) {
        say("\u2705 복사됐습니다 \u2014 다른 항목의 붙여넣기 칸이나 문서\u00b7메일에 "
            + "Ctrl+V. (그림판 등 이미지 편집기에는 [다운로드] 를 쓰세요)", "ok");
      } else {
        say("\u26a0 이 브라우저에서는 복사가 막혀 있습니다. [다운로드] 를 쓰거나 "
            + "이미지에서 오른쪽 클릭 \u2192 [이미지 복사] 를 이용하세요.", "err");
      }
    }).finally(function () { btn.disabled = false; });
  });
})();
</script></body></html>
"""


def render_copy_image_button(
    data_url: str,
    *,
    filename: str = "image",
    label: str = "📋 클립보드로 복사",
    hint: str = "",
    height: int = 92,
) -> None:
    """이미지를 클립보드로 복사하는 버튼(iframe 컴포넌트)을 렌더한다.

    ``data_url`` 은 ``data:image/png;base64,...`` 형태. base64 문자열에는
    ``<`` 가 없어 ``</script>`` 조기 종료 위험이 없으므로 그대로 삽입한다.

    호출 지점은 **모달 등 '필요할 때만 렌더되는 곳'** 이어야 한다 — 원본
    바이트가 그대로 프론트로 실려가므로, 상세보기처럼 사진이 여러 장 있는
    화면에 항상 깔아두면 rerun 마다 전부 재전송된다.
    """
    import streamlit.components.v1 as _st_components

    body = (
        _COPY_IMAGE_HTML
        .replace("__DATA_URL__", data_url)
        .replace("__FILENAME__", html.escape(filename, quote=True))
        .replace("__LABEL__", html.escape(label))
        .replace("__HINT__", html.escape(hint))
    )
    _st_components.html(body, height=height)


# 상태/긴급도 라벨도 외부에서 재사용 가능하도록 노출
__all__ = [
    "render_card",
    "render_card_grid_css",
    "render_badge",
    "render_count_metric",
    "humanize_dt",
    "render_copy_image_button",
    "STATUS_LABELS",
    "STATUS_COLORS",
]
