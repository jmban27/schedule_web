import calendar
import datetime

import altair as alt
import pandas as pd
import streamlit as st

from common import (
    require_login, sidebar_user_info, run_query, run_write,
    get_subjects, get_overdue_lectures, add_event,
)


user_id, name, authenticator = require_login()

with st.sidebar:
    sidebar_user_info(name, authenticator)


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
            f"{ev['title']}{cat_tag} ({ev['start_time']}-{ev['end_time']})",
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


page_schedule(user_id)