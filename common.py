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
    return run_query(
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
# ============================================================
def add_event(user_id, category, subject_id, title, event_date, start_time, end_time, memo, lecture_id=None):
    run_write(
        "INSERT INTO events (user_id, category, subject_id, lecture_id, title, event_date, "
        "start_time, end_time, memo) VALUES (:uid, :cat, :sid, :lid, :title, :d, :st, :et, :memo);",
        {
            "uid": user_id, "cat": category, "sid": subject_id, "lid": lecture_id, "title": title,
            "d": event_date, "st": start_time, "et": end_time, "memo": memo,
        },
    )
