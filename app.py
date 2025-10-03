# app.py
import os
import re
import pandas as pd
import streamlit as st
import google.generativeai as genai
from typing import List, Tuple, Dict, Any
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# ---------- PAGE CONFIG ----------
st.set_page_config(page_title="ปลอบใจ (Chatbot)", page_icon="🙋‍♀️", layout="centered")
st.title("🙋‍♀️ ปลอบใจ · สวัสดีค่ะ")

# ---------- PROMPT ----------
try:
    from prompt import PROMPT_WORKAW  # ถ้ามีไฟล์ prompt.py
except Exception:
    PROMPT_WORKAW = (
        "You are 'ปลอบใจ', an empathetic Thai assistant. "
        "ตอบเป็นภาษาไทยที่สุภาพ อ่อนโยน ช่วยปลอบใจ ให้คำแนะนำเบื้องต้น "
        "และแนะนำแหล่งความช่วยเหลือเมื่อเหมาะสม."
    )

# ---------- API KEY ----------
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "AIzaSyDZnQReJi1TI5PCE6owFmB0w3uemCqplsM")
if not GOOGLE_API_KEY:
    st.error("ไม่พบ GOOGLE_API_KEY ใน Environment/Secrets"); st.stop()
genai.configure(api_key=GOOGLE_API_KEY)

# ---------- GEMINI CONFIG ----------
generation_config = {
    "temperature": 0.1,
    "top_p": 0.2,
    "top_k": 64,
    "max_output_tokens": 1024,
    "response_mime_type": "text/plain",
}
SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}
model = genai.GenerativeModel(
    model_name="gemini-2.0-flash",
    safety_settings=SAFETY_SETTINGS,
    generation_config=generation_config,
    system_instruction=PROMPT_WORKAW,
)

# ---------- STATIC DATASOURCE ----------
DATA_PATH = "Data_Set_Depression_Categorized.xlsx"  # วางไฟล์ไว้โฟลเดอร์เดียวกับ app.py
SHEET_QUESTION = "Question"
SHEET_2Q9Q = "2Q9Q"

def _norm_text(s: Any) -> str:
    if pd.isna(s):
        return ""
    return str(s).strip()

# ---------- FUZZY + THAI NORMALIZATION ----------
from rapidfuzz import fuzz
from pythainlp import word_tokenize
from pythainlp.util import normalize as th_normalize

def _normalize_thai(s: str) -> str:
    s = (s or "").strip()
    s = th_normalize(s)  # จัดรูปสระ-วรรณยุกต์
    return s.lower()

def _tokenize(q: str) -> List[str]:
    # ใช้ตัดคำไทย + เก็บคำอังกฤษ/ตัวเลข (ความยาว >= 2)
    toks = word_tokenize(q or "", keep_whitespace=False)
    toks = [t.lower() for t in toks if len(t.strip()) >= 2]
    return toks

@st.cache_data(show_spinner=False)
def load_static_data(path: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"ไม่พบไฟล์ '{path}' โปรดวางไฟล์ไว้ในโฟลเดอร์เดียวกับ app.py")
    sheets = pd.read_excel(path, sheet_name=[SHEET_QUESTION, SHEET_2Q9Q])
    df_q = sheets.get(SHEET_QUESTION)
    df_2q9q = sheets.get(SHEET_2Q9Q)
    if df_q is None or df_q.empty:
        raise ValueError(f"ชีต '{SHEET_QUESTION}' ว่างหรือไม่พบ")
    if df_2q9q is None or df_2q9q.empty:
        raise ValueError(f"ชีต '{SHEET_2Q9Q}' ว่างหรือไม่พบ")
    df_q = df_q.applymap(_norm_text)
    df_2q9q = df_2q9q.applymap(_norm_text)
    return df_q, df_2q9q

try:
    DF_QUESTION, DF_2Q9Q = load_static_data(DATA_PATH)
    st.info(f"📄 ใช้ข้อมูลแบบคงที่จากไฟล์ `{DATA_PATH}` (ชีต: {SHEET_QUESTION}, {SHEET_2Q9Q})")
except Exception as e:
    st.error(str(e)); st.stop()

# ---------- RETRIEVAL CONTROLS (Sidebar) ----------
with st.sidebar:
    st.subheader("🔎 การค้นหาหลักฐาน (จาก Dataset)")
    base_top_k = st.slider("จำนวนแถวสูงสุด (top_k)", 1, 10, 3, 1)
    min_hits = st.slider("เกณฑ์คำที่ตรงขั้นต่ำ/แถว", 0, 3, 1, 1,
                         help="ขั้นต่ำของจำนวนคำค้นที่ต้องพบในแถวนั้น (0 = ผ่อนคลาย)")
    auto_expand = st.checkbox("Auto-expand เมื่อคำถามคลุมเครือ", value=True,
                              help="ถ้าคำถามสั้น/คลุมเครือ จะขยาย top_k อัตโนมัติ (สูงสุด 10)")
    similarity_threshold = st.slider("เกณฑ์ความคล้าย (fuzzy) ขั้นต่ำ", 0, 100, 55, 1,
                                     help="ต่ำกว่าเกณฑ์นี้ถือว่าไม่พบ match ชัดเจน (จะถือว่า AI-generated)")

# ---------- เตรียมคอร์ปัสสำหรับค้นหา ----------
@st.cache_data(show_spinner=False)
def build_search_corpus(df_q: pd.DataFrame, df_2q9q: pd.DataFrame):
    def build(df, sheet_name):
        rows = []
        for i, row in df.iterrows():
            text_by_col = {c: _normalize_thai(str(row[c])) for c in df.columns}
            joined = " ".join(text_by_col.values())
            rows.append({
                "sheet": sheet_name,
                "row_idx": i,
                "text_joined": joined,
                "by_col": text_by_col,
                "cols": list(df.columns),
            })
        return rows
    return build(DF_QUESTION, SHEET_QUESTION), build(DF_2Q9Q, SHEET_2Q9Q)

CORPUS_Q, CORPUS_2Q9Q = build_search_corpus(DF_QUESTION, DF_2Q9Q)

def search_relevant_rows(
    query: str, base_top_k: int = 3, min_hits: int = 1, auto_expand: bool = True, sim_threshold: int = 55
) -> Tuple[List[Dict], str]:
    """
    คืนค่า:
      - sources: [{sheet, row_1based, columns:[...]}]
      - evidence_text: ข้อความอ้างอิงย่อสำหรับส่งเข้าโมเดล
    กลไกให้คะแนน:
      score = (keyword_hits) + 0.5 * (fuzzy_token_set_ratio/100) + 0.2 * (#cols_hit)
    """
    q_norm = _normalize_thai(query)
    tokens = _tokenize(q_norm)
    if not tokens:
        return [], ""

    eff_top_k = base_top_k
    if auto_expand and len(tokens) <= 2:  # คำถามคลุมเครือ (สั้น/คำค้นน้อย)
        eff_top_k = min(10, base_top_k * 2)

    def score_row(entry):
        text_all = entry["text_joined"]
        fuzzy_score = fuzz.token_set_ratio(q_norm, text_all)
        hits = sum(1 for t in tokens if t in text_all)
        if hits < min_hits and fuzzy_score < sim_threshold:
            return None
        cols_hit = [c for c, v in entry["by_col"].items() if any(t in v for t in tokens)]
        score = hits + 0.5 * (fuzzy_score / 100.0) + 0.2 * len(cols_hit)
        return {
            "score": score,
            "fuzzy": fuzzy_score,
            "hits": hits,
            "cols_hit": cols_hit,
            "sheet": entry["sheet"],
            "row_idx": entry["row_idx"],
            "by_col": entry["by_col"],
        }

    scored = []
    for e in CORPUS_Q + CORPUS_2Q9Q:
        r = score_row(e)
        if r is not None:
            scored.append(r)

    scored.sort(key=lambda x: (x["score"], x["fuzzy"], x["hits"]), reverse=True)
    scored = scored[:eff_top_k]

    sources, evidence_blocks = [], []
    for r in scored:
        by_col = r["by_col"]
        show_cols = r["cols_hit"][:4] if r["cols_hit"] else list(by_col.keys())[:3]
        lines = [f"{c}: {by_col[c]}" for c in show_cols]
        sources.append({
            "sheet": r["sheet"],
            "row_1based": r["row_idx"] + 1,
            "columns": show_cols,
        })
        evidence_blocks.append(
            f"[SOURCE sheet={r['sheet']} row={r['row_idx']+1} cols={', '.join(show_cols)} "
            f"fuzzy={r['fuzzy']} hits={r['hits']}]"
            "\n" + "\n".join(lines)
        )

    evidence_text = ""
    if evidence_blocks:
        evidence_text = "ต่อไปนี้คือข้อมูลอ้างอิงจากชุดข้อมูล (สรุปย่อ):\n" + "\n\n".join(evidence_blocks)
    return sources, evidence_text

def format_sources_for_user(sources: List[Dict]) -> str:
    if not sources:
        return "ที่มา: ตอบโดยโมเดล (AI-generated) — ไม่พบแถวที่ตรงใน Dataset"
    items = [
        f"- Sheet **{s['sheet']}** · Row **{s['row_1based']}** · Cols **{', '.join(s['columns'])}**"
        for s in sources
    ]
    return "ที่มา (อ้างอิงจาก Dataset):\n" + "\n".join(items)

# ---------- SIDEBAR: Tools ----------
def clear_history():
    st.session_state["messages"] = [
        {"role": "model", "content": "ปลอบใจ สวัสดีค่ะ วันนี้เป็นอย่างไรบ้าง อยากให้ช่วยเรื่องอะไรบอกได้นะคะ 💛"}
    ]
    st.rerun()

with st.sidebar:
    st.divider()
    if st.button("🧹 ล้างประวัติแชท"):
        clear_history()
    st.caption("บอทจะระบุ Row/Column ถ้าคำตอบอ้างอิงจาก Dataset")

# ---------- INIT CHAT ----------
if "messages" not in st.session_state:
    st.session_state["messages"] = [
        {
            "role": "model",
            "content": "ปลอบใจ สวัสดีค่ะ วันนี้เป็นอย่างไรบ้างให้ปลอบใจช่วยด้านไหนดีคะ "
                       "ทำแบบประเมินอาการซึมเศร้า หรือ ปรึกษาปัญหาซึมเศร้าไหมคะ ?"
        },
    ]

# ---------- SHOW HISTORY ----------
for m in st.session_state["messages"]:
    with st.chat_message("assistant" if m["role"] == "model" else "user"):
        st.write(m["content"])

# ---------- CHAT LOOP ----------
if prompt := st.chat_input("พิมพ์ข้อความถึงปลอบใจ..."):
    st.session_state["messages"].append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    try:
        # 1) หาแหล่งข้อมูลจาก Dataset ก่อน
        sources, evidence_text = search_relevant_rows(
            query=prompt,
            base_top_k=base_top_k,
            min_hits=min_hits,
            auto_expand=auto_expand,
            sim_threshold=similarity_threshold
        )

        # 2) สร้าง history สำหรับโมเดล
        history = [{"role": m["role"], "parts": [{"text": m["content"]}]} for m in st.session_state["messages"]]

        # ถ้ามีหลักฐานจาก Dataset ให้แทรกเป็นบริบท
        if evidence_text:
            insert_at = min(1, len(history))  # อย่าทับ system_instruction
            history.insert(insert_at, {"role": "user", "parts": [{"text": evidence_text}]})

        # 3) เรียกโมเดล (ยกเว้นคำสั่ง 'add')
        norm = prompt.strip().lower()
        if norm.startswith("add") or norm.endswith("add"):
            reply = "ขอบคุณสำหรับคำแนะนำค่ะ"
        else:
            chat_session = model.start_chat(history=history)
            response = chat_session.send_message(prompt)
            reply = response.text

        # 4) แสดงผลลัพธ์ + ส่วน 'ที่มา'
        st.session_state["messages"].append({"role": "model", "content": reply})
        with st.chat_message("assistant"):
            st.write(reply)
            st.caption(format_sources_for_user(sources))

    except Exception as e:
        st.error(f"เกิดข้อผิดพลาด: {e}")
