import streamlit as st
import streamlit_authenticator as stauth
import datetime
import pandas as pd
from sqlalchemy import text

# ============================================================
# 페이지 설정
# ============================================================
st.set_page_config(page_title="나만의 스케줄 관리 앱", page_icon="📅", layout="centered")

# ============================================================
# Supabase(Postgres) 연결
# .streamlit/secrets.toml 의 [connections.supabase_db] 설정을 사용합니다.
# ============================================================
conn = st.connection("supabase_db", type="sql")


# ============================================================
# 사용자 인증 정보를 Supabase users 테이블에서 불러오기
# (streamlit-authenticator가 요구하는 {"usernames": {...}} 형태로 변환)
# ============================================================
def load_credentials():
    df = conn.query("SELECT username, name, email, password FROM users;", ttl=0)
    credentials = {"usernames": {}}
    for _, row in df.iterrows():
        credentials["usernames"][row["username"]] = {
            "name": row["name"],
            "email": row["email"],
            "password": row["password"],  # Supabase에는 이미 해시된 값이 저장됨
        }
    return credentials


# 세션 동안 한 번만 Supabase에서 계정 정보를 불러옴
if "credentials" not in st.session_state:
    st.session_state["credentials"] = load_credentials()

authenticator = stauth.Authenticate(
    st.session_state["credentials"],
    cookie_name="schedule_app_cookie",
    cookie_key=st.secrets["auth"]["cookie_key"],
    cookie_expiry_days=7,
)

# ============================================================
# 로그인 (혼자만 사용 — 회원가입 없이 미리 등록된 계정으로만 로그인)
# ============================================================
if not st.session_state.get("authentication_status"):
    st.title("📅 나만의 스케줄 관리 앱")

    authenticator.login(location="main")

    if st.session_state.get("authentication_status") is False:
        st.error("아이디 또는 비밀번호가 올바르지 않습니다.")
    elif st.session_state.get("authentication_status") is None:
        st.info("로그인 정보를 입력해 주세요.")

    st.stop()

# ============================================================
# 로그인 성공 이후 화면
# ============================================================
username = st.session_state["username"]
name = st.session_state["name"]

with st.sidebar:
    st.write(f"👋 반갑습니다, **{name}**님")
    authenticator.logout("로그아웃", "sidebar")
    st.divider()
    st.header("메뉴")
    menu = st.selectbox("이동할 화면", ["스케줄 홈", "통계/분석"])

st.title("📅 나만의 스케줄 관리 앱")


# ============================================================
# 사용자별 데이터 처리 함수 (user_id 기준으로 완전히 격리됨)
# ============================================================
def get_user_id(username: str) -> int:
    df = conn.query("SELECT id FROM users WHERE username = :u;", params={"u": username}, ttl=0)
    return int(df.iloc[0]["id"])


def save_schedule(user_id: int, title: str, date, time):
    with conn.session as s:
        s.execute(
            text(
                "INSERT INTO schedules (user_id, title, date, time) "
                "VALUES (:uid, :title, :date, :time);"
            ),
            {"uid": user_id, "title": title, "date": date, "time": time},
        )
        s.commit()


def load_schedules(user_id: int) -> pd.DataFrame:
    return conn.query(
        "SELECT id, title, date, time FROM schedules WHERE user_id = :uid ORDER BY date, time;",
        params={"uid": user_id},
        ttl=0,  # 캐시하지 않고 매번 최신 데이터를 조회 → 실시간 반영
    )


def delete_schedule(schedule_id: int):
    with conn.session as s:
        s.execute(text("DELETE FROM schedules WHERE id = :id;"), {"id": schedule_id})
        s.commit()


user_id = get_user_id(username)

# ============================================================
# 화면 1: 스케줄 홈
# ============================================================
if menu == "스케줄 홈":
    st.subheader("새 일정 추가하기")

    title = st.text_input("일정 제목", placeholder="예: 미드텀 시험 공부")
    date = st.date_input("날짜", datetime.date.today())
    time = st.time_input("시간", datetime.time(12, 0))

    if st.button("일정 저장하기"):
        if title:
            save_schedule(user_id, title, date, time)
            st.success(f"✅ 등록 완료: [{title}]이(가) {date} {time}으로 저장되었습니다!")
            st.rerun()
        else:
            st.warning("⚠️ 일정 제목을 입력해 주세요.")

    st.divider()
    st.subheader("내 일정 목록")

    schedules_df = load_schedules(user_id)

    if schedules_df.empty:
        st.info("아직 등록된 일정이 없습니다.")
    else:
        for _, row in schedules_df.iterrows():
            col1, col2 = st.columns([5, 1])
            with col1:
                st.write(f"📌 **{row['title']}** — {row['date']} {row['time']}")
            with col2:
                if st.button("삭제", key=f"del_{row['id']}"):
                    delete_schedule(row["id"])
                    st.rerun()

# ============================================================
# 화면 2: 통계/분석
# ============================================================
elif menu == "통계/분석":
    st.subheader("📊 나의 일정 통계")

    schedules_df = load_schedules(user_id)

    if schedules_df.empty:
        st.info("분석할 데이터가 없습니다. 먼저 일정을 등록해 주세요.")
    else:
        schedules_df["date"] = pd.to_datetime(schedules_df["date"])
        monthly = schedules_df.groupby(schedules_df["date"].dt.to_period("M")).size()
        monthly.index = monthly.index.astype(str)

        st.bar_chart(monthly)
        st.metric("총 등록 일정 수", len(schedules_df))
