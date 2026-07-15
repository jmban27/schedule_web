import calendar
import datetime

import altair as alt
import pandas as pd
import streamlit as st
from sqlalchemy import text

from common import require_login, sidebar_user_info, run_query, run_write, get_subjects, conn

st.set_page_config(page_title="공부 시간 기록", page_icon="📖", layout="wide")

user_id, name, authenticator = require_login()

with st.sidebar:
    sidebar_user_info(name, authenticator)


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


page_study_time(user_id)
