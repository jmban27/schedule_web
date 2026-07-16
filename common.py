"""
5개 페이지(홈, 공부 시간 기록, 일정 관리, 강의 수강 현황, 학점 관리)가
공통으로 사용하는 DB 연결 / 로그인 / 헬퍼 함수 모음입니다.
각 페이지 파일 맨 위에서 이 모듈을 import해서 사용합니다.
"""

import pandas as pd
import streamlit as st
import streamlit_authenticator as stauth
from sqlalchemy import text

# ============================================================
# Supabase(Postgres) 연결
# ============================================================
conn = st.connection("supabase_db", type="sql")


def run_query(query: str, params: dict | None = None, ttl: int = 0) -> pd.DataFrame:
    return conn.query(query, params=params or {}, ttl=ttl)


def run_write(query: str, params: dict | None = None):
    with conn.session as s:
        s.execute(text(query), params or {})
        s.commit()


def run_write_returning_id(query: str, params: dict | None = None) -> int:
    """INSERT ... RETURNING id 전용. 커밋까지 확실히 처리하고 새로 생긴 id를 반환합니다."""
    with conn.session as s:
        result = s.execute(text(query), params or {})
        new_id = result.scalar()
        s.commit()
    return int(new_id)


# ============================================================
# 세션 캐시 (같은 세션 안에서는 DB를 매번 다시 조회하지 않도록)
# - 쓰기(추가/수정/삭제)는 여전히 즉시 DB에 반영되어 안전합니다.
# - 대신 메모리 상의 캐시도 같이 업데이트해서, DB를 다시 읽어오는
#   왕복을 없애고 화면이 훨씬 빠르게 반응하도록 합니다.
# ============================================================
def _cache_store() -> dict:
    return st.session_state.setdefault("_cache", {})


def cached_query(key: str, query: str, params: dict | None = None) -> pd.DataFrame:
    """캐시에 있으면 그대로 반환, 없으면 DB에서 가져와 캐시에 저장 후 반환."""
    store = _cache_store()
    if key not in store:
        store[key] = run_query(query, params)
    return store[key]


def get_cache(key: str) -> pd.DataFrame | None:
    return _cache_store().get(key)


def set_cache(key: str, df: pd.DataFrame):
    _cache_store()[key] = df


def invalidate_cache(key: str):
    _cache_store().pop(key, None)


def cache_append_row(key: str, row: dict):
    store = _cache_store()
    new_row_df = pd.DataFrame([row])
    if key in store and not store[key].empty:
        store[key] = pd.concat([store[key], new_row_df], ignore_index=True)
    else:
        store[key] = new_row_df


def cache_update_row(key: str, id_col: str, id_value, updates: dict):
    store = _cache_store()
    df = store.get(key)
    if df is not None and not df.empty:
        mask = df[id_col] == id_value
        for col, val in updates.items():
            df.loc[mask, col] = val


def cache_delete_row(key: str, id_col: str, id_value):
    store = _cache_store()
    df = store.get(key)
    if df is not None and not df.empty:
        store[key] = df[df[id_col] != id_value].reset_index(drop=True)


def cache_delete_rows(key: str, id_col: str, id_values):
    store = _cache_store()
    df = store.get(key)
    if df is not None and not df.empty:
        store[key] = df[~df[id_col].isin(list(id_values))].reset_index(drop=True)


# ============================================================
# 로그인
# ============================================================
def load_credentials():
    df = run_query("SELECT username, name, email, password FROM users;")
    credentials = {"usernames": {}}
    for _, row in df.iterrows():
        credentials["usernames"][row["username"]] = {
            "name": row["name"],
            "email": row["email"],
            "password": row["password"],
        }
    return credentials


def get_user_id(username: str) -> int:
    df = run_query("SELECT id FROM users WHERE username = :u;", {"u": username})
    return int(df.iloc[0]["id"])


def require_login():
    """모든 페이지 맨 위에서 호출. 로그인 안 되어 있으면 로그인 폼을 보여주고 멈춥니다.
    반환값: (user_id, name, authenticator)
    """
    try:
        if "credentials" not in st.session_state:
            st.session_state["credentials"] = load_credentials()
    except Exception:
        st.error("⚠️ 데이터베이스 연결에 실패했습니다. 잠시 후 다시 시도해 주세요.")
        st.stop()

    authenticator = stauth.Authenticate(
        st.session_state["credentials"],
        cookie_name="study_app_cookie",
        cookie_key=st.secrets["auth"]["cookie_key"],
        cookie_expiry_days=7,
    )

    if not st.session_state.get("authentication_status"):
        st.title("📚 나만의 학습 관리 허브")
        authenticator.login(location="main")

        if st.session_state.get("authentication_status") is False:
            st.error("아이디 또는 비밀번호가 올바르지 않습니다.")
        elif st.session_state.get("authentication_status") is None:
            st.info("로그인 정보를 입력해 주세요.")
        st.stop()

    username = st.session_state["username"]
    name = st.session_state["name"]
    user_id = get_user_id(username)
    return user_id, name, authenticator


def sidebar_user_info(name: str, authenticator):
    st.write(f"👋 반갑습니다, **{name}**님")
    authenticator.logout("로그아웃", "sidebar")


# ============================================================
# 공통: 과목(subjects) — 공부 시간 기록 / 일정 관리 / 강의 수강 현황에서 함께 사용
# ============================================================
def get_subjects(user_id: int) -> pd.DataFrame:
    return cached_query(
        f"subjects_{user_id}",
        "SELECT id, name, color FROM subjects WHERE user_id = :uid ORDER BY name;",
        {"uid": user_id},
    )


# ============================================================
# 공통: 기한 지난 강의 — 일정 관리 / 강의 수강 현황에서 함께 사용
# ============================================================
def get_overdue_lectures(user_id: int) -> pd.DataFrame:
    return run_query(
        "SELECT l.title, l.due_date, s.name AS subject_name FROM lectures l "
        "JOIN subjects s ON l.subject_id = s.id "
        "WHERE l.user_id = :uid AND l.is_completed = false AND l.due_date IS NOT NULL "
        "AND l.due_date <= CURRENT_DATE ORDER BY l.due_date;",
        {"uid": user_id},
    )


# ============================================================
# 공통: 캘린더 일정 추가 — 일정 관리 / 강의 수강 현황(마감일 자동 연동)에서 함께 사용
# 이벤트는 유저별로 전체를 한 번에 캐싱해두고(날짜 필터는 각 페이지에서 메모리로 처리),
# 새 일정이 생기면 그 캐시에도 즉시 추가합니다.
# ============================================================
def add_event(user_id, category, subject_id, title, event_date, start_time, end_time, memo, lecture_id=None):
    new_id = run_write_returning_id(
        "INSERT INTO events (user_id, category, subject_id, lecture_id, title, event_date, "
        "start_time, end_time, memo) VALUES (:uid, :cat, :sid, :lid, :title, :d, :st, :et, :memo) "
        "RETURNING id;",
        {
            "uid": user_id, "cat": category, "sid": subject_id, "lid": lecture_id, "title": title,
            "d": event_date, "st": start_time, "et": end_time, "memo": memo,
        },
    )
    subject_name = None
    if subject_id:
        subjects_df = get_subjects(user_id)
        match = subjects_df[subjects_df["id"] == subject_id] if not subjects_df.empty else subjects_df
        if not match.empty:
            subject_name = match.iloc[0]["name"]

    cache_append_row(
        f"all_events_{user_id}",
        {
            "id": new_id, "category": category, "subject_id": subject_id, "title": title,
            "event_date": event_date, "start_time": start_time, "end_time": end_time,
            "memo": memo, "is_done": False, "subject_name": subject_name,
        },
    )
    return new_id