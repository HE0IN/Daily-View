"""Daily View core domain layer.

UI에서 직접 디스크를 다루지 않고, 모든 I/O는 이 패키지를 통한다.
파일 기반 저장이 SQLite로 마이그레이션되어도 UI 코드는 변경되지 않도록
``repository`` 인터페이스를 단일 진입점으로 둔다.
"""
