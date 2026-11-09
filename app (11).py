"""오늘 한 가지 — Streamlit 모바일 할 일 앱.
실행: streamlit run app.py
배포: GitHub에 app.py, requirements.txt 업로드 → Streamlit Community Cloud 연결.
영구 DB 없는 독립 실행 버전: 세션 종료/새로고침 시 데이터가 사라질 수 있으므로 JSON 백업 필수.
QR은 배포된 웹앱의 공개 URL만 담으며 할 일 데이터는 공유하지 않음.
"""
from __future__ import annotations

import html
import io
import json
import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

import qrcode
import streamlit as st

TZ = ZoneInfo("Asia/Seoul")

def now():
    return datetime.now(TZ)

def parse_dt(value):
    result = datetime.fromisoformat(value)
    return result.replace(tzinfo=TZ) if result.tzinfo is None else result.astimezone(TZ)

def new_task(title, day, clock=None, memo=""):
    return {"id": str(uuid.uuid4()), "title": title.strip(), "day": day.isoformat(),
            "due": datetime.combine(day, clock, TZ).isoformat() if clock else None,
            "memo": memo.strip(), "done": False, "done_at": None}

def validate_backup(payload):
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("지원하지 않는 백업 형식입니다.")
    items = payload.get("tasks")
    if not isinstance(items, list) or len(items) > 3000:
        raise ValueError("할 일은 최대 3,000개까지 가져올 수 있습니다.")
    clean = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("잘못된 할 일 항목입니다.")
        title, memo, key = item.get("title"), item.get("memo", ""), item.get("id")
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100:
            raise ValueError("할 일 이름은 1~100자여야 합니다.")
        if not isinstance(memo, str) or len(memo) > 1000:
            raise ValueError("메모는 1,000자 이하여야 합니다.")
        if not isinstance(key, str) or not 1 <= len(key) <= 100 or key in seen:
            raise ValueError("항목 ID가 잘못되었거나 중복되었습니다.")
        day = date.fromisoformat(item["day"])
        due = parse_dt(item["due"]) if item.get("due") else None
        if due and due.date() != day:
            raise ValueError("예정 날짜와 시간이 일치하지 않습니다.")
        if not isinstance(item.get("done"), bool):
            raise ValueError("완료 상태가 올바르지 않습니다.")
        done_at = parse_dt(item["done_at"]).isoformat() if item.get("done_at") else None
        clean.append({"id": key, "title": title.strip(), "day": day.isoformat(),
                      "due": due.isoformat() if due else None, "memo": memo,
                      "done": item["done"], "done_at": done_at})
        seen.add(key)
    return clean

def snooze(item, minutes=10):
    target = now() + timedelta(minutes=minutes)
    item.update(due=target.isoformat(), day=target.date().isoformat(), done=False, done_at=None)

def ics_text(item):
    def escape(value):
        return value.replace("\\", "\\\\").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,").replace("\r", "")
    start = parse_dt(item["due"])
    def utc(value):
        return value.astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//OneToday//KO", "BEGIN:VEVENT",
             "UID:" + item["id"] + "@onetoday", "DTSTAMP:" + utc(now()),
             "DTSTART:" + utc(start), "DTEND:" + utc(start + timedelta(minutes=15)),
             "SUMMARY:" + escape(item["title"]), "DESCRIPTION:" + escape(item["memo"]),
             "BEGIN:VALARM", "TRIGGER:-PT10M", "ACTION:DISPLAY", "DESCRIPTION:할 일 확인",
             "END:VALARM", "END:VEVENT", "END:VCALENDAR"]
    # RFC 5545: UTF-8 문자를 자르지 않고 75 octet 이내로 접기.
    folded = []
    for line in lines:
        part = ""
        for char in line:
            if len((part + char).encode("utf-8")) > 75:
                folded.append(part)
                part = " "
            part += char
        folded.append(part)
    return "\r\n".join(folded) + "\r\n"

st.set_page_config(page_title="오늘 한 가지", page_icon="🌱", layout="centered")
st.markdown("""<style>
.stApp {background:#f6f8f5;color:#20372d;}
.block-container {max-width:780px;padding-top:2rem;padding-bottom:3rem;}
h1,h2,h3 {letter-spacing:-.04em;}
.stButton>button,.stDownloadButton>button {min-height:48px;border-radius:14px;}
div[data-testid="stForm"] {background:white;border-radius:20px;padding:20px;}
div[data-testid="stMetric"] {background:white;padding:16px;border-radius:16px;}
.focus {background:#e5f1e8;border:1px solid #c0d7c7;border-radius:22px;padding:24px;margin:16px 0;}
.focus small {color:#435e4e;} .focus h2 {margin:8px 0;}
@media(max-width:600px){.block-container{padding-left:1rem;padding-right:1rem;}h1{font-size:2rem;}}
</style>""", unsafe_allow_html=True)
if "tasks" not in st.session_state:
    st.session_state.tasks = []
if "undo" not in st.session_state:
    st.session_state.undo = None

def remember():
    st.session_state.undo = json.loads(json.dumps(st.session_state.tasks))

def update_done(item):
    remember()
    item["done"] = not item["done"]
    item["done_at"] = now().isoformat() if item["done"] else None
    st.rerun()

def task_card(item):
    with st.container(border=True):
        prefix = "✅ " if item["done"] else "○ "
        st.markdown("**" + prefix + html.escape(item["title"]) + "**")
        when = parse_dt(item["due"]).strftime("%H:%M") if item["due"] else "시간 없음"
        st.caption(f"{item['day']} · {when}")
        if item["memo"]:
            st.text(item["memo"])
        c1, c2 = st.columns(2)
        if c1.button("되돌리기" if item["done"] else "완료했어요", key="done_" + item["id"], use_container_width=True):
            update_done(item)
        if not item["done"] and c2.button("10분 뒤", key="later_" + item["id"], use_container_width=True):
            remember()
            snooze(item)
            st.rerun()
        with st.expander("수정 · 일정 변경 · 삭제"):
            with st.form("edit_" + item["id"]):
                title = st.text_input("할 일", value=item["title"], max_chars=100)
                day = st.date_input("날짜", value=date.fromisoformat(item["day"]))
                timed = st.checkbox("시간 지정", value=bool(item["due"]))
                clock = st.time_input("시간", value=parse_dt(item["due"]).time().replace(tzinfo=None) if item["due"] else time(9))
                memo = st.text_area("메모", value=item["memo"], max_chars=1000)
                if st.form_submit_button("수정 저장", use_container_width=True):
                    if not title.strip():
                        st.error("할 일 이름을 입력해 주세요.")
                    else:
                        remember()
                        replacement = new_task(title, day, clock if timed else None, memo)
                        replacement.update(id=item["id"], done=item["done"], done_at=item["done_at"])
                        item.update(replacement)
                        st.rerun()
            if item["due"]:
                st.download_button("휴대폰 캘린더용 일정 내려받기", ics_text(item).encode("utf-8"),
                                   file_name="todo.ics", mime="text/calendar", key="cal_" + item["id"])
                st.caption("파일을 캘린더 앱으로 가져오세요. 10분 전 알림이 포함되지만 실제 알림은 캘린더 설정에 따릅니다.")
            confirm = st.checkbox("이 할 일을 삭제할게요", key="confirm_" + item["id"])
            if st.button("삭제", key="del_" + item["id"], disabled=not confirm):
                remember()
                st.session_state.tasks = [t for t in st.session_state.tasks if t["id"] != item["id"]]
                st.rerun()

st.caption("작게 적고, 하나씩 해내요")
st.title("🌱 오늘 한 가지")
st.write("기억하려고 애쓰지 말고, 여기에 잠깐 맡겨두세요.")
st.info("이 버전은 임시 세션 저장입니다. 새로고침·접속 종료 시 기록이 사라질 수 있어요. 사용 후 ‘백업·QR’에서 백업해 주세요. 다른 기기에는 자동 동기화되지 않습니다.", icon="ℹ️")
if st.session_state.undo is not None:
    if st.button("↩ 마지막 변경 취소"):
        st.session_state.tasks = st.session_state.undo
        st.session_state.undo = None
        st.rerun()

@st.fragment(run_every="30s")
def live_notice():
    overdue = [t for t in st.session_state.tasks if not t["done"] and t["due"] and parse_dt(t["due"]) <= now()]
    if overdue:
        st.warning(f"다시 확인할 일 {len(overdue)}개가 있어요. 가장 이른 일정: {min(overdue, key=lambda x: x['due'])['title']}", icon="⏰")
    st.caption("한국 시간 기준 · 열려 있는 앱에서 약 30초마다 일정 확인. 앱을 닫거나 휴대폰을 잠그면 푸시·소리 알림은 제공되지 않습니다.")
live_notice()

today_tab, add_tab, history_tab, settings_tab = st.tabs(["🏠 오늘", "＋ 추가", "📋 전체·기록", "🔗 백업·QR"])
with today_tab:
    today = now().date().isoformat()
    todays = [t for t in st.session_state.tasks if t["day"] == today]
    finished = sum(t["done"] for t in todays)
    a, b = st.columns(2)
    a.metric("오늘의 할 일", len(todays))
    b.metric("완료", finished)
    st.progress(finished / len(todays) if todays else 0)
    pending = sorted([t for t in st.session_state.tasks if not t["done"] and t["day"] <= today], key=lambda t: (t["day"], t["due"] or "~"))
    if pending:
        first = pending[0]
        label = parse_dt(first["due"]).strftime("%m월 %d일 %H:%M") if first["due"] else first["day"] + " · 시간 없음"
        st.markdown(f'<div class="focus"><small>먼저 확인할 한 가지 · {html.escape(label)}</small><h2>{html.escape(first["title"])}</h2><small>급하게 하지 않아도 괜찮아요. 하나씩 시작해요.</small></div>', unsafe_allow_html=True)
        for item in pending:
            task_card(item)
    else:
        st.success("지금 남아 있는 오늘의 일은 없어요. 새 할 일은 ‘＋ 추가’에서 적어주세요.")
    st.caption("지난 날짜의 미완료 항목도 함께 표시합니다. 내일 이후 일정은 ‘전체·기록’에서 확인하세요.")
with add_tab:
    st.subheader("무엇을 기억해 둘까요?")
    with st.form("add", clear_on_submit=True):
        title = st.text_input("할 일 이름 *", placeholder="예: 오후에 택배 보내기", max_chars=100)
        day = st.date_input("날짜", value=now().date())
        timed = st.checkbox("시간도 정할게요", value=False)
        clock = st.time_input("예정 시간", value=time(9))
        memo = st.text_area("메모 · 준비물", placeholder="예: 신분증 챙기기", max_chars=1000)
        if st.form_submit_button("＋ 할 일 저장", type="primary", use_container_width=True):
            if not title.strip():
                st.error("할 일 이름을 입력해 주세요.")
            elif len(st.session_state.tasks) >= 3000:
                st.error("저장 한도 3,000개입니다. 백업 후 이전 항목을 정리해 주세요.")
            else:
                remember()
                st.session_state.tasks.append(new_task(title, day, clock if timed else None, memo))
                st.rerun()
with history_tab:
    st.subheader("전체 일정과 완료 기록")
    state = st.selectbox("보기", ["미완료", "완료", "전체"])
    search = st.text_input("할 일·메모 검색", max_chars=100)
    items = sorted(st.session_state.tasks, key=lambda t: (t["day"], t["due"] or "~"))
    items = [t for t in items if (state == "전체" or t["done"] == (state == "완료")) and search.casefold() in (t["title"] + " " + t["memo"]).casefold()]
    if not items:
        st.info("표시할 항목이 없어요.")
    # 탭 간 동일 항목 위젯 충돌 방지: 별도 키 네임스페이스.
    for item in items:
        with st.container(border=True):
            st.write(("✅ " if item["done"] else "○ ") + item["title"])
            st.caption(item["day"] + " · " + (parse_dt(item["due"]).strftime("%H:%M") if item["due"] else "시간 없음"))
            if item["memo"]:
                st.text(item["memo"])
            if st.button("완료 취소" if item["done"] else "완료", key="history_" + item["id"]):
                update_done(item)
            # 미래 항목도 오늘 화면에 나타나기 전에 수정 가능.
            with st.expander("날짜 변경"):
                new_day = st.date_input("이동할 날짜", date.fromisoformat(item["day"]), key="move_date_" + item["id"])
                if st.button("이 날짜로 옮기기", key="move_" + item["id"]):
                    remember()
                    item["day"] = new_day.isoformat()
                    if item["due"]:
                        item["due"] = datetime.combine(new_day, parse_dt(item["due"]).time().replace(tzinfo=None), TZ).isoformat()
                    st.rerun()
with settings_tab:
    st.subheader("기록 백업")
    backup = json.dumps({"version": 1, "exported_at": now().isoformat(), "tasks": st.session_state.tasks}, ensure_ascii=False, indent=2)
    st.download_button("💾 JSON 백업 내려받기", backup.encode("utf-8"), file_name=f"today-backup-{now():%Y%m%d}.json", mime="application/json", use_container_width=True)
    st.caption("백업 파일에는 할 일과 메모가 포함됩니다. 민감한 정보는 적지 말고 파일을 안전하게 보관하세요.")
    uploaded = st.file_uploader("이전 백업 가져오기", type=["json"])
    if uploaded is not None:
        try:
            if uploaded.size > 2_000_000:
                raise ValueError("2MB 이하의 백업을 사용해 주세요.")
            loaded = validate_backup(json.loads(uploaded.getvalue().decode("utf-8")))
            st.caption(f"검증 완료: {len(loaded)}개")
            accepted = st.checkbox("현재 목록을 이 백업으로 교체하는 데 동의합니다.")
            if st.button("백업 복원", disabled=not accepted):
                remember()
                st.session_state.tasks = loaded
                st.success("복원했어요. 오늘 또는 전체·기록 탭에서 확인하세요.")
        except (ValueError, TypeError, KeyError, OverflowError, UnicodeError):
            st.error("백업을 읽지 못했어요. 이 앱에서 내려받은 정상적인 JSON 백업인지 확인해 주세요.")
    st.divider()
    st.subheader("휴대폰 접속 QR")
    st.write("GitHub는 코드를 보관하고, Streamlit Community Cloud가 앱을 실행합니다. 배포된 앱 주소를 입력하면 접속용 QR을 만들어요.")
    url = st.text_input("배포된 앱 URL", placeholder="https://내앱이름.streamlit.app", max_chars=500)
    if url:
        parsed = urlparse(url.strip())
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or any(c.isspace() for c in url):
            st.error("로그인 정보가 포함되지 않은 올바른 HTTPS 앱 주소를 입력해 주세요.")
        else:
            try:
                image = qrcode.make(url.strip())
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                st.image(buffer.getvalue(), caption="휴대폰 카메라로 스캔해 접속하세요.", width=240)
                st.download_button("QR 이미지 내려받기", buffer.getvalue(), "today-qr.png", "image/png")
                st.caption("QR은 접속 주소만 공유합니다. 현재 할 일은 전송되지 않습니다. 다른 휴대폰에서 이어 쓰려면 백업 파일을 가져오세요.")
            except (ValueError, qrcode.exceptions.DataOverflowError):
                st.error("QR을 만들지 못했어요. 앱의 기본 주소만 입력해 주세요.")
    with st.expander("GitHub → Streamlit 배포 안내"):
        st.markdown("""1. GitHub 저장소에 **app.py**와 **requirements.txt** 두 파일을 올립니다.
2. Streamlit Community Cloud에서 GitHub 저장소를 연결합니다.
3. 실행 파일(Main file path)을 **app.py**로 선택해 배포합니다.
4. 배포된 HTTPS 주소를 위에 입력한 뒤 QR을 내려받습니다.
5. 휴대폰으로 스캔해 접속합니다. 필요하면 브라우저의 ‘홈 화면에 추가’를 사용하세요.

**주의:** GitHub Pages만으로는 Python/Streamlit 앱이 실행되지 않습니다. 이 버전은 로그인·영구 저장·기기 간 자동 동기화·백그라운드 푸시를 제공하지 않습니다. 상시 사용 서비스로 확장하려면 사용자 인증과 외부 데이터베이스를 추가해야 합니다.""")
