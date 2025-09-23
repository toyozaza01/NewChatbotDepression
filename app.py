import os
import pandas as pd
import streamlit as st
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# ---- ถ้ามีไฟล์ prompt.py ให้ import ตามเดิม ----
try:
    from prompt import PROMPT_WORKAW
except Exception:
    PROMPT_WORKAW = "You are a helpful, empathetic Thai assistant."

# ---- Streamlit page setup ----
st.set_page_config(page_title="ปลอบใจ (Chatbot)", page_icon="🙋‍♀️", layout="centered")
st.title("🙋‍♀️ ปลอบใจ  สวัสดีค่ะ")

# ---- Load secrets (สำคัญมาก) ----
GOOGLE_API_KEY = st.secrets.get("GOOGLE_API_KEY", os.getenv("GOOGLE_API_KEY", ""))
if not GOOGLE_API_KEY:
    st.error("ไม่พบ GOOGLE_API_KEY ใน Secrets (Settings → Secrets) หรือ Environment Variable")
    st.stop()

genai.configure(api_key=GOOGLE_API_KEY)

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
    model_name="gemini-1.5-flash",
    safety_settings=SAFETY_SETTINGS,
    generation_config=generation_config,
    system_instruction=PROMPT_WORKAW,
)

# ---- Sidebar: Clear chat ----
def clear_history():
    st.session_state["messages"] = [
        {"role": "model", "content": "ปลอบใจ สวัสดีค่ะ วันนี้เป็นอย่างไรบ้าง สบายดีไหมคะ อยากให้ปลอบใจช่วยเรื่องอะไรสอบถามได้นะคะ"}
    ]
    st.rerun()

with st.sidebar:
    if st.button("🧹 Clear History"):
        clear_history()

# ---- Init chat history ----
if "messages" not in st.session_state:
    st.session_state["messages"] = [
        {"role": "model", "content": "ปลอบใจ สวัสดีค่ะ วันนี้คนดีของปลอบใจ สอบถามข้อมูลเรื่องใดคะ"},
    ]

# ---- Dataset loading options ----
st.markdown("**แหล่งข้อมูลสำหรับโมเดล (เลือกอย่างใดอย่างหนึ่ง):**")
tab1, tab2 = st.tabs(["📁 อัปโหลดไฟล์", "📦 ใช้ไฟล์ใน repo"])

file_content = ""
with tab1:
    uploaded = st.file_uploader("อัปโหลดไฟล์ Excel (เช่น Data_Set_Depression_Categorized.xlsx)", type=["xlsx"])
    if uploaded is not None:
        try:
            df = pd.read_excel(uploaded)
            file_content = df.to_string(index=False)
            st.success("อ่านไฟล์จากการอัปโหลดสำเร็จ")
        except Exception as e:
            st.error(f"อ่านไฟล์อัปโหลดไม่สำเร็จ: {e}")

with tab2:
    # วางไฟล์ไว้ในโฟลเดอร์ ./data ภายใน repo ของคุณ
    default_path = "data/Data_Set_Depression_Categorized.xlsx"
    if st.button("โหลดไฟล์จาก repo (data/Data_Set_Depression_Categorized.xlsx)"):
        try:
            df = pd.read_excel(default_path)
            file_content = df.to_string(index=False)
            st.success(f"อ่านไฟล์จาก {default_path} สำเร็จ")
        except Exception as e:
            st.error(f"อ่านไฟล์ใน repo ไม่สำเร็จ: {e}")

# ---- Render history ----
for msg in st.session_state["messages"]:
    with st.chat_message("assistant" if msg["role"] == "model" else "user"):
        st.write(msg["content"])

# ---- Chat input ----
if prompt := st.chat_input("พิมพ์ข้อความถึงปลอบใจ..."):
    st.session_state["messages"].append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    try:
        # เตรียม history ตามรูปแบบ Gemini chat
        history = [{"role": m["role"], "parts": [{"text": m["content"]}]} for m in st.session_state["messages"]]

        # ถ้าอยากให้โมเดลเห็นข้อมูลจากไฟล์ ให้แทรกเป็นข้อความในประวัติ
        if file_content:
            # แทรกหลังข้อความเปิดตัว เพื่อไม่ทับ system_instruction
            insert_at = min(1, len(history))
            history.insert(insert_at, {"role": "user", "parts": [{"text": file_content}]})

        # กรณีคำสั่งพิเศษ
        if prompt.strip().lower().startswith("add") or prompt.strip().lower().endswith("add"):
            reply_text = "ขอบคุณสำหรับคำแนะนำค่ะ"
        else:
            chat_session = model.start_chat(history=history)
            response = chat_session.send_message(prompt)
            reply_text = response.text

        st.session_state["messages"].append({"role": "model", "content": reply_text})
        with st.chat_message("assistant"):
            st.write(reply_text)

    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดขณะเรียกโมเดล: {e}")
