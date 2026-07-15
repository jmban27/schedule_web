import datetime

import pandas as pd
import streamlit as st
from sqlalchemy import text

from common import (
    require_login, sidebar_user_info, run_query, run_write, conn,
    get_subjects, get_overdue_lectures, add_event,
)

st.set_page_config(page_title="강의 수강 현황", page_icon="🎓", layout="wide")

user_id, name, authenticator = require_login()

with st.sidebar:
    sidebar_user_info(name, authenticator)


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


page_lectures(user_id)
