import streamlit as st
import requests
import json
import os
import zipfile
import io
import time
from datetime import datetime

# ─── Page Config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Owix PDF Accessibility Auto-Tagger",
    layout="wide",
)

# ─── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');

html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
.stApp { background-color: #0f0f0f; color: #e0e0e0; }
h1, h2, h3 { font-family: 'IBM Plex Mono', monospace !important; color: #f0f0f0 !important; }

.header-banner {
    background: linear-gradient(135deg, #1a1a1a 0%, #111 100%);
    border-left: 4px solid #00d4aa;
    padding: 20px 24px; margin-bottom: 24px; border-radius: 0 8px 8px 0;
}
.header-banner h1 { margin: 0 0 4px 0; font-size: 1.6rem; letter-spacing: -0.5px; }
.header-banner p  { margin: 0; color: #888; font-size: 0.85rem; font-family: 'IBM Plex Mono', monospace; }

.file-card {
    background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px;
    padding: 10px 14px; margin: 5px 0;
    font-family: 'IBM Plex Mono', monospace; font-size: 0.80rem;
}
.file-card.success  { border-left: 3px solid #00d4aa; }
.file-card.failed   { border-left: 3px solid #ff4d6d; }
.file-card.waiting  { border-left: 3px solid #444; }
.file-card.running  { border-left: 3px solid #f5a623; }

.key-row {
    display: flex; align-items: center; gap: 10px;
    background: #141414; border: 1px solid #2a2a2a;
    border-radius: 8px; padding: 9px 14px; margin: 5px 0;
    font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem;
}
.key-row.active   { border-left: 3px solid #00d4aa; }
.key-row.used     { border-left: 3px solid #444; opacity:.55; }
.key-row.pending  { border-left: 3px solid #f5a623; }
.key-row.error    { border-left: 3px solid #ff4d6d; }
.pill {
    display:inline-block; padding:2px 8px; border-radius:20px;
    font-size:.68rem; font-weight:600; font-family:'IBM Plex Mono',monospace;
}
.pill.active  { background:#003d30; color:#00d4aa; }
.pill.used    { background:#1a1a1a; color:#555; }
.pill.pending { background:#2a1a00; color:#f5a623; }
.pill.error   { background:#2a0010; color:#ff4d6d; }

.metric-row { display:flex; gap:12px; margin:14px 0; }
.metric-card {
    flex:1; background:#1a1a1a; border:1px solid #2a2a2a;
    border-radius:8px; padding:12px; text-align:center;
}
.metric-card .val { font-size:1.8rem; font-family:'IBM Plex Mono',monospace; font-weight:600; }
.metric-card .lbl { font-size:.70rem; color:#555; text-transform:uppercase; letter-spacing:1px; margin-top:2px; }
.val.green  { color:#00d4aa; } .val.red   { color:#ff4d6d; }
.val.orange { color:#f5a623; } .val.white { color:#e0e0e0; }
.val.blue   { color:#4da6ff; }

.stButton>button {
    background:#00d4aa!important; color:#0f0f0f!important;
    font-family:'IBM Plex Mono',monospace!important; font-weight:600!important;
    border:none!important; border-radius:6px!important; padding:10px 20px!important;
}
.stButton>button:hover { background:#00bfa5!important; }
hr { border-color:#2a2a2a!important; }
.stTextInput input, .stTextArea textarea {
    background:#141414!important; color:#e0e0e0!important;
    border-color:#2a2a2a!important; font-family:'IBM Plex Mono',monospace!important;
    font-size:.80rem!important;
}
.stSelectbox div[data-baseweb] { background:#141414!important; border-color:#2a2a2a!important; }
</style>
""", unsafe_allow_html=True)

# ─── Session State ────────────────────────────────────────────────────────────
def init_state():
    defaults = {
        "api_keys":    [],   # list of key strings
        "key_status":  [],   # [{key, status, files_done, error}]
        "results":     {},   # fname → {status, data, error, key_used}
        "processing_done": False,
        "log":         [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# ─── Helpers ──────────────────────────────────────────────────────────────────
API_URL = "https://api.nutrient.io/accessibility/autotag"

def add_log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    st.session_state.log.append(f"[{ts}] {msg}")

def call_api(api_key, file_bytes, filename, conformance="pdfua-1"):
    try:
        r = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (filename, file_bytes, "application/pdf")},
            data={"data": json.dumps({"conformance": conformance})},
            stream=True, timeout=120,
        )
        if r.ok:
            out = io.BytesIO()
            for chunk in r.iter_content(chunk_size=8096):
                out.write(chunk)
            return True, out.getvalue(), None
        return False, None, f"[{r.status_code}] {r.text}"
    except Exception as e:
        return False, None, str(e)

def is_quota_error(err):
    kw = ["quota", "limit", "exceeded", "402", "403", "429", "insufficient", "page", "plan"]
    return bool(err and any(k in err.lower() for k in kw))

def parse_keys(raw):
    return [k.strip() for k in raw.replace(",", "\n").splitlines() if k.strip()]

def mask_key(key):
    return key[:10] + "…" + key[-4:] if len(key) > 14 else key[:4] + "…"

def build_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, info in st.session_state.results.items():
            if info["status"] == "success":
                zf.writestr(fname.replace(".pdf", "_tagged.pdf"), info["data"])
    buf.seek(0)
    return buf.read()

# ─── Header ───────────────────────────────────────────────────────────────────
st.markdown("""
<div class="header-banner">
  <h1>♿ Owix PDF Accessibility Auto-Tagger</h1>
  <p>OWIX API · pdfua-1 · BULK API key bulk processing · MULTIPLE FILE</p>
</div>
""", unsafe_allow_html=True)

col_left, col_right = st.columns([1.2, 1.8], gap="large")

# ══════════════════════════════════════════════════════════════════════════════
# LEFT — Config
# ══════════════════════════════════════════════════════════════════════════════
with col_left:
    st.markdown("### ⚙️ Configuration")

    # API Keys input
    st.markdown("**🔑 API Keys** — one per line")
    st.caption("Keys rotate automatically when quota runs out. No manual switching needed.")

    keys_raw = st.text_area(
        "keys",
        placeholder="pdf_live_aaaaaaaaaaaaaaaa\npdf_live_bbbbbbbbbbbbbb\npdf_live_cccccccccccccc\n...",
        height=180,
        label_visibility="collapsed",
    )
    parsed_keys = parse_keys(keys_raw)

    if parsed_keys:
        capacity = len(parsed_keys) * 10
        st.markdown(
            f"<span style='font-family:IBM Plex Mono,monospace;font-size:.78rem;color:#00d4aa;'>"
            f"✅ {len(parsed_keys)} key(s) · ~{capacity} files capacity"
            f"</span>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("⚠️ Enter at least one API key.")

    st.markdown("---")
    conformance = st.selectbox("Conformance", ["pdfua-1", "pdfua-2"], index=0)

    st.markdown("---")
    st.markdown("### 📂 Upload PDFs")

    max_files = max(len(parsed_keys) * 10, 10)
    st.caption(f"Capacity: **{max_files} files** with {len(parsed_keys)} key(s)")

    uploaded_files = st.file_uploader(
        "PDFs", type=["pdf"], accept_multiple_files=True,
        key="pdf_uploader", label_visibility="collapsed",
    )

    if uploaded_files and len(uploaded_files) > max_files:
        st.warning(f"⚠️ Only {max_files} files can run with {len(parsed_keys)} key(s). Add more keys to increase capacity.")
        uploaded_files = uploaded_files[:max_files]

    if uploaded_files:
        st.caption(f"**{len(uploaded_files)} file(s) selected**")
        for f in uploaded_files:
            sz = len(f.getvalue()) / 1024
            st.markdown(
                f"<div class='file-card waiting'>📄 {f.name} &nbsp;·&nbsp; {sz:.1f} KB</div>",
                unsafe_allow_html=True,
            )

    st.markdown("---")

    can_run = bool(uploaded_files and parsed_keys)
    if st.button("▶ Start Bulk Processing", disabled=not can_run, use_container_width=True):
        # Reset
        st.session_state.results = {}
        st.session_state.log = []
        st.session_state.processing_done = False
        st.session_state.api_keys = parsed_keys
        st.session_state.key_status = [
            {"key": k, "status": "pending", "files_done": 0, "error": None}
            for k in parsed_keys
        ]

        key_idx = 0
        progress = st.progress(0, text="Starting…")
        status_slot = st.empty()
        total = len(uploaded_files)

        for i, uf in enumerate(uploaded_files):

            # No keys left — mark remaining as waiting
            if key_idx >= len(st.session_state.api_keys):
                for rf in uploaded_files[i:]:
                    st.session_state.results[rf.name] = {
                        "status": "waiting", "data": None,
                        "error": "All keys exhausted", "key_used": None,
                    }
                add_log("⛔ All API keys exhausted.")
                break

            active_key  = st.session_state.api_keys[key_idx]
            active_mask = mask_key(active_key)
            st.session_state.key_status[key_idx]["status"] = "active"

            progress.progress(int(i / total * 100),
                text=f"File {i+1}/{total} · Key {key_idx+1}/{len(st.session_state.api_keys)}")
            status_slot.info(f"🔄 **{uf.name}** via key `{active_mask}`")
            add_log(f"START → {uf.name} [key {key_idx+1}]")

            ok, data, err = call_api(active_key, uf.getvalue(), uf.name, conformance)

            if ok:
                st.session_state.results[uf.name] = {
                    "status": "success", "data": data,
                    "error": None, "key_used": key_idx + 1,
                }
                st.session_state.key_status[key_idx]["files_done"] += 1
                add_log(f"✅ {uf.name}")

            elif is_quota_error(err):
                # This key is exhausted — rotate and retry same file
                st.session_state.key_status[key_idx]["status"] = "used"
                st.session_state.key_status[key_idx]["error"] = "Quota exhausted"
                add_log(f"🔁 Key {key_idx+1} exhausted → rotating to key {key_idx+2}")
                key_idx += 1

                if key_idx < len(st.session_state.api_keys):
                    next_key = st.session_state.api_keys[key_idx]
                    st.session_state.key_status[key_idx]["status"] = "active"
                    add_log(f"RETRY → {uf.name} [key {key_idx+1}]")

                    ok2, data2, err2 = call_api(next_key, uf.getvalue(), uf.name, conformance)
                    if ok2:
                        st.session_state.results[uf.name] = {
                            "status": "success", "data": data2,
                            "error": None, "key_used": key_idx + 1,
                        }
                        st.session_state.key_status[key_idx]["files_done"] += 1
                        add_log(f"✅ {uf.name} (retry ok)")
                    else:
                        st.session_state.results[uf.name] = {
                            "status": "failed", "data": None,
                            "error": err2, "key_used": key_idx + 1,
                        }
                        add_log(f"❌ {uf.name} retry failed | {err2}")
                else:
                    st.session_state.results[uf.name] = {
                        "status": "waiting", "data": None,
                        "error": "All keys exhausted", "key_used": None,
                    }
            else:
                # Non-quota failure (bad PDF, network, etc.)
                st.session_state.results[uf.name] = {
                    "status": "failed", "data": None,
                    "error": err, "key_used": key_idx + 1,
                }
                st.session_state.key_status[key_idx]["error"] = err
                add_log(f"❌ {uf.name} | {err}")

            time.sleep(0.2)

        # Mark last active key as used
        if key_idx < len(st.session_state.key_status):
            if st.session_state.key_status[key_idx]["status"] == "active":
                st.session_state.key_status[key_idx]["status"] = "used"

        progress.progress(100, text="All done!")
        time.sleep(0.5)
        progress.empty(); status_slot.empty()
        st.session_state.processing_done = True
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# RIGHT — Results
# ══════════════════════════════════════════════════════════════════════════════
with col_right:

    # Key status panel
    if st.session_state.key_status:
        st.markdown("### 🔑 Key Status")
        for idx, ks in enumerate(st.session_state.key_status):
            stat = ks["status"]
            icon = {"active":"⚡","used":"✔","pending":"⏳","error":"❌"}.get(stat,"⏳")
            note = f"{ks['files_done']} file(s)"
            if ks["error"]: note += f" · {ks['error'][:45]}"
            st.markdown(f"""
            <div class='key-row {stat}'>
              <span class='pill {stat}'>{icon} Key {idx+1}</span>
              <code style='flex:1;color:#555;font-size:.74rem;'>{mask_key(ks['key'])}</code>
              <span style='color:#555;font-size:.74rem;'>{note}</span>
            </div>
            """, unsafe_allow_html=True)
        st.markdown("---")

    st.markdown("### 📊 Results")
    results = st.session_state.results

    if not results:
        st.markdown("""
        <div style='background:#141414;border:1px dashed #2a2a2a;border-radius:8px;
                    padding:40px;text-align:center;color:#444;font-family:IBM Plex Mono,monospace;'>
            Upload PDFs and click Start Bulk Processing
        </div>
        """, unsafe_allow_html=True)
    else:
        total   = len(results)
        success = sum(1 for v in results.values() if v["status"] == "success")
        failed  = sum(1 for v in results.values() if v["status"] == "failed")
        waiting = sum(1 for v in results.values() if v["status"] == "waiting")
        keys_used = len(set(v["key_used"] for v in results.values() if v.get("key_used")))

        st.markdown(f"""
        <div class="metric-row">
          <div class="metric-card"><div class="val white">{total}</div><div class="lbl">Total</div></div>
          <div class="metric-card"><div class="val green">{success}</div><div class="lbl">Success</div></div>
          <div class="metric-card"><div class="val red">{failed}</div><div class="lbl">Failed</div></div>
          <div class="metric-card"><div class="val orange">{waiting}</div><div class="lbl">Waiting</div></div>
          <div class="metric-card"><div class="val blue">{keys_used}</div><div class="lbl">Keys Used</div></div>
        </div>
        """, unsafe_allow_html=True)

        for fname, info in results.items():
            status = info["status"]
            key_n  = info.get("key_used")
            key_tag = f" · Key {key_n}" if key_n else ""

            if status == "success":
                icon, cls = "✅", "success"
                note = f"Tagged{key_tag}"
            elif status == "failed":
                icon, cls = "❌", "failed"
                note = f"{(info['error'] or '')[:65]}{key_tag}"
            elif status == "waiting":
                icon, cls = "⏳", "waiting"
                note = "Keys exhausted — add more keys & reprocess"
            else:
                icon, cls = "🔄", "running"
                note = "Processing…"

            st.markdown(
                f"<div class='file-card {cls}'>"
                f"{icon} &nbsp;<b>{fname}</b>"
                f"<span style='margin-left:auto;color:#555;font-size:.74rem;'>{note}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

        # Downloads
        if success > 0:
            st.markdown("---")
            st.markdown("### 📥 Download")
            dl1, dl2 = st.columns(2)
            with dl1:
                st.download_button(
                    f"⬇ Download All (ZIP) · {success} file(s)",
                    data=build_zip(),
                    file_name=f"tagged_pdfs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                    mime="application/zip",
                    use_container_width=True,
                )
            with dl2:
                sel = st.selectbox(
                    "Individual",
                    options=[k for k, v in results.items() if v["status"] == "success"],
                    label_visibility="collapsed",
                )
            if sel:
                st.download_button(
                    f"⬇ {sel.replace('.pdf','_tagged.pdf')}",
                    data=results[sel]["data"],
                    file_name=sel.replace(".pdf", "_tagged.pdf"),
                    mime="application/pdf",
                    use_container_width=True,
                    key=f"dl_{sel}",
                )

        # Warning for waiting files
        if waiting > 0:
            st.markdown(f"""
            <div style='background:#1f1300;border:1px solid #f5a623;border-radius:8px;
                        padding:14px 18px;margin:12px 0;font-family:IBM Plex Mono,monospace;
                        font-size:.82rem;color:#f5a623;'>
                ⚠️ {waiting} file(s) unprocessed — add more API keys and click Start again.
            </div>
            """, unsafe_allow_html=True)

    # Log
    if st.session_state.log:
        st.markdown("---")
        with st.expander("📋 Log", expanded=False):
            st.code("\n".join(st.session_state.log), language=None)
