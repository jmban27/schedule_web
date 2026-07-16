import altair as alt
import pandas as pd
import streamlit as st

from common import require_login, sidebar_user_info, run_query, run_write


user_id, name, authenticator = require_login()

with st.sidebar:
    sidebar_user_info(name, authenticator)


GRADE_POINTS = {
    "A+": 4.3, "A0": 4.0, "A-": 3.7,
    "B+": 3.3, "B0": 3.0, "B-": 2.7,
    "C+": 2.3, "C0": 2.0, "C-": 1.7,
    "D+": 1.3, "D0": 1.0, "D-": 0.7,
    "F": 0.0,
}
GRADE_OPTIONS = ["(미입력)"] + list(GRADE_POINTS.keys()) + ["P"]


CATEGORIES = ["MR", "ME", "CC", "교양"]
ALL_CATEGORIES = CATEGORIES + ["응통"]
PIE_COLORS = {"MR": "#7c3aed", "ME": "#0ea5e9", "CC": "#f59e0b", "교양": "#10b981"}


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
        if current_grade not in GRADE_OPTIONS:
            current_grade = "(미입력)"
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


def render_completion_pie(completed: float, required: float, color: str):
    if required <= 0:
        data = pd.DataFrame({"구분": ["목표 미설정"], "값": [1]})
        return (
            alt.Chart(data)
            .mark_arc(innerRadius=45)
            .encode(theta="값:Q", color=alt.Color("구분:N", scale=alt.Scale(range=["#e5e7eb"]), legend=None))
            .properties(height=170)
        )
    remaining = max(required - completed, 0)
    data = pd.DataFrame({"구분": ["이수", "미이수"], "값": [completed, remaining]})
    return (
        alt.Chart(data)
        .mark_arc(innerRadius=45)
        .encode(
            theta=alt.Theta("값:Q"),
            color=alt.Color(
                "구분:N",
                scale=alt.Scale(domain=["이수", "미이수"], range=[color, "#e5e7eb"]),
                legend=None,
            ),
            tooltip=["구분", "값"],
        )
        .properties(height=170)
    )


TIMETABLE_DAYS = ["월", "화", "수", "목", "금", "토"]
TIMETABLE_HOURS = list(range(9, 20))  # 9~19시 (11칸, 마지막 칸은 19:00~20:00)
TIMETABLE_PALETTE = ["#7c3aed", "#0ea5e9", "#f59e0b", "#10b981", "#ef4444", "#ec4899", "#6366f1", "#84cc16", "#14b8a6", "#f97316"]


def get_timetable_courses(user_id: int) -> pd.DataFrame:
    return run_query(
        "SELECT id, name, format, campus, category, credit, day_of_week, start_hour, end_hour, color "
        "FROM timetable_courses WHERE user_id = :uid ORDER BY created_at;",
        {"uid": user_id},
    )


def add_timetable_course(user_id: int, name: str, format_: str, campus: str, category: str,
                          credit: float, day_of_week: str, start_hour: int, end_hour: int):
    existing = run_query(
        "SELECT DISTINCT name, color FROM timetable_courses WHERE user_id = :uid;", {"uid": user_id}
    )
    match = existing[existing["name"] == name] if not existing.empty else existing
    if not match.empty:
        color = match.iloc[0]["color"]
    else:
        distinct_count = int(existing["name"].nunique()) if not existing.empty else 0
        color = TIMETABLE_PALETTE[distinct_count % len(TIMETABLE_PALETTE)]

    run_write(
        "INSERT INTO timetable_courses "
        "(user_id, name, format, campus, category, credit, day_of_week, start_hour, end_hour, color) "
        "VALUES (:uid, :name, :fmt, :campus, :category, :credit, :day, :sh, :eh, :color);",
        {
            "uid": user_id, "name": name, "fmt": format_, "campus": campus, "category": category,
            "credit": credit, "day": day_of_week, "sh": start_hour, "eh": end_hour, "color": color,
        },
    )


def delete_timetable_course(course_id: int):
    run_write("DELETE FROM timetable_courses WHERE id = :id;", {"id": course_id})


def render_weekly_timetable_html(courses_df: pd.DataFrame) -> str:
    html = "<table style='width:100%;border-collapse:collapse;table-layout:fixed;'>"
    html += "<tr><th style='width:50px;'></th>" + "".join(
        f"<th style='padding:6px;font-size:12px;color:#666;'>{d}</th>" for d in TIMETABLE_DAYS
    ) + "</tr>"
    for h in TIMETABLE_HOURS:
        html += f"<tr><td style='font-size:11px;color:#999;text-align:right;padding-right:6px;vertical-align:top;'>{h}:00</td>"
        for d in TIMETABLE_DAYS:
            match = (
                courses_df[
                    (courses_df["day_of_week"] == d)
                    & (courses_df["start_hour"] <= h)
                    & (courses_df["end_hour"] > h)
                ]
                if not courses_df.empty else pd.DataFrame()
            )
            if not match.empty:
                row = match.iloc[0]
                html += (
                    f"<td style='background:{row['color']};color:#fff;font-size:11px;text-align:center;"
                    f"padding:8px 2px;border:1px solid #fff;overflow:hidden;'>{row['name']}</td>"
                )
            else:
                html += "<td style='background:#fafafa;border:1px solid #eee;height:38px;'></td>"
        html += "</tr>"
    html += "</table>"
    return html


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
            course_category = st.selectbox("구분", ALL_CATEGORIES)
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

    cat_tabs = st.tabs(ALL_CATEGORIES)
    for cat, tab in zip(ALL_CATEGORIES, cat_tabs):
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

            if cat == "응통":
                st.caption(f"**응통 이수 학점**: {completed_cat}학점 (졸업 필요 학점 계산에는 포함되지 않아요)")
            else:
                req_cat = required_by_cat[cat]
                rate_cat = round(completed_cat / req_cat * 100, 1) if req_cat else 0
                st.caption(f"**{cat} 이수 현황**: {completed_cat} / {req_cat}학점 ({rate_cat}%)")

    st.divider()

    # ---- 요약 통계 ----
    st.subheader("📊 이수 현황 요약")
    grad_df = courses_df[courses_df["category"] != "응통"] if not courses_df.empty else courses_df
    eung_df = courses_df[courses_df["category"] == "응통"] if not courses_df.empty else courses_df

    if grad_df.empty:
        completed_credits = 0.0
        gpa = 0.0
    else:
        completed_mask = grad_df["progress_count"] >= grad_df["progress_required"]
        completed_credits = float(grad_df.loc[completed_mask, "credit"].sum())

        grad_grade_clean = grad_df["grade"].astype(str).str.strip()
        graded = grad_df[grad_grade_clean.isin(GRADE_POINTS.keys())]
        if not graded.empty:
            weighted_sum = sum(
                float(r["credit"]) * GRADE_POINTS[str(r["grade"]).strip()] for _, r in graded.iterrows()
            )
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

    st.markdown("**카테고리별 이수율**")
    pie_cols = st.columns(4)
    for cat, col in zip(CATEGORIES, pie_cols):
        subset = grad_df[grad_df["category"] == cat] if not grad_df.empty else pd.DataFrame()
        completed_cat = (
            float(subset.loc[subset["progress_count"] >= subset["progress_required"], "credit"].sum())
            if not subset.empty else 0.0
        )
        req_cat = required_by_cat[cat]
        rate_cat = round(completed_cat / req_cat * 100, 1) if req_cat else 0
        with col:
            st.altair_chart(render_completion_pie(completed_cat, req_cat, PIE_COLORS[cat]), use_container_width=True)
            st.caption(f"**{cat}**: {completed_cat}/{req_cat}학점 ({rate_cat}%)")

    # ---- 응통 (졸업 필요 학점 자체 계산에는 미포함, 대신 포함 시 결과를 별도로 보여줌) ----
    eung_graded = pd.DataFrame()
    if eung_df.empty:
        eung_credits = 0.0
        eung_gpa = 0.0
    else:
        eung_completed_mask = eung_df["progress_count"] >= eung_df["progress_required"]
        eung_credits = float(eung_df.loc[eung_completed_mask, "credit"].sum())

        eung_grade_clean = eung_df["grade"].astype(str).str.strip()
        eung_graded = eung_df[eung_grade_clean.isin(GRADE_POINTS.keys())]
        if not eung_graded.empty:
            eung_weighted = sum(
                float(r["credit"]) * GRADE_POINTS[str(r["grade"]).strip()] for _, r in eung_graded.iterrows()
            )
            eung_credit_sum = float(eung_graded["credit"].sum())
            eung_gpa = eung_weighted / eung_credit_sum if eung_credit_sum else 0.0
        else:
            eung_gpa = 0.0

    combined_credits = completed_credits + eung_credits
    combined_rate = round(combined_credits / settings["total"] * 100, 1) if settings["total"] else 0

    st.markdown("**응통** (졸업 필요 학점 자체 계산에는 포함되지 않지만, 포함했을 때 결과를 아래에서 확인할 수 있어요)")
    e1, e2, e3 = st.columns(3)
    e1.metric("응통 이수 학점", f"{eung_credits}학점")
    e2.metric("응통 GPA", f"{eung_gpa:.2f}" if not eung_graded.empty else "성적 미입력" if not eung_df.empty else "-")
    e3.metric("응통 포함 시 총 이수 학점", f"{combined_credits} / {settings['total']} ({combined_rate}%)")

    st.divider()

    # ============================================================
    # 시간표 제작 (위의 체크리스트와는 완전히 별개의 과목 목록)
    # ============================================================
    st.subheader("🗓️ 시간표 제작")
    st.caption("이 파트는 위의 이수 체크리스트와 별개로, '이 시간표대로 수강하면 어떻게 되는지' 시뮬레이션하는 공간이에요.")

    with st.form("add_timetable_course_form", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([2.2, 1.4, 1.2, 1.2])
        with c1:
            tt_name = st.text_input("과목명", key="tt_name")
        with c2:
            tt_format = st.selectbox("진행 방식", ["대면", "비대면", "블렌디드"], key="tt_format")
        with c3:
            tt_campus = st.selectbox("캠퍼스", ["신촌", "송도"], key="tt_campus")
        with c4:
            tt_category = st.selectbox("구분", CATEGORIES, key="tt_category")

        c5, = st.columns(1)
        with c5:
            tt_credit = st.selectbox("학점", [0.5, 1, 2, 3], key="tt_credit")

        st.markdown("**시간 블록 1** (필수)")
        c6, c7, c8 = st.columns(3)
        with c6:
            tt_day1 = st.selectbox("요일", TIMETABLE_DAYS, key="tt_day1")
        with c7:
            tt_start1 = st.selectbox("시작 시간", TIMETABLE_HOURS, key="tt_start1")
        with c8:
            tt_end1 = st.selectbox("종료 시간", list(range(10, 21)), key="tt_end1")

        tt_add_slot2 = st.checkbox("요일/시간 블록을 하나 더 추가 (예: 주 2회 수업)", key="tt_add_slot2")

        tt_day2 = tt_start2 = tt_end2 = None
        if tt_add_slot2:
            st.markdown("**시간 블록 2**")
            c9, c10, c11 = st.columns(3)
            with c9:
                tt_day2 = st.selectbox("요일 ", TIMETABLE_DAYS, key="tt_day2")
            with c10:
                tt_start2 = st.selectbox("시작 시간 ", TIMETABLE_HOURS, key="tt_start2")
            with c11:
                tt_end2 = st.selectbox("종료 시간 ", list(range(10, 21)), key="tt_end2")

        tt_submitted = st.form_submit_button("➕ 시간표에 추가")
        if tt_submitted:
            if not tt_name.strip():
                st.warning("과목명을 입력해 주세요.")
            elif tt_end1 <= tt_start1:
                st.warning("시간 블록 1의 종료 시간이 시작 시간보다 늦어야 합니다.")
            elif tt_add_slot2 and tt_end2 <= tt_start2:
                st.warning("시간 블록 2의 종료 시간이 시작 시간보다 늦어야 합니다.")
            else:
                add_timetable_course(
                    user_id, tt_name.strip(), tt_format, tt_campus, tt_category,
                    tt_credit, tt_day1, tt_start1, tt_end1,
                )
                if tt_add_slot2:
                    add_timetable_course(
                        user_id, tt_name.strip(), tt_format, tt_campus, tt_category,
                        tt_credit, tt_day2, tt_start2, tt_end2,
                    )
                st.rerun()

    timetable_df = get_timetable_courses(user_id)
    st.markdown(render_weekly_timetable_html(timetable_df), unsafe_allow_html=True)

    if not timetable_df.empty:
        st.markdown("**등록된 과목**")
        for _, row in timetable_df.iterrows():
            c1, c2 = st.columns([5, 1])
            with c1:
                st.markdown(
                    f"<span style='display:inline-block;width:10px;height:10px;border-radius:50%;"
                    f"background:{row['color']};margin-right:6px;'></span>"
                    f"{row['name']} · {row['category']} · {row['credit']}학점 · "
                    f"{row['day_of_week']} {row['start_hour']}:00~{row['end_hour']}:00 · "
                    f"{row['format']} · {row['campus']}",
                    unsafe_allow_html=True,
                )
            with c2:
                if st.button("삭제", key=f"del_tt_{row['id']}"):
                    delete_timetable_course(row["id"])
                    st.rerun()

    st.divider()

    # ---- 이 시간표대로 수강했을 때의 예상 이수 현황 ----
    st.subheader("📊 이 시간표대로 수강하면?")
    st.caption("위 '이수 현황 요약'에서 이미 이수 처리한 학점 + 이 시간표에 등록한 과목 학점을 합산해서 보여줘요.")

    if timetable_df.empty:
        st.info("아직 시간표에 등록된 과목이 없습니다.")
    else:
        # 같은 과목이 여러 요일(시간 블록)에 걸쳐 등록되어 있어도 학점은 한 번만 계산
        unique_tt = timetable_df.drop_duplicates(subset="name")[["name", "category", "credit"]]

        tt_total = float(unique_tt["credit"].sum())
        combined_total = completed_credits + tt_total
        combined_rate = round(combined_total / settings["total"] * 100, 1) if settings["total"] else 0

        tm1, tm2 = st.columns(2)
        tm1.metric("예상 총 이수 학점 (기존 이수 + 시간표)", f"{combined_total} / {settings['total']}")
        tm2.metric("예상 총 이수율", f"{combined_rate}%")

        st.markdown("**카테고리별 예상 이수율** (기존 이수 + 시간표 합산)")
        tt_pie_cols = st.columns(4)
        for cat, col in zip(CATEGORIES, tt_pie_cols):
            existing_cat_credit = (
                float(
                    grad_df.loc[
                        (grad_df["category"] == cat) & (grad_df["progress_count"] >= grad_df["progress_required"]),
                        "credit",
                    ].sum()
                )
                if not grad_df.empty else 0.0
            )
            tt_cat_credit = float(unique_tt.loc[unique_tt["category"] == cat, "credit"].sum())
            combined_cat = existing_cat_credit + tt_cat_credit
            req_cat = required_by_cat[cat]
            rate_cat = round(combined_cat / req_cat * 100, 1) if req_cat else 0
            with col:
                st.altair_chart(render_completion_pie(combined_cat, req_cat, PIE_COLORS[cat]), use_container_width=True)
                st.caption(f"**{cat}**: {combined_cat}/{req_cat}학점 ({rate_cat}%)")


page_credits(user_id)