"""HTTP+IP 호환 클립보드 paste 컴포넌트 (정식 declare_component).

기존 streamlit-paste-button (navigator.clipboard.read, Secure Context 필요)
대신 paste 이벤트 (Secure Context 무관) 를 사용해 HTTP+IP 환경에서도 동작.

Python 에서 호출:
    from components.paste_clipboard import paste_clipboard

    result = paste_clipboard(key="my_paste")  # base64 dataURL 또는 None

    if result:
        # data:image/png;base64,iVBOR... 형태
        ...
"""

from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_BUILD_DIR = Path(__file__).parent / "frontend"

# declare_component — path 의 index.html 을 iframe 으로 띄움.
_paste_component = components.declare_component(
    "paste_clipboard",
    path=str(_BUILD_DIR),
)


def paste_clipboard(
    *,
    key: str | None = None,
    label: str = "여기를 클릭하고 Ctrl+V 로 이미지 붙여넣기",
    height: int = 200,
) -> str | None:
    """클립보드 paste 컴포넌트.

    반환값: 마지막으로 paste 된 이미지의 dataURL (data:image/png;base64,...).
            없으면 None.
    Streamlit 패턴상 같은 컴포넌트가 rerun 마다 같은 값을 다시 반환하므로
    호출자는 별도 nonce 또는 session_state 로 "이미 처리한 dataURL" 을 추적해
    중복 처리를 방지해야 한다.
    """
    return _paste_component(label=label, height=height, key=key, default=None)


__all__ = ["paste_clipboard"]
