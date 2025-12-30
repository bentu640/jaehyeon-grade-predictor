import streamlit as st
import pandas as pd
import json
import plotly.graph_objects as go
from supabase import create_client, Client

# ==========================================
# 0. 기본 설정
# ==========================================
st.set_page_config(page_title="재현고 내신 등급컷 예측 시스템", page_icon="📈")

@st.cache_resource
def init_supabase():
    try:
        if "SUPABASE_URL" in st.secrets and "SUPABASE_KEY" in st.secrets:
            return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
        return None
    except:
        return None

supabase = init_supabase()

# 과목 데이터
SUBJECT_CONFIG = {
    "국어(1학년)": {"obj": 24, "sub": 6}, "영어(1학년)": {"obj": 22, "sub": 5}, "수학(1학년)": {"obj": 17, "sub": 5},
    "통합사회": {"obj": 24, "sub": 6}, "통합과학": {"obj": 22, "sub": 5}, "한국사": {"obj": 20, "sub": 8},
    "대수": {"obj": 17, "sub": 5}, "미적분1": {"obj": 17, "sub": 5}, "확률과 통계": {"obj": 17, "sub": 5},
    "수학과제탐구": {"obj": 17, "sub": 5}, "국어(2학년)": {"obj": 24, "sub": 6}, "영어(2학년)": {"obj": 22, "sub": 8},
    "물리": {"obj": 20, "sub": 6}, "화학": {"obj": 20, "sub": 6}, "생물": {"obj": 20, "sub": 6}, "지구": {"obj": 20, "sub": 6},
    "사회문화": {"obj": 20, "sub": 8}, "윤리": {"obj": 25, "sub": 5}, "지리": {"obj": 20, "sub": 6}, "역사": {"obj": 20, "sub": 6},
    "중국어": {"obj": 28, "sub": 0}, "일본어": {"obj": 28, "sub": 0},
    "독서와 작문": {"obj": 24, "sub": 6}, "영어 독해와 작문": {"obj": 22, "sub": 8}, "전문 수학": {"obj": 17, "sub": 5},
    "언어생활탐구": {"obj": 24, "sub": 6}, "경제수학": {"obj": 17, "sub": 5}, "미적분2": {"obj": 17, "sub": 5},
    "심화 영어": {"obj": 22, "sub": 8}, "경제": {"obj": 20, "sub": 8}, "한국지리 탐구": {"obj": 20, "sub": 6},
    "동아시아 역사 기행": {"obj": 20, "sub": 6}, "윤리와 사상": {"obj": 25, "sub": 5}, "전자기와 양자": {"obj": 20, "sub": 6},
    "화학 반응의 세계": {"obj": 19, "sub": 6}, "생물의 유전": {"obj": 20, "sub": 6}, "행성우주과학": {"obj": 20, "sub": 6}
}

GRADE_SUBJECTS = {
    "1학년": ["국어(1학년)", "영어(1학년)", "수학(1학년)", "통합사회", "통합과학", "한국사"],
    "2학년": ["대수", "미적분1", "확률과 통계", "수학과제탐구", "국어(2학년)", "영어(2학년)", "물리", "화학", "생물", "지구", "사회문화", "윤리", "지리", "역사", "중국어", "일본어"],
    "3학년": ["독서와 작문", "영어 독해와 작문", "전문 수학", "언어생활탐구", "경제수학", "미적분2", "심화 영어", "경제", "한국지리 탐구", "동아시아 역사 기행", "윤리와 사상", "전자기와 양자", "화학 반응의 세계", "생물의 유전", "행성우주과학"]
}

# ----------------------------------
# DB 헬퍼 함수
# ----------------------------------
def get_sys_config():
    if not supabase: return {"current_round": 1, "exam_closed": False, "term_end_mode": False}
    try:
        res = supabase.table("system_config").select("value").eq("key", "config").execute()
        if res.data: 
            conf = res.data[0]['value']
            if "term_end_mode" not in conf: conf["term_end_mode"] = False
            return conf
    except: pass
    return {"current_round": 1, "exam_closed": False, "term_end_mode": False}

def save_sys_config(conf):
    if supabase:
        supabase.table("system_config").upsert({"key": "config", "value": conf}).execute()

def get_subject_setting(sub, round_num):
    if not supabase: return {}
    try:
        res = supabase.table("subject_settings").select("settings").eq("subject", sub).eq("round", round_num).execute()
        if res.data: 
            s = res.data[0]['settings']
            if "term_mid_cuts" not in s: s["term_mid_cuts"] = {"1": 90.0, "2": 80.0, "3": 70.0}
            if "term_adj" not in s or isinstance(s["term_adj"], float):
                s["term_adj"] = {"1": 0.0, "2": 0.0, "3": 0.0}
            return s
    except: pass
    
    conf = SUBJECT_CONFIG.get(sub, {"obj": 20, "sub": 0})
    return {
        "active": False, 
        "obj_answers": [1] * conf["obj"], "obj_scores": [3.0] * conf["obj"],
        "sub_criteria": ["채점 기준"] * conf["sub"], "sub_max_scores": [5.0] * conf["sub"],
        "prev_avg": 60.0, "prev_cuts": {"1": 90.0, "2": 80.0, "3": 70.0},
        "cut_weights": {"1": 1.0, "2": 1.2, "3": 1.5},
        "dev_predict": {"1": 95, "2": 85, "3": 75, "4": 65, "5": 55},
        "homer_mode": False, "homer_adj": {"1": 0.0, "2": 0.0, "3": 0.0},
        "term_mid_cuts": {"1": 90.0, "2": 80.0, "3": 70.0},
        "term_adj": {"1": 0.0, "2": 0.0, "3": 0.0}
    }

# ----------------------------------
# 예측 및 랭킹 알고리즘
# ----------------------------------
def get_prediction(sub_name, round_num):
    d = get_subject_setting(sub_name, round_num)
    res = supabase.table("submissions").select("total, prev_grade").eq("subject", sub_name).eq("round", round_num).execute()
    df = pd.DataFrame(res.data)
    
    if df.empty: 
        raw_cuts = d["prev_cuts"]
    else:
        g_avgs = {}
        for g in range(1, 6):
            target = df[df['prev_grade'] == g]
            g_avgs[g] = target['total'].mean() if not target.empty else float(d["dev_predict"][str(g)])
        cur_avg = (g_avgs[1]*0.1 + g_avgs[2]*0.24 + g_avgs[3]*0.32 + g_avgs[4]*0.24 + g_avgs[5]*0.1)
        delta = cur_avg - d["prev_avg"]
        raw_cuts = {g: round(d["prev_cuts"][g] + (delta * d["cut_weights"][g]), 1) for g in ["1", "2", "3"]}
    
    homer_cuts = raw_cuts.copy()
    if d.get("homer_mode", False):
        adj = d["homer_adj"]
        homer_cuts = {
            "1": raw_cuts["1"] + adj["1"], "2": raw_cuts["2"] + adj["2"], "3": raw_cuts["3"] + adj["3"]
        }
        is_homer = True
    else:
        is_homer = False
        
    return raw_cuts, homer_cuts, len(df), is_homer

def get_term_prediction(sub_name, round_num, current_exam_cuts):
    d = get_subject_setting(sub_name, round_num)
    mid_cuts = d.get("term_mid_cuts", {"1": 90, "2": 80, "3": 70})
    adj = d.get("term_adj", {"1": 0.0, "2": 0.0, "3": 0.0})
    if isinstance(adj, float): adj = {"1": adj, "2": adj, "3": adj}

    term_cuts = {}
    for g in ["1", "2", "3"]:
        final_cut = current_exam_cuts[g]
        val = (final_cut * 0.3) + (mid_cuts[g] * 0.3) + 40 + adj[g]
        term_cuts[g] = round(val, 2)
    return term_cuts

def get_my_rank(sub_name, my_score, round_num):
    res = supabase.table("submissions").select("total").eq("subject", sub_name).eq("round", round_num).execute()
    valid_scores = [r['total'] for r in res.data if r['total'] is not None]
    scores = sorted(valid_scores, reverse=True)
    try: 
        rank = scores.index(my_score) + 1
        tied = scores.count(my_score)
        return rank, tied, len(scores)
    except: 
        return 0, 0, len(scores)

def get_my_term_rank(sub_name, my_term_total, round_num):
    res = supabase.table("submissions").select("total, mid_score, perf_score").eq("subject", sub_name).eq("round", round_num).execute()
    term_scores = []
    for r in res.data:
        if r['total'] is not None and r.get('mid_score') is not None and r.get('perf_score') is not None:
            score = (r['total'] * 0.3) + (r['mid_score'] * 0.3) + r['perf_score']
            term_scores.append(round(score, 2))
    
    term_scores.sort(reverse=True)
    try:
        my_val = round(my_term_total, 2)
        rank = term_scores.index(my_val) + 1
        tied = term_scores.count(my_val)
        return rank, tied, len(term_scores)
    except:
        return 0, 0, len(term_scores)

# 세션 초기화
if "init" not in st.session_state:
    st.session_state.page = "login"
    st.session_state.signup_step = 1
    st.session_state.signup_info = {}
    st.session_state.user = None
    st.session_state.init = True

# ==========================================
# 페이지 라우팅
# ==========================================

# 1. 로그인
if st.session_state.page == "login":
    st.title("📈 재현고 내신 등급컷 예측 시스템")
    t1, t2 = st.tabs(["로그인", "회원가입"])
    with t1:
        lid = st.text_input("ID", key="l_id"); lpw = st.text_input("PW", type="password", key="l_pw")
        if st.button("로그인"):
            if not supabase: st.error("DB 연결 실패"); st.stop()
            res = supabase.table("users").select("*").eq("username", lid).execute()
            if res.data and str(res.data[0]["password"]) == str(lpw):
                u = res.data[0]
                sys_conf = get_sys_config()
                st.session_state.update({"user": lid, "role": u["role"], "grade": u["grade"], "prev_grades": u["prev_grades"]})
                
                last_conf = u.get("last_confirmed_round", 1)
                curr_round = sys_conf["current_round"]
                if curr_round > 1 and last_conf < curr_round: st.session_state.page = "update_grades"
                else: st.session_state.page = "main"
                st.rerun()
            else: st.error("로그인 실패")
    with t2:
        if st.session_state.signup_step == 1:
            st.session_state.signup_info["grade"] = st.radio("학년", ["1학년", "2학년", "3학년"], key="su_g")
            if st.button("다음"): st.session_state.signup_step = 2; st.rerun()
        elif st.session_state.signup_step == 2:
            s_n = st.text_input("닉네임"); s_p = st.text_input("비번", type="password")
            gr = st.session_state.signup_info["grade"]
            subs = GRADE_SUBJECTS.get(gr, [])
            sel = st.multiselect("수강 과목", subs)
            pg = {s: min(5, st.number_input(f"{s} 직전 등급 (1~5)", 1, 5, 3, key=f"p_{s}")) for s in sel}
            if st.button("가입"):
                if not supabase: st.error("DB 연결 실패"); st.stop()
                chk = supabase.table("users").select("username").eq("username", s_n).execute()
                if chk.data: st.error("이미 사용 중인 아이디입니다.")
                else:
                    sys_conf = get_sys_config()
                    supabase.table("users").insert({"username": s_n, "password": s_p, "role": "user", "grade": gr, "prev_grades": pg, "last_confirmed_round": sys_conf["current_round"]}).execute()
                    st.session_state.signup_step = 1; st.success("가입 완료!"); st.rerun()

# 2. 등급 강제 업데이트
elif st.session_state.page == "update_grades":
    sys_conf = get_sys_config()
    st.title("🆙 이전 시험 등급 확정")
    st.warning(f"📢 현재 **{sys_conf['current_round']}회차** 시험 기간입니다.\n정확한 등급 예측을 위해 **직전 시험의 실제 등급**을 입력해야 넘어갈 수 있습니다.")
    with st.form("force_update_form"):
        new_pg = {}
        current_subs = list(st.session_state.prev_grades.keys())
        for s in current_subs:
            val = st.number_input(f"{s} 성적표 등급 (1~9)", 1, 9, 3, key=f"up_{s}")
            new_pg[s] = min(5, val)
        if st.form_submit_button("✅ 저장하고 메인으로 이동"):
            supabase.table("users").update({"prev_grades": new_pg, "last_confirmed_round": sys_conf["current_round"]}).eq("username", st.session_state.user).execute()
            last_round = sys_conf["current_round"] - 1
            if last_round > 0:
                for sub, grade in new_pg.items():
                    chk = supabase.table("submissions").select("*").eq("username", st.session_state.user).eq("subject", sub).eq("round", last_round).execute()
                    if chk.data: supabase.table("submissions").update({"final_grade": grade}).eq("username", st.session_state.user).eq("subject", sub).eq("round", last_round).execute()
                    else: supabase.table("submissions").insert({"username": st.session_state.user, "subject": sub, "round": last_round, "total": None, "final_grade": grade}).execute()
            st.session_state.prev_grades = new_pg; st.session_state.page = "main"; st.success("업데이트 완료!"); st.rerun()

elif st.session_state.page == "main":
    user, role = st.session_state.user, st.session_state.role
    sys_conf = get_sys_config()
    cur_round = sys_conf["current_round"]
    
    st.sidebar.title(f"👤 {user}")
    st.sidebar.info(f"현재 시험: {cur_round}회차")
    if sys_conf["term_end_mode"]: st.sidebar.success("💯 학기말 모드 ON")
    if st.sidebar.button("🔄 새로고침"): st.rerun()
    if st.sidebar.button("로그아웃"): st.session_state.page = "login"; st.rerun()

    if role == "admin":
        st.header("🛠 관리자 모드")
        t1, t2, t3 = st.tabs(["과목 설정", "시스템 설정", "데이터 추출"])
        
        with t1:
            sel_sub = st.selectbox("과목 선택", list(SUBJECT_CONFIG.keys()))
            d = get_subject_setting(sel_sub, cur_round)
            st.write(f"### {cur_round}회차 {sel_sub} 설정")
            c1, c2 = st.columns(2)
            act = c1.checkbox("채점 활성화", value=d["active"], key=f"act_{sel_sub}")
            hom = c2.checkbox("😈 호머 보정 켜기", value=d.get("homer_mode", False), key=f"hom_{sel_sub}")
            
            # [수정] 관리자 입력 폼: 모든 number_input의 min/max 제한 제거 (value와 step만 사용)
            with st.form(f"admin_f_{sel_sub}"):
                d["active"] = act
                d["homer_mode"] = hom
                d["prev_avg"] = st.number_input("지난 평균", value=float(d["prev_avg"]), step=0.1, key=f"pa_{sel_sub}")
                
                st.divider()
                st.markdown("#### 📅 학기말 예측 설정 (중간고사 컷 입력)")
                tmc = st.columns(3)
                d["term_mid_cuts"]["1"] = tmc[0].number_input("중간 1컷", value=float(d["term_mid_cuts"]["1"]), step=0.1, key=f"tm1_{sel_sub}")
                d["term_mid_cuts"]["2"] = tmc[1].number_input("중간 2컷", value=float(d["term_mid_cuts"]["2"]), step=0.1, key=f"tm2_{sel_sub}")
                d["term_mid_cuts"]["3"] = tmc[2].number_input("중간 3컷", value=float(d["term_mid_cuts"]["3"]), step=0.1, key=f"tm3_{sel_sub}")
                
                st.caption("등급별 변동 보정치 (음수 가능)")
                tadj = st.columns(3)
                d["term_adj"]["1"] = tadj[0].number_input("1컷 보정", value=float(d["term_adj"]["1"]), step=0.1, key=f"ta1_{sel_sub}")
                d["term_adj"]["2"] = tadj[1].number_input("2컷 보정", value=float(d["term_adj"]["2"]), step=0.1, key=f"ta2_{sel_sub}")
                d["term_adj"]["3"] = tadj[2].number_input("3컷 보정", value=float(d["term_adj"]["3"]), step=0.1, key=f"ta3_{sel_sub}")
                st.divider()

                if hom:
                    st.info("😈 호머 보정치")
                    hc = st.columns(3)
                    d["homer_adj"] = {
                        "1": hc[0].number_input("1컷+", value=float(d["homer_adj"]["1"]), step=0.1, key=f"ha1_{sel_sub}"), 
                        "2": hc[1].number_input("2컷+", value=float(d["homer_adj"]["2"]), step=0.1, key=f"ha2_{sel_sub}"), 
                        "3": hc[2].number_input("3컷+", value=float(d["homer_adj"]["3"]), step=0.1, key=f"ha3_{sel_sub}")
                    }
                
                st.write("#### 1. 등급컷 기준 (W: 가중치, 전: 전년도)")
                c = st.columns(3)
                d["cut_weights"] = {
                    "1": c[0].number_input("1W", value=float(d["cut_weights"]["1"]), step=0.01, key=f"cw1_{sel_sub}"),
                    "2": c[1].number_input("2W", value=float(d["cut_weights"]["2"]), step=0.01, key=f"cw2_{sel_sub}"),
                    "3": c[2].number_input("3W", value=float(d["cut_weights"]["3"]), step=0.01, key=f"cw3_{sel_sub}")
                }
                cc = st.columns(3)
                d["prev_cuts"] = {
                    "1": cc[0].number_input("전1컷", value=float(d["prev_cuts"]["1"]), step=0.1, key=f"pc1_{sel_sub}"),
                    "2": cc[1].number_input("전2컷", value=float(d["prev_cuts"]["2"]), step=0.1, key=f"pc2_{sel_sub}"),
                    "3": cc[2].number_input("전3컷", value=float(d["prev_cuts"]["3"]), step=0.1, key=f"pc3_{sel_sub}")
                }
                
                st.write("#### 2. 이번 시험 예상 평균")
                gc = st.columns(5)
                for i in range(1, 6): 
                    d["dev_predict"][str(i)] = gc[i-1].number_input(f"{i}등급 평균", value=float(d["dev_predict"][str(i)]), step=0.1, key=f"dp_{i}_{sel_sub}")

                st.write("#### 3. 정답 및 배점")
                for i in range(0, SUBJECT_CONFIG[sel_sub]["obj"], 4):
                    cols = st.columns(4)
                    for j in range(4):
                        idx = i+j
                        if idx < SUBJECT_CONFIG[sel_sub]["obj"]:
                            d["obj_answers"][idx] = cols[j].selectbox(f"Q{idx+1}", [1,2,3,4,5], index=d["obj_answers"][idx]-1, key=f"ans_{sel_sub}_{idx}")
                            # [수정] 배점 제한 제거
                            d["obj_scores"][idx] = cols[j].number_input(f"Q{idx+1}점", value=float(d["obj_scores"][idx]), step=0.1, key=f"sco_{sel_sub}_{idx}")
                
                if SUBJECT_CONFIG[sel_sub]["sub"] > 0:
                    st.write("#### 4. 서술형 설정")
                    for k in range(SUBJECT_CONFIG[sel_sub]["sub"]):
                        d["sub_criteria"][k] = st.text_input(f"서술{k+1}기준", d["sub_criteria"][k], key=f"scri_{sel_sub}_{k}")
                        # [수정] 만점 제한 제거
                        d["sub_max_scores"][k] = st.number_input(f"서술{k+1}만점", value=float(d["sub_max_scores"][k]), step=0.1, key=f"smax_{sel_sub}_{k}")
                
                if st.form_submit_button("✅ 과목 설정 저장"):
                    supabase.table("subject_settings").upsert({"subject": sel_sub, "round": cur_round, "settings": d}).execute()
                    st.success("저장 완료!")

        with t2:
            with st.form("sys_form"):
                st.write(f"현재 시험 회차: **{cur_round}회**")
                col_sys1, col_sys2 = st.columns(2)
                is_closed = col_sys1.checkbox("⛔ 채점 종료 (실제 등급 입력 모드)", value=sys_conf["exam_closed"])
                is_term_mode = col_sys2.checkbox("💯 학기말 모드 켜기 (중간+기말+수행)", value=sys_conf["term_end_mode"])
                
                if st.form_submit_button("설정 적용"):
                    sys_conf["exam_closed"] = is_closed
                    sys_conf["term_end_mode"] = is_term_mode
                    save_sys_config(sys_conf)
                    st.success("적용됨")
            
            st.divider()
            if st.button("🚀 새 시험 시작 (회차 증가)"):
                sys_conf["current_round"] += 1
                sys_conf["exam_closed"] = False
                sys_conf["term_end_mode"] = False
                save_sys_config(sys_conf)
                st.success(f"{sys_conf['current_round']}회차 시험이 시작되었습니다!"); st.rerun()

        with t3:
            r_sel = st.number_input("추출할 회차", 1, cur_round, cur_round)
            if st.button("데이터 추출"):
                res = supabase.table("submissions").select("*").eq("round", r_sel).execute()
                if res.data:
                    df = pd.DataFrame(res.data)
                    st.dataframe(df); st.download_button("다운로드", df.to_csv().encode('utf-8-sig'), f"round_{r_sel}.csv")

    else:
        # 학생 모드
        my_subs = list(st.session_state.prev_grades.keys())
        tabs = st.tabs(my_subs + ["종합 성적표"])
        
        for i, sub in enumerate(my_subs):
            with tabs[i]:
                if sys_conf["exam_closed"]: st.info("⛔ 채점이 종료되었습니다. 성적표 탭에서 실제 등급을 입력하세요."); continue
                d = get_subject_setting(sub, cur_round)
                if not d.get("active"): st.warning("비공개 상태"); continue
                
                my_sub = supabase.table("submissions").select("*").eq("username", user).eq("subject", sub).eq("round", cur_round).execute()
                is_sub, edit_mode = len(my_sub.data) > 0, st.session_state.get(f"ed_{sub}", False)
                
                if is_sub and not edit_mode:
                    row = my_sub.data[0]
                    raw, homer, cnt, is_h = get_prediction(sub, cur_round)
                    rank, tied, tot = get_my_rank(sub, row['total'], cur_round)
                    
                    rank_msg = f"{rank}등 / {tot}명"
                    if tied > 1: rank_msg = f"{rank}등 (동점 {tied}명) / {tot}명"
                    
                    st.info(f"🏆 점수: {row['total']}점 ({rank_msg})")
                    c1, c2 = st.columns(2)
                    c1.success(f"📊 실시간 컷\n1등급: {raw['1']}\n2등급: {raw['2']}\n3등급: {raw['3']}")
                    if is_h: c2.error(f"😈 호머 컷\n1등급: {homer['1']}\n2등급: {homer['2']}\n3등급: {homer['3']}")
                    
                    target = homer if is_h else raw
                    fig = go.Figure(go.Indicator(mode="gauge+number", value=row['total'], gauge={'axis': {'range': [0, 100]}, 'steps': [{'range': [0, target['3']], 'color': "#ffdede"}, {'range': [target['3'], target['2']], 'color': "#fff5de"}, {'range': [target['2'], target['1']], 'color': "#deffde"}, {'range': [target['1'], 100], 'color': "#e5deff"}]}))
                    st.plotly_chart(fig, use_container_width=True)

                    if st.button("수정", key=f"re_{sub}"): st.session_state[f"ed_{sub}"] = True; st.rerun()

                    # [학기말 모드 표시]
                    if sys_conf["term_end_mode"]:
                        st.divider()
                        st.subheader("💯 학기말 최종 등급 예측")
                        st.caption("중간고사 점수와 수행평가 점수를 입력하세요.")
                        
                        prev_mid = row.get('mid_score') or 0.0
                        prev_perf = row.get('perf_score') or 0.0
                        
                        with st.form(f"term_{sub}"):
                            c_t1, c_t2 = st.columns(2)
                            in_mid = c_t1.number_input("중간고사 점수", 0.0, 100.0, float(prev_mid), key=f"im_{sub}")
                            in_perf = c_t2.number_input("수행평가 (40점 만점)", 0.0, 40.0, float(prev_perf), key=f"ip_{sub}")
                            
                            if st.form_submit_button("결과 확인"):
                                supabase.table("submissions").update({"mid_score": in_mid, "perf_score": in_perf}).eq("username", user).eq("subject", sub).eq("round", cur_round).execute()
                                st.success("저장됨"); st.rerun()
                        
                        if row.get('mid_score') is not None:
                            term_cuts = get_term_prediction(sub, cur_round, target)
                            my_term_score = round((row['total']*0.3) + (row['mid_score']*0.3) + row['perf_score'], 2)
                            
                            t_rank, t_tied, t_tot = get_my_term_rank(sub, my_term_score, cur_round)
                            t_rank_msg = f"{t_rank}등 / {t_tot}명"
                            if t_tied > 1: t_rank_msg = f"{t_rank}등 (동점 {t_tied}명) / {t_tot}명"
                            
                            if my_term_score >= term_cuts['1']: t_grade = "1등급"
                            elif my_term_score >= term_cuts['2']: t_grade = "2등급"
                            elif my_term_score >= term_cuts['3']: t_grade = "3등급"
                            else: t_grade = "4등급 이하"
                            
                            st.markdown(f"""
                            <div style="background-color:#f0f2f6; padding:15px; border-radius:10px;">
                                <h4>🏁 학기말 예측: <span style="color:blue">{t_grade}</span></h4>
                                <p>환산 점수: <b>{my_term_score}점</b> (석차: {t_rank_msg})</p>
                                <small>1컷: {term_cuts['1']} / 2컷: {term_cuts['2']} / 3컷: {term_cuts['3']}</small>
                            </div>
                            """, unsafe_allow_html=True)

                else:
                    with st.form(f"f_{sub}"):
                        prev = my_sub.data[0] if is_sub else {}
                        def_m = prev.get('marks', [1]*SUBJECT_CONFIG[sub]["obj"])
                        def_s = prev.get('sub_vals', [0.0]*SUBJECT_CONFIG[sub]["sub"])
                        st.write("#### 객관식")
                        marks = [st.columns(6)[idx%6].selectbox(f"{idx+1}",[1,2,3,4,5],index=int(def_m[idx])-1, key=f"m_{sub}_{idx}") for idx in range(SUBJECT_CONFIG[sub]["obj"])]
                        
                        sub_vals = []
                        if SUBJECT_CONFIG[sub]["sub"] > 0:
                            st.write("#### 서술형")
                            for k in range(SUBJECT_CONFIG[sub]["sub"]):
                                v = st.number_input(f"서술{k+1} (기준:{d['sub_criteria'][k]})", 0.0, d['sub_max_scores'][k], float(def_s[k]), key=f"s_{sub}_{k}")
                                sub_vals.append(v)
                        
                        if st.form_submit_button("제출"):
                            op = sum(d["obj_scores"][x] for x, m in enumerate(marks) if m==d["obj_answers"][x])
                            supabase.table("submissions").upsert({"username":user, "subject":sub, "round":cur_round, "total":op+sum(sub_vals), "prev_grade":st.session_state.prev_grades[sub], "marks":marks, "sub_vals":sub_vals}).execute()
                            st.session_state[f"ed_{sub}"] = False; st.rerun()
        
        with tabs[-1]:
            st.header("📋 종합 성적표")
            view_round = st.selectbox("회차 선택", range(cur_round, 0, -1))
            
            if sys_conf["exam_closed"] and view_round == cur_round:
                st.write("📢 실제 등급을 입력하여 다음 예측 정확도를 높이세요.")
                with st.form("real_grade"):
                    new_pg = {}
                    for s in my_subs:
                        default_val = st.session_state.prev_grades.get(s, 5)
                        val = st.number_input(f"{s} 확정 등급 (1~9)", 1, 9, int(default_val), key=f"real_{s}")
                        new_pg[s] = min(5, val)
                    
                    if st.form_submit_button("저장"):
                        supabase.table("users").update({"prev_grades": new_pg, "last_confirmed_round": sys_conf["current_round"]}).eq("username", user).execute()
                        for sub, grade in new_pg.items():
                            chk = supabase.table("submissions").select("*").eq("username", user).eq("subject", sub).eq("round", cur_round).execute()
                            if chk.data: supabase.table("submissions").update({"final_grade": grade}).eq("username", user).eq("subject", sub).eq("round", cur_round).execute()
                            else: supabase.table("submissions").insert({"username": user, "subject": sub, "round": cur_round, "total": None, "final_grade": grade}).execute()
                        st.session_state.prev_grades = new_pg; st.success("저장됨"); st.balloons()
            else:
                res = supabase.table("submissions").select("*").eq("username", user).eq("round", view_round).execute()
                rows = []
                for r in res.data:
                    final_g = r.get('final_grade')
                    if final_g:
                        grade_display = f"{final_g}등급 (확정)"
                        score_display = f"{r['total']}점" if r['total'] is not None else "-"
                    else:
                        if r['total'] is not None:
                            raw, homer, _, is_h = get_prediction(r['subject'], view_round)
                            cuts = homer if is_h else raw
                            grade_val = "1" if r['total']>=cuts['1'] else "2" if r['total']>=cuts['2'] else "3" if r['total']>=cuts['3'] else "4↓"
                            grade_display = f"{grade_val}등급 (예측)"
                            score_display = f"{r['total']}점"
                        else: continue
                    rows.append({"과목":r['subject'], "점수":score_display, "등급":grade_display})
                if rows: st.table(pd.DataFrame(rows))
                else: st.info("기록이 없습니다.")