import streamlit as st

from common import require_login, sidebar_user_info

# ============================================================
# 페이지 설정
# ============================================================
st.set_page_config(page_title="나만의 학습 관리 허브", page_icon="🎓", layout="wide")

# ============================================================
# 로그인
# ============================================================
user_id, name, authenticator = require_login()

with st.sidebar:
    sidebar_user_info(name, authenticator)

# ============================================================
# 홈 화면
# ============================================================
col1, col2, col3 = st.columns([1, 1, 1])
with col2:
    st.image("images/logo.png", use_container_width=True)

st.markdown(
    "<h1 style='text-align:center;margin-top:0;'>나만의 학습 관리 허브</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "<p style='text-align:center;color:#666;font-size:17px;max-width:640px;margin:0 auto;'>"
    "공부 시간 기록부터 일정 관리, 강의 수강 현황, 졸업 학점 관리까지 — "
    "학업에 필요한 모든 걸 한 곳에서 관리할 수 있는 개인 학습 관리 앱입니다."
    "</p>",
    unsafe_allow_html=True,
)

st.markdown("<br>", unsafe_allow_html=True)
st.divider()

st.markdown(f"### 👋 반갑습니다, {name}님")
st.info("왼쪽 사이드바에서 원하는 메뉴를 선택해 주세요: **공부 시간 기록 · 일정 관리 · 강의 수강 현황 · 학점 관리**")

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown("**📖 공부 시간 기록**")
    st.caption("10분 단위로 공부 시간을 기록하고, 월별 통계를 확인하세요.")
with c2:
    st.markdown("**🗓️ 일정 관리**")
    st.caption("할 일을 캘린더에 배치하고 완성율을 추적하세요.")
with c3:
    st.markdown("**🎓 강의 수강 현황**")
    st.caption("과목별 강의 수강 현황과 마감 기한을 관리하세요.")
with c4:
    st.markdown("**🎓 학점 관리**")
    st.caption("졸업 학점과 GPA를 카테고리별로 관리하세요.")
