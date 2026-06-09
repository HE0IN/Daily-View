"""미구현목록 — 새 프로그램에서 '안 되는 것들'을 캡쳐+메모로 쌓아두는 수집함.

기존 도면 프로그램에선 되던 게 새 프로그램에선 안 되는 항목들을 부담 없이
모아두고, 그중 실제 개발이 필요한 것만 [개발 요청] 으로 새요청등록(prefill)에
넘겨 담당자확인요청으로 승격한다.

- 항목은 kind="unimplemented" 인 Issue (담당자/상태 워크플로우 없음).
- 승격하면 kind 가 dev 로 바뀌며 미구현목록에서 빠지고 개발목록에 나타난다.
"""

from __future__ import annotations

import streamlit as st
from PIL import Image as PILImage  # noqa: F401 (paste 디코드 결과 타입)

from components.paste_clipboard import paste_clipboard
from core import repository
from core.images import decode_image_data_url
from core.models import Role, Urgency

user = st.session_state.get("user")
if not user:
    st.stop()

name: str = user["name"]
current_project: str | None = st.session_state.get("_current_project")

# 비(非)상세 페이지 진입 = 상세보기 편집모드 정리 (stale 방지, 다른 페이지와 동일).
for _ek in list(st.session_state.keys()):
    if str(_ek).startswith("_edit_mode_"):
        st.session_state[_ek] = False

if current_project:
    st.caption(f"{current_project} / 미구현목록")
st.title("미구현목록")
st.caption(
    "새 프로그램에서 '안 되는 것'을 캡쳐+메모로 모아둡니다. "
    "정식 개발이 필요하면 항목의 **[개발 요청]** 으로 승격하세요."
)


# ---------------------------------------------------------------------------
# 등록 폼 — 제목 + 설명 + 캡쳐(붙여넣기/업로드)
# ---------------------------------------------------------------------------

nonce = int(st.session_state.setdefault("unimpl_nonce", 0))

with st.expander("➕ 미구현 항목 추가", expanded=True):
    u_title = st.text_input(
        "제목 (안 되는 현상)",
        key=f"unimpl_title_{nonce}",
        placeholder="예: 기존 도면의 치수 자동표기가 새 프로그램에선 안 됨",
    )
    u_desc = st.text_area(
        "설명 (상황/조건 메모)",
        key=f"unimpl_desc_{nonce}",
        height=80,
    )

    ic1, ic2 = st.columns(2)
    with ic1:
        st.markdown("**파일에서**")
        u_files = st.file_uploader(
            "이미지",
            type=["png", "jpg", "jpeg", "webp", "gif"],
            accept_multiple_files=True,
            key=f"unimpl_files_{nonce}",
            label_visibility="collapsed",
        )
    with ic2:
        st.markdown("**클립보드 (Ctrl+V)** — 여러 번 가능")
        try:
            u_paste = paste_clipboard(key=f"unimpl_paste_{nonce}")
        except Exception as exc:  # pragma: no cover - 컴포넌트 환경 의존
            u_paste = None
            st.caption(f"paste 컴포넌트 오류: {exc}")

    _lk = f"_unimpl_last_paste_{nonce}"
    _pk = f"_unimpl_paste_imgs_{nonce}"
    if u_paste and st.session_state.get(_lk) != u_paste:
        st.session_state[_lk] = u_paste
        try:
            _img, _, _ = decode_image_data_url(u_paste)
            _lst = list(st.session_state.get(_pk, []))
            _lst.append(_img)
            st.session_state[_pk] = _lst
        except Exception as exc:  # noqa: BLE001
            st.error(
                "붙여넣기 이미지를 처리할 수 없습니다. DRM(문서보안)으로 보호된 "
                f"화면·이미지는 붙여넣기가 차단될 수 있습니다. ({exc})"
            )

    u_paste_imgs = list(st.session_state.get(_pk, []))
    if u_paste_imgs:
        if st.button(
            f"클립보드 이미지 비우기 ({len(u_paste_imgs)}장)",
            key=f"unimpl_paste_clear_{nonce}",
        ):
            st.session_state.pop(_pk, None)
            st.session_state.pop(_lk, None)
            st.rerun()

    # 미리보기
    _prev = list(u_files or [])
    _total = len(_prev) + len(u_paste_imgs)
    if _total:
        cols = st.columns(min(_total, 4))
        _i = 0
        for _k, _pi in enumerate(u_paste_imgs, start=1):
            with cols[_i % len(cols)]:
                st.image(_pi, caption=f"클립보드#{_k}", width="stretch")
            _i += 1
        for _f in _prev:
            with cols[_i % len(cols)]:
                st.image(_f, caption=_f.name, width="stretch")
            _i += 1

    if st.button("추가", type="primary", key=f"unimpl_add_{nonce}"):
        if not u_title.strip():
            st.error("제목을 입력해주세요.")
        else:
            try:
                iss = repository.create_issue(
                    title=u_title.strip(),
                    description=u_desc or "",
                    urgency=Urgency.normal,  # 미구현은 긴급도 의미 없음 — 기본값
                    author=name,
                    author_role=Role.reviewer,
                    kind="unimplemented",
                    project=current_project,
                )
                for _k, _pi in enumerate(u_paste_imgs, start=1):
                    try:
                        repository.add_image_from_pil(
                            iss.id, _pi, f"pasted_{_k}.png", name, kind="request"
                        )
                    except Exception:  # noqa: BLE001
                        pass
                for _f in _prev:
                    try:
                        repository.add_image_from_bytes(
                            iss.id, _f.getvalue(), _f.name, name, kind="request"
                        )
                    except Exception:  # noqa: BLE001
                        pass
                st.session_state.pop(_pk, None)
                st.session_state.pop(_lk, None)
                st.session_state["unimpl_nonce"] = nonce + 1
                st.toast("미구현 항목이 추가되었습니다", icon="✅")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"추가 실패: {exc}")


st.divider()


# ---------------------------------------------------------------------------
# 목록 — 미구현 항목 (제목 + 이미지 수 + [열기] / [개발 요청])
# ---------------------------------------------------------------------------

items = repository.list_issues(
    kind="unimplemented",
    project=current_project,
    include_closed=True,
    include_archived=False,
)
st.subheader(f"미구현 항목 ({len(items)})")

if not items:
    st.caption("아직 미구현 항목이 없습니다. 위에서 추가하세요.")
else:
    for entry in items:
        with st.container(border=True):
            c1, c2, c3 = st.columns([6, 1, 1.2])
            with c1:
                st.markdown(f"**{entry.title}**")
                _created = str(entry.created_at)[:16].replace("T", " ")
                st.caption(f"📷 이미지 {entry.images_count}장 · {_created}")
            with c2:
                if st.button("열기", key=f"unimpl_open_{entry.id}", width="stretch"):
                    st.session_state["_detail_item_id"] = entry.id
                    st.session_state["_detail_origin"] = "pages/5_미구현목록.py"
                    st.query_params["id"] = entry.id
                    st.switch_page("pages/3_상세보기.py")
            with c3:
                if st.button(
                    "개발 요청",
                    key=f"unimpl_promote_{entry.id}",
                    type="primary",
                    width="stretch",
                ):
                    # 새요청등록에 승격 모드로 진입 (제목/설명/이미지는 그 항목에서 로드).
                    st.session_state["promote_id"] = entry.id
                    st.switch_page("pages/2_새요청등록.py")
