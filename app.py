import calendar
import datetime

import altair as alt
import pandas as pd
import streamlit as st
import streamlit_authenticator as stauth
from sqlalchemy import text

# ============================================================
# 페이지 설정
# ============================================================
st.set_page_config(page_title="나만의 공부 관리 앱", page_icon="📚", layout="wide")

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
    st.title("📚 나만의 공부 관리 앱")
    authenticator.login(location="main")

    if st.session_state.get("authentication_status") is False:
        st.error("아이디 또는 비밀번호가 올바르지 않습니다.")
    elif st.session_state.get("authentication_status") is None:
        st.info("로그인 정보를 입력해 주세요.")
    st.stop()

username = st.session_state["username"]
name = st.session_state["name"]


def get_user_id(username: str) -> int:
    df = run_query("SELECT id FROM users WHERE username = :u;", {"u": username})
    return int(df.iloc[0]["id"])


user_id = get_user_id(username)

# ============================================================
# 공통: 과목(subjects) 관련
# ============================================================
def get_subjects(user_id: int) -> pd.DataFrame:
    return run_query(
        "SELECT id, name, color FROM subjects WHERE user_id = :uid ORDER BY name;",
        {"uid": user_id},
    )


def add_subject(user_id: int, name: str, color: str):
    run_write(
        "INSERT INTO subjects (user_id, name, color) VALUES (:uid, :name, :color);",
        {"uid": user_id, "name": name, "color": color},
    )


def delete_subject(subject_id: int):
    run_write("DELETE FROM subjects WHERE id = :id;", {"id": subject_id})


def subjects_manager(user_id: int):
    with st.expander("⚙️ 과목 설정 (추가 / 삭제)"):
        subjects_df = get_subjects(user_id)

        col1, col2 = st.columns([3, 1])
        with col1:
            new_name = st.text_input("새 과목명", placeholder="예: 선형대수", key="new_subject_name")
        with col2:
            new_color = st.color_picker("색상", value="#4C6EF5", key="new_subject_color")

        if st.button("➕ 과목 추가"):
            if new_name.strip():
                try:
                    add_subject(user_id, new_name.strip(), new_color)
                    st.success(f"'{new_name}' 과목을 추가했습니다.")
                    st.rerun()
                except Exception:
                    st.warning("이미 존재하는 과목명입니다.")
            else:
                st.warning("과목명을 입력해 주세요.")

        if not subjects_df.empty:
            st.divider()
            for _, row in subjects_df.iterrows():
                c1, c2 = st.columns([5, 1])
                with c1:
                    st.markdown(
                        f"<span style='display:inline-block;width:12px;height:12px;"
                        f"border-radius:50%;background:{row['color']};margin-right:8px;'></span>"
                        f"{row['name']}",
                        unsafe_allow_html=True,
                    )
                with c2:
                    if st.button("삭제", key=f"del_subject_{row['id']}"):
                        delete_subject(row["id"])
                        st.rerun()


# ============================================================
# 페이지 1: 공부 시간 기록
# ============================================================
HOUR_LABELS = [f"{(6 + r) % 24:02d}:00" for r in range(24)]
MIN_LABELS = ["00", "10", "20", "30", "40", "50"]


def load_study_blocks(user_id: int, study_date: datetime.date) -> pd.DataFrame:
    return run_query(
        "SELECT subject_id, slot_index FROM study_blocks "
        "WHERE user_id = :uid AND study_date = :d;",
        {"uid": user_id, "d": study_date},
    )


def save_study_grid(user_id: int, study_date: datetime.date, grid_df: pd.DataFrame, name_to_id: dict):
    with conn.session as s:
        s.execute(
            text("DELETE FROM study_blocks WHERE user_id = :uid AND study_date = :d;"),
            {"uid": user_id, "d": study_date},
        )
        for r, hour_label in enumerate(HOUR_LABELS):
            for c, min_label in enumerate(MIN_LABELS):
                val = grid_df.iat[r, c]
                if val:
                    slot_index = r * 6 + c
                    s.execute(
                        text(
                            "INSERT INTO study_blocks (user_id, subject_id, study_date, slot_index) "
                            "VALUES (:uid, :sid, :d, :si);"
                        ),
                        {"uid": user_id, "sid": name_to_id[val], "d": study_date, "si": slot_index},
                    )
        s.commit()


def _minutes_from_anchor(t: datetime.time) -> int:
    """06:00을 0분으로 하는 상대 분(分) 값 (그리드 기준)."""
    return ((t.hour - 6) % 24) * 60 + t.minute


def quick_fill_blocks(user_id: int, study_date: datetime.date, subject_id: int,
                       start_time: datetime.time, end_time: datetime.time) -> int:
    start_min = _minutes_from_anchor(start_time)
    end_min = _minutes_from_anchor(end_time)
    if end_min <= start_min:
        end_min += 24 * 60
    end_min = min(end_min, 24 * 60)

    slot_start = start_min // 10
    slot_end = end_min // 10
    if slot_end <= slot_start:
        return 0

    with conn.session as s:
        s.execute(
            text(
                "DELETE FROM study_blocks WHERE user_id = :uid AND study_date = :d "
                "AND slot_index >= :s AND slot_index < :e;"
            ),
            {"uid": user_id, "d": study_date, "s": slot_start, "e": slot_end},
        )
        for slot in range(slot_start, slot_end):
            s.execute(
                text(
                    "INSERT INTO study_blocks (user_id, subject_id, study_date, slot_index) "
                    "VALUES (:uid, :sid, :d, :si);"
                ),
                {"uid": user_id, "sid": subject_id, "d": study_date, "si": slot},
            )
        s.commit()
    return slot_end - slot_start


def get_month_daily_minutes(user_id: int, year: int, month: int) -> dict:
    start = datetime.date(year, month, 1)
    end = datetime.date(year + (month == 12), (month % 12) + 1, 1)
    df = run_query(
        "SELECT study_date, COUNT(*) AS slots FROM study_blocks "
        "WHERE user_id = :uid AND study_date >= :start AND study_date < :end "
        "GROUP BY study_date;",
        {"uid": user_id, "start": start, "end": end},
    )
    return {row["study_date"]: int(row["slots"]) * 10 for _, row in df.iterrows()}


def render_month_heatmap(daily_minutes: dict, year: int, month: int):
    cal = calendar.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(year, month)
    max_min = max(daily_minutes.values()) if daily_minutes else 1

    html = "<table style='width:100%;table-layout:fixed;border-collapse:separate;border-spacing:4px;text-align:center;'>"
    html += "<tr>" + "".join(
        f"<th style='padding:4px;color:#888;font-size:12px;'>{d}</th>" for d in ["월", "화", "수", "목", "금", "토", "일"]
    ) + "</tr>"

    for week in weeks:
        html += "<tr>"
        for day in week:
            in_month = day.month == month
            minutes = daily_minutes.get(day, 0) if in_month else 0
            alpha = 0.08 if minutes == 0 else min(1.0, 0.15 + 0.85 * (minutes / max_min))
            h, m = divmod(minutes, 60)
            if not in_month:
                time_txt = ""
            else:
                time_txt = f"{h}시간 {m}분" if minutes > 0 else "-"
            text_color = "#fff" if alpha > 0.5 else "#444"
            sub_color = "#eee" if alpha > 0.5 else "#999"
            opacity_style = f"background: rgba(124,58,237,{alpha});" if in_month else "background:#f4f4f4;"
            day_num = day.day if in_month else ""
            html += (
                f"<td style='{opacity_style}width:14.28%;height:64px;border-radius:8px;color:{text_color};"
                f"overflow:hidden;box-sizing:border-box;padding:6px 2px;'>"
                f"<div style='font-size:11px;color:{sub_color};'>{day_num}</div>"
                f"<div style='font-size:14px;font-weight:700;margin-top:2px;white-space:nowrap;'>{time_txt}</div></td>"
            )
        html += "</tr>"
    html += "</table>"

    st.markdown(html, unsafe_allow_html=True)
    total = sum(daily_minutes.values())
    th, tm = divmod(total, 60)
    st.caption(f"{month}월 총 공부 시간: {th}시간 {tm}분")


def page_study_time(user_id: int):
    st.title("📖 공부 시간 기록")

    subjects_manager(user_id)
    subjects_df = get_subjects(user_id)

    if subjects_df.empty:
        st.info("먼저 위의 '과목 설정'에서 공부할 과목을 추가해 주세요.")
        return

    name_to_id = dict(zip(subjects_df["name"], subjects_df["id"]))
    name_to_color = dict(zip(subjects_df["name"], subjects_df["color"]))

    study_date = st.date_input("기록할 날짜", datetime.date.today(), key="study_grid_date")

    # ---- 빠른 입력: 과목 + 시작~종료 시간으로 한 번에 채우기 ----
    st.subheader("⏱️ 빠르게 기록하기")
    with st.form("quick_fill_form", clear_on_submit=False):
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
        with c1:
            quick_subject = st.selectbox("과목", list(subjects_df["name"]), key="quick_subject")
        with c2:
            quick_start = st.time_input("시작 시간", datetime.time(9, 0), step=600, key="quick_start")
        with c3:
            quick_end = st.time_input("종료 시간", datetime.time(11, 0), step=600, key="quick_end")
        with c4:
            st.write("")
            fill_submitted = st.form_submit_button("✅ 채우기", type="primary")

        if fill_submitted:
            filled = quick_fill_blocks(
                user_id, study_date, name_to_id[quick_subject], quick_start, quick_end
            )
            if filled > 0:
                st.success(f"{quick_subject} — {filled * 10}분이 기록되었습니다!")
                st.rerun()
            else:
                st.warning("종료 시간이 시작 시간보다 늦어야 합니다.")

    st.caption("같은 시간대를 다시 채우면 이전 과목이 덮어씌워집니다. 겹치지 않게만 채우면 여러 과목을 자유롭게 기록할 수 있어요.")

    # 그리드 초기화 + 기존 데이터 반영
    grid_df = pd.DataFrame("", index=HOUR_LABELS, columns=MIN_LABELS)
    blocks_df = load_study_blocks(user_id, study_date)
    id_to_name = dict(zip(subjects_df["id"], subjects_df["name"]))
    for _, row in blocks_df.iterrows():
        r, c = divmod(int(row["slot_index"]), 6)
        grid_df.iat[r, c] = id_to_name.get(row["subject_id"], "")

    with st.expander("🔧 세부 수정 (10분 단위로 칸 하나씩 직접 지정)"):
        st.caption("각 칸을 클릭해서 과목을 선택하세요 (10분 단위, 06:00 ~ 다음날 05:50).")

        column_config = {
            col: st.column_config.SelectboxColumn(
                col, options=[""] + list(subjects_df["name"]), width="small"
            )
            for col in MIN_LABELS
        }

        edited_df = st.data_editor(
            grid_df,
            column_config=column_config,
            use_container_width=True,
            height=560,
            key="study_grid_editor",
        )

        if st.button("💾 세부 수정 내용 저장", type="primary"):
            save_study_grid(user_id, study_date, edited_df, name_to_id)
            st.success("저장되었습니다!")
            st.rerun()

    # 과목별 공부 시간 요약
    st.subheader("오늘의 과목별 공부 시간")
    counts = (edited_df.values.flatten() != "").sum()
    total_minutes = int(counts) * 10
    if total_minutes == 0:
        st.info("아직 기록된 공부 시간이 없습니다.")
    else:
        subj_counter = {}
        for val in edited_df.values.flatten():
            if val:
                subj_counter[val] = subj_counter.get(val, 0) + 1

        for subj, cnt in sorted(subj_counter.items(), key=lambda x: -x[1]):
            minutes = cnt * 10
            h, m = divmod(minutes, 60)
            pct = cnt * 10 / (24 * 60) * 100
            st.markdown(
                f"<div style='margin-bottom:6px;'>"
                f"<span style='display:inline-block;width:10px;height:10px;border-radius:50%;"
                f"background:{name_to_color.get(subj, '#999')};margin-right:6px;'></span>"
                f"{subj} — {h}시간 {m}분"
                f"<div style='background:#eee;border-radius:4px;height:6px;margin-top:2px;'>"
                f"<div style='background:{name_to_color.get(subj, '#999')};width:{pct}%;"
                f"height:6px;border-radius:4px;'></div></div></div>",
                unsafe_allow_html=True,
            )
        th, tm = divmod(total_minutes, 60)
        st.metric("오늘 총 공부 시간", f"{th}시간 {tm}분")

        pie_df = pd.DataFrame(
            {"과목": list(subj_counter.keys()), "분": [c * 10 for c in subj_counter.values()]}
        )
        pie_chart = (
            alt.Chart(pie_df)
            .mark_arc(innerRadius=60)
            .encode(
                theta=alt.Theta("분:Q"),
                color=alt.Color(
                    "과목:N",
                    scale=alt.Scale(domain=list(pie_df["과목"]), range=[name_to_color[s] for s in pie_df["과목"]]),
                    legend=alt.Legend(title=None),
                ),
                tooltip=["과목", "분"],
            )
            .properties(height=280)
        )
        st.altair_chart(pie_chart, use_container_width=True)

    st.divider()

    # 월별 히트맵
    st.subheader("📅 월별 공부 시간 통계")
    if "heatmap_month" not in st.session_state:
        st.session_state["heatmap_month"] = datetime.date.today().replace(day=1)

    nav1, nav2, nav3 = st.columns([1, 2, 1])
    with nav1:
        if st.button("◀ 이전 달"):
            m = st.session_state["heatmap_month"]
            st.session_state["heatmap_month"] = (m.replace(day=1) - datetime.timedelta(days=1)).replace(day=1)
    with nav3:
        if st.button("다음 달 ▶"):
            m = st.session_state["heatmap_month"]
            st.session_state["heatmap_month"] = (m.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    with nav2:
        m = st.session_state["heatmap_month"]
        st.markdown(f"<h4 style='text-align:center;'>{m.year}년 {m.month}월</h4>", unsafe_allow_html=True)

    m = st.session_state["heatmap_month"]
    daily_minutes = get_month_daily_minutes(user_id, m.year, m.month)
    render_month_heatmap(daily_minutes, m.year, m.month)


# ============================================================
# 페이지 2: 일정 관리
# ============================================================
def load_todos(user_id: int, category: str) -> pd.DataFrame:
    return run_query(
        "SELECT t.id, t.content, t.subject_id, s.name AS subject_name "
        "FROM todos t LEFT JOIN subjects s ON t.subject_id = s.id "
        "WHERE t.user_id = :uid AND t.category = :cat ORDER BY t.created_at;",
        {"uid": user_id, "cat": category},
    )


def add_todo(user_id: int, category: str, subject_id, content: str):
    run_write(
        "INSERT INTO todos (user_id, category, subject_id, content) "
        "VALUES (:uid, :cat, :sid, :content);",
        {"uid": user_id, "cat": category, "sid": subject_id, "content": content},
    )


def delete_todo(todo_id: int):
    run_write("DELETE FROM todos WHERE id = :id;", {"id": todo_id})


def add_event(user_id, category, subject_id, title, event_date, start_time, end_time, memo, lecture_id=None):
    run_write(
        "INSERT INTO events (user_id, category, subject_id, lecture_id, title, event_date, "
        "start_time, end_time, memo) VALUES (:uid, :cat, :sid, :lid, :title, :d, :st, :et, :memo);",
        {
            "uid": user_id, "cat": category, "sid": subject_id, "lid": lecture_id, "title": title,
            "d": event_date, "st": start_time, "et": end_time, "memo": memo,
        },
    )


def load_events(user_id: int, category, date_from: datetime.date, date_to: datetime.date) -> pd.DataFrame:
    if category is None:
        return run_query(
            "SELECT e.id, e.category, e.title, e.event_date, e.start_time, e.end_time, e.memo, e.is_done, "
            "s.name AS subject_name FROM events e LEFT JOIN subjects s ON e.subject_id = s.id "
            "WHERE e.user_id = :uid "
            "AND e.event_date BETWEEN :df AND :dt ORDER BY e.event_date, e.start_time;",
            {"uid": user_id, "df": date_from, "dt": date_to},
        )
    return run_query(
        "SELECT e.id, e.category, e.title, e.event_date, e.start_time, e.end_time, e.memo, e.is_done, "
        "s.name AS subject_name FROM events e LEFT JOIN subjects s ON e.subject_id = s.id "
        "WHERE e.user_id = :uid AND e.category = :cat "
        "AND e.event_date BETWEEN :df AND :dt ORDER BY e.event_date, e.start_time;",
        {"uid": user_id, "cat": category, "df": date_from, "dt": date_to},
    )


def toggle_event_done(event_id: int, is_done: bool):
    run_write("UPDATE events SET is_done = :v WHERE id = :id;", {"v": is_done, "id": event_id})


def delete_event(event_id: int):
    run_write("DELETE FROM events WHERE id = :id;", {"id": event_id})


def get_overdue_lectures(user_id: int) -> pd.DataFrame:
    return run_query(
        "SELECT l.title, l.due_date, s.name AS subject_name FROM lectures l "
        "JOIN subjects s ON l.subject_id = s.id "
        "WHERE l.user_id = :uid AND l.is_completed = false AND l.due_date IS NOT NULL "
        "AND l.due_date <= CURRENT_DATE ORDER BY l.due_date;",
        {"uid": user_id},
    )


def _event_minutes(t: datetime.time | None):
    return t.hour * 60 + t.minute if t is not None else None


def _event_color(ev, subjects_color: dict, default_color: str, category_colors: dict | None = None) -> str:
    subj = ev.get("subject_name")
    if subj and subj in subjects_color:
        return subjects_color[subj]
    if category_colors and ev.get("category") in category_colors:
        return category_colors[ev["category"]]
    return default_color


def render_timetable_day(events_df: pd.DataFrame, subjects_color: dict, default_color: str, category_colors: dict | None = None) -> str:
    hour_h = 30
    total_h = hour_h * 24
    timed = (
        events_df[events_df["start_time"].notna() & events_df["end_time"].notna()]
        if not events_df.empty else events_df
    )

    html = "<div style='display:flex;'>"
    html += "<div style='width:46px;flex-shrink:0;'>"
    for h in range(24):
        html += (
            f"<div style='height:{hour_h}px;font-size:10px;color:#999;text-align:right;"
            f"padding-right:6px;box-sizing:border-box;'>{h:02d}:00</div>"
        )
    html += "</div>"
    html += f"<div style='position:relative;flex:1;height:{total_h}px;border-left:1px solid #e5e5e5;'>"
    for h in range(24):
        top = h * hour_h
        html += f"<div style='position:absolute;top:{top}px;left:0;right:0;border-top:1px solid #f0f0f0;'></div>"
    for _, ev in timed.iterrows():
        s_min, e_min = _event_minutes(ev["start_time"]), _event_minutes(ev["end_time"])
        if e_min <= s_min:
            e_min = s_min + 30
        top = s_min / 60 * hour_h
        height = max((e_min - s_min) / 60 * hour_h, 18)
        color = _event_color(ev, subjects_color, default_color, category_colors)
        style_extra = "opacity:0.4;text-decoration:line-through;" if bool(ev["is_done"]) else ""
        html += (
            f"<div style='position:absolute;top:{top}px;height:{height}px;left:6px;right:6px;"
            f"background:{color};color:white;border-radius:5px;padding:3px 6px;font-size:12px;"
            f"overflow:hidden;box-shadow:0 1px 2px rgba(0,0,0,0.15);{style_extra}'>{ev['title']}</div>"
        )
    html += "</div></div>"
    return html


def render_timetable_week(events_df: pd.DataFrame, week_start: datetime.date, subjects_color: dict, default_color: str, category_colors: dict | None = None) -> str:
    hour_h = 26
    total_h = hour_h * 24
    labels = ["월", "화", "수", "목", "금", "토", "일"]

    html = "<div style='padding-top:22px;'><div style='display:flex;'>"
    html += "<div style='width:40px;flex-shrink:0;'>"
    for h in range(24):
        html += f"<div style='height:{hour_h}px;font-size:9px;color:#999;text-align:right;padding-right:4px;'>{h:02d}</div>"
    html += "</div>"

    for i in range(7):
        d = week_start + datetime.timedelta(days=i)
        day_events = events_df[events_df["event_date"] == d] if not events_df.empty else pd.DataFrame()
        timed = (
            day_events[day_events["start_time"].notna() & day_events["end_time"].notna()]
            if not day_events.empty else day_events
        )
        html += f"<div style='flex:1;position:relative;height:{total_h}px;border-left:1px solid #eee;'>"
        html += (
            f"<div style='position:absolute;top:-20px;left:0;right:0;text-align:center;"
            f"font-size:11px;font-weight:600;color:#555;'>{labels[i]} {d.day}</div>"
        )
        for h in range(24):
            top = h * hour_h
            html += f"<div style='position:absolute;top:{top}px;left:0;right:0;border-top:1px solid #f5f5f5;'></div>"
        for _, ev in timed.iterrows():
            s_min, e_min = _event_minutes(ev["start_time"]), _event_minutes(ev["end_time"])
            if e_min <= s_min:
                e_min = s_min + 30
            top = s_min / 60 * hour_h
            height = max((e_min - s_min) / 60 * hour_h, 15)
            color = _event_color(ev, subjects_color, default_color, category_colors)
            style_extra = "opacity:0.4;text-decoration:line-through;" if bool(ev["is_done"]) else ""
            html += (
                f"<div style='position:absolute;top:{top}px;height:{height}px;left:2px;right:2px;"
                f"background:{color};color:#fff;font-size:9px;border-radius:4px;padding:1px 4px;"
                f"overflow:hidden;{style_extra}'>{ev['title']}</div>"
            )
        html += "</div>"
    html += "</div></div>"
    return html


def render_day_events(user_id: int, category, d: datetime.date, key_prefix: str):
    events_df = load_events(user_id, category, d, d)
    if events_df.empty:
        st.caption("일정 없음")
        return
    for _, ev in events_df.iterrows():
        cat_tag = ""
        if category is None:
            cat_tag = " 📚" if ev["category"] == "study" else " 🏠"
        checked = st.checkbox(
            f"{ev['title']}{cat_tag} ({ev['start_time']}~{ev['end_time']})",
            value=bool(ev["is_done"]),
            key=f"ev_{key_prefix}_{ev['id']}",
        )
        if checked != bool(ev["is_done"]):
            toggle_event_done(ev["id"], checked)
            st.rerun()
        with st.expander("상세"):
            st.write(ev["memo"] or "메모 없음")
            if ev["subject_name"]:
                st.caption(f"과목: {ev['subject_name']}")
            if st.button("이 일정 삭제", key=f"del_ev_{key_prefix}_{ev['id']}"):
                delete_event(ev["id"])
                st.rerun()


def render_month_calendar_html(events_df: pd.DataFrame, ref_date: datetime.date, color_fn) -> str:
    cal = calendar.Calendar(firstweekday=0)
    html = "<table style='width:100%;border-collapse:collapse;table-layout:fixed;'><tr>"
    html += "".join(
        f"<th style='color:#888;font-size:12px;padding:6px;'>{d}</th>" for d in ["월", "화", "수", "목", "금", "토", "일"]
    )
    html += "</tr>"
    for week in cal.monthdatescalendar(ref_date.year, ref_date.month):
        html += "<tr>"
        for day in week:
            in_month = day.month == ref_date.month
            day_rows = pd.DataFrame()
            if in_month and not events_df.empty:
                day_rows = events_df[events_df["event_date"] == day]

            bg = "#fafafa" if in_month else "#f4f4f4"
            title_html = ""
            for _, ev in day_rows.head(3).iterrows():
                chip_color = color_fn(ev)
                title_html += (
                    f"<div style='background:{chip_color};color:#fff;border-radius:3px;font-size:10px;"
                    f"padding:1px 4px;margin-top:3px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;'>{ev['title']}</div>"
                )
            if len(day_rows) > 3:
                title_html += f"<div style='font-size:10px;color:#888;margin-top:2px;'>+{len(day_rows) - 3}개 더</div>"

            html += (
                f"<td style='background:{bg};vertical-align:top;padding:6px;border:1px solid #eee;"
                f"height:110px;width:14.28%;'>"
                f"<div style='font-size:12px;font-weight:600;color:#555;'>{day.day if in_month else ''}</div>"
                f"{title_html}</td>"
            )
        html += "</tr>"
    html += "</table>"
    return html


def render_schedule_category(user_id: int, category: str, subjects_df: pd.DataFrame):
    subjects_color = dict(zip(subjects_df["name"], subjects_df["color"]))
    default_color = "#7c3aed" if category == "study" else "#0ea5e9"

    if category == "study":
        overdue = get_overdue_lectures(user_id)
        if not overdue.empty:
            lines = [f"- **{r['subject_name']}** · {r['title']} (마감 {r['due_date']})" for _, r in overdue.iterrows()]
            st.warning("⚠️ 기한이 지났거나 오늘 마감인 강의가 있습니다.\n" + "\n".join(lines))

    # ---- To-do 목록 ----
    st.subheader("📝 할 일 목록 (날짜 미정)")

    with st.form(f"todo_form_{category}", clear_on_submit=True):
        c1, c2, c3 = st.columns([3, 2, 1])
        with c1:
            content = st.text_input("할 일", key=f"todo_content_{category}")
        subject_id = None
        if category == "study" and not subjects_df.empty:
            with c2:
                subj_name = st.selectbox("과목", [""] + list(subjects_df["name"]), key=f"todo_subject_{category}")
                if subj_name:
                    subject_id = int(subjects_df[subjects_df["name"] == subj_name]["id"].iloc[0])
        with c3:
            st.write("")
            submitted = st.form_submit_button("➕ 추가")
        if submitted and content.strip():
            add_todo(user_id, category, subject_id, content.strip())
            st.rerun()

    todos_df = load_todos(user_id, category)
    if todos_df.empty:
        st.caption("등록된 할 일이 없습니다.")
    else:
        for _, row in todos_df.iterrows():
            c1, c2, c3 = st.columns([4, 1.3, 1])
            with c1:
                tag = f" `{row['subject_name']}`" if row["subject_name"] else ""
                st.write(f"• {row['content']}{tag}")
            with c2:
                if st.button("📅 배치", key=f"place_{category}_{row['id']}"):
                    st.session_state[f"placing_{row['id']}"] = True
            with c3:
                if st.button("삭제", key=f"del_todo_{category}_{row['id']}"):
                    delete_todo(row["id"])
                    st.rerun()

            if st.session_state.get(f"placing_{row['id']}"):
                with st.form(f"place_form_{row['id']}"):
                    d = st.date_input("날짜", datetime.date.today())
                    st_time = st.time_input("시작 시간", datetime.time(9, 0))
                    et_time = st.time_input("종료 시간", datetime.time(10, 0))
                    memo = st.text_area("메모", "")
                    ok = st.form_submit_button("캘린더에 등록")
                    if ok:
                        add_event(
                            user_id, category, row["subject_id"], row["content"], d, st_time, et_time, memo
                        )
                        delete_todo(row["id"])
                        st.session_state[f"placing_{row['id']}"] = False
                        st.rerun()

    st.divider()

    # ---- 캘린더 ----
    st.subheader("🗓️ 캘린더")
    view = st.radio("보기", ["일", "주", "월"], horizontal=True, key=f"view_{category}")

    ref_key = f"ref_date_{category}"
    if ref_key not in st.session_state:
        st.session_state[ref_key] = datetime.date.today()
    ref_date = st.session_state[ref_key]

    nav1, nav2, nav3 = st.columns([1, 3, 1])
    with nav1:
        if st.button("◀", key=f"prev_{category}"):
            delta = {"일": 1, "주": 7, "월": 30}[view]
            st.session_state[ref_key] = ref_date - datetime.timedelta(days=delta)
            st.rerun()
    with nav3:
        if st.button("▶", key=f"next_{category}"):
            delta = {"일": 1, "주": 7, "월": 30}[view]
            st.session_state[ref_key] = ref_date + datetime.timedelta(days=delta)
            st.rerun()
    with nav2:
        st.markdown(f"<div style='text-align:center;font-weight:600;'>{ref_date}</div>", unsafe_allow_html=True)

    if view == "일":
        st.write(f"**{ref_date} 일정**")
        day_events_df = load_events(user_id, category, ref_date, ref_date)
        st.markdown(render_timetable_day(day_events_df, subjects_color, default_color), unsafe_allow_html=True)
        st.caption("⬇️ 완료 체크와 상세/삭제는 아래에서 할 수 있어요.")
        render_day_events(user_id, category, ref_date, key_prefix=category)

    elif view == "주":
        week_start = ref_date - datetime.timedelta(days=ref_date.weekday())
        week_events_df = load_events(user_id, category, week_start, week_start + datetime.timedelta(days=6))
        st.markdown(render_timetable_week(week_events_df, week_start, subjects_color, default_color), unsafe_allow_html=True)
        st.caption("⬇️ 완료 체크와 상세/삭제는 아래에서 할 수 있어요.")
        for i in range(7):
            d = week_start + datetime.timedelta(days=i)
            st.markdown(f"**{d} ({['월','화','수','목','금','토','일'][i]})**")
            render_day_events(user_id, category, d, key_prefix=category)

    else:  # 월
        month_start = ref_date.replace(day=1)
        month_end = (month_start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
        events_df = load_events(user_id, category, month_start, month_end)

        def color_fn(ev):
            return _event_color(ev, subjects_color, default_color)

        html = render_month_calendar_html(events_df, ref_date, color_fn)
        st.markdown(html, unsafe_allow_html=True)
        st.caption("칸을 클릭할 수는 없어요 — '일/주' 보기에서 날짜를 이동해 상세 일정을 확인·체크하세요.")

    if category == "study":
        st.divider()

        # ---- 주간 완성율 통계 (공부 일정에만 표시) ----
        st.subheader("📊 주간 완성율 통계")
        week_start = ref_date - datetime.timedelta(days=ref_date.weekday())
        week_end = week_start + datetime.timedelta(days=6)
        week_events = load_events(user_id, category, week_start, week_end)

        labels = ["월", "화", "수", "목", "금", "토", "일"]
        rates = []
        for i in range(7):
            d = week_start + datetime.timedelta(days=i)
            day_events = week_events[week_events["event_date"] == d] if not week_events.empty else pd.DataFrame()
            if len(day_events) == 0:
                rates.append(0)
            else:
                rates.append(round(day_events["is_done"].sum() / len(day_events) * 100))

        chart_df = pd.DataFrame({"요일": labels, "완성율": rates})
        bars = alt.Chart(chart_df).mark_bar(color=default_color, size=32).encode(
            x=alt.X("요일:N", sort=labels, title=None),
            y=alt.Y(
                "완성율:Q",
                scale=alt.Scale(domain=[0, 100]),
                axis=alt.Axis(values=list(range(0, 101, 10)), title="완성율(%)"),
            ),
        )
        value_labels = bars.mark_text(dy=-8, color="#333", fontSize=12).encode(text=alt.Text("완성율:Q"))
        st.altair_chart((bars + value_labels).properties(height=320), use_container_width=True)

        if len(week_events) > 0:
            overall = round(week_events["is_done"].sum() / len(week_events) * 100)
            st.caption(f"이번 주({week_start} ~ {week_end}) 전체 완성율: {overall}%")
        else:
            st.caption("이번 주에는 등록된 일정이 없습니다.")


def render_combined_calendar(user_id: int, subjects_df: pd.DataFrame):
    subjects_color = dict(zip(subjects_df["name"], subjects_df["color"]))
    category_colors = {"study": "#7c3aed", "personal": "#0ea5e9"}

    st.caption("🟣 공부 일정 · 🔵 개인 일정")
    view = st.radio("보기", ["일", "주", "월"], horizontal=True, key="view_combined")

    ref_key = "ref_date_combined"
    if ref_key not in st.session_state:
        st.session_state[ref_key] = datetime.date.today()
    ref_date = st.session_state[ref_key]

    nav1, nav2, nav3 = st.columns([1, 3, 1])
    with nav1:
        if st.button("◀", key="prev_combined"):
            delta = {"일": 1, "주": 7, "월": 30}[view]
            st.session_state[ref_key] = ref_date - datetime.timedelta(days=delta)
            st.rerun()
    with nav3:
        if st.button("▶", key="next_combined"):
            delta = {"일": 1, "주": 7, "월": 30}[view]
            st.session_state[ref_key] = ref_date + datetime.timedelta(days=delta)
            st.rerun()
    with nav2:
        st.markdown(f"<div style='text-align:center;font-weight:600;'>{ref_date}</div>", unsafe_allow_html=True)

    if view == "일":
        st.write(f"**{ref_date} 일정**")
        day_events_df = load_events(user_id, None, ref_date, ref_date)
        st.markdown(
            render_timetable_day(day_events_df, subjects_color, category_colors["personal"], category_colors),
            unsafe_allow_html=True,
        )
        st.caption("⬇️ 완료 체크와 상세/삭제는 아래에서 할 수 있어요.")
        render_day_events(user_id, None, ref_date, key_prefix="combined")

    elif view == "주":
        week_start = ref_date - datetime.timedelta(days=ref_date.weekday())
        week_events_df = load_events(user_id, None, week_start, week_start + datetime.timedelta(days=6))
        st.markdown(
            render_timetable_week(week_events_df, week_start, subjects_color, category_colors["personal"], category_colors),
            unsafe_allow_html=True,
        )
        st.caption("⬇️ 완료 체크와 상세/삭제는 아래에서 할 수 있어요.")
        for i in range(7):
            d = week_start + datetime.timedelta(days=i)
            st.markdown(f"**{d} ({['월','화','수','목','금','토','일'][i]})**")
            render_day_events(user_id, None, d, key_prefix="combined")

    else:  # 월
        month_start = ref_date.replace(day=1)
        month_end = (month_start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
        events_df = load_events(user_id, None, month_start, month_end)

        def color_fn(ev):
            return _event_color(ev, subjects_color, category_colors["personal"], category_colors)

        html = render_month_calendar_html(events_df, ref_date, color_fn)
        st.markdown(html, unsafe_allow_html=True)
        st.caption("칸을 클릭할 수는 없어요 — '일/주' 보기에서 날짜를 이동해 상세 일정을 확인·체크하세요.")


def page_schedule(user_id: int):
    st.title("🗓️ 일정 관리")
    subjects_df = get_subjects(user_id)
    tab1, tab2, tab3 = st.tabs(["📚 공부 일정", "🏠 개인 일정", "📌 최종 내 일정"])
    with tab1:
        render_schedule_category(user_id, "study", subjects_df)
    with tab2:
        render_schedule_category(user_id, "personal", subjects_df)
    with tab3:
        st.subheader("📌 공부 + 개인 통합 캘린더")
        render_combined_calendar(user_id, subjects_df)


# ============================================================
# 페이지 3: 강의 수강 현황 트래커
# ============================================================
def load_lectures(user_id: int, subject_id: int) -> pd.DataFrame:
    return run_query(
        "SELECT id, title, due_date, is_completed FROM lectures "
        "WHERE user_id = :uid AND subject_id = :sid ORDER BY due_date NULLS LAST;",
        {"uid": user_id, "sid": subject_id},
    )


def add_lecture(user_id: int, subject_id: int, title: str, due_date):
    with conn.session as s:
        result = s.execute(
            text(
                "INSERT INTO lectures (user_id, subject_id, title, due_date) "
                "VALUES (:uid, :sid, :title, :due) RETURNING id;"
            ),
            {"uid": user_id, "sid": subject_id, "title": title, "due": due_date},
        )
        lecture_id = result.scalar()
        s.commit()

    if lecture_id and due_date:
        add_event(user_id, "study", subject_id, f"[강의] {title}", due_date, None, None, "", lecture_id=lecture_id)
    return lecture_id


def update_lecture_done(lecture_id: int, is_completed: bool):
    run_write("UPDATE lectures SET is_completed = :v WHERE id = :id;", {"v": is_completed, "id": lecture_id})


def delete_lecture(lecture_id: int):
    run_write("DELETE FROM lectures WHERE id = :id;", {"id": lecture_id})


def page_lectures(user_id: int):
    st.title("🎓 강의 수강 현황 트래커")

    subjects_df = get_subjects(user_id)
    if subjects_df.empty:
        st.info("먼저 '공부 시간 기록' 페이지에서 과목을 추가해 주세요.")
        return

    overdue = get_overdue_lectures(user_id)
    if not overdue.empty:
        lines = [f"- **{r['subject_name']}** · {r['title']} (마감 {r['due_date']})" for _, r in overdue.iterrows()]
        st.warning("⚠️ 기한이 지났거나 오늘 마감인 강의가 있습니다.\n" + "\n".join(lines))

    tabs = st.tabs(list(subjects_df["name"]))
    for tab, (_, subj) in zip(tabs, subjects_df.iterrows()):
        with tab:
            subject_id = int(subj["id"])

            with st.form(f"lecture_form_{subject_id}", clear_on_submit=True):
                c1, c2, c3 = st.columns([3, 2, 1])
                with c1:
                    title = st.text_input("강의명", key=f"lec_title_{subject_id}")
                with c2:
                    due = st.date_input("마감 기한", datetime.date.today(), key=f"lec_due_{subject_id}")
                with c3:
                    st.write("")
                    ok = st.form_submit_button("➕ 추가")
                if ok and title.strip():
                    add_lecture(user_id, subject_id, title.strip(), due)
                    st.rerun()

            lectures_df = load_lectures(user_id, subject_id)

            if lectures_df.empty:
                st.caption("등록된 강의가 없습니다.")
            else:
                for _, lec in lectures_df.iterrows():
                    c1, c2, c3 = st.columns([3, 2, 1])
                    with c1:
                        checked = st.checkbox(
                            lec["title"], value=bool(lec["is_completed"]), key=f"lec_done_{lec['id']}"
                        )
                        if checked != bool(lec["is_completed"]):
                            update_lecture_done(lec["id"], checked)
                            st.rerun()
                    with c2:
                        overdue_flag = (
                            lec["due_date"]
                            and lec["due_date"] < datetime.date.today()
                            and not lec["is_completed"]
                        )
                        due_txt = str(lec["due_date"]) if lec["due_date"] else "미정"
                        if overdue_flag:
                            st.markdown(f"⚠️ {due_txt}")
                        else:
                            st.write(due_txt)
                    with c3:
                        if st.button("삭제", key=f"del_lec_{lec['id']}"):
                            delete_lecture(lec["id"])
                            st.rerun()

                st.divider()
                total = len(lectures_df)
                completed = int(lectures_df["is_completed"].sum())
                missed = int(
                    (
                        (lectures_df["due_date"].notna())
                        & (lectures_df["due_date"] < datetime.date.today())
                        & (~lectures_df["is_completed"])
                    ).sum()
                )
                rate = round(completed / total * 100) if total else 0

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("총 강의", total)
                m2.metric("완료", completed)
                m3.metric("기한 초과", missed)
                m4.metric("수강률", f"{rate}%")


# ============================================================
# 페이지 4: 학점 관리
# ============================================================
GRADE_POINTS = {
    "A+": 4.3, "A0": 4.0, "A-": 3.7,
    "B+": 3.3, "B0": 3.0, "B-": 2.7,
    "C+": 2.3, "C0": 2.0, "C-": 1.7,
    "D+": 1.3, "D0": 1.0, "D-": 0.7,
    "F": 0.0,
}
GRADE_OPTIONS = ["(미입력)"] + list(GRADE_POINTS.keys()) + ["P"]


CATEGORIES = ["MR", "ME", "CC", "교양"]


def get_credit_settings(user_id: int) -> dict:
    df = run_query(
        "SELECT total_required, mr_required, me_required, cc_required "
        "FROM credit_settings WHERE user_id = :uid;",
        {"uid": user_id},
    )
    if df.empty:
        run_write(
            "INSERT INTO credit_settings (user_id, total_required, mr_required, me_required, cc_required) "
            "VALUES (:uid, 130, 0, 0, 0);",
            {"uid": user_id},
        )
        return {"total": 130.0, "MR": 0.0, "ME": 0.0, "CC": 0.0}
    row = df.iloc[0]
    return {
        "total": float(row["total_required"]),
        "MR": float(row["mr_required"]),
        "ME": float(row["me_required"]),
        "CC": float(row["cc_required"]),
    }


def update_credit_settings(user_id: int, total: float, mr: float, me: float, cc: float):
    run_write(
        "UPDATE credit_settings SET total_required = :t, mr_required = :mr, "
        "me_required = :me, cc_required = :cc WHERE user_id = :uid;",
        {"t": total, "mr": mr, "me": me, "cc": cc, "uid": user_id},
    )


def ensure_chapel_seed(user_id: int):
    df = run_query(
        "SELECT id FROM credit_courses WHERE user_id = :uid AND name = '채플';", {"uid": user_id}
    )
    if df.empty:
        run_write(
            "INSERT INTO credit_courses "
            "(user_id, name, format, campus, category, credit, progress_count, progress_required) "
            "VALUES (:uid, '채플', '대면', '신촌', 'CC', 0.5, 0, 4);",
            {"uid": user_id},
        )


def get_courses(user_id: int) -> pd.DataFrame:
    return run_query(
        "SELECT id, name, format, campus, category, credit, grade, progress_count, progress_required "
        "FROM credit_courses WHERE user_id = :uid ORDER BY created_at;",
        {"uid": user_id},
    )


def add_course(user_id: int, name: str, format_: str, campus: str, category: str, credit: float):
    run_write(
        "INSERT INTO credit_courses "
        "(user_id, name, format, campus, category, credit, progress_count, progress_required) "
        "VALUES (:uid, :name, :fmt, :campus, :category, :credit, 0, 1);",
        {"uid": user_id, "name": name, "fmt": format_, "campus": campus, "category": category, "credit": credit},
    )


def update_course_progress(course_id: int, new_count: int):
    run_write("UPDATE credit_courses SET progress_count = :v WHERE id = :id;", {"v": new_count, "id": course_id})


def update_course_grade(course_id: int, grade):
    run_write("UPDATE credit_courses SET grade = :g WHERE id = :id;", {"g": grade, "id": course_id})


def delete_course(course_id: int):
    run_write("DELETE FROM credit_courses WHERE id = :id;", {"id": course_id})


def render_course_row(c: pd.Series):
    is_multi = c["progress_required"] > 1
    is_complete = c["progress_count"] >= c["progress_required"]

    col1, col2, col3, col4 = st.columns([3.2, 2, 1.6, 0.8])

    with col1:
        if is_multi:
            st.write(f"{'✅' if is_complete else '⬜'} **{c['name']}** ({c['credit']}학점)")
            st.caption(f"{c['format']} · {c['campus']} · {c['progress_count']}/{c['progress_required']}회 이수")
        else:
            checked = st.checkbox(
                f"{c['name']} ({c['credit']}학점)",
                value=is_complete,
                key=f"course_check_{c['id']}",
            )
            st.caption(f"{c['format']} · {c['campus']}")
            if checked != is_complete:
                update_course_progress(c["id"], 1 if checked else 0)
                st.rerun()

    with col2:
        current_grade = c["grade"] if c["grade"] else "(미입력)"
        grade = st.selectbox(
            "성적", GRADE_OPTIONS, index=GRADE_OPTIONS.index(current_grade),
            key=f"grade_{c['id']}", label_visibility="collapsed",
        )
        if grade != current_grade:
            update_course_grade(c["id"], None if grade == "(미입력)" else grade)
            st.rerun()

    with col3:
        if is_multi:
            b1, b2 = st.columns(2)
            with b1:
                if st.button("－", key=f"minus_{c['id']}"):
                    update_course_progress(c["id"], max(0, c["progress_count"] - 1))
                    st.rerun()
            with b2:
                if st.button("＋", key=f"plus_{c['id']}"):
                    update_course_progress(c["id"], min(c["progress_required"], c["progress_count"] + 1))
                    st.rerun()

    with col4:
        if st.button("삭제", key=f"del_course_{c['id']}"):
            delete_course(c["id"])
            st.rerun()


def page_credits(user_id: int):
    st.title("🎓 학점 관리")

    ensure_chapel_seed(user_id)
    settings = get_credit_settings(user_id)
    cg_required = max(0.0, settings["total"] - settings["MR"] - settings["ME"] - settings["CC"])
    required_by_cat = {"MR": settings["MR"], "ME": settings["ME"], "CC": settings["CC"], "교양": cg_required}

    st.subheader("🎯 목표 졸업 학점")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        new_total = st.number_input("총 졸업 학점", min_value=0.0, value=settings["total"], step=0.5, key="total_required_input")
    with c2:
        new_mr = st.number_input("MR 학점", min_value=0.0, value=settings["MR"], step=0.5, key="mr_required_input")
    with c3:
        new_me = st.number_input("ME 학점", min_value=0.0, value=settings["ME"], step=0.5, key="me_required_input")
    with c4:
        new_cc = st.number_input("CC 학점", min_value=0.0, value=settings["CC"], step=0.5, key="cc_required_input")

    computed_cg = new_total - new_mr - new_me - new_cc
    if computed_cg < 0:
        st.warning(f"MR+ME+CC 합이 총 졸업학점보다 큽니다. (교양 학점이 {computed_cg}로 음수가 됩니다)")
    else:
        st.caption(f"교양 학점(자동 계산) = 총 졸업학점 − (MR+ME+CC) = **{computed_cg}학점**")

    if st.button("저장", key="save_settings"):
        update_credit_settings(user_id, new_total, new_mr, new_me, new_cc)
        st.success("저장되었습니다.")
        st.rerun()

    st.divider()

    # ---- 과목 추가 ----
    st.subheader("➕ 과목 추가")
    with st.form("add_course_form", clear_on_submit=True):
        c1, c2, c3, c4, c5 = st.columns([2.5, 1.6, 1.3, 1.3, 1])
        with c1:
            course_name = st.text_input("과목명")
        with c2:
            course_format = st.selectbox("진행 방식", ["대면", "비대면", "블렌디드"])
        with c3:
            course_campus = st.selectbox("캠퍼스", ["신촌", "송도"])
        with c4:
            course_category = st.selectbox("구분", CATEGORIES)
        with c5:
            course_credit = st.selectbox("학점", [0.5, 1, 2, 3])
        submitted = st.form_submit_button("추가")
        if submitted and course_name.strip():
            add_course(user_id, course_name.strip(), course_format, course_campus, course_category, course_credit)
            st.rerun()

    st.divider()

    # ---- 체크리스트 (카테고리별 탭) ----
    st.subheader("📋 이수 과목 체크리스트")
    courses_df = get_courses(user_id)

    cat_tabs = st.tabs(CATEGORIES)
    for cat, tab in zip(CATEGORIES, cat_tabs):
        with tab:
            subset = courses_df[courses_df["category"] == cat] if not courses_df.empty else pd.DataFrame()
            if subset.empty:
                st.caption("등록된 과목이 없습니다.")
                completed_cat = 0.0
            else:
                for _, c in subset.iterrows():
                    render_course_row(c)
                completed_mask = subset["progress_count"] >= subset["progress_required"]
                completed_cat = float(subset.loc[completed_mask, "credit"].sum())

            req_cat = required_by_cat[cat]
            rate_cat = round(completed_cat / req_cat * 100, 1) if req_cat else 0
            st.caption(f"**{cat} 이수 현황**: {completed_cat} / {req_cat}학점 ({rate_cat}%)")

    st.divider()

    # ---- 요약 통계 ----
    st.subheader("📊 이수 현황 요약")
    if courses_df.empty:
        completed_credits = 0.0
        gpa = 0.0
    else:
        completed_mask = courses_df["progress_count"] >= courses_df["progress_required"]
        completed_credits = float(courses_df.loc[completed_mask, "credit"].sum())

        graded = courses_df[courses_df["grade"].isin(GRADE_POINTS.keys())]
        if not graded.empty:
            weighted_sum = sum(float(r["credit"]) * GRADE_POINTS[r["grade"]] for _, r in graded.iterrows())
            credit_sum = float(graded["credit"].sum())
            gpa = weighted_sum / credit_sum if credit_sum else 0.0
        else:
            gpa = 0.0

    completion_rate = round(completed_credits / settings["total"] * 100, 1) if settings["total"] else 0

    m1, m2, m3 = st.columns(3)
    m1.metric("이수 학점", f"{completed_credits} / {settings['total']}")
    m2.metric("완성율", f"{completion_rate}%")
    m3.metric("평점 (GPA)", f"{gpa:.2f}")

    st.progress(min(1.0, completed_credits / settings["total"]) if settings["total"] else 0)


# ============================================================
# 사이드바 + 메뉴
# ============================================================
with st.sidebar:
    st.write(f"👋 반갑습니다, **{name}**님")
    authenticator.logout("로그아웃", "sidebar")
    st.divider()
    st.header("메뉴")
    menu = st.radio(
        "이동할 화면",
        ["공부 시간 기록", "일정 관리", "강의 수강 현황", "학점 관리"],
        label_visibility="collapsed",
    )

if menu == "공부 시간 기록":
    page_study_time(user_id)
elif menu == "일정 관리":
    page_schedule(user_id)
elif menu == "강의 수강 현황":
    page_lectures(user_id)
else:
    page_credits(user_id)
